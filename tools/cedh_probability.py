"""Minimal cEDH interaction probability calculator.

This module estimates the chance that one opponent has seen at least one
effective answer after drawing a known number of cards.
"""

from __future__ import annotations

import argparse


def stop_probability(deck_size: int, answer_count: int, cards_seen: int) -> float:
    """Return the probability of seeing at least one answer.

    The formula is the complement of missing every answer in a sample drawn
    without replacement:

        1 - C(deck_size - answer_count, cards_seen) / C(deck_size, cards_seen)

    The implementation uses iterative multiplication so it does not need to
    compute large combinations directly.
    """

    if deck_size <= 0:
        raise ValueError("deck_size must be greater than 0")
    if answer_count < 0:
        raise ValueError("answer_count must be at least 0")
    if cards_seen < 0:
        raise ValueError("cards_seen must be at least 0")

    answers = min(answer_count, deck_size)
    seen = min(cards_seen, deck_size)

    if seen == 0 or answers == 0:
        return 0.0
    if answers == deck_size:
        return 1.0

    no_answer_probability = 1.0

    for draw_index in range(seen):
        remaining_cards = deck_size - draw_index
        remaining_non_answers = deck_size - answers - draw_index

        if remaining_non_answers <= 0:
            return 1.0

        no_answer_probability *= remaining_non_answers / remaining_cards

    return 1.0 - no_answer_probability


def format_percent(value: float) -> str:
    """Format a probability as a percentage with two decimal places."""

    return f"{value * 100:.2f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="计算单个 cEDH 对手至少见过一张有效互动的概率。"
    )
    parser.add_argument(
        "--deck-size",
        type=int,
        required=True,
        help="牌库大小，例如指挥官通常为 99。",
    )
    parser.add_argument(
        "--answers",
        type=int,
        required=True,
        help="牌库中的有效互动数量。",
    )
    parser.add_argument(
        "--seen",
        type=int,
        required=True,
        help="对手累计看过的牌数，通常为起手数量加后续抽牌数量。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    p_stop = stop_probability(args.deck_size, args.answers, args.seen)
    p_win = 1.0 - p_stop

    print(f"对手阻止概率：{format_percent(p_stop)}")
    print(f"我通过的概率：{format_percent(p_win)}")


if __name__ == "__main__":
    main()
