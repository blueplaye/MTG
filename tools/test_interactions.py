import copy
import json
import tempfile
import unittest
from pathlib import Path

from cedh.interactions import (
    DEFAULT_CATALOG_PATH,
    InteractionCatalogError,
    answer_matches,
    card_can_answer,
    load_interactions,
    matching_answers,
)


class InteractionCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_interactions()
        with DEFAULT_CATALOG_PATH.open("r", encoding="utf-8") as handle:
            cls.raw_data = json.load(handle)

    def test_default_catalog_loads(self):
        self.assertEqual(self.catalog.data["schema_version"], 1)
        self.assertGreaterEqual(len(self.catalog.cards), 30)

    def test_broad_counter_covers_narrow_spell_requirements(self):
        self.assertTrue(card_can_answer(self.catalog, "Force of Will", "oracle_consult"))
        self.assertTrue(card_can_answer(self.catalog, "Force of Will", "spell_combo"))

    def test_narrow_counter_does_not_cover_creature_board_win(self):
        self.assertFalse(card_can_answer(self.catalog, "Force of Negation", "creature_board"))

    def test_remove_scope_coverage(self):
        self.assertTrue(card_can_answer(self.catalog, "Nature's Claim", "breach_graveyard"))
        self.assertTrue(card_can_answer(self.catalog, "Assassin's Trophy", "artifact_loop"))
        self.assertFalse(card_can_answer(self.catalog, "Swords to Plowshares", "artifact_loop"))

    def test_graveyard_wildcard_is_allowed_for_win_types(self):
        self.assertTrue(card_can_answer(self.catalog, "Endurance", "breach_graveyard"))
        self.assertTrue(card_can_answer(self.catalog, "Faerie Macabre", "breach_graveyard"))

    def test_triggered_ability_answers_oracle(self):
        matches = matching_answers(self.catalog, "Tale's End", "oracle_consult")
        self.assertTrue(
            any(
                answer["family"] == "counter" and answer["scope"] == "triggered_ability"
                for answer in matches
            )
        )

    def test_answer_matching_supports_win_type_wildcard(self):
        self.assertTrue(
            answer_matches(
                {"family": "remove", "scope": "creature"},
                {"family": "remove", "scope": "*"},
            )
        )

    def test_duplicate_card_names_raise_error(self):
        data = copy.deepcopy(self.raw_data)
        data["cards"].append(copy.deepcopy(data["cards"][0]))

        with self.assertRaises(InteractionCatalogError):
            self._load_temp_catalog(data)

    def test_unknown_answer_scope_raises_error(self):
        data = copy.deepcopy(self.raw_data)
        data["cards"][0]["answers"][0]["scope"] = "everything"

        with self.assertRaises(InteractionCatalogError):
            self._load_temp_catalog(data)

    def test_wildcard_is_not_allowed_on_card_answers(self):
        data = copy.deepcopy(self.raw_data)
        data["cards"][0]["answers"][0]["scope"] = "*"

        with self.assertRaises(InteractionCatalogError):
            self._load_temp_catalog(data)

    def test_unknown_requirement_raises_error(self):
        data = copy.deepcopy(self.raw_data)
        data["cards"][0]["cost_options"][1]["requires"] = ["mysterious_resource"]

        with self.assertRaises(InteractionCatalogError):
            self._load_temp_catalog(data)

    def _load_temp_catalog(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interactions.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_interactions(path)


if __name__ == "__main__":
    unittest.main()
