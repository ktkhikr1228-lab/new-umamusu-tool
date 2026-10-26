import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_gametora_cards as importer
import research_missing_card_skills as research

ROOT = Path(__file__).resolve().parents[2]


class ReviewedSkillSupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.supplements = importer.read_json(ROOT / "backend/data/reviewed_skill_supplements.json")
        cls.skills = {s["id"]: s["name"] for c in cls.supplements["cards"] for s in c["skills"]}
        cls.gold = {"神速"}

    def cards(self):
        return [{"id": int(c["source_id"]), **{k:c[k] for k in ["source_id","char","card","rarity","type"]},
                 "name": importer.build_card_name(c["card"], c["char"]), "skills": [], "rare_skills": []}
                for c in self.supplements["cards"]]

    def apply(self, cards=None, supplements=None):
        return importer.apply_reviewed_skill_supplements(self.cards() if cards is None else cards,
            self.supplements if supplements is None else supplements, self.skills, self.gold)

    def test_azuma_r_and_ssr_skills_and_gold_without_input_mutation(self):
        cards = self.cards()
        before = copy.deepcopy(cards)
        result, report = self.apply(cards)
        self.assertEqual(result[0]["skills"], ["快速", "末脚", "弧を描いて"])
        self.assertEqual(result[0]["rare_skills"], [])
        self.assertEqual(result[1]["skills"], ["快速", "末脚", "弧を描いて", "神速"])
        self.assertEqual(result[1]["rare_skills"], ["神速"])
        self.assertEqual([r["status"] for r in report], ["applied", "applied"])
        self.assertEqual(cards, before)

    def test_source_recovers_and_is_authoritative_on_disagreement(self):
        cards = self.cards()
        cards[0]["skills"] = ["快速"]
        cards[1]["skills"] = ["弧を描いて", "末脚", "快速", "神速"]
        cards[1]["rare_skills"] = ["神速"]
        result, report = self.apply(cards)
        self.assertEqual(result, cards)
        self.assertEqual(report[0]["status"], "source_differs")
        self.assertEqual(report[0]["only_in_supplement"], ["弧を描いて", "末脚"])
        self.assertEqual(report[1]["status"], "source_matches")

    def test_wrong_identity_and_unknown_skill_fail(self):
        for field, value in [("char","別人"),("rarity","SSR"),("card","別版"),("type","根性")]:
            supplement = copy.deepcopy(self.supplements)
            supplement["cards"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity"):
                self.apply(supplements=supplement)
        for field,value in [("id","999999"),("name","間違った名前")]:
            supplement = copy.deepcopy(self.supplements)
            supplement["cards"][0]["skills"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "skill"):
                self.apply(supplements=supplement)

    def test_invalid_provenance_and_duplicates_fail(self):
        for key,value in [("sources",[]),("sources",["http://example.com"]),("reviewed_on","")]:
            supplement=copy.deepcopy(self.supplements)
            supplement["cards"][0][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.apply(supplements=supplement)
        supplement=copy.deepcopy(self.supplements)
        supplement["cards"].append(supplement["cards"][0])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.apply(supplements=supplement)

    def test_unknown_card_is_not_added(self):
        self.assertEqual(self.apply(cards=[]), ([], []))
        with self.assertRaises(ValueError):
            self.apply(supplements={"schema_version": 2, "cards": []})

    def test_cli_repeat_import_preserves_supplement_and_raw_missing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=[{"support_id":int(c["source_id"]),"name_jp":c["char"],"title_ja":c["card"],
                  "rarity":c["rarity"],"type":"friend"} for c in self.supplements["cards"]]
            importer.write_json(root/"raw.json",raw)
            importer.write_json(root/"skills.json",[{"id":int(k),"jpname":v,"rarity":2 if v in self.gold else 1} for k,v in self.skills.items()])
            command=[sys.executable, importer.__file__,"--support-cards",str(root/"raw.json"),
                     "--skills",str(root/"skills.json"),"--cards-json",str(root/"cards.json"),
                     "--factor-skill-aliases-json",str(root/"aliases.json"),"--no-backup"]
            first=subprocess.run(command,check=True,capture_output=True,text=True,encoding="utf-8")
            report=json.loads(first.stdout)
            self.assertEqual(report["missing_skill_card_count"],2)
            self.assertEqual(report["skill_supplement_count"],2)
            before=(root/"cards.json").read_bytes()
            subprocess.run(command,check=True,capture_output=True)
            self.assertEqual(before,(root/"cards.json").read_bytes())
            # Applied fallback cards must not suppress raw-upstream research.
            calls=[]
            def fetch(url):
                calls.append(url)
                return "no results"
            result,_=research.research_missing(report,importer.read_json(root/"cards.json"),self.skills,fetch=fetch)
            self.assertEqual(len(result["cards"]),2)
            self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
