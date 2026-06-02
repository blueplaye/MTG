import unittest
from math import comb

from tools.cedh_probability import stop_probability


class StopProbabilityTest(unittest.TestCase):
    def test_zero_cards_seen_has_zero_stop_probability(self):
        self.assertEqual(stop_probability(99, 10, 0), 0.0)

    def test_zero_answers_has_zero_stop_probability(self):
        self.assertEqual(stop_probability(99, 0, 14), 0.0)

    def test_all_cards_are_answers(self):
        self.assertEqual(stop_probability(99, 99, 1), 1.0)

    def test_cards_seen_is_capped_at_deck_size(self):
        self.assertEqual(stop_probability(99, 1, 120), 1.0)

    def test_common_cedh_example_is_stable(self):
        probability = stop_probability(99, 10, 14)
        expected = 1 - comb(99 - 10, 14) / comb(99, 14)
        self.assertAlmostEqual(probability, expected)

    def test_answer_count_is_capped_at_deck_size(self):
        self.assertEqual(stop_probability(99, 120, 1), 1.0)

    def test_invalid_values_raise_errors(self):
        with self.assertRaises(ValueError):
            stop_probability(0, 1, 1)
        with self.assertRaises(ValueError):
            stop_probability(99, -1, 1)
        with self.assertRaises(ValueError):
            stop_probability(99, 1, -1)


if __name__ == "__main__":
    unittest.main()
