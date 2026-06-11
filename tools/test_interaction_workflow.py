import copy
import json
import tempfile
import unittest
from pathlib import Path

from cedh.audit import audit_catalog
from cedh.audit import candidate_card_names, catalog_card_names
from cedh.interaction_candidates import (
    collect_card_frequencies,
    fetch_topdeck_tournaments,
    generate_candidates,
    iter_deck_card_names,
    limit_tournaments,
    parse_decklist_text,
    ranked_frequencies,
    summarize_topdeck_payload,
    suggest_interaction_fields,
    topdeck_tournament_ids,
)
from cedh.interactions import (
    DEFAULT_V2_CATALOG_PATH,
    InteractionCatalogError,
    load_interactions,
)
from cedh.scryfall import extract_base_card_data, suggest_cost_options
from cedh.scryfall import build_card_index


FORCE_OF_WILL = {
    "id": "scryfall-force",
    "oracle_id": "oracle-force",
    "name": "Force of Will",
    "mana_cost": "{3}{U}{U}",
    "cmc": 5,
    "colors": ["U"],
    "color_identity": ["U"],
    "type_line": "Instant",
    "oracle_text": (
        "You may pay 1 life and exile a blue card from your hand rather than pay "
        "this spell's mana cost.\nCounter target spell."
    ),
    "layout": "normal",
    "scryfall_uri": "https://scryfall.com/card/test/1/force-of-will",
}

WEAR_TEAR = {
    "id": "scryfall-wear-tear",
    "oracle_id": "oracle-wear-tear",
    "name": "Wear // Tear",
    "cmc": 3,
    "color_identity": ["R", "W"],
    "type_line": "Instant // Instant",
    "layout": "split",
    "card_faces": [
        {
            "name": "Wear",
            "mana_cost": "{1}{R}",
            "colors": ["R"],
            "type_line": "Instant",
            "oracle_text": "Destroy target artifact.",
        },
        {
            "name": "Tear",
            "mana_cost": "{W}",
            "colors": ["W"],
            "type_line": "Instant",
            "oracle_text": "Destroy target enchantment.",
        },
    ],
}

PACT_OF_NEGATION = {
    "id": "scryfall-pact",
    "oracle_id": "oracle-pact",
    "name": "Pact of Negation",
    "mana_cost": "{0}",
    "cmc": 0,
    "colors": ["U"],
    "color_identity": ["U"],
    "type_line": "Instant",
    "oracle_text": "Counter target spell.",
    "layout": "normal",
    "scryfall_uri": "https://scryfall.com/card/test/2/pact-of-negation",
}

ISLAND = {
    "id": "island",
    "oracle_id": "island-oracle",
    "name": "Island",
    "mana_cost": "",
    "cmc": 0,
    "colors": [],
    "color_identity": ["U"],
    "type_line": "Basic Land — Island",
    "oracle_text": "({T}: Add {U}.)",
    "layout": "normal",
}

SOL_RING = {
    "id": "sol-ring",
    "oracle_id": "sol-ring-oracle",
    "name": "Sol Ring",
    "mana_cost": "{1}",
    "cmc": 1,
    "colors": [],
    "color_identity": [],
    "type_line": "Artifact",
    "oracle_text": "{T}: Add {C}{C}.",
    "layout": "normal",
}

MOX_DIAMOND = {
    "id": "mox-diamond",
    "oracle_id": "mox-diamond-oracle",
    "name": "Mox Diamond",
    "mana_cost": "{0}",
    "cmc": 0,
    "colors": [],
    "color_identity": [],
    "type_line": "Artifact",
    "oracle_text": (
        "If this artifact would enter, you may discard a land card instead. "
        "If you do, put this artifact onto the battlefield. If you don't, "
        "put it into its owner's graveyard.\n{T}: Add one mana of any color."
    ),
    "layout": "normal",
}

UNDERWORLD_BREACH = {
    "id": "underworld-breach",
    "oracle_id": "underworld-breach-oracle",
    "name": "Underworld Breach",
    "mana_cost": "{1}{R}",
    "cmc": 2,
    "colors": ["R"],
    "color_identity": ["R"],
    "type_line": "Enchantment",
    "oracle_text": (
        "Each nonland card in your graveyard has escape. The escape cost is "
        "equal to the card's mana cost plus exile three other cards from your graveyard."
    ),
    "layout": "normal",
}

ENLIGHTENED_TUTOR = {
    "id": "enlightened-tutor",
    "oracle_id": "enlightened-tutor-oracle",
    "name": "Enlightened Tutor",
    "mana_cost": "{W}",
    "cmc": 1,
    "colors": ["W"],
    "color_identity": ["W"],
    "type_line": "Instant",
    "oracle_text": (
        "Search your library for an artifact or enchantment card, reveal it, "
        "then shuffle and put that card on top."
    ),
    "layout": "normal",
}

NECROPOTENCE = {
    "id": "necropotence",
    "oracle_id": "necropotence-oracle",
    "name": "Necropotence",
    "mana_cost": "{B}{B}{B}",
    "cmc": 3,
    "colors": ["B"],
    "color_identity": ["B"],
    "type_line": "Enchantment",
    "oracle_text": (
        "Skip your draw step.\n"
        "If a card or token would be put into your graveyard from anywhere, exile it instead."
    ),
    "layout": "normal",
}

FORCE_OF_NEGATION = {
    "id": "force-of-negation",
    "oracle_id": "force-of-negation-oracle",
    "name": "Force of Negation",
    "mana_cost": "{1}{U}{U}",
    "cmc": 3,
    "colors": ["U"],
    "color_identity": ["U"],
    "type_line": "Instant",
    "oracle_text": (
        "If it's not your turn, you may exile a blue card from your hand rather "
        "than pay this spell's mana cost.\nCounter target noncreature spell. "
        "If that spell is countered this way, exile it instead of putting it into "
        "its owner's graveyard."
    ),
    "layout": "normal",
}

BOSEIJU = {
    "id": "boseiju",
    "oracle_id": "boseiju-oracle",
    "name": "Boseiju, Who Endures",
    "mana_cost": "",
    "cmc": 0,
    "colors": [],
    "color_identity": ["G"],
    "type_line": "Legendary Land",
    "oracle_text": (
        "{T}: Add {G}.\n"
        "Channel - {1}{G}, Discard this card: Destroy target artifact, "
        "enchantment, or nonbasic land an opponent controls."
    ),
    "layout": "normal",
}

VOICE_OF_VICTORY = {
    "id": "voice-of-victory",
    "oracle_id": "voice-of-victory-oracle",
    "name": "Voice of Victory",
    "mana_cost": "{1}{W}",
    "cmc": 2,
    "colors": ["W"],
    "color_identity": ["W"],
    "type_line": "Creature - Human Bard",
    "oracle_text": "Your opponents can't cast spells during your turn.",
    "layout": "normal",
}

KUTZIL = {
    "id": "kutzil",
    "oracle_id": "kutzil-oracle",
    "name": "Kutzil, Malamet Exemplar",
    "mana_cost": "{1}{G}{W}",
    "cmc": 3,
    "colors": ["G", "W"],
    "color_identity": ["G", "W"],
    "type_line": "Legendary Creature - Cat Warrior",
    "oracle_text": "Your opponents can't cast spells during your turn.",
    "layout": "normal",
}

RANGER_CAPTAIN = {
    "id": "ranger-captain",
    "oracle_id": "ranger-captain-oracle",
    "name": "Ranger-Captain of Eos",
    "mana_cost": "{1}{W}{W}",
    "cmc": 3,
    "colors": ["W"],
    "color_identity": ["W"],
    "type_line": "Creature - Human Soldier",
    "oracle_text": (
        "When this creature enters, you may search your library for a creature card "
        "with mana value 1 or less, reveal it, put it into your hand, then shuffle.\n"
        "Sacrifice this creature: Your opponents can't cast noncreature spells this turn."
    ),
    "layout": "normal",
}


class InteractionWorkflowTest(unittest.TestCase):
    def test_v2_empty_template_loads(self):
        catalog = load_interactions(DEFAULT_V2_CATALOG_PATH)
        self.assertEqual(catalog.data["schema_version"], 2)
        self.assertEqual(catalog.cards, [])

    def test_v2_card_requires_base_data(self):
        data = self._v2_template()
        data["cards"].append(
            {
                "name": "Force of Will",
                "scryfall_id": "scryfall-force",
                "oracle_id": "oracle-force",
                "answers": [{"family": "counter", "scope": "any_spell"}],
                "cost_options": [{"mode": "mana", "generic": 3, "colors": ["U", "U"]}],
                "confidence": "reviewed",
                "review_notes": "已核对。",
            }
        )

        with self.assertRaises(InteractionCatalogError):
            self._load_temp_catalog(data)

    def test_v2_card_with_base_data_loads(self):
        data = self._v2_template()
        data["cards"].append(self._reviewed_force_card())
        catalog = self._load_temp_catalog(data)

        self.assertEqual(catalog.get_card("force of will")["base"]["mana_value"], 5)

    def test_v2_answer_requirements_and_channel_cost_load(self):
        data = self._v2_template()
        card = self._reviewed_force_card()
        card["answers"][0]["requirements"] = ["already_on_battlefield"]
        card["cost_options"] = [
            {
                "mode": "channel",
                "generic": 1,
                "colors": ["G"],
                "requires": ["discard_from_hand"],
            }
        ]
        data["cards"].append(card)
        catalog = self._load_temp_catalog(data)

        self.assertEqual(
            catalog.get_card("force of will")["answers"][0]["requirements"],
            ["already_on_battlefield"],
        )

    def test_extract_base_card_data_for_normal_card(self):
        base = extract_base_card_data(FORCE_OF_WILL)

        self.assertEqual(base["mana_cost"], "{3}{U}{U}")
        self.assertEqual(base["mana_value"], 5)
        self.assertEqual(base["colors"], ["U"])
        self.assertEqual(base["type_line"], "Instant")
        self.assertEqual(base["faces"], [])

    def test_extract_base_card_data_for_split_card(self):
        base = extract_base_card_data(WEAR_TEAR)

        self.assertEqual(base["mana_cost"], "{1}{R} // {W}")
        self.assertEqual(base["colors"], ["W", "R"])
        self.assertEqual(len(base["faces"]), 2)
        self.assertEqual(base["faces"][1]["name"], "Tear")

    def test_scryfall_index_finds_card_and_face_names(self):
        index = build_card_index([WEAR_TEAR, FORCE_OF_WILL])

        self.assertEqual(index.require("Force of Will")["id"], "scryfall-force")
        self.assertEqual(index.require("Wear")["id"], "scryfall-wear-tear")
        self.assertEqual(index.require("Tear")["id"], "scryfall-wear-tear")

    def test_suggest_cost_options_tracks_pitch_requirement(self):
        options = suggest_cost_options(FORCE_OF_WILL)

        self.assertIn(
            {"mode": "pitch", "requires": ["blue_card_in_hand"], "life": 1},
            options,
        )

    def test_suggest_interaction_fields_does_not_confuse_pitch_blue_for_target_blue(self):
        suggestion = suggest_interaction_fields(FORCE_OF_WILL)
        answer = suggestion["answers"][0]

        self.assertEqual(answer, {"family": "counter", "scope": "any_spell"})

    def test_suggest_interaction_fields_rejects_common_graveyard_false_positives(self):
        for card in (MOX_DIAMOND, UNDERWORLD_BREACH, NECROPOTENCE):
            with self.subTest(card=card["name"]):
                suggestion = suggest_interaction_fields(card)
                self.assertEqual(suggestion["answers"], [])

    def test_suggest_interaction_fields_does_not_treat_tutors_as_removal(self):
        suggestion = suggest_interaction_fields(ENLIGHTENED_TUTOR)

        self.assertEqual(suggestion["answers"], [])

    def test_force_of_negation_is_counter_not_graveyard_hate(self):
        suggestion = suggest_interaction_fields(FORCE_OF_NEGATION)

        self.assertEqual(
            suggestion["answers"],
            [{"family": "counter", "scope": "noncreature_spell"}],
        )

    def test_channel_interaction_uses_channel_timing_and_cost(self):
        suggestion = suggest_interaction_fields(BOSEIJU)

        self.assertEqual(
            suggestion["answers"],
            [{"family": "remove", "scope": "artifact_or_enchantment"}],
        )
        self.assertEqual(
            suggestion["cost_options"],
            [
                {
                    "mode": "channel",
                    "generic": 1,
                    "colors": ["G"],
                    "requires": ["discard_from_hand"],
                }
            ],
        )
        self.assertEqual(suggestion["timing"]["source"], "channel")
        self.assertTrue(suggestion["timing"]["usable_from_hand_as_response"])

    def test_during_your_turn_static_locks_do_not_stop_opponent_win_turn(self):
        for card in (VOICE_OF_VICTORY, KUTZIL):
            with self.subTest(card=card["name"]):
                suggestion = suggest_interaction_fields(card)
                self.assertEqual(suggestion["answers"], [])
                self.assertFalse(suggestion["timing"]["usable_from_hand_as_response"])

    def test_this_turn_activated_locks_can_stop_opponent_win_turn_if_in_play(self):
        suggestion = suggest_interaction_fields(RANGER_CAPTAIN)

        self.assertEqual(
            suggestion["answers"],
            [
                {
                    "family": "prevent_casting",
                    "scope": "noncreature_spells",
                    "requirements": ["already_on_battlefield"],
                }
            ],
        )
        self.assertFalse(suggestion["timing"]["usable_from_hand_as_response"])

    def test_decklist_text_parser_handles_quantities_and_sections(self):
        text = """
        Commander:
        1 Kinnan, Bonder Prodigy
        1x Force of Will
        2 Island [SLD]
        // side note
        """

        self.assertEqual(
            parse_decklist_text(text),
            ["Kinnan, Bonder Prodigy", "Force of Will", "Island"],
        )

    def test_topdeck_fixture_counts_one_copy_per_deck(self):
        payload = [
            {
                "standings": [
                    {"deckObj": {"mainboard": [{"name": "Force of Will"}, {"name": "Force of Will"}]}},
                    {"decklist": "1 Force of Will\n1 Swan Song"},
                ]
            }
        ]
        deck_count, counts = collect_card_frequencies(iter_deck_card_names(payload))
        ranked = ranked_frequencies(deck_count, counts, min_decks=1)

        self.assertEqual(deck_count, 2)
        self.assertEqual(counts["Force of Will"], 2)
        self.assertEqual(counts["Swan Song"], 1)
        self.assertEqual(ranked[0].name, "Force of Will")

    def test_topdeck_deck_obj_ignores_uuid_fields(self):
        uuid = "6ad8011d-3471-4369-9d68-b264cc027487"
        payload = [
            {
                "standings": [
                    {
                        "deckObj": {
                            "metadata": {"id": uuid, "name": "Blue Farm"},
                            "mainboard": {
                                uuid: {
                                    "id": uuid,
                                    "cardId": uuid,
                                    "name": "Force of Will",
                                    "quantity": 1,
                                },
                                "Swan Song": 1,
                            },
                        }
                    }
                ]
            }
        ]

        deck_count, counts = collect_card_frequencies(iter_deck_card_names(payload))

        self.assertEqual(deck_count, 1)
        self.assertEqual(counts["Force of Will"], 1)
        self.assertEqual(counts["Swan Song"], 1)
        self.assertNotIn(uuid, counts)
        self.assertNotIn("Blue Farm", counts)

    def test_topdeck_payload_can_be_limited_to_first_events(self):
        payload = [
            {"standings": [{"decklist": "1 Force of Will"}]},
            {"standings": [{"decklist": "1 Swan Song"}]},
            {"standings": [{"decklist": "1 Pact of Negation"}]},
        ]
        limited = limit_tournaments(payload, 2)
        summary = summarize_topdeck_payload(limited)

        self.assertEqual(summary["top_level_tournament_count"], 2)
        self.assertEqual(summary["deck_count"], 2)
        self.assertEqual(summary["unique_card_count"], 2)

    def test_topdeck_limited_fetch_uses_standings_for_selected_tids(self):
        module = __import__("cedh.interaction_candidates", fromlist=[""])
        original_post = module._post_topdeck_tournament_query
        original_standings = module.fetch_topdeck_tournament_standings
        calls = []

        module._post_topdeck_tournament_query = lambda *args, **kwargs: [
            {"TID": "event-1"},
            {"TID": "event-2"},
            {"TID": "event-3"},
        ]

        def fake_standings(api_key, tid):
            calls.append(tid)
            return [{"decklist": f"1 Force of Will\n1 {tid}"}]

        module.fetch_topdeck_tournament_standings = fake_standings
        try:
            payload = fetch_topdeck_tournaments("test", event_limit=2)
        finally:
            module._post_topdeck_tournament_query = original_post
            module.fetch_topdeck_tournament_standings = original_standings

        self.assertEqual(calls, ["event-1", "event-2"])
        self.assertEqual(len(payload), 2)
        self.assertEqual(topdeck_tournament_ids([{"TID": "event-1"}]), ["event-1"])

    def test_audit_reports_review_and_candidate_gaps(self):
        data = self._v2_template()
        card = self._reviewed_force_card()
        card["confidence"] = "needs_review"
        data["cards"].append(card)
        catalog = self._load_temp_catalog(data)
        candidates = {
            "candidates": [
                {"name": "Force of Will"},
                {"name": "Swan Song"},
            ]
        }

        report = audit_catalog(catalog, candidates=candidates)

        self.assertEqual(report["review_needed"], ["Force of Will"])
        self.assertEqual(report["missing_candidates"], ["Swan Song"])

    def test_processed_card_name_sets_are_normalized(self):
        data = self._v2_template()
        data["cards"].append(self._reviewed_force_card())
        catalog = self._load_temp_catalog(data)
        candidates = {"candidates": [{"name": "  force   of will "}, {"name": "Swan Song"}]}

        self.assertEqual(catalog_card_names(catalog), {"force of will"})
        self.assertEqual(candidate_card_names(candidates), {"force of will", "swan song"})

    def test_generate_candidates_reports_progress(self):
        messages = []
        original_fetch_topdeck = __import__(
            "cedh.interaction_candidates", fromlist=["fetch_topdeck_tournaments"]
        ).fetch_topdeck_tournaments

        module = __import__("cedh.interaction_candidates", fromlist=[""])
        module.fetch_topdeck_tournaments = lambda *args, **kwargs: [
            {"standings": [{"decklist": "1 Force of Will\n1 Island"}]}
        ]
        try:
            report = generate_candidates(
                api_key="test",
                min_decks=1,
                candidate_limit=2,
                card_index=build_card_index([FORCE_OF_WILL, ISLAND]),
                progress=messages.append,
            )
        finally:
            module.fetch_topdeck_tournaments = original_fetch_topdeck

        self.assertEqual(report["candidate_count"], 1)
        self.assertTrue(any("开始查询 TopDeck" in message for message in messages))
        self.assertTrue(any("识别" in message for message in messages))
        self.assertTrue(any("候选生成完成" in message for message in messages))

    def test_generate_candidates_continues_after_scryfall_lookup_error(self):
        messages = []
        original_fetch_topdeck = __import__(
            "cedh.interaction_candidates", fromlist=["fetch_topdeck_tournaments"]
        ).fetch_topdeck_tournaments

        module = __import__("cedh.interaction_candidates", fromlist=[""])
        module.fetch_topdeck_tournaments = lambda *args, **kwargs: [
            {"standings": [{"decklist": "1 Force of Will\n1 Not A Card"}]}
        ]
        try:
            report = generate_candidates(
                api_key="test",
                min_decks=1,
                candidate_limit=2,
                card_index=build_card_index([FORCE_OF_WILL]),
                progress=messages.append,
            )
        finally:
            module.fetch_topdeck_tournaments = original_fetch_topdeck

        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["lookup_error_count"], 1)
        self.assertTrue(any("本地索引未找到" in message for message in messages))

    def test_candidate_limit_applies_after_interaction_detection(self):
        original_fetch_topdeck = __import__(
            "cedh.interaction_candidates", fromlist=["fetch_topdeck_tournaments"]
        ).fetch_topdeck_tournaments

        module = __import__("cedh.interaction_candidates", fromlist=[""])
        module.fetch_topdeck_tournaments = lambda *args, **kwargs: [
            {
                "standings": [
                    {"decklist": "1 Island\n1 Sol Ring\n1 Force of Will"},
                    {"decklist": "1 Island\n1 Sol Ring"},
                    {"decklist": "1 Island\n1 Sol Ring"},
                    {"decklist": "1 Island\n1 Sol Ring\n1 Pact of Negation"},
                ]
            }
        ]
        try:
            report = generate_candidates(
                api_key="test",
                min_decks=1,
                candidate_limit=2,
                card_index=build_card_index(
                    [ISLAND, SOL_RING, FORCE_OF_WILL, PACT_OF_NEGATION]
                ),
            )
        finally:
            module.fetch_topdeck_tournaments = original_fetch_topdeck

        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["interaction_candidate_pool_count"], 2)
        self.assertEqual(
            {candidate["name"] for candidate in report["candidates"]},
            {"Force of Will", "Pact of Negation"},
        )
        self.assertEqual(report["candidates"][0]["base"]["type_line"], "Instant")
        self.assertEqual(report["candidates"][0]["base"]["colors"], ["U"])

    def _v2_template(self):
        with DEFAULT_V2_CATALOG_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _reviewed_force_card(self):
        return {
            "name": "Force of Will",
            "scryfall_id": FORCE_OF_WILL["id"],
            "oracle_id": FORCE_OF_WILL["oracle_id"],
            "base": extract_base_card_data(FORCE_OF_WILL),
            "answers": [{"family": "counter", "scope": "any_spell"}],
            "cost_options": [
                {"mode": "mana", "generic": 3, "colors": ["U", "U"]},
                {"mode": "pitch", "requires": ["blue_card_in_hand"], "life": 1},
            ],
            "confidence": "reviewed",
            "review_notes": "已核对 Oracle 文本和替代费用。",
        }

    def _load_temp_catalog(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interactions.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_interactions(path)


if __name__ == "__main__":
    unittest.main()
