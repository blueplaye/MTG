"""Scryfall helpers for interaction catalog work."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCRYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
USER_AGENT = "MTG-cEDH-risk-tool/0.1; local catalog review"
MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
CHANNEL_COST_RE = re.compile(
    r"channel\s*[—-]\s*([^,:]+),\s*discard this card:",
    re.IGNORECASE,
)
COLOR_ORDER = ("W", "U", "B", "R", "G")
DEFAULT_SCRYFALL_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "scryfall"


def fetch_card_named(name: str, exact: bool = True) -> Mapping[str, Any]:
    """Fetch one card from Scryfall by name."""

    query_key = "exact" if exact else "fuzzy"
    url = f"{SCRYFALL_NAMED_URL}?{urlencode({query_key: name})}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})

    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bulk_data_manifest() -> Mapping[str, Any]:
    """Fetch the Scryfall bulk-data manifest."""

    request = Request(
        SCRYFALL_BULK_DATA_URL,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def oracle_cards_download_uri(manifest: Mapping[str, Any]) -> str:
    """Return the Oracle Cards download URI from a Scryfall bulk-data manifest."""

    for row in manifest.get("data", []):
        if row.get("type") == "oracle_cards":
            uri = row.get("download_uri")
            if isinstance(uri, str) and uri:
                return uri
    raise ValueError("Scryfall bulk-data manifest does not include oracle_cards")


def download_oracle_cards(
    cache_dir: str | Path = DEFAULT_SCRYFALL_CACHE_DIR,
    force: bool = False,
) -> Path:
    """Download Oracle Cards bulk data into the local cache and return the path."""

    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "oracle_cards.json"

    if target.exists() and not force:
        return target

    manifest = fetch_bulk_data_manifest()
    download_uri = oracle_cards_download_uri(manifest)
    request = Request(download_uri, headers={"User-Agent": USER_AGENT})

    with urlopen(request, timeout=180) as response:
        target.write_bytes(response.read())

    return target


def load_oracle_cards(path: str | Path) -> list[Mapping[str, Any]]:
    """Load Scryfall Oracle Cards bulk data from disk."""

    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ScryfallCardIndex:
    """Case-insensitive lookup index for Scryfall card data."""

    def __init__(self, cards: Iterable[Mapping[str, Any]]) -> None:
        self.by_name: dict[str, Mapping[str, Any]] = {}
        for card in cards:
            self.add(card)

    def add(self, card: Mapping[str, Any]) -> None:
        for name in _card_lookup_names(card):
            self.by_name.setdefault(_normalize_lookup_name(name), card)

    def get(self, name: str) -> Mapping[str, Any] | None:
        return self.by_name.get(_normalize_lookup_name(name))

    def require(self, name: str) -> Mapping[str, Any]:
        card = self.get(name)
        if card is None:
            raise KeyError(f"Scryfall card not found in local index: {name}")
        return card


def build_card_index(cards: Iterable[Mapping[str, Any]]) -> ScryfallCardIndex:
    """Build a Scryfall card lookup index."""

    return ScryfallCardIndex(cards)


def load_card_index(path: str | Path) -> ScryfallCardIndex:
    """Load Oracle Cards bulk data and build a lookup index."""

    return build_card_index(load_oracle_cards(path))


def extract_base_card_data(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return the base card fields stored in interactions.v2.json."""

    faces = [_extract_face(face) for face in card.get("card_faces", [])]
    return {
        "mana_cost": card.get("mana_cost") or _join_face_field(faces, "mana_cost"),
        "mana_value": card.get("cmc", card.get("mana_value", 0)),
        "colors": card.get("colors") or _unique_colors_from_faces(faces),
        "color_identity": card.get("color_identity", []),
        "type_line": card.get("type_line") or _join_face_field(faces, "type_line"),
        "oracle_text": card.get("oracle_text") or _join_face_field(faces, "oracle_text"),
        "layout": card.get("layout", ""),
        "faces": faces,
    }


def parse_mana_cost(mana_cost: str) -> dict[str, Any]:
    """Convert a Scryfall mana cost string into generic and color requirements."""

    generic = 0
    colors: list[str] = []

    for symbol in MANA_SYMBOL_RE.findall(mana_cost):
        if symbol.isdigit():
            generic += int(symbol)
            continue

        symbol_colors = [color for color in COLOR_ORDER if color in symbol]
        if symbol_colors:
            colors.extend(symbol_colors)
        elif symbol == "X":
            continue
        else:
            generic += 1

    return {"generic": generic, "colors": colors}


def suggest_cost_options(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate conservative cost option suggestions from Scryfall data."""

    base = extract_base_card_data(card)
    parsed = parse_mana_cost(base["mana_cost"])
    options: list[dict[str, Any]] = []
    if base["mana_cost"] or "land" not in base["type_line"].casefold():
        options.append(
            {
                "mode": "mana",
                "generic": parsed["generic"],
                "colors": parsed["colors"],
            }
        )
    text = base["oracle_text"].casefold()
    mana_cost = base["mana_cost"]
    channel_cost = _channel_cost(base["oracle_text"])

    if "{u/p}" in mana_cost.casefold() or "2 life rather than pay" in text:
        options.append({"mode": "life_or_mana", "colors": parsed["colors"], "life": 2})
    if "exile a blue card" in text and "rather than pay this spell's mana cost" in text:
        pitch_option: dict[str, Any] = {"mode": "pitch", "requires": ["blue_card_in_hand"]}
        if "pay 1 life" in text:
            pitch_option["life"] = 1
        options.append(pitch_option)
    if "exile a green card" in text and "rather than pay this spell's mana cost" in text:
        options.append({"mode": "pitch", "requires": ["green_card_in_hand"]})
    if "if you control a commander" in text and "without paying its mana cost" in text:
        options.append({"mode": "free", "requires": ["commander_in_play"]})
    if "if an opponent cast three or more spells" in text:
        options.append({"mode": "free", "requires": ["opponent_cast_three_spells_this_turn"]})
    if channel_cost:
        channel_parsed = parse_mana_cost(channel_cost)
        options.append(
            {
                "mode": "channel",
                "generic": channel_parsed["generic"],
                "colors": channel_parsed["colors"],
                "requires": ["discard_from_hand"],
            }
        )

    return options


def _channel_cost(oracle_text: str) -> str | None:
    match = CHANNEL_COST_RE.search(oracle_text)
    if not match:
        return None
    return match.group(1).strip()


def _extract_face(face: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": face.get("name", ""),
        "mana_cost": face.get("mana_cost", ""),
        "colors": face.get("colors", []),
        "type_line": face.get("type_line", ""),
        "oracle_text": face.get("oracle_text", ""),
    }


def _join_face_field(faces: list[Mapping[str, Any]], field: str) -> str:
    return " // ".join(str(face.get(field, "")) for face in faces if face.get(field))


def _unique_colors_from_faces(faces: list[Mapping[str, Any]]) -> list[str]:
    colors = {color for face in faces for color in face.get("colors", [])}
    return [color for color in COLOR_ORDER if color in colors]


def _card_lookup_names(card: Mapping[str, Any]) -> list[str]:
    names = []
    card_name = card.get("name")
    if isinstance(card_name, str) and card_name:
        names.append(card_name)

    for face in card.get("card_faces", []):
        face_name = face.get("name")
        if isinstance(face_name, str) and face_name:
            names.append(face_name)

    return names


def _normalize_lookup_name(name: str) -> str:
    return " ".join(name.casefold().split())
