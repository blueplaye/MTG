"""Load and validate the cEDH interaction catalog.

The catalog intentionally describes interaction capabilities, not odds. Later
probability code can combine these structured answers with deck statistics,
mana availability, and assumptions about extra resources.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_CATALOG_PATH = DATA_DIR / "interactions.v1.json"
DEFAULT_V2_CATALOG_PATH = DATA_DIR / "interactions.v2.json"

VALID_COLORS = frozenset({"W", "U", "B", "R", "G", "C"})
VALID_COST_MODES = frozenset({"mana", "free", "pitch", "life_or_mana", "channel"})
VALID_LIMIT_KEYS = frozenset({"mana_value", "max_mana_value", "min_mana_value"})
VALID_CONFIDENCE = frozenset({"suggested", "needs_review", "reviewed"})
REQUIRED_BASE_FIELDS = frozenset(
    {
        "mana_cost",
        "mana_value",
        "colors",
        "color_identity",
        "type_line",
        "oracle_text",
        "layout",
        "faces",
    }
)
REQUIRED_FACE_FIELDS = frozenset(
    {"name", "mana_cost", "colors", "type_line", "oracle_text"}
)

SCOPE_COVERAGE: dict[str, dict[str, frozenset[str]]] = {
    "counter": {
        "any_spell": frozenset(
            {"noncreature_spell", "creature_spell", "instant_or_sorcery"}
        ),
        "noncreature_spell": frozenset({"instant_or_sorcery"}),
        "spell_or_ability": frozenset(
            {
                "any_spell",
                "noncreature_spell",
                "creature_spell",
                "instant_or_sorcery",
                "activated_ability",
                "triggered_ability",
            }
        ),
    },
    "remove": {
        "permanent": frozenset(
            {
                "creature",
                "artifact",
                "enchantment",
                "artifact_or_enchantment",
                "nonland_permanent",
            }
        ),
        "nonland_permanent": frozenset(
            {"creature", "artifact", "enchantment", "artifact_or_enchantment"}
        ),
        "artifact_or_enchantment": frozenset({"artifact", "enchantment"}),
    },
    "graveyard_hate": {
        "all_graveyards": frozenset(
            {"target_card", "target_player_graveyard", "shuffle_or_bottom"}
        ),
        "target_player_graveyard": frozenset({"target_card", "shuffle_or_bottom"}),
    },
}


class InteractionCatalogError(ValueError):
    """Raised when the interaction catalog is malformed."""


@dataclass(frozen=True)
class InteractionCatalog:
    """Validated interaction catalog data."""

    data: Mapping[str, Any]
    path: Path | None = None

    @property
    def cards(self) -> Sequence[Mapping[str, Any]]:
        return self.data["cards"]

    @property
    def win_types(self) -> Mapping[str, Mapping[str, Any]]:
        return self.data["win_types"]

    @property
    def families(self) -> Mapping[str, Mapping[str, Any]]:
        return self.data["families"]

    @property
    def cards_by_name(self) -> dict[str, Mapping[str, Any]]:
        return {_normalize_name(card["name"]): card for card in self.cards}

    def get_card(self, name: str) -> Mapping[str, Any]:
        try:
            return self.cards_by_name[_normalize_name(name)]
        except KeyError as exc:
            raise KeyError(f"unknown interaction card: {name}") from exc


def load_interactions(path: str | Path = DEFAULT_CATALOG_PATH) -> InteractionCatalog:
    """Load and validate an interaction catalog JSON file."""

    catalog_path = Path(path)
    with catalog_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    catalog = InteractionCatalog(data=data, path=catalog_path)
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: InteractionCatalog) -> None:
    """Validate catalog shape, references, and enum values."""

    data = catalog.data
    schema_version = data.get("schema_version")
    if schema_version not in {1, 2}:
        raise InteractionCatalogError("schema_version must be 1 or 2")

    families = _require_mapping(data, "families")
    requirement_terms = _require_mapping(data, "requirement_terms")
    constraint_terms = _require_mapping(data, "constraint_terms")
    win_types = _require_mapping(data, "win_types")
    cards = _require_list(data, "cards")

    for family, spec in families.items():
        if not isinstance(spec, Mapping):
            raise InteractionCatalogError(f"family {family!r} must be an object")
        scopes = spec.get("scopes")
        if not isinstance(scopes, Mapping) or not scopes:
            raise InteractionCatalogError(f"family {family!r} must define scopes")

    for win_type, spec in win_types.items():
        if not isinstance(spec, Mapping):
            raise InteractionCatalogError(f"win_type {win_type!r} must be an object")
        answered_by = _require_list(spec, f"win_types.{win_type}.answered_by")
        for answer in answered_by:
            _validate_answer(answer, families, allow_wildcard=True)

    seen_names: set[str] = set()
    for card in cards:
        if not isinstance(card, Mapping):
            raise InteractionCatalogError("cards entries must be objects")

        name = card.get("name")
        if not isinstance(name, str) or not name.strip():
            raise InteractionCatalogError("cards entries must have a non-empty name")

        normalized = _normalize_name(name)
        if normalized in seen_names:
            raise InteractionCatalogError(f"duplicate card name: {name}")
        seen_names.add(normalized)

        answers = _require_list(card, f"cards.{name}.answers")
        cost_options = _require_list(card, f"cards.{name}.cost_options")

        if schema_version == 2:
            _validate_v2_card_metadata(card, f"cards.{name}")

        for answer in answers:
            _validate_answer(answer, families, allow_wildcard=False)
            _validate_constraints(answer, constraint_terms, f"cards.{name}.answers")
            _validate_answer_requirements(
                answer, requirement_terms, f"cards.{name}.answers"
            )
            _validate_limits(answer, f"cards.{name}.answers")

        for option in cost_options:
            _validate_cost_option(option, requirement_terms, f"cards.{name}.cost_options")


def answers_for_win_type(
    catalog: InteractionCatalog, win_type: str
) -> tuple[Mapping[str, Any], ...]:
    """Return structured answer requirements for a win type."""

    try:
        answered_by = catalog.win_types[win_type]["answered_by"]
    except KeyError as exc:
        raise KeyError(f"unknown win type: {win_type}") from exc
    return tuple(answered_by)


def answer_matches(
    card_answer: Mapping[str, Any], accepted_answer: Mapping[str, Any]
) -> bool:
    """Return True when a card answer covers a win type answer requirement."""

    if card_answer.get("family") != accepted_answer.get("family"):
        return False

    accepted_scope = accepted_answer.get("scope")
    if accepted_scope == "*":
        return True

    card_scope = card_answer.get("scope")
    if card_scope == accepted_scope:
        return True

    coverage = SCOPE_COVERAGE.get(str(card_answer.get("family")), {})
    return accepted_scope in coverage.get(str(card_scope), frozenset())


def card_can_answer(
    catalog: InteractionCatalog, card: str | Mapping[str, Any], win_type: str
) -> bool:
    """Return True when a catalog card has at least one matching answer."""

    card_data = catalog.get_card(card) if isinstance(card, str) else card
    accepted_answers = answers_for_win_type(catalog, win_type)

    return any(
        answer_matches(card_answer, accepted_answer)
        for card_answer in card_data.get("answers", ())
        for accepted_answer in accepted_answers
    )


def matching_answers(
    catalog: InteractionCatalog, card: str | Mapping[str, Any], win_type: str
) -> tuple[Mapping[str, Any], ...]:
    """Return the card answer entries that match a win type."""

    card_data = catalog.get_card(card) if isinstance(card, str) else card
    accepted_answers = answers_for_win_type(catalog, win_type)
    matches: list[Mapping[str, Any]] = []

    for card_answer in card_data.get("answers", ()):
        if any(answer_matches(card_answer, accepted) for accepted in accepted_answers):
            matches.append(card_answer)

    return tuple(matches)


def _normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


def _require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise InteractionCatalogError(f"{key} must be an object")
    return value


def _require_list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key.split(".")[-1])
    if not isinstance(value, list):
        raise InteractionCatalogError(f"{key} must be a list")
    return value


def _validate_answer(
    answer: Any, families: Mapping[str, Mapping[str, Any]], allow_wildcard: bool
) -> None:
    if not isinstance(answer, Mapping):
        raise InteractionCatalogError("answer entries must be objects")

    family = answer.get("family")
    scope = answer.get("scope")
    if family not in families:
        raise InteractionCatalogError(f"unknown answer family: {family!r}")

    if scope == "*":
        if allow_wildcard:
            return
        raise InteractionCatalogError("wildcard scopes are only allowed in win_types")

    scopes = families[family].get("scopes", {})
    if scope not in scopes:
        raise InteractionCatalogError(
            f"unknown scope {scope!r} for answer family {family!r}"
        )


def _validate_constraints(
    answer: Mapping[str, Any], constraint_terms: Mapping[str, Any], context: str
) -> None:
    constraints = answer.get("constraints", [])
    if not isinstance(constraints, list):
        raise InteractionCatalogError(f"{context}.constraints must be a list")

    for constraint in constraints:
        if constraint not in constraint_terms:
            raise InteractionCatalogError(f"unknown constraint: {constraint!r}")


def _validate_answer_requirements(
    answer: Mapping[str, Any], requirement_terms: Mapping[str, Any], context: str
) -> None:
    requirements = answer.get("requirements", [])
    if not isinstance(requirements, list):
        raise InteractionCatalogError(f"{context}.requirements must be a list")

    for requirement in requirements:
        if requirement not in requirement_terms:
            raise InteractionCatalogError(f"unknown requirement: {requirement!r}")


def _validate_limits(answer: Mapping[str, Any], context: str) -> None:
    limits = answer.get("limits", {})
    if not isinstance(limits, Mapping):
        raise InteractionCatalogError(f"{context}.limits must be an object")

    for key, value in limits.items():
        if key not in VALID_LIMIT_KEYS:
            raise InteractionCatalogError(f"unknown limit key: {key!r}")
        if not isinstance(value, int) or value < 0:
            raise InteractionCatalogError(f"limit {key!r} must be a non-negative int")


def _validate_cost_option(
    option: Any, requirement_terms: Mapping[str, Any], context: str
) -> None:
    if not isinstance(option, Mapping):
        raise InteractionCatalogError(f"{context} entries must be objects")

    mode = option.get("mode")
    if mode not in VALID_COST_MODES:
        raise InteractionCatalogError(f"unknown cost mode: {mode!r}")

    generic = option.get("generic", 0)
    if not isinstance(generic, int) or generic < 0:
        raise InteractionCatalogError(f"{context}.generic must be a non-negative int")

    colors = option.get("colors", [])
    if not isinstance(colors, list):
        raise InteractionCatalogError(f"{context}.colors must be a list")
    for color in colors:
        if color not in VALID_COLORS:
            raise InteractionCatalogError(f"unknown mana color: {color!r}")

    life = option.get("life", 0)
    if not isinstance(life, int) or life < 0:
        raise InteractionCatalogError(f"{context}.life must be a non-negative int")

    requires = option.get("requires", [])
    if not isinstance(requires, list):
        raise InteractionCatalogError(f"{context}.requires must be a list")
    for requirement in requires:
        if requirement not in requirement_terms:
            raise InteractionCatalogError(f"unknown requirement: {requirement!r}")


def _validate_v2_card_metadata(card: Mapping[str, Any], context: str) -> None:
    for key in ("scryfall_id", "oracle_id", "review_notes"):
        value = card.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InteractionCatalogError(f"{context}.{key} must be a non-empty string")

    confidence = card.get("confidence")
    if confidence not in VALID_CONFIDENCE:
        raise InteractionCatalogError(f"{context}.confidence is invalid: {confidence!r}")

    base = card.get("base")
    if not isinstance(base, Mapping):
        raise InteractionCatalogError(f"{context}.base must be an object")

    missing = REQUIRED_BASE_FIELDS - set(base)
    if missing:
        raise InteractionCatalogError(
            f"{context}.base is missing required fields: {sorted(missing)}"
        )

    _validate_string_field(base, "mana_cost", f"{context}.base")
    _validate_number_field(base, "mana_value", f"{context}.base")
    _validate_color_list(base, "colors", f"{context}.base")
    _validate_color_list(base, "color_identity", f"{context}.base")
    _validate_string_field(base, "type_line", f"{context}.base")
    _validate_string_field(base, "oracle_text", f"{context}.base", allow_empty=False)
    _validate_string_field(base, "layout", f"{context}.base")

    faces = base.get("faces")
    if not isinstance(faces, list):
        raise InteractionCatalogError(f"{context}.base.faces must be a list")

    for index, face in enumerate(faces):
        if not isinstance(face, Mapping):
            raise InteractionCatalogError(f"{context}.base.faces[{index}] must be an object")
        missing_face_fields = REQUIRED_FACE_FIELDS - set(face)
        if missing_face_fields:
            raise InteractionCatalogError(
                f"{context}.base.faces[{index}] is missing required fields: "
                f"{sorted(missing_face_fields)}"
            )
        _validate_string_field(face, "name", f"{context}.base.faces[{index}]", allow_empty=False)
        _validate_string_field(face, "mana_cost", f"{context}.base.faces[{index}]")
        _validate_color_list(face, "colors", f"{context}.base.faces[{index}]")
        _validate_string_field(face, "type_line", f"{context}.base.faces[{index}]")
        _validate_string_field(
            face, "oracle_text", f"{context}.base.faces[{index}]", allow_empty=False
        )


def _validate_string_field(
    data: Mapping[str, Any], key: str, context: str, allow_empty: bool = True
) -> None:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise InteractionCatalogError(f"{context}.{key} must be a string")


def _validate_number_field(data: Mapping[str, Any], key: str, context: str) -> None:
    value = data.get(key)
    if not isinstance(value, (int, float)) or value < 0:
        raise InteractionCatalogError(f"{context}.{key} must be a non-negative number")


def _validate_color_list(data: Mapping[str, Any], key: str, context: str) -> None:
    value = data.get(key)
    if not isinstance(value, list):
        raise InteractionCatalogError(f"{context}.{key} must be a list")
    for color in value:
        if color not in VALID_COLORS:
            raise InteractionCatalogError(f"unknown color in {context}.{key}: {color!r}")
