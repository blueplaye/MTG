"""Print an audit report for an interaction catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from cedh.audit import audit_catalog
from cedh.interactions import DEFAULT_V2_CATALOG_PATH, load_interactions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审阅互动字典结构和人工校对状态。")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_V2_CATALOG_PATH)
    parser.add_argument("--candidates", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    candidates = None
    if args.candidates:
        candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    report = audit_catalog(load_interactions(args.catalog), candidates=candidates)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
