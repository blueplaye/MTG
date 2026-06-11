"""Fetch Scryfall data and print suggested interaction fields for cards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from cedh.interaction_candidates import suggest_interaction_fields
from cedh.scryfall import fetch_card_named


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 Scryfall 并生成单卡审校建议。")
    parser.add_argument("names", nargs="+", help="英文牌名。")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rows = []
    for name in args.names:
        card = fetch_card_named(name)
        rows.append(
            {
                "name": card.get("name", name),
                "scryfall_id": card.get("id", ""),
                "oracle_id": card.get("oracle_id", ""),
                **suggest_interaction_fields(card),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
