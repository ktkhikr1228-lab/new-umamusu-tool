import json
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
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

    def friend_fixture(self):
        return json.loads((Path(__file__).parent / "fixtures/gametora_friend.json").read_text(encoding="utf-8"))

    def test_real_friend_card_specific_rewards_and_gold(self):
        f = self.friend_fixture()
        skills = importer.make_skill_map(f["skills"])
        events = importer.make_friend_event_skill_map(f["friend"], f["cards"], skills, f["rewards"])
        self.assertEqual(events["10021"], ["展開窺い", "尻尾上がり", "集中力"])
        self.assertEqual(events["30021"], ["展開窺い", "尻尾上がり", "集中力", "コンセントレーション"])
        self.assertEqual(events["30305"], ["心惹かれて", "中盤巧者", "遊びはおしまいっ！", "お先に失礼っ！"])
        cards = importer.convert_support_cards(f["cards"], skills, events,
            importer.make_rare_skill_names(f["skills"], skills))
        self.assertEqual(cards[-1]["rare_skills"], ["お先に失礼っ！"])
        self.assertNotIn("コンセントレーション", cards[-1]["skills"])

    def test_friend_history_disabled_and_no_reward_events(self):
        event = [1, [[1, [36]]], 1, [9, [["old", [1, [[1, [37]]]]]]]]
        cards = [{"support_id": 10, "char_id": 90, "type": "friend"}]
        data = [[90, [None, event], [[1, "no", 1]], [[1, [[1, [37]]], 1, [14]]]], [None, [], [], []]]
        self.assertEqual(importer.make_friend_event_skill_map(data, cards,
            {"1": "current", "2": "old"}, [["sk", 1, 1], ["sk", 1, 2]]), {"10": ["current"]})
        override = [1, [[1, [36]]], 1, [2, [[10, [1, "no", 1, [14]]]]]]
        self.assertIsNone(importer.select_friend_event(override, "10"))
        self.assertIsNone(importer.select_friend_event(event + [[14]], "10"))

    def test_friend_char_id_does_not_leak_to_other_cards(self):
        f = self.friend_fixture()
        cards = f["cards"] + [{"support_id": 999, "char_id": 9052, "type": "friend"},
                              {"support_id": 998, "char_id": 9001, "type": "speed"}]
        events = importer.make_friend_event_skill_map(f["friend"], cards,
            importer.make_skill_map(f["skills"]), f["rewards"])
        self.assertNotIn("999", events)
        self.assertNotIn("998", events)

    def test_missing_skill_report_distinguishes_absent_friend_record(self):
        cards = [{"source_id": "1", "name": "missing", "type": "友人", "skills": []},
                 {"source_id": "2", "name": "empty", "type": "友人", "skills": []},
                 {"source_id": "3", "name": "known", "type": "友人", "skills": ["hint"]}]
        report = importer.find_missing_skill_cards(cards, {"2": []})
        self.assertEqual([r["reason"] for r in report],
                         ["friend_events_not_in_source", "no_resolved_skills"])
        self.assertEqual(importer.find_missing_skill_cards(cards)[0]["reason"], "no_resolved_skills")

    def test_friend_invalid_input_and_missing_dictionary_fail(self):
        f = self.friend_fixture()
        for data in [{}, [[1, []]], [[None, [123], [], []]], [[9001, [], [None], []]]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                importer.make_friend_event_skill_map(data, f["cards"], {}, f["rewards"])
        with self.assertRaisesRegex(ValueError, "event-rewards"):
            importer.make_friend_event_skill_map(f["friend"], f["cards"], {}, None)
        with self.assertRaisesRegex(ValueError, "reference"):
            importer.make_friend_event_skill_map([[9001, [[1, [[1, [35]]]]], [], []]],
                f["cards"], {}, f["rewards"])

    def test_download_latest_includes_friend_events(self):
        manifest = {target["manifest_key"]: "hash" for target in importer.DOWNLOAD_TARGETS.values()}
        with patch.object(importer, "fetch_manifest", return_value=(manifest, "manifest")), \
                patch.object(importer, "download_file") as download:
            result = importer.download_latest_gametora_files(Path("unused"), ["manifest"])
        self.assertIn("friend_events", result)
        self.assertTrue(any("training_events/friend.hash.json" in call.args[0]
                            for call in download.call_args_list))

    def test_friend_cli_integration_and_idempotence(self):
        f = self.friend_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in f.items():
                (root / (key + ".json")).write_text(json.dumps(value), encoding="utf-8")
            output = root / "output.json"
            command = [sys.executable, str(Path(importer.__file__)),
                "--support-cards", str(root / "cards.json"), "--skills", str(root / "skills.json"),
                "--friend-events", str(root / "friend.json"), "--event-rewards", str(root / "rewards.json"),
                "--cards-json", str(output), "--factor-skill-aliases-json", str(root / "aliases.json"), "--no-backup"]
            first = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
            report = json.loads(first.stdout)
            self.assertEqual(report["friend_event_card_count"], 3)
            self.assertEqual(report["missing_skill_card_count"], 0)
            before = output.read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(before, output.read_bytes())

    def test_merge_preserves_ids_and_is_idempotent(self):
        cards = importer.convert_support_cards(self.fixture["cards"], self.skills, self.event_map())
        existing = [{**cards[0], "id": 7}]
        merged, _, _ = importer.merge_cards(existing, cards, False)
        again, _, _ = importer.merge_cards(merged, cards, False)
        self.assertEqual(merged, again)
        self.assertEqual(merged[0]["id"], 7)


if __name__ == "__main__":
    unittest.main()
