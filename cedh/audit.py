"""Audit helpers for interaction catalog review."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .interactions import InteractionCatalog, load_interactions


def audit_catalog(
    catalog: InteractionCatalog,
    candidates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a machine-readable audit report."""

    names = [card["name"] for card in catalog.cards]
    duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
    review_needed = [
        card["name"]
        for card in catalog.cards
        if card.get("confidence") != "reviewed"
    ]
    cards_by_name = {name.casefold(): name for name in names}
    missing_candidates: list[str] = []

    if candidates:
        for candidate in candidates.get("candidates", []):
            name = candidate.get("name", "")
            if name and name.casefold() not in cards_by_name:
                missing_candidates.append(name)

    return {
        "card_count": len(catalog.cards),
        "duplicate_names": duplicate_names,
        "review_needed": sorted(review_needed),
        "missing_candidates": sorted(set(missing_candidates)),
        "family_distribution": _family_distribution(catalog),
    }


def audit_catalog_path(
    catalog_path: str,
    candidates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return audit_catalog(load_interactions(catalog_path), candidates=candidates)


def catalog_card_names(catalog: InteractionCatalog) -> set[str]:
    """Return normalized card names already present in a catalog."""

    return {_normalize_name(card["name"]) for card in catalog.cards}


def candidate_card_names(candidates: Mapping[str, Any]) -> set[str]:
    """Return normalized card names already present in a candidate report."""

    return {
        _normalize_name(candidate["name"])
        for candidate in candidates.get("candidates", [])
        if isinstance(candidate, Mapping) and isinstance(candidate.get("name"), str)
    }


def _family_distribution(catalog: InteractionCatalog) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for card in catalog.cards:
        for answer in card.get("answers", []):
            counts[answer.get("family", "")] += 1
    return dict(sorted(counts.items()))


def _normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())
