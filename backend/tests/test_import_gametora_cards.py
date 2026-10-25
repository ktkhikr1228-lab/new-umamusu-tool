import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_gametora_cards as importer


class GameToraImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).parent / "fixtures/gametora.json").read_text(encoding="utf-8"))
        cls.skills = importer.make_skill_map(cls.fixture["skills"])

    def event_map(self):
        return importer.make_event_skill_map(
            [self.fixture["ssr"], self.fixture["sr"]], self.skills, self.fixture["rewards"]
        )

    def test_real_ssr_reward_references_use_offset(self):
        self.assertEqual(self.event_map()["30001"], ["軽やかステップ", "直滑降", "末脚", "全身全霊"])

    def test_real_sr_choices_and_bond_rewards(self):
        self.assertEqual(self.event_map()["20001"], ["追込焦り"])

    def test_array_events_require_dictionary(self):
        with self.assertRaisesRegex(ValueError, "event-rewards"):
            importer.make_event_skill_map([self.fixture["ssr"]], self.skills)

    def test_invalid_reference_fails_instead_of_misclassifying(self):
        for reference in [35, 99999, True, "472"]:
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                importer.extract_array_event_skill_ids([[557, [[28, [reference]]]]], self.fixture["rewards"])

    def test_history_and_metadata_are_not_current_rewards(self):
        event = [557, [[28, [472]]], 200511, [9, [["pre_first_anni", [558, [[28, [473]]]]]]]]
        self.assertEqual(importer.extract_array_event_skill_ids([event], self.fixture["rewards"]), ["201142"])

    def test_duplicate_cards_and_files_merge_stably(self):
        data = self.fixture["ssr"]
        actual = importer.make_event_skill_map([data, data], self.skills, self.fixture["rewards"])
        self.assertEqual(actual["30001"], self.event_map()["30001"])

    def test_named_event_format_still_supported(self):
        self.assertEqual(importer.make_event_skill_map([
            [{"support_card_id": 30001, "skills": [200511]}]
        ], self.skills), {"30001": ["全身全霊"]})

    def test_gold_classification_is_from_skill_rarity(self):
        cards = importer.convert_support_cards(self.fixture["cards"], self.skills, self.event_map(),
            importer.make_rare_skill_names(self.fixture["skills"], self.skills))
        by_id = {card["source_id"]: card for card in cards}
        self.assertEqual(by_id["30001"]["rare_skills"], ["全身全霊"])
        self.assertEqual(by_id["20001"]["rare_skills"], [])
        self.assertIn("栄養補給", by_id["30001"]["skills"])
        self.assertEqual(len(by_id["30001"]["skills"]), len(set(by_id["30001"]["skills"])))

    def test_skill_rarity_does_not_assume_all_event_skills_are_gold(self):
        self.assertEqual(importer.make_rare_skill_names([
            {"id": 1, "jpname": "gold", "rarity": "2"},
            {"id": 2, "jpname": "normal", "rarity": 1},
            {"id": 3, "jpname": "unique", "rarity": 5},
        ], {"1": "gold", "2": "normal", "3": "unique"}), {"gold"})

    def test_cli_offline_paths_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for key in ("cards", "skills", "ssr", "sr", "rewards"):
                paths[key] = root / (key + ".json")
                paths[key].write_text(json.dumps(self.fixture[key]), encoding="utf-8")
            output = root / "output.json"
            aliases = root / "aliases.json"
            command = [sys.executable, str(Path(importer.__file__)),
                "--support-cards", str(paths["cards"]), "--skills", str(paths["skills"]),
                "--ssr-events", str(paths["ssr"]), "--sr-events", str(paths["sr"]),
                "--event-rewards", str(paths["rewards"]), "--cards-json", str(output),
                "--factor-skill-aliases-json", str(aliases), "--no-backup"]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(first.stdout)["event_card_count"], 2)
            before = output.read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(before, output.read_bytes())
            self.assertEqual(len(json.loads(before)), 2)
            self.assertTrue(aliases.exists())

    def test_merge_preserves_ids_and_is_idempotent(self):
        cards = importer.convert_support_cards(self.fixture["cards"], self.skills, self.event_map())
        existing = [{**cards[0], "id": 7}]
        merged, _, _ = importer.merge_cards(existing, cards, False)
        again, _, _ = importer.merge_cards(merged, cards, False)
        self.assertEqual(merged, again)
        self.assertEqual(merged[0]["id"], 7)


if __name__ == "__main__":
    unittest.main()
