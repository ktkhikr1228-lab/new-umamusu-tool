import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import research_missing_card_skills as research

R_URL = "https://gamewith.jp/uma-musume/article/show/584373"
SSR_URL = "https://game8.jp/umamusume/836270"
CARD = {"id": 10149, "source_id": "10149", "name": "［巫女］吾妻", "char": "吾妻",
        "card": "巫女", "rarity": "R", "skills": []}
SKILLS = {"1": "快速", "2": "末脚", "3": "神速", "4": "弧を描いて"}
PAGE = """<title>吾妻(Rサポート)の評価とイベント</title><h2>巫女</h2>
<h3>育成イベント</h3><a>快速</a><a>末脚</a><a>弧を描いて</a>
<h3>おすすめサポカ</h3><a>神速</a><script>快速</script>"""


class ResearchMissingSkillsTests(unittest.TestCase):
    def test_extracts_only_skill_sections_and_exact_names(self):
        evidence = research.extract_evidence(PAGE, CARD, SKILLS, R_URL)
        self.assertEqual([s["name"] for s in evidence["skills"]], sorted(["弧を描いて", "末脚", "快速"]))
        self.assertIsNone(research.extract_evidence(PAGE.replace("<a>快速</a><a>末脚</a><a>弧を描いて</a>", "快速を習得できる。神速以上。"), CARD, SKILLS, R_URL))

    def test_rejects_other_rarity_character_and_card_title(self):
        for page in [PAGE.replace("(R", "(SSR"), PAGE.replace("吾妻", "別人"), PAGE.replace("巫女", "別カード")]:
            with self.subTest(page=page):
                self.assertIsNone(research.extract_evidence(page, CARD, SKILLS, R_URL))

    def test_limits_source_urls(self):
        for url in ["http://gamewith.jp/uma-musume/article/show/1", "https://gamewith.jp.evil.test/uma-musume/article/show/1",
                    "https://gamewith.jp@evil.test/uma-musume/article/show/1", "https://gamewith.jp/other/1"]:
            self.assertFalse(research.source_url(url))
        self.assertTrue(research.source_url(R_URL))

    def fetch(self, url):
        if url.startswith("https://search.yahoo.co.jp/"):
            return f'<a href="{R_URL}">R</a><a href="{SSR_URL}">SSR</a>'
        if url == R_URL:
            return PAGE
        return PAGE.replace("(R", "(SSR").replace("巫女", "いとどめでたき、まつりかな")

    def test_only_missing_cards_are_searched_and_inputs_unchanged(self):
        cards = [copy.deepcopy(CARD), {**CARD, "id": 2, "source_id": "2", "skills": ["快速"]}]
        before = copy.deepcopy(cards)
        calls = []
        def fetch(url):
            calls.append(url)
            return self.fetch(url)
        report, changes = research.research_missing({"missing_skill_cards": [{"source_id": "10149"}]}, cards, SKILLS, fetch=fetch)
        self.assertEqual(len(report["cards"]), 1)
        self.assertEqual(report["cards"][0]["status"], "needs_review")
        self.assertEqual(len([c for c in calls if c.startswith("https://search.yahoo.co.jp/")]), 1)
        self.assertEqual(changes["added"], ["10149"])
        self.assertEqual(cards, before)
        self.assertFalse(report["automatic_application"])

    def test_stable_results_and_resolved_cards_do_not_repeat_search(self):
        missing = {"missing_skill_cards": [{"source_id": "10149"}]}
        first, _ = research.research_missing(missing, [CARD], SKILLS, fetch=self.fetch)
        second, changes = research.research_missing(missing, [CARD], SKILLS, first, self.fetch)
        self.assertEqual(first, second)
        self.assertEqual(changes, {"added": [], "changed": [], "resolved": []})
        def fail(url):
            self.fail("No search should run for resolved cards")
        report, changes = research.research_missing({"missing_skill_cards": []}, [CARD], SKILLS, first, fail)
        self.assertEqual(report["cards"], [])
        self.assertEqual(changes["resolved"], ["10149"])

    def test_failures_are_visible_and_previous_evidence_stays_separate(self):
        first, _ = research.research_missing({"missing_skill_cards": [{"source_id": "10149"}]}, [CARD], SKILLS, fetch=self.fetch)
        def fetch(url):
            if url == R_URL:
                raise TimeoutError("temporarily blocked")
            return self.fetch(url)
        report, _ = research.research_missing({"missing_skill_cards": [{"source_id": "10149"}]}, [CARD], SKILLS, first, fetch)
        result = report["cards"][0]
        self.assertEqual(result["status"], "fetch_failed")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["errors"])
        self.assertTrue(result["previous_evidence"])
        def search_fail(url):
            raise TimeoutError()
        self.assertEqual(research.research_card(CARD, SKILLS, search_fail)["status"], "search_failed")

    def test_changes_detect_new_candidates(self):
        missing = {"missing_skill_cards": [{"source_id": "10149"}]}
        first, _ = research.research_missing(missing, [CARD], SKILLS, fetch=self.fetch)
        def fetch(url):
            return self.fetch(url).replace("<a>末脚</a>", "")
        _, changes = research.research_missing(missing, [CARD], SKILLS, first, fetch)
        self.assertEqual(changes["changed"], ["10149"])

    def test_shorter_query_fallback_stays_card_specific(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if "search.yahoo.co.jp" in url:
                return "no links" if len(calls) == 1 else f'<a href="{R_URL}">result</a>'
            return PAGE
        entry = research.research_card(CARD, SKILLS, fetch)
        self.assertEqual(entry["status"], "needs_review")
        self.assertEqual(len(entry["searches"]), 2)
        self.assertIn("吾妻 R", entry["searches"][1]["query"])

    def test_no_results_is_explicit(self):
        entry = research.research_card(CARD, SKILLS, lambda url: "no results")
        self.assertEqual(entry["status"], "not_found")
        self.assertEqual(entry["candidates"], [])

    def test_cli_no_missing_cards_needs_no_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in [("import", {"missing_skill_cards": []}), ("cards", [CARD]), ("skills", [])]:
                (root / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")
            before = (root / "cards.json").read_bytes()
            run = subprocess.run([sys.executable, research.__file__, "--import-report", str(root / "import.json"),
                "--cards-json", str(root / "cards.json"), "--skills", str(root / "skills.json"),
                "--report-json", str(root / "report.json"), "--summary", str(root / "summary.md")],
                capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertEqual(json.loads(run.stdout)["target_count"], 0)
            self.assertEqual(before, (root / "cards.json").read_bytes())
            self.assertIn("自動反映していません", (root / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
