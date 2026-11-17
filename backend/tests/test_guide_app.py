import json
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
from guide_app import publish  # noqa: E402
from guide_app import extract  # noqa: E402
from contextlib import contextmanager  # noqa: E402

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


class GuideAppPublishTests(unittest.TestCase):
    RACE = "東京 芝 2400m"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "extracted"
        self.conn = db.connect(Path(self.tmp.name) / "guide.sqlite3")
        write(self.root / "ev" / "a.csv", HEADER + "\n".join([
            f"{self.RACE},逃げ,super_recommended,末脚,1.png,ready,",          # サイトと同じ → 変更なし
            f"{self.RACE},逃げ,super_recommended,左回り◯,1.png,ready,",       # サイトではおすすめ → 区分変更
            f"{self.RACE},逃げ,recommended,コーナー回復○,2.png,ready,",       # サイトにない → 追加
            f"{self.RACE},逃げ,recommended,左回り◎,2.png,,",                  # 未確認 → 含めない
            f"{self.RACE},逃げ,recommended,謎スキル,2.png,ready,",             # マスタにない → 公開できない
        ]) + "\n")
        import_all(self.conn, self.root, MASTER)
        self.site = publish.Published({self.RACE: {"逃げ": {"super_recommended": ["末脚"], "recommended": ["左回り○"]}}})

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def plan(self):
        return publish.plan_event(self.conn, MASTER, self.site, "ev")

    def test_published_status(self):
        self.assertEqual(self.site.status(self.RACE, "逃げ", "末脚", "super_recommended"), "same")
        self.assertEqual(self.site.status(self.RACE, "逃げ", "左回り◯", "super_recommended"), "moved")
        self.assertEqual(self.site.status(self.RACE, "先行", "末脚", "super_recommended"), "new")

    def test_plan_splits_rows_by_what_changes(self):
        plan = self.plan()
        self.assertEqual([r["skill"] for r in plan.added], ["コーナー回復○"])
        self.assertEqual([(r["skill"], r["current_tier"]) for r in plan.moved], [("左回り○", "recommended")])
        self.assertEqual((plan.unchanged, plan.draft), (1, 1))
        self.assertEqual([r["skill"] for r in plan.blocked], ["謎スキル"])

    def test_send_refuses_blocked_rows_then_records_success(self):
        calls = []
        with self.assertRaises(publish.PublishError):
            publish.send(self.conn, self.plan(), MASTER.names, Path("unused"), dispatch=lambda *a: calls.append(a))
        with self.conn:
            self.conn.execute("UPDATE skills SET status = 'rejected' WHERE skill = '謎スキル'")
        dry = publish.send(self.conn, self.plan(), MASTER.names, Path("unused"), dry_run=True)
        self.assertEqual((dry["rows"], dry["requests"], dry["sent"], calls), (2, 1, False, []))

        token = write(Path(self.tmp.name) / "token", "secret\n")
        result = publish.send(self.conn, self.plan(), MASTER.names, token, dispatch=lambda req, tok: calls.append((req, tok)))
        self.assertTrue(result["sent"])
        self.assertEqual(calls[0][1], "secret")
        self.assertEqual({r["skill"] for r in calls[0][0]["rows"]}, {"コーナー回復○", "左回り○"})
        after = self.plan()
        self.assertEqual((after.rows, after.requested), ([], 2))  # 送った行は二重に依頼しない
        self.assertEqual(publish.history(self.conn)[0]["rows"], 2)
        self.assertEqual(publish.reset_requested(self.conn, "ev"), 2)
        self.assertEqual(len(self.plan().rows), 2)

    def test_failed_dispatch_is_reported_and_logged(self):
        with self.conn:
            self.conn.execute("UPDATE skills SET status = 'rejected' WHERE skill = '謎スキル'")
        token = write(Path(self.tmp.name) / "token", "secret")

        def boom(req, tok):
            raise RuntimeError("network down")
        with self.assertRaises(publish.PublishError):
            publish.send(self.conn, self.plan(), MASTER.names, token, dispatch=boom)
        self.assertEqual(publish.history(self.conn)[0]["result"]["error"], "RuntimeError")   # 例外の文は残さない(トークンが混ざりうる)
        self.assertEqual(len(self.plan().rows), 2)  # 何も送れていないので依頼済みにはしない

    def test_missing_token_is_explained(self):
        with self.conn:
            self.conn.execute("UPDATE skills SET status = 'rejected' WHERE skill = '謎スキル'")
        with self.assertRaises(publish.PublishError):
            publish.send(self.conn, self.plan(), MASTER.names, Path(self.tmp.name) / "none", dispatch=lambda *a: None)

    def test_large_requests_are_split_under_the_size_limit(self):
        names = [f"テストスキル{i:04d}" for i in range(900)]
        rows = [{"race": self.RACE, "strategy": "逃げ", "tier": "recommended", "skill": n} for n in names]
        requests = publish.build_requests("ev", rows, names)
        self.assertGreater(len(requests), 1)
        self.assertEqual(sum(len(r["rows"]) for r in requests), 900)
        for r in requests:
            size = len(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode())
            self.assertLessEqual(size, publish.CHUNK_BYTES)

    def test_published_source_falls_back_to_local_file(self):
        local = write(Path(self.tmp.name) / "race.json", json.dumps({self.RACE: {"逃げ": {"recommended": ["末脚"]}}}))

        def offline(*a, **k):
            raise OSError("offline")
        source = publish.PublishedSource("https://example.invalid/x.json", local, opener=offline)
        current = source.refresh()
        self.assertEqual((current.source, current.size), ("手元のrace_data.json", 1))
        self.assertIn("offline", source.error)

    def test_review_marks_site_tier_difference_as_attention(self):
        data = review.group(self.conn, MASTER, "ev", self.RACE, "逃げ", self.site)
        rows = {r["skill"]: r for im in data["images"] for r in im["rows"]}
        self.assertEqual(rows["末脚"]["published"], "same")
        self.assertTrue(any("サイトでは" in a for a in rows["左回り○"]["attention"]))
        todo = review.overview(self.conn, self.site)[0]["todo"]
        self.assertEqual(todo, 1)  # 未確認は左回り◎だけ(サイトにない)


class GuideAppExtractTests(unittest.TestCase):
    RACE, EV = "京都 芝 3000m", "2026-11_LOH"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox = base / "inbox"
        self.db_path = base / "guide.sqlite3"
        for rel in ("1_nige/super/a1.png", "1_nige/recommended/a2.png", "2_senkou/super/b1.png"):
            write(self.inbox / self.EV / rel, "img")
        write(base / "key", "secret")
        self.readers = [extract.Reader(n, "https://example.invalid/api", f"model-{n}", key_file=base / "key")
                        for n in ("gemini", "claude", "grok")]
        self.answers = {
            ("gemini", "a1.png"): ["末脚", "左回り◎", "コーナー回復○"],
            ("claude", "a1.png"): ["末脚", "左回り◎"],
            ("grok", "a1.png"): ["末脚", "左回り◎", "謎スキル"],
            ("gemini", "a2.png"): ["左回り〇"], ("claude", "a2.png"): ["左回り○"], ("grok", "a2.png"): ["左回り◯"],
            ("gemini", "b1.png"): ["末脚"], ("claude", "b1.png"): ["末脚"], ("grok", "b1.png"): ["末脚"],
        }
        self.calls = []
        self.failing = set()
        self.course, self.tab, self.heading = self.RACE, {}, {}

    def tearDown(self):
        self.tmp.cleanup()

    @contextmanager
    def connect(self):
        conn = db.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def fake_call(self, reader, image):
        self.calls.append((reader.name, image.name))
        if (reader.name, image.name) in self.failing:
            raise extract.ExtractError(f"{reader.name}: HTTP 503")
        return {"course": self.course, "strategy": self.tab.get(image.name, ""),
                "sections": [{"tier": self.heading.get(image.name, ""), "skills": self.answers[(reader.name, image.name)]}]}

    def extractor(self, readers=None, auto=False):
        return extract.Extractor(self.connect, self.inbox, readers or self.readers, MASTER, call=self.fake_call, auto_confirm=auto)

    def rows(self):
        with self.connect() as conn:
            return {(r["source_file"], r["skill"]): dict(r) for r in conn.execute("SELECT * FROM skills")}

    def test_list_shots_reads_strategy_and_tier_from_folders(self):
        write(self.inbox / self.EV / "3_sashi" / "old.png", "img")  # 区分フォルダなし
        write(self.inbox / self.EV / "notes" / "x.png", "img")       # 脚質でないフォルダは無視
        shots = extract.list_shots(self.inbox, self.EV)
        self.assertEqual([(s.file, s.strategy, s.tier) for s in shots], [
            ("a1.png", "逃げ", "super_recommended"), ("a2.png", "逃げ", "recommended"),
            ("b1.png", "先行", "super_recommended"), ("old.png", "差し", None)])

    def test_votes_unanimous_and_minority(self):
        ex = self.extractor()
        self.assertEqual(ex.estimate(self.EV)["requests"], 9)
        job = ex.start(self.EV, self.RACE, wait=True)
        self.assertEqual((job.state, job.done, job.requests, job.errors), ("finished", 3, 9, []))
        rows = self.rows()
        self.assertEqual((rows[("a1.png", "末脚")]["votes"], rows[("a1.png", "末脚")]["readers"]), (3, 3))
        self.assertEqual((rows[("a1.png", "コーナー回復○")]["votes"], rows[("a1.png", "コーナー回復○")]["read_by"]), (1, "gemini"))
        self.assertEqual(rows[("a1.png", "謎スキル")]["votes"], 1)
        circle = rows[("a2.png", "左回り○")]   # 丸の表記ゆれは同じスキルとして数える
        self.assertEqual((circle["votes"], circle["tier"], circle["strategy"], circle["race"]), (3, "recommended", "逃げ", self.RACE))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM skills WHERE strategy = '先行'").fetchone()[0], 1)
            data = review.group(conn, MASTER, self.EV, self.RACE, "逃げ")
        attention = {r["skill"]: r["attention"] for im in data["images"] for r in im["rows"]}
        self.assertEqual(attention["末脚"], [])
        self.assertEqual(attention["左回り◎"], [])   # 全モデル一致なら◎でも要注意にしない
        self.assertTrue(any("3モデル中1モデルだけ" in a for a in attention["コーナー回復○"]))
        self.assertTrue(any("マスタにない" in a for a in attention["謎スキル"]))

    def test_failed_reader_is_retried_alone_and_votes_are_updated(self):
        self.failing = {("grok", "b1.png")}
        ex = self.extractor()
        job = ex.start(self.EV, self.RACE, wait=True)
        self.assertEqual(len(job.errors), 1)
        with self.connect() as conn:
            row = conn.execute("SELECT votes, readers FROM skills WHERE strategy = '先行'").fetchone()
            self.assertEqual((row["votes"], row["readers"]), (2, 3))   # 1モデル失敗 → 一致扱いにしない
            pending = extract.captures(conn, self.inbox, [r.name for r in self.readers])[0]["pending"]
        self.assertEqual(pending, 1)
        self.failing, self.calls = set(), []
        self.assertEqual(ex.estimate(self.EV), ex.estimate(self.EV) | {"images": 1, "requests": 1})
        ex.start(self.EV, self.RACE, wait=True)
        self.assertEqual(self.calls, [("grok", "b1.png")])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT votes FROM skills WHERE strategy = '先行'").fetchone()[0], 3)
        self.calls = []
        again = ex.start(self.EV, self.RACE, wait=True)   # もう読む画像がなければ、呼び出しなしで突き合わせ直すだけ
        self.assertEqual((again.state, again.requests, self.calls), ("finished", 0, []))

    def test_rerun_keeps_manual_review(self):
        ex = self.extractor()
        ex.start(self.EV, self.RACE, wait=True)
        with self.connect() as conn, conn:
            conn.execute("UPDATE skills SET status = 'ready', skill = '直した名前' WHERE extracted_skill = '謎スキル'")
        ex.start(self.EV, self.RACE, force=True, wait=True)
        row = next(r for r in self.rows().values() if r["extracted_skill"] == "謎スキル")
        self.assertEqual((row["status"], row["skill"]), ("ready", "直した名前"))

    def test_start_validates_race_readers_and_keys(self):
        ex = self.extractor()
        for bad in ("京都芝3000m", "京都 芝 3050m", "ロンシャン 芝 2400m"):
            with self.assertRaises(extract.ExtractError):
                ex.start(self.EV, bad, wait=True)
        with self.assertRaises(extract.ExtractError):
            extract.Extractor(self.connect, self.inbox, [], MASTER, call=self.fake_call).start(self.EV, self.RACE)
        nokey = [extract.Reader("x", "https://example.invalid", "m", key_file=Path(self.tmp.name) / "none")]
        with self.assertRaises(extract.ExtractError):
            self.extractor(nokey).start(self.EV, self.RACE, wait=True)
        self.assertEqual(self.calls, [])

    def test_tierless_images_use_headings_from_the_model(self):
        write(self.inbox / "old-ev" / "1_nige" / "o.png", "img")
        calls = lambda reader, image: {"super_recommended": ["末脚"], "recommended": ["左回り○"], "unknown": []}  # noqa: E731
        ex = extract.Extractor(self.connect, self.inbox, self.readers[:2], MASTER, call=calls)
        ex.start("old-ev", self.RACE, wait=True)
        with self.connect() as conn:
            got = {r["skill"]: r["tier"] for r in conn.execute("SELECT skill, tier FROM skills WHERE event = 'old-ev'")}
        self.assertEqual(got, {"末脚": "super_recommended", "左回り○": "recommended"})

    def test_race_is_detected_from_images_and_missing_course_is_explained(self):
        job = self.extractor().start(self.EV, wait=True)   # レース指定なし
        self.assertEqual((job.state, job.race), ("finished", self.RACE))
        with self.connect() as conn:
            self.assertEqual({r["race"] for r in conn.execute("SELECT race FROM skills")}, {self.RACE})
            self.assertEqual(extract.captures(conn, self.inbox, ["gemini", "claude", "grok"])[0]["race"], self.RACE)
        write(self.inbox / "ev2" / "1_nige" / "super" / "z.png", "img")
        self.answers.update({(n, "z.png"): ["末脚"] for n in ("gemini", "claude", "grok")})
        self.course, self.calls = "", []
        ex = self.extractor()
        job = ex.start("ev2", wait=True)
        self.assertEqual(job.state, "failed")
        self.assertIn("コースを読み取れません", job.errors[-1])
        self.calls = []
        job = ex.start("ev2", "阪神 芝 2200m", wait=True)   # レースを選び直せば、呼び出しなしで行ができる
        self.assertEqual((job.state, job.rows, self.calls), ("finished", 1, []))

    def test_folder_and_image_mismatch_is_flagged(self):
        self.tab = {"a1.png": "先行"}                          # 逃げフォルダなのに先行タブ
        self.heading = {"a2.png": "super_recommended"}        # おすすめフォルダなのに超おすすめの見出し
        job = self.extractor(auto=True).start(self.EV, wait=True)
        self.assertEqual(job.warnings, 2)
        with self.connect() as conn:
            warnings = {r["source_file"]: r["warning"] for r in conn.execute("SELECT source_file, warning FROM images")}
            data = review.group(conn, MASTER, self.EV, self.RACE, "逃げ")
            drafts = {r["source_file"] for r in conn.execute("SELECT source_file FROM skills WHERE status = 'draft'")}
        self.assertIn("脚質タブは「先行」", warnings["a1.png"])
        self.assertIn("「超おすすめスキル」の見出しが写っています", warnings["a2.png"])
        self.assertEqual(warnings["b1.png"], "")
        self.assertTrue(all(im["warning"] for im in data["images"]))
        self.assertEqual(drafts, {"a1.png", "a2.png"})          # 食い違う画像は自動確定しない

    def test_auto_confirm_follows_the_majority(self):
        self.answers[("claude", "a1.png")] = ["末脚", "左回り◎", "コーナー回復○"]   # コーナー回復○は2/3
        self.answers[("grok", "b1.png")] = ["末脚", "左回り◎"]                      # 左回り◎は1/3(実在)
        job = self.extractor(auto=True).start(self.EV, wait=True)
        rows = self.rows()
        self.assertEqual(rows[("a1.png", "末脚")]["status"], "ready")                # 3/3
        self.assertEqual(rows[("a1.png", "コーナー回復○")]["status"], "ready")       # 2/3
        self.assertEqual(rows[("a1.png", "謎スキル")]["status"], "rejected")         # 1/3・マスタになし
        with self.connect() as conn:
            lone = conn.execute("SELECT status FROM skills WHERE strategy = '先行' AND skill = '左回り◎'").fetchone()
            reviewed = {r["source_file"]: r["reviewed_at"] for r in conn.execute("SELECT source_file, reviewed_at FROM images")}
            stats = {s["name"]: s for s in extract.reader_stats(conn, ["gemini", "claude", "grok"])}
        self.assertEqual(lone["status"], "draft")                                   # 1/3・実在 → 人が見る
        self.assertIsNotNone(reviewed["a1.png"])
        self.assertIsNone(reviewed["b1.png"])
        self.assertEqual((job.auto_rejected, stats["grok"]["solo"], stats["grok"]["solo_rejected"]), (1, 2, 1))
        self.assertEqual(stats["gemini"]["calls"], 3)
        with self.connect() as conn, conn:   # 人が直した行は、やり直しても自動で変えない
            conn.execute("UPDATE skills SET status = 'draft', memo = '' WHERE extracted_skill = '謎スキル'")
            conn.execute("UPDATE skills SET status = 'rejected' WHERE source_file = 'a1.png' AND skill = '末脚'")
        self.extractor(auto=True).start(self.EV, wait=True)
        self.assertEqual(self.rows()[("a1.png", "末脚")]["status"], "rejected")

    def test_master_refresh_from_remote_and_fallback(self):
        master = SkillMaster(["古い名前"])

        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(["末脚", "新スキル"]).encode()
        info = publish.refresh_master(master, "https://example.invalid/m.json", opener=lambda url, timeout: Response())
        self.assertEqual((info["source"], info["skills"], master.canonical("新スキル")), ("GitHub main", 2, "新スキル"))

        def offline(url, timeout):
            raise OSError("offline")
        info = publish.refresh_master(master, "https://example.invalid/m.json", opener=offline)
        self.assertIn("offline", info["error"])
        self.assertEqual(master.canonical("新スキル"), "新スキル")   # 取得に失敗しても中身は消えない

    def test_missing_cells_warns_about_forgotten_captures(self):
        with self.connect() as conn:
            capture = extract.captures(conn, self.inbox, ["gemini"])[0]
        self.assertEqual((capture["images"], capture["pending"]), (3, 3))
        self.assertIn("先行 おすすめ", capture["missing"])
        self.assertIn("追込 超おすすめ", capture["missing"])
        self.assertNotIn("逃げ 超おすすめ", capture["missing"])

    def two_stage(self, spot_check=0, auto=True):
        readers = [extract.Reader(r.name, r.base_url, r.model, key_file=r.key_file, primary=(r.name == "gemini")) for r in self.readers]
        return extract.Extractor(self.connect, self.inbox, readers, MASTER, call=self.fake_call, auto_confirm=auto,
                                 spot_check=spot_check, parallel_images=2)

    def test_two_stage_sends_only_doubtful_images_to_the_council(self):
        # a1.png は gemini の読みが全部マスタにある → 1次だけで通す。b1.png はマスタにない名前 → 会議へ
        self.answers[("gemini", "b1.png")] = ["末脚", "謎スキル"]
        ex = self.two_stage()
        self.assertEqual(ex.estimate(self.EV)["requests"], 3)          # 最初は1次のモデルの分だけ
        job = ex.start(self.EV, wait=True)
        self.assertEqual((job.state, job.council), ("finished", 1))
        self.assertEqual(sorted(self.calls), sorted([("gemini", "a1.png"), ("gemini", "a2.png"), ("gemini", "b1.png"),
                                                     ("claude", "b1.png"), ("grok", "b1.png")]))
        rows = self.rows()
        self.assertEqual((rows[("a1.png", "末脚")]["readers"], rows[("a1.png", "末脚")]["status"]), (1, "ready"))
        self.assertEqual(rows[("a1.png", "左回り◎")]["status"], "ready")    # 1次だけの画像では◎も通す
        with self.connect() as conn:
            b1 = {r["skill"]: (r["votes"], r["readers"], r["status"]) for r in conn.execute("SELECT * FROM skills WHERE strategy = '先行'")}
            pending = extract.captures(conn, self.inbox, ["gemini", "claude", "grok"], "gemini")[0]["pending"]
            reason = conn.execute("SELECT council_reason FROM images WHERE source_file = 'b1.png'").fetchone()[0]
        self.assertEqual(b1, {"末脚": (3, 3, "ready"), "謎スキル": (1, 3, "rejected")})   # 会議の多数決で決まる
        self.assertEqual((pending, reason), (0, "マスタにない名前がある"))
        self.calls = []
        ex.start(self.EV, wait=True)                                   # やり直しても呼び直さない
        self.assertEqual(self.calls, [])

    def test_two_stage_escalates_mismatch_failure_and_spot_checks(self):
        self.tab = {"a1.png": "先行"}                 # 設定と食い違う
        self.failing = {("gemini", "a2.png")}        # 1次が読めない
        job = self.two_stage().start(self.EV, wait=True)
        with self.connect() as conn:
            got = {r["source_file"]: (r["council"], r["council_reason"]) for r in conn.execute("SELECT * FROM images")}
        self.assertEqual(got["a1.png"], (1, "撮影時の設定と食い違う"))
        self.assertEqual(got["a2.png"], (1, "1次のモデルが読めなかった"))
        self.assertEqual(got["b1.png"][0], 0)
        self.assertEqual(job.council, 2)
        self.assertEqual(self.rows()[("a2.png", "左回り○")]["votes"], 2)   # 1次が読めなくても、会議の2モデルで行ができる
        picked = [f for f in ("x%d.png" % i for i in range(200)) if extract.spot_checked(f, 5)]
        self.assertTrue(20 <= len(picked) <= 60)                           # おおよそ5枚に1枚
        self.assertFalse(extract.spot_checked("a.png", 0))

    def test_parallel_reading_respects_reader_interval(self):
        slow = [extract.Reader("gemini", "https://example.invalid", "m", key_file=self.readers[0].key_file, min_interval=0.05)]
        started = []
        def call(reader, image):
            started.append(extract.time.monotonic())
            return {"course": self.RACE, "strategy": "", "sections": [{"tier": "", "skills": ["末脚"]}]}
        extract.Extractor(self.connect, self.inbox, slow, MASTER, call=call, parallel_images=3).start(self.EV, wait=True)
        gaps = [b - a for a, b in zip(sorted(started), sorted(started)[1:])]
        self.assertEqual(len(started), 3)
        self.assertTrue(all(g >= 0.04 for g in gaps), gaps)

    def test_half_and_full_width_punctuation_count_as_the_same_skill(self):
        master = SkillMaster(["かっとばせ！", "末脚"])
        self.assertEqual(master.canonical("かっとばせ!"), "かっとばせ！")
        rows = extract.tally({"gemini": ["かっとばせ！"], "gpt": ["かっとばせ！"], "claude": ["かっとばせ!"]}, master)
        self.assertEqual([(r["skill"], r["votes"]) for r in rows], [("かっとばせ！", 3)])

    def test_similar_names_are_never_merged_into_one_vote(self):
        # 似た名前を同じスキルの票として数えると、○と◎の取り違えが多数決を通ってしまう
        rows = extract.tally({"a": ["左回り○"], "b": ["左回り◎"], "c": ["左回りO"]}, MASTER)
        self.assertEqual({r["skill"]: r["votes"] for r in rows}, {"左回り○": 1, "左回り◎": 1, "左回りO": 1})

    def test_auto_confirm_leaves_risky_rows_for_a_human(self):
        site = publish.Published({self.RACE: {"逃げ": {"recommended": ["末脚"]}}})   # サイトでは末脚はおすすめ
        ex = extract.Extractor(self.connect, self.inbox, self.readers, MASTER, call=self.fake_call,
                               auto_confirm=True, get_published=lambda: site)
        ex.start(self.EV, wait=True)
        rows = self.rows()
        self.assertEqual(rows[("a1.png", "末脚")]["status"], "draft")        # サイトと区分が違う → 人が見る
        self.assertEqual(rows[("a1.png", "左回り◎")]["status"], "ready")     # 3/3で問題なし
        # 人が未確認に戻した行・区分を変えた行は、やり直しても自動で変えない
        with self.connect() as conn:
            review.update_row(conn, rows[("a1.png", "左回り◎")]["id"], {"status": "draft"})
            review.update_row(conn, rows[("a2.png", "左回り○")]["id"], {"tier": "super_recommended", "status": "draft"})
        ex.start(self.EV, wait=True)
        with self.connect() as conn:
            got = [dict(r) for r in conn.execute("SELECT skill, tier, status FROM skills WHERE source_file IN ('a1.png','a2.png') AND skill LIKE '左回り%' ORDER BY skill")]
        self.assertEqual(got, [{"skill": "左回り○", "tier": "super_recommended", "status": "draft"},
                               {"skill": "左回り◎", "tier": "super_recommended", "status": "draft"}])

    def test_both_headings_in_one_image_is_flagged(self):
        both = {"course": self.RACE, "strategy": "逃げ", "sections": [
            {"tier": "super_recommended", "skills": ["末脚"]}, {"tier": "recommended", "skills": ["左回り○"]}]}
        shot = extract.list_shots(self.inbox, self.EV)[0]
        warnings = extract.image_warnings(shot, self.RACE, [both, both, both])
        self.assertTrue(any("両方の区分" in w for w in warnings))

    def test_readings_from_removed_readers_do_not_vote(self):
        self.extractor().start(self.EV, self.RACE, wait=True)
        two = self.readers[:2]   # grok を設定から外した
        self.extractor(two).start(self.EV, self.RACE, wait=True)
        row = self.rows()[("a1.png", "末脚")]
        self.assertEqual((row["votes"], row["readers"]), (2, 2))

    def test_key_with_newline_is_rejected_without_leaking(self):
        write(Path(self.tmp.name) / "badkey", "sk-SECRET\nnote")
        reader = extract.Reader("x", "https://example.invalid", "m", key_file=Path(self.tmp.name) / "badkey")
        with self.assertRaises(extract.ExtractError) as caught:
            reader.key()
        self.assertNotIn("SECRET", str(caught.exception))

    def test_master_refuses_to_shrink_and_migrations_can_rerun(self):
        master = SkillMaster([f"スキル{i}" for i in range(200)])
        with self.assertRaises(ValueError):
            master.update(["スキル1"])
        self.assertEqual(len(master.names), 200)
        with self.connect() as conn:   # 版だけ巻き戻して、適用済みの文をもう一度流しても起動できる
            conn.execute("PRAGMA user_version = 4")
            conn.commit()
        with self.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))

    def test_parse_names_accepts_common_reply_shapes(self):
        skills = lambda text: [s["skills"] for s in extract.parse_reply(text)["sections"]]  # noqa: E731
        self.assertEqual(skills('["末脚", "左回り○", "末脚"]'), [["末脚", "左回り○"]])
        self.assertEqual(skills('はい。\n```json\n["末脚"]\n```'), [["末脚"]])
        self.assertEqual(skills("1. 末脚\n- 左回り○"), [["末脚", "左回り○"]])
        full = extract.parse_reply('{"course": "中山 芝3600m(長距離)", "strategy": "逃げ", "sections": ['
                                   '{"heading": "超おすすめスキル", "skills": ["末脚"]}, {"heading": "おすすめスキル", "skills": ["左回り○"]},'
                                   '{"heading": "", "skills": []}]}')
        self.assertEqual((full["course"], full["strategy"]), ("中山 芝 3600m", "逃げ"))
        self.assertEqual([s["tier"] for s in full["sections"]], ["super_recommended", "recommended"])
        self.assertEqual(extract.parse_reply('{"course": "", "sections": []}')["sections"], [])  # スキルなしの画面
        with self.assertRaises(extract.ExtractError):
            extract.parse_reply("")

    def test_call_reader_sends_image_and_never_leaks_the_key_in_errors(self):
        image = self.inbox / self.EV / "1_nige" / "super" / "a1.png"
        seen = {}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"choices": [{"message": {"content": '{"course": "京都 芝 3000m", "sections": [{"heading": "", "skills": ["末脚"]}]}'}}]}).encode()

        def opener(request, timeout):
            seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
            seen["body"] = json.loads(request.data)
            return Response()
        got = extract.call_reader(self.readers[0], image, opener=opener)
        self.assertEqual((got["course"], got["sections"][0]["skills"]), ("京都 芝 3000m", ["末脚"]))
        self.assertEqual((seen["url"], seen["auth"]), ("https://example.invalid/api/chat/completions", "Bearer secret"))
        self.assertTrue(seen["body"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

        gateway = extract.Reader("gw", "https://example.invalid/v1", "m", key_file=Path(self.tmp.name) / "key",
                                 key_header="X-Gravitee-Api-Key")
        extract.call_reader(gateway, image, opener=opener)
        self.assertIsNone(seen["auth"])   # 専用ヘッダーのときはAuthorizationを送らない
        self.assertEqual(gateway.auth_headers(), {"X-Gravitee-Api-Key": "secret"})

        def refuse(request, timeout):
            raise OSError("connection refused")
        extract.time.sleep = lambda s: None
        with self.assertRaises(extract.ExtractError) as caught:
            extract.call_reader(self.readers[0], image, opener=refuse)
        self.assertNotIn("secret", str(caught.exception))

    def test_config_reads_readers(self):
        cfg_path = write(Path(self.tmp.name) / "c.toml", '''data_root = "data"
[[readers]]
name = "gemini"
base_url = "https://example.invalid/openai"
model = "m1"
key_env = "GEMINI_API_KEY"
min_interval = 4
[[readers]]
name = "claude"
base_url = "https://example.invalid/api"
model = "m2"
key_file = "keys/friend"
''')
        cfg = load_config(cfg_path)
        self.assertEqual([(r.name, r.min_interval) for r in cfg.readers], [("gemini", 4.0), ("claude", 0.0)])
        self.assertEqual(cfg.readers[1].key_file, Path(self.tmp.name).resolve() / "keys" / "friend")
        self.assertEqual(cfg.inbox_dir, Path(self.tmp.name).resolve() / "data" / "screenshots" / "inbox")
        bad = write(Path(self.tmp.name) / "bad.toml", '[[readers]]\nname = "x"\nbase_url = "u"\nmodel = "m"\n')
        with self.assertRaises(ValueError):
            load_config(bad)


if __name__ == "__main__":
    unittest.main()
