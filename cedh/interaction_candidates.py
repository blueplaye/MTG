"""Generate and classify high-frequency interaction candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

from .scryfall import (
    ScryfallCardIndex,
    download_oracle_cards,
    extract_base_card_data,
    load_card_index,
    suggest_cost_options,
)


TOPDECK_TOURNAMENTS_URL = "https://topdeck.gg/api/v2/tournaments"
TOPDECK_API_BASE_URL = "https://topdeck.gg/api/v2"
USER_AGENT = "MTG-cEDH-risk-tool/0.1"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
CARD_NAME_KEYS = frozenset({"name", "cardName", "card_name"})
CARD_HINT_KEYS = frozenset(
    {
        "quantity",
        "qty",
        "count",
        "cardId",
        "card_id",
        "scryfallId",
        "scryfall_id",
        "oracleId",
        "oracle_id",
        "manaCost",
        "mana_cost",
        "typeLine",
        "type_line",
    }
)
CARD_SECTION_KEYS = frozenset(
    {
        "mainboard",
        "sideboard",
        "commander",
        "commanders",
        "companion",
        "companions",
        "cards",
        "deck",
        "decklist",
        "board",
        "boards",
        "maindeck",
    }
)
NON_CARD_KEYS = frozenset(
    {
        "id",
        "_id",
        "deckid",
        "deck_id",
        "player",
        "playername",
        "player_name",
        "deckname",
        "deck_name",
        "metadata",
        "meta",
        "event",
        "tournament",
        "standing",
        "standings",
    }
)


@dataclass(frozen=True)
class CardFrequency:
    name: str
    deck_count: int
    appearance_rate: float


def fetch_topdeck_tournaments(
    api_key: str,
    days: int = 183,
    participant_min: int = 48,
    event_limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Any:
    """Fetch recent EDH tournaments from TopDeck."""

    if event_limit and event_limit > 0:
        metadata_payload = _post_topdeck_tournament_query(
            api_key,
            days=days,
            participant_min=participant_min,
            columns=["name"],
        )
        tids = topdeck_tournament_ids(metadata_payload)[:event_limit]
        if tids:
            tournaments = []
            for index, tid in enumerate(tids, start=1):
                if progress:
                    progress(f"拉取赛事牌表 [{index}/{len(tids)}]：{tid}")
                tournaments.append(
                    {
                        "TID": tid,
                        "standings": fetch_topdeck_tournament_standings(api_key, tid),
                    }
                )
            return tournaments

    return _post_topdeck_tournament_query(
        api_key,
        days=days,
        participant_min=participant_min,
        columns=["decklist"],
    )


def fetch_topdeck_tournament_standings(api_key: str, tid: str) -> Any:
    """Fetch standings for one TopDeck tournament."""

    request = Request(
        f"{TOPDECK_API_BASE_URL}/tournaments/{tid}/standings",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def topdeck_tournament_ids(topdeck_payload: Any) -> list[str]:
    """Return top-level tournament IDs from a TopDeck bulk response."""

    rows: Sequence[Any]
    if isinstance(topdeck_payload, list):
        rows = topdeck_payload
    elif isinstance(topdeck_payload, Mapping):
        rows = topdeck_payload.get("data") or topdeck_payload.get("tournaments") or []
    else:
        rows = []

    tids = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tid = row.get("TID") or row.get("tid")
        if isinstance(tid, str) and tid:
            tids.append(tid)

    return tids


def _post_topdeck_tournament_query(
    api_key: str,
    days: int,
    participant_min: int,
    columns: Sequence[str],
) -> Any:
    payload = {
        "game": "Magic: The Gathering",
        "format": "EDH",
        "last": days,
        "participantMin": participant_min,
        "columns": list(columns),
    }
    request = Request(
        TOPDECK_TOURNAMENTS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def limit_tournaments(topdeck_payload: Any, event_limit: int | None) -> Any:
    """Return a payload limited to the first N top-level tournaments when possible."""

    if event_limit is None or event_limit <= 0:
        return topdeck_payload
    if isinstance(topdeck_payload, list):
        return topdeck_payload[:event_limit]
    if isinstance(topdeck_payload, Mapping):
        for key in ("data", "tournaments"):
            value = topdeck_payload.get(key)
            if isinstance(value, list):
                limited = dict(topdeck_payload)
                limited[key] = value[:event_limit]
                return limited
    return topdeck_payload


def count_top_level_tournaments(topdeck_payload: Any) -> int | None:
    """Return top-level tournament count when the payload shape exposes one."""

    if isinstance(topdeck_payload, list):
        return len(topdeck_payload)
    if isinstance(topdeck_payload, Mapping):
        for key in ("data", "tournaments"):
            value = topdeck_payload.get(key)
            if isinstance(value, list):
                return len(value)
    return None


def iter_deck_card_names(topdeck_payload: Any) -> Iterable[set[str]]:
    """Yield unique card names per deck from a flexible TopDeck-like payload."""

    for node in _walk(topdeck_payload):
        if not isinstance(node, Mapping):
            continue

        deck_obj = node.get("deckObj")
        if isinstance(deck_obj, Mapping):
            names = set(_names_from_deck_obj(deck_obj))
            if names:
                yield names
                continue

        decklist = node.get("decklist")
        if isinstance(decklist, str):
            names = set(parse_decklist_text(decklist))
            if names:
                yield names
        elif isinstance(decklist, Mapping):
            names = set(_names_from_deck_obj(decklist))
            if names:
                yield names


def collect_card_frequencies(decks: Iterable[Iterable[str]]) -> tuple[int, Counter[str]]:
    """Count in how many decks each card appears, at most once per deck."""

    counts: Counter[str] = Counter()
    deck_count = 0

    for deck in decks:
        unique_names = {
            _normalize_card_name(name)
            for name in deck
            if name.strip() and not _is_uuid(name.strip())
        }
        if not unique_names:
            continue
        deck_count += 1
        counts.update(unique_names)

    return deck_count, counts


def ranked_frequencies(
    deck_count: int, counts: Counter[str], min_decks: int = 2
) -> list[CardFrequency]:
    """Return sorted card frequencies."""

    if deck_count <= 0:
        return []

    rows = [
        CardFrequency(name=name, deck_count=count, appearance_rate=count / deck_count)
        for name, count in counts.items()
        if count >= min_decks
    ]
    return sorted(rows, key=lambda row: (-row.deck_count, row.name.casefold()))


def summarize_topdeck_payload(topdeck_payload: Any) -> dict[str, Any]:
    """Summarize TopDeck payload size without calling Scryfall."""

    deck_count, counts = collect_card_frequencies(iter_deck_card_names(topdeck_payload))
    top_cards = ranked_frequencies(deck_count, counts, min_decks=1)[:25]
    return {
        "top_level_tournament_count": count_top_level_tournaments(topdeck_payload),
        "deck_count": deck_count,
        "unique_card_count": len(counts),
        "top_cards": [
            {
                "name": card.name,
                "deck_count": card.deck_count,
                "appearance_rate": round(card.appearance_rate, 6),
            }
            for card in top_cards
        ],
    }


def parse_decklist_text(text: str) -> list[str]:
    """Parse common Moxfield/TopDeck text decklist lines."""

    names: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.endswith(":"):
            continue

        match = re.match(r"^(?:(?:\d+)x?\s+)?(.+?)(?:\s+\[[^\]]+\])?$", line)
        if not match:
            continue

        name = re.sub(r"\s+\([^)]*\)$", "", match.group(1)).strip()
        if name:
            names.append(name)

    return names


def suggest_interaction_fields(card: Mapping[str, Any]) -> dict[str, Any]:
    """Suggest interaction fields from Scryfall card data."""

    base = extract_base_card_data(card)
    text = base["oracle_text"].casefold()
    timing = infer_interaction_timing(base)
    answers: list[dict[str, Any]] = []
    reasons: list[str] = []

    def add(answer: dict[str, Any], reason: str) -> None:
        if answer not in answers:
            answers.append(answer)
        if reason not in reasons:
            reasons.append(reason)

    if "counter target spell, activated ability, or triggered ability" in text:
        add({"family": "counter", "scope": "spell_or_ability"}, "反击咒语或异能")
    elif "counter target spell" in text:
        add({"family": "counter", "scope": "any_spell"}, "反击任意咒语")
    if "counter target noncreature spell" in text:
        add({"family": "counter", "scope": "noncreature_spell"}, "反击非生物咒语")
    if "counter target creature spell" in text:
        add({"family": "counter", "scope": "creature_spell"}, "反击生物咒语")
    if "counter target instant or sorcery spell" in text:
        add({"family": "counter", "scope": "instant_or_sorcery"}, "反击瞬间或法术")
    if "counter target activated or triggered ability" in text:
        add({"family": "counter", "scope": "activated_ability"}, "反击起动式异能")
        add({"family": "counter", "scope": "triggered_ability"}, "反击触发式异能")
    elif "counter target activated ability" in text:
        add({"family": "counter", "scope": "activated_ability"}, "反击起动式异能")
    elif "counter target triggered ability" in text:
        add({"family": "counter", "scope": "triggered_ability"}, "反击触发式异能")

    _add_remove_suggestions(text, add)
    _add_graveyard_hate_suggestions(text, add)
    _add_prevent_casting_suggestions(text, add)
    if "change the target" in text:
        add(
            {
                "family": "redirect",
                "scope": "spell_with_target",
                "constraints": ["target_has_target"],
            },
            "改变目标",
        )
    if "you can't lose the game" in text or "your opponents can't win the game" in text:
        add({"family": "special", "scope": "lose_prevention"}, "防止输掉游戏")
    if "exile any number of target spells" in text:
        add({"family": "special", "scope": "exile_stack"}, "放逐堆叠上的咒语")

    for answer in answers:
        _add_common_constraints(answer, text)
        _add_timing_requirements(answer, timing)

    return {
        "base": base,
        "answers": answers,
        "cost_options": suggest_cost_options(card),
        "timing": timing,
        "candidate_reasons": reasons,
    }


def build_candidate_record(
    frequency: CardFrequency, scryfall_card: Mapping[str, Any]
) -> dict[str, Any]:
    suggestions = suggest_interaction_fields(scryfall_card)
    return {
        "name": scryfall_card.get("name", frequency.name),
        "scryfall_id": scryfall_card.get("id", ""),
        "oracle_id": scryfall_card.get("oracle_id", ""),
        "deck_count": frequency.deck_count,
        "appearance_rate": round(frequency.appearance_rate, 6),
        "scryfall_uri": scryfall_card.get("scryfall_uri", ""),
        **suggestions,
    }


def generate_candidates(
    api_key: str | None = None,
    days: int = 183,
    participant_min: int = 48,
    min_decks: int = 2,
    candidate_limit: int = 300,
    event_limit: int | None = None,
    skip_names: Iterable[str] = (),
    card_index: ScryfallCardIndex | None = None,
    scryfall_cache_dir: str | os.PathLike[str] | None = None,
    refresh_scryfall: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fetch TopDeck data and build Scryfall-enriched candidate records."""

    def report(message: str) -> None:
        if progress:
            progress(message)

    token = api_key or os.environ.get("TOPDECK_API_KEY")
    if not token:
        raise RuntimeError("TOPDECK_API_KEY is required")

    report(
        "开始查询 TopDeck："
        f"近 {days} 天，participantMin={participant_min}，"
        f"event_limit={event_limit or '全部'}"
    )
    payload = fetch_topdeck_tournaments(
        token,
        days=days,
        participant_min=participant_min,
        event_limit=event_limit,
        progress=report,
    )
    total_tournaments = count_top_level_tournaments(payload)
    report(f"TopDeck 返回赛事数：{total_tournaments if total_tournaments is not None else '未知'}")

    limited_payload = limit_tournaments(payload, event_limit)
    processed_tournaments = count_top_level_tournaments(limited_payload)
    report(
        "本轮处理赛事数："
        f"{processed_tournaments if processed_tournaments is not None else '未知'}"
    )

    deck_count, counts = collect_card_frequencies(iter_deck_card_names(limited_payload))
    report(f"解析牌表：{deck_count} 副；唯一牌名：{len(counts)}")

    normalized_skip_names = {_normalize_card_name(name).casefold() for name in skip_names}
    frequencies = ranked_frequencies(deck_count, counts, min_decks=min_decks)
    report(
        f"达到出现门槛的唯一牌：{len(frequencies)} 张；"
        f"已处理跳过名单：{len(normalized_skip_names)} 张"
    )

    if card_index is None:
        report("准备 Scryfall Oracle Cards 本地索引")
        oracle_cards_path = download_oracle_cards(
            cache_dir=scryfall_cache_dir or ".cache/scryfall",
            force=refresh_scryfall,
        )
        report(f"读取 Scryfall Oracle Cards：{oracle_cards_path}")
        card_index = load_card_index(oracle_cards_path)
        report(f"Scryfall 本地索引已建立：{len(card_index.by_name)} 个可查名称")

    interaction_candidates = []
    skipped_existing = []
    lookup_errors = []
    scanned_count = 0

    for index, frequency in enumerate(frequencies, start=1):
        if _normalize_card_name(frequency.name).casefold() in normalized_skip_names:
            skipped_existing.append(frequency.name)
            report(f"[{index}/{len(frequencies)}] 跳过已处理：{frequency.name}")
            continue

        scanned_count += 1
        report(
            f"[{index}/{len(frequencies)}] 识别：{frequency.name} "
            f"({frequency.deck_count}/{deck_count} 副；"
            f"已命中互动 {len(interaction_candidates)} 张)"
        )

        card = card_index.get(frequency.name)
        if card is None:
            lookup_errors.append(
                {
                    "name": frequency.name,
                    "error": "not found in Scryfall Oracle Cards bulk data",
                }
            )
            report("  Scryfall 本地索引未找到，已跳过")
            continue

        suggestion = suggest_interaction_fields(card)
        if suggestion["answers"]:
            interaction_candidates.append(build_candidate_record(frequency, card))
            report(f"  命中互动候选：{card.get('name', frequency.name)}")
        else:
            report(f"  未命中互动关键词：{card.get('name', frequency.name)}")

    candidates = sorted(
        interaction_candidates,
        key=lambda row: (-row["deck_count"], str(row["name"]).casefold()),
    )[:candidate_limit]

    report(
        f"候选生成完成：扫描 {scanned_count} 张，"
        f"命中互动 {len(interaction_candidates)} 张，输出 {len(candidates)} 张，"
        f"跳过已处理 {len(skipped_existing)} 张，查询失败 {len(lookup_errors)} 张"
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "TopDeck.gg + Scryfall",
            "days": days,
            "participant_min": participant_min,
            "min_decks": min_decks,
            "candidate_limit": candidate_limit,
            "event_limit": event_limit,
        },
        "top_level_tournament_count": total_tournaments,
        "processed_tournament_count": processed_tournaments,
        "deck_count": deck_count,
        "unique_card_count": len(counts),
        "scanned_card_count": scanned_count,
        "interaction_candidate_pool_count": len(interaction_candidates),
        "skipped_existing_count": len(skipped_existing),
        "skipped_existing": skipped_existing,
        "lookup_error_count": len(lookup_errors),
        "lookup_errors": lookup_errors,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _add_remove_suggestions(text: str, add) -> None:
    artifact_enchantment = re.search(
        r"(?:destroy|exile) target "
        r"(?:artifact or enchantment|enchantment or artifact|"
        r"artifact, enchantment|artifact, creature, or enchantment)",
        text,
    )
    artifact_creature = re.search(
        r"(?:destroy|exile) target (?:artifact or creature|creature or artifact)",
        text,
    )

    if artifact_enchantment:
        add({"family": "remove", "scope": "artifact_or_enchantment"}, "处理神器或结界")
    if artifact_creature:
        add({"family": "remove", "scope": "artifact"}, "去除目标神器")
        add({"family": "remove", "scope": "creature"}, "去除目标生物")

    if re.search(r"(?:destroy|exile) target creature(?! card)", text):
        add({"family": "remove", "scope": "creature"}, "去除目标生物")
    if not artifact_enchantment and not artifact_creature and re.search(
        r"(?:destroy|exile) target artifact(?! card)", text
    ):
        add({"family": "remove", "scope": "artifact"}, "去除目标神器")
    if not artifact_enchantment and re.search(
        r"(?:destroy|exile) target enchantment(?! card)", text
    ):
        add({"family": "remove", "scope": "enchantment"}, "去除目标结界")
    if re.search(r"(?:destroy|exile) target nonland permanent", text):
        add({"family": "remove", "scope": "nonland_permanent"}, "处理非地永久物")
    if re.search(r"(?:destroy|exile) target permanent", text):
        add({"family": "remove", "scope": "permanent"}, "处理永久物")
    if re.search(r"return target nonland permanent.+owner's hand", text):
        add(
            {
                "family": "remove",
                "scope": "nonland_permanent",
                "constraints": ["returns_to_hand"],
            },
            "弹回非地永久物",
        )
    elif re.search(r"return target permanent.+owner's hand", text):
        add(
            {
                "family": "remove",
                "scope": "permanent",
                "constraints": ["returns_to_hand"],
            },
            "弹回永久物",
        )


def _add_graveyard_hate_suggestions(text: str, add) -> None:
    if "graveyard" not in text:
        return

    if "exile all graveyards" in text:
        add({"family": "graveyard_hate", "scope": "all_graveyards"}, "放逐所有坟场")
    if re.search(r"exile (?:each opponent's|target player's) graveyard", text):
        add(
            {"family": "graveyard_hate", "scope": "target_player_graveyard"},
            "放逐牌手坟场",
        )
    if re.search(
        r"(?:exile|put|shuffle) (?:up to one |each |any number of )?"
        r"target .{0,40}card from (?:a|target player's) graveyard",
        text,
    ):
        add({"family": "graveyard_hate", "scope": "target_card"}, "处理坟场中的目标牌")
    if re.search(
        r"target player .{0,80}(?:cards from their graveyard|their graveyard)"
        r".{0,80}(?:bottom of their library|shuffles? .*library)",
        text,
    ):
        add({"family": "graveyard_hate", "scope": "shuffle_or_bottom"}, "洗回或置于牌库底")
    if re.search(
        r"(?:opponent|opponents).{0,80}graveyard.{0,80}exile (?:it|them) instead",
        text,
    ):
        add({"family": "graveyard_hate", "scope": "replacement_effect"}, "对手坟场替代效应")


def _add_prevent_casting_suggestions(text: str, add) -> None:
    if re.search(r"target player can't cast noncreature spells this turn", text):
        add({"family": "prevent_casting", "scope": "noncreature_spells"}, "限制非生物咒语")
    if re.search(r"target player can't cast spells this turn", text):
        add(
            {"family": "prevent_casting", "scope": "target_player_spells_this_turn"},
            "限制目标牌手本回合施放咒语",
        )
    if re.search(
        r"(?:your opponents|opponents) can't cast noncreature spells"
        r" this turn",
        text,
    ):
        add({"family": "prevent_casting", "scope": "noncreature_spells"}, "限制非生物咒语")
    if re.search(
        r"(?:your opponents|opponents) can't cast spells"
        r" this turn",
        text,
    ):
        add(
            {"family": "prevent_casting", "scope": "opponents_spells_this_turn"},
            "限制对手本回合施放咒语",
        )
    if re.search(r"can't cast spells until", text):
        add({"family": "prevent_casting", "scope": "next_spell_only"}, "限制后续施放")


def infer_interaction_timing(base: Mapping[str, Any]) -> dict[str, Any]:
    """Return a coarse timing hint for candidate review and later estimators."""

    text = str(base.get("oracle_text", "")).casefold()
    type_line = str(base.get("type_line", "")).casefold()

    if _has_channel_ability(text):
        return {
            "speed": "instant",
            "source": "channel",
            "usable_from_hand_as_response": True,
        }
    if re.search(r"\binstant\b", type_line):
        return {
            "speed": "instant",
            "source": "card_type",
            "usable_from_hand_as_response": True,
        }
    if _has_flash_timing(text):
        return {
            "speed": "instant",
            "source": "flash",
            "usable_from_hand_as_response": True,
        }
    if _is_permanent_type(type_line):
        return {
            "speed": "battlefield",
            "source": "permanent",
            "usable_from_hand_as_response": False,
            "requirements": ["already_on_battlefield"],
        }
    return {
        "speed": "sorcery",
        "source": "card_type",
        "usable_from_hand_as_response": False,
    }


def _add_timing_requirements(answer: dict[str, Any], timing: Mapping[str, Any]) -> None:
    if timing.get("usable_from_hand_as_response"):
        return

    requirements = list(answer.get("requirements", []))
    for requirement in timing.get("requirements", []):
        if requirement not in requirements:
            requirements.append(requirement)
    if requirements:
        answer["requirements"] = sorted(requirements)


def _has_channel_ability(text: str) -> bool:
    return bool(re.search(r"(?:^|\n)channel\s*[—-]", text))


def _has_flash_timing(text: str) -> bool:
    return bool(re.search(r"(?:^|\n)flash(?:\n|$)|as though it had flash", text))


def _is_permanent_type(type_line: str) -> bool:
    return any(
        card_type in type_line
        for card_type in (
            "artifact",
            "battle",
            "creature",
            "enchantment",
            "land",
            "planeswalker",
        )
    )


def _add_common_constraints(answer: dict[str, Any], text: str) -> None:
    constraints = list(answer.get("constraints", []))
    if "if it's blue" in text or "target blue spell" in text or "target blue permanent" in text:
        constraints.append("target_is_blue")
    if "target instant spell" in text:
        constraints.append("target_is_instant")
    if "nonblack creature" in text:
        constraints.append("target_is_nonblack")

    if constraints:
        answer["constraints"] = sorted(set(constraints))

    if answer.get("family") not in {"counter", "remove"}:
        return

    if mana_value_match := re.search(r"mana value (\d+) or less", text):
        answer["limits"] = {"max_mana_value": int(mana_value_match.group(1))}
    elif mana_value_match := re.search(r"mana value (\d+) or greater", text):
        answer["limits"] = {"min_mana_value": int(mana_value_match.group(1))}
    elif mana_value_match := re.search(r"mana value (\d+)", text):
        answer["limits"] = {"mana_value": int(mana_value_match.group(1))}


def _names_from_deck_obj(deck_obj: Mapping[str, Any]) -> Iterable[str]:
    for key, value in deck_obj.items():
        key_text = str(key)
        if _is_non_card_key(key_text):
            continue

        if _looks_like_card_name_key(key_text, value):
            yield key_text
            continue

        yield from _names_from_structured_deck(
            value,
            in_card_collection=_is_card_section_key(key_text) or _is_uuid(key_text),
        )


def _names_from_structured_deck(value: Any, in_card_collection: bool) -> Iterable[str]:
    if isinstance(value, Mapping):
        name = _card_name_from_mapping(value, in_card_collection=in_card_collection)
        if name:
            yield name

        for key, nested in value.items():
            key_text = str(key)
            if _is_non_card_key(key_text):
                continue

            if _looks_like_card_name_key(key_text, nested):
                yield key_text
                continue

            yield from _names_from_structured_deck(
                nested,
                in_card_collection=(
                    in_card_collection
                    or _is_card_section_key(key_text)
                    or _is_uuid(key_text)
                ),
            )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _names_from_structured_deck(
                item,
                in_card_collection=in_card_collection,
            )


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            yield from _walk(nested)


def _normalize_card_name(name: str) -> str:
    return " ".join(name.split())


def _card_name_from_mapping(
    value: Mapping[str, Any], in_card_collection: bool
) -> str | None:
    for key in CARD_NAME_KEYS:
        name = value.get(key)
        if isinstance(name, str) and _is_plausible_card_name(name):
            if in_card_collection or any(hint in value for hint in CARD_HINT_KEYS):
                return _normalize_card_name(name)
    return None


def _looks_like_card_name_key(key: str, value: Any) -> bool:
    if not _is_plausible_card_name(key):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, Mapping):
        return any(hint in value for hint in CARD_HINT_KEYS)
    return False


def _is_plausible_card_name(name: str) -> bool:
    normalized = _normalize_card_name(name)
    if not normalized or _is_uuid(normalized):
        return False
    if normalized.isdigit():
        return False
    if _is_non_card_key(normalized):
        return False
    return bool(re.search(r"[A-Za-z]", normalized))


def _is_card_section_key(key: str) -> bool:
    return key.casefold() in CARD_SECTION_KEYS


def _is_non_card_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    compact = normalized.replace("_", "")
    return normalized in NON_CARD_KEYS or compact in NON_CARD_KEYS


def _is_uuid(value: str) -> bool:
    return bool(UUID_RE.fullmatch(value.strip()))
