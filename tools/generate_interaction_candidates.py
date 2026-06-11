"""Generate high-frequency interaction candidates from TopDeck + Scryfall."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from cedh.interaction_candidates import generate_candidates
from cedh.audit import candidate_card_names, catalog_card_names
from cedh.interactions import DEFAULT_V2_CATALOG_PATH, load_interactions
from cedh.progress import ProgressReporter
from cedh.scryfall import DEFAULT_SCRYFALL_CACHE_DIR


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "interaction_candidates.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成 cEDH 高频互动候选牌清单。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--days", type=int, default=183)
    parser.add_argument("--participant-min", type=int, default=48)
    parser.add_argument("--min-decks", type=int, default=2)
    parser.add_argument("--candidate-limit", type=int, default=300, help="最终输出的互动候选数量。")
    parser.add_argument("--top-n", type=int, help="兼容旧参数；等同于 --candidate-limit。")
    parser.add_argument("--event-limit", type=int, default=2, help="只处理前 N 个赛事；0 表示不限制。")
    parser.add_argument("--scryfall-cache-dir", type=Path, default=DEFAULT_SCRYFALL_CACHE_DIR)
    parser.add_argument("--refresh-scryfall", action="store_true", help="重新下载 Scryfall Oracle Cards bulk data。")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_V2_CATALOG_PATH)
    parser.add_argument("--existing-candidates", type=Path)
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="不要跳过字典或旧候选清单中已经出现过的牌。",
    )
    parser.add_argument("--quiet", action="store_true", help="不显示实时进度。")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    progress = ProgressReporter(enabled=not args.quiet)
    candidate_limit = args.top_n if args.top_n is not None else args.candidate_limit
    skip_names = set()
    if not args.include_existing:
        if args.catalog.exists():
            progress(f"读取已收录字典：{args.catalog}")
            skip_names.update(catalog_card_names(load_interactions(args.catalog)))
        if args.existing_candidates and args.existing_candidates.exists():
            progress(f"读取旧候选清单：{args.existing_candidates}")
            skip_names.update(
                candidate_card_names(
                    json.loads(args.existing_candidates.read_text(encoding="utf-8"))
                )
            )
    progress(f"本轮会跳过已处理牌名：{len(skip_names)} 张")

    report = generate_candidates(
        days=args.days,
        participant_min=args.participant_min,
        min_decks=args.min_decks,
        candidate_limit=candidate_limit,
        event_limit=None if args.event_limit <= 0 else args.event_limit,
        skip_names=skip_names,
        scryfall_cache_dir=args.scryfall_cache_dir,
        refresh_scryfall=args.refresh_scryfall,
        progress=progress,
    )
    progress(f"写入候选文件：{args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入候选清单：{args.output}")


if __name__ == "__main__":
    main()
