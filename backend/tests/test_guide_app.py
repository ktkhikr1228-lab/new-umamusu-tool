import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from guide_app import db  # noqa: E402
from guide_app.config import load_config  # noqa: E402
from guide_app.importer import import_all, normalize_strategy, normalize_tier  # noqa: E402
from guide_app.skill_master import SkillMaster  # noqa: E402
from guide_app import review  # noqa: E402

HEADER = "race,strategy,tier,skill,source_file,status,memo\n"
MASTER = SkillMaster(["左回り○", "左回り◎", "末脚", "コーナー回復○"])


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class GuideAppImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "extracted"
        self.conn = db.connect(Path(self.tmp.name) / "guide.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM skills ORDER BY id")]

    def test_imports_nested_csv_and_uses_folder_as_event(self):
        write(self.root / "2026-11_LOH" / "kyoto_nige.csv",
              HEADER + "京都 芝 3000m,逃げ,super_recommended,左回り〇,a.png,draft,\n"
                       "京都 芝 3000m,nige,おすすめ,末脚,b.png,,unknown_skill:要確認\n")
        report = import_all(self.conn, self.root, MASTER)
        self.assertEqual(report.added, 2)
        rows = self.rows()
        self.assertEqual({r["event"] for r in rows}, {"2026-11_LOH"})
        self.assertEqual(rows[0]["extracted_skill"], "左回り〇")
        self.assertEqual(rows[0]["skill"], "左回り○")  # 丸の表記ゆれはマスタ表記に補正
        self.assertEqual(rows[1]["strategy"], "逃げ")
        self.assertEqual(rows[1]["tier"], "recommended")
        self.assertEqual(rows[1]["status"], "draft")
        self.assertEqual(rows[1]["memo"], "unknown_skill:要確認")

    def test_reimport_keeps_manual_edits_and_skips_unchanged_files(self):
        path = write(self.root / "ev1" / "a.csv", HEADER + "東京 芝 2400m,差し,recommended,末脚,a.png,draft,\n")
        import_all(self.conn, self.root, MASTER)
        with self.conn:
            self.conn.execute("UPDATE skills SET skill = '直した名前', status = 'ready'")
        self.assertEqual(import_all(self.conn, self.root, MASTER).unchanged, 1)

        write(path, path.read_text(encoding="utf-8") + "東京 芝 2400m,差し,recommended,左回り○,b.png,draft,\n")
        report = import_all(self.conn, self.root, MASTER)
        self.assertEqual((report.added, report.files[0].skipped), (1, 1))
        first = self.rows()[0]
        self.assertEqual((first["skill"], first["status"]), ("直した名前", "ready"))

    def test_same_skill_in_different_events_is_kept_separately(self):
        line = "東京 芝 2400m,差し,recommended,末脚,a.png,draft,\n"
        write(self.root / "2026-06_CM" / "a.csv", HEADER + line)
        write(self.root / "2026-12_CM" / "a.csv", HEADER + line)
        import_all(self.conn, self.root, MASTER)
        self.assertEqual(sorted(r["event"] for r in self.rows()), ["2026-06_CM", "2026-12_CM"])

    def test_reports_missing_columns_and_bad_rows_without_failing(self):
        write(self.root / "ev" / "broken.csv", "foo,bar\n1,2\n")
        write(self.root / "ev" / "bad_row.csv", HEADER + "東京 芝 2400m,謎,recommended,末脚,,,\n")
        report = import_all(self.conn, self.root, MASTER)
        self.assertEqual(report.added, 0)
        self.assertEqual(len(report.problems), 2)
        self.assertIn("必要な列", report.problems[1])

    def test_japanese_headers_and_root_level_csv(self):
        write(self.root / "x.csv", "レース,脚質,区分,スキル,状態\n中山 芝 2500m,追い込み,超おすすめ,末脚,確認済み\n")
        import_all(self.conn, self.root, MASTER)
        row = self.rows()[0]
        self.assertEqual((row["event"], row["strategy"], row["tier"], row["status"]),
                         ("unknown", "追込", "super_recommended", "ready"))

    def test_status_counts(self):
        write(self.root / "ev" / "a.csv", HEADER + "東京 芝 2400m,差し,recommended,末脚,,ready,\n"
                                                  "東京 芝 2400m,差し,recommended,左回り○,,,\n")
        import_all(self.conn, self.root, MASTER)
        counts = dict(db.status_counts(self.conn)[0])
        self.assertEqual((counts["total"], counts["ready"], counts["draft"], counts["unpublished"]), (2, 1, 1, 1))

    def test_status_constraint_rejects_unknown_values(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO skills (event, race, strategy, tier, extracted_skill, skill, status)"
                              " VALUES ('e','r','逃げ','recommended','s','s','bogus')")


class GuideAppHelpersTests(unittest.TestCase):
    def test_normalizers(self):
        self.assertEqual(normalize_strategy("2_senkou"), "先行")
        self.assertIsNone(normalize_strategy("謎"))
        self.assertEqual(normalize_tier("super"), "super_recommended")
        self.assertIsNone(normalize_tier("?"))

    def test_skill_master_matching(self):
        self.assertEqual(MASTER.canonical("左回り◯"), "左回り○")
        self.assertIsNone(MASTER.canonical("左回り"))
        self.assertIn("コーナー回復○", MASTER.suggest("コーナ回復○"))

    def test_config_defaults_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = write(Path(tmp) / "c.toml", 'data_root = "data"\nport = 9000\n')
            os.environ.pop("GUIDE_APP_CONFIG", None)
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.extracted_dir, Path(tmp).resolve() / "data" / "extracted")
            self.assertEqual(cfg.port, 9000)
            self.assertTrue(cfg.skill_master_path.name == "skill_master.json")


class GuideAppReviewTests(unittest.TestCase):
    RACE, STRAT, EV = "東京 芝 2400m", "逃げ", "ev"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "extracted"
        self.conn = db.connect(Path(self.tmp.name) / "guide.sqlite3")
        write(self.root / self.EV / "a.csv", HEADER + "\n".join([
            f"{self.RACE},逃げ,super_recommended,末脚,1.png,,",
            f"{self.RACE},逃げ,super_recommended,謎スキル,1.png,,",
            f"{self.RACE},逃げ,super_recommended,左回り◎,1.png,,",
            f"{self.RACE},逃げ,super_recommended,左回り○,1.png,,",
            f"{self.RACE},逃げ,recommended,コーナー回復○,2.png,,",
            f"{self.RACE},逃げ,recommended,末脚,2.png,,",
        ]) + "\n")
        import_all(self.conn, self.root, MASTER)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def group(self):
        return review.group(self.conn, MASTER, self.EV, self.RACE, self.STRAT)

    def rows(self):
        return {(r["source_file"], r["skill"], r["tier"]): r for im in self.group()["images"] for r in im["rows"]}

    def test_attention_reasons(self):
        rows = self.rows()
        self.assertIn("スキルマスタにない名前", rows[("1.png", "謎スキル", "super_recommended")]["attention"])
        self.assertIn("同じ画像に○と◎の両方がある", rows[("1.png", "左回り○", "super_recommended")]["attention"])
        self.assertIn("◎は○との読み違いが多い", rows[("1.png", "左回り◎", "super_recommended")]["attention"])
        self.assertIn("超おすすめ・おすすめの両方にある", rows[("2.png", "末脚", "recommended")]["attention"])
        self.assertEqual(rows[("2.png", "コーナー回復○", "recommended")]["attention"], [])

    def test_review_image_approves_only_matched_rows(self):
        result = review.review_image(self.conn, MASTER, self.EV, "2.png", self.RACE, self.STRAT)
        self.assertEqual(result, {"approved": 1, "pending": 1, "already_reviewed": False})
        rows = self.rows()
        self.assertEqual(rows[("2.png", "コーナー回復○", "recommended")]["status"], "ready")
        self.assertEqual(rows[("2.png", "末脚", "recommended")]["status"], "draft")
        image = next(i for i in self.group()["images"] if i["file"] == "2.png")
        self.assertIsNotNone(image["reviewed_at"])

    def test_update_row_and_validation(self):
        row = self.rows()[("1.png", "謎スキル", "super_recommended")]
        updated = review.update_row(self.conn, row["id"], {"skill": "左回り○", "status": "ready"})
        self.assertEqual((updated["skill"], updated["extracted_skill"], updated["status"]), ("左回り○", "謎スキル", "ready"))
        for bad in ({"status": "bogus"}, {"tier": "x"}, {"skill": " "}, {"event": "x"}, {}):
            with self.assertRaises(review.ReviewError):
                review.update_row(self.conn, row["id"], bad)
        with self.assertRaises(review.ReviewError):
            review.update_row(self.conn, 99999, {"status": "ready"})

    def test_bulk_tier_change_marks_duplicates_rejected(self):
        result = review.set_images_tier(self.conn, self.EV, self.RACE, self.STRAT, ["2.png"], "super_recommended")
        self.assertEqual(result, {"changed": 1, "duplicates": 1})
        rows = self.rows()
        self.assertEqual(rows[("2.png", "コーナー回復○", "super_recommended")]["status"], "draft")
        dup = rows[("2.png", "末脚", "recommended")]  # 1.pngに超おすすめの末脚があるので区分は変えず却下
        self.assertEqual((dup["status"], dup["memo"]), ("rejected", "区分変更時に重複"))
        with self.assertRaises(review.ReviewError):
            review.set_images_tier(self.conn, self.EV, self.RACE, self.STRAT, [], "recommended")

    def test_row_tier_conflict_is_explained(self):
        row = self.rows()[("2.png", "末脚", "recommended")]
        with self.assertRaises(review.ReviewError):
            review.update_row(self.conn, row["id"], {"tier": "super_recommended"})

    def test_overview_counts_reviewed_images(self):
        review.review_image(self.conn, MASTER, self.EV, "2.png", self.RACE, self.STRAT)
        ev = review.overview(self.conn)[0]
        self.assertEqual((ev["images"], ev["images_reviewed"], ev["ready"]), (2, 1, 1))

    def test_hidden_events_go_last_and_can_be_restored(self):
        write(self.root / "smoke-test" / "a.csv", HEADER + f"{self.RACE},逃げ,recommended,末脚,9.png,,\n")
        import_all(self.conn, self.root, MASTER)
        review.set_event_hidden(self.conn, "smoke-test", True)
        events = review.overview(self.conn)
        self.assertEqual([(e["event"], e["hidden"]) for e in events], [("ev", False), ("smoke-test", True)])
        review.set_event_hidden(self.conn, "smoke-test", False)
        self.assertFalse(any(e["hidden"] for e in review.overview(self.conn)))
        with self.assertRaises(review.ReviewError):
            review.set_event_hidden(self.conn, "none", True)

    def test_review_image_twice_reports_already_reviewed(self):
        first = review.review_image(self.conn, MASTER, self.EV, "2.png", self.RACE, self.STRAT)
        second = review.review_image(self.conn, MASTER, self.EV, "2.png", self.RACE, self.STRAT)
        self.assertEqual((first["already_reviewed"], second["already_reviewed"], second["approved"]), (False, True, 0))

    def test_image_index_prefers_event_folder(self):
        shots = Path(self.tmp.name) / "shots"
        write(shots / "other" / "x.png", "a")
        write(shots / "inbox" / "ev" / "1_nige" / "x.png", "b")
        index = review.ImageIndex(shots)
        self.assertEqual(index.find("ev", "x.png").read_text(), "b")
        self.assertEqual(index.find("ev", "C:\\uma\\x.png").read_text(), "b")
        self.assertIsNone(index.find("ev", "none.png"))


if __name__ == "__main__":
    unittest.main()
