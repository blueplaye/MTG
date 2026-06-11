"""Print TopDeck data scale without Scryfall enrichment or file writes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from cedh.interaction_candidates import (
    fetch_topdeck_tournaments,
    summarize_topdeck_payload,
)
from cedh.progress import ProgressReporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查看 TopDeck 查询结果规模。")
    parser.add_argument("--days", type=int, default=183)
    parser.add_argument("--participant-min", type=int, default=48)
    parser.add_argument("--event-limit", type=int, default=2, help="只统计前 N 个赛事；0 表示不限制。")
    parser.add_argument("--quiet", action="store_true", help="不显示实时进度。")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    progress = ProgressReporter(enabled=not args.quiet)
    api_key = os.environ.get("TOPDECK_API_KEY")
    if not api_key:
        raise RuntimeError("TOPDECK_API_KEY is required")

    progress(
        "开始查询 TopDeck："
        f"近 {args.days} 天，participantMin={args.participant_min}，"
        f"event_limit={None if args.event_limit <= 0 else args.event_limit}"
    )
    payload = fetch_topdeck_tournaments(
        api_key,
        days=args.days,
        participant_min=args.participant_min,
        event_limit=None if args.event_limit <= 0 else args.event_limit,
        progress=progress,
    )
    progress("TopDeck 数据已返回，开始统计规模")
    summary = summarize_topdeck_payload(payload)
    progress(
        f"统计完成：赛事={summary['top_level_tournament_count']}，"
        f"牌表={summary['deck_count']}，唯一牌名={summary['unique_card_count']}"
    )
    summary["query"] = {
        "days": args.days,
        "participant_min": args.participant_min,
        "event_limit": None if args.event_limit <= 0 else args.event_limit,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
