"""guide_app の自動処理(automation.py)のテスト。通信・時計はすべて偽物に差し替える。"""
import contextlib
import dataclasses
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from guide_app import automation, extract, publish  # noqa: E402
from guide_app.config import load_config  # noqa: E402
from guide_app.server import App  # noqa: E402

WEBHOOK = "https://discord.invalid/api/webhooks/123/SECRET-TOKEN"
MINUTE = 60
SITE = {"東京 芝 2400m": {"逃げ": {"super_recommended": ["末脚"], "recommended": []}}}   # サイトに出ている内容(別のコース)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b""


class AutomationTestCase(unittest.TestCase):
    EV, RACE = "2026-11_LOH", "京都 芝 3000m"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        write(self.base / "master.json", json.dumps(["末脚", "左回り○", "コーナー回復○"], ensure_ascii=False))
        write(self.base / "key", "api-key")
        write(self.base / "token", "gh-token")
        write(self.base / "webhook", WEBHOOK + "\n")
        self.cfg_path = write(self.base / "c.toml", '''data_root = "data"
skill_master_path = "master.json"
token_file = "{token}"
discord_webhook_file = "webhook"
port = 8090
[[readers]]
name = "gemini"
base_url = "https://example.invalid/a"
model = "m1"
key_file = "key"
[[readers]]
name = "claude"
base_url = "https://example.invalid/b"
model = "m2"
key_file = "key"
'''.replace("{token}", str(self.base / "token").replace("\\", "/")))
        self.inbox = self.base / "data" / "screenshots" / "inbox"
        self.now = time.time()
        self.reader_calls, self.failing = [], set()
        self.posts, self.webhook_error = [], None
        self.dispatched, self.dispatch_error = [], None
        self.app = None

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 偽物 ----
    def clock(self):
        return self.now

    def advance(self, minutes):
        self.now += minutes * MINUTE

    def fake_call(self, reader, image):
        self.reader_calls.append((reader.name, image.name))
        if (reader.name, image.name) in self.failing:
            raise extract.ExtractError(f"{reader.name}: HTTP 503")
        return {"course": self.RACE, "strategy": "", "sections": [{"tier": "super_recommended", "skills": ["末脚"]}]}

    def fake_open(self, request, timeout):
        if self.webhook_error:
            raise self.webhook_error
        self.posts.append(json.loads(request.data.decode("utf-8"))["content"])
        self.assertEqual(request.full_url, WEBHOOK)
        return FakeResponse()

    def fake_dispatch(self, request, token):
        if self.dispatch_error:
            raise self.dispatch_error
        self.dispatched.append(request)

    def make(self, **flags):
        """Appを作り直す(=再起動)。DBとファイルはそのまま。"""
        cfg = dataclasses.replace(load_config(self.cfg_path), **flags)
        app = App(cfg)
        app.extractor = extract.Extractor(app.connect, cfg.inbox_dir, list(cfg.readers), app.master,
                                          call=self.fake_call, auto_confirm=cfg.auto_confirm)
        app.published_source.current = publish.Published(SITE, "GitHub main", "2026-01-01 00:00:00")
        app.master_info = {"source": "GitHub main"}
        app.automation = automation.Automation(
            app, clock=self.clock, dispatch=self.fake_dispatch,
            notifier=automation.Notifier(cfg.discord_webhook_file, opener=self.fake_open, clock=self.clock))
        self.app = app
        return app

    def tick(self):
        self.app.automation.tick()
        thread = self.app.extractor._thread
        if thread:
            thread.join()
        self.assertEqual(self.app.automation.errors, {})

    def shot(self, rel="1_nige/a1.png", event=None):
        return write(self.inbox / (event or self.EV) / rel, "img")

    def sql(self, statement, args=()):
        with self.app.connect() as conn, conn:
            return conn.execute(statement, args).fetchall()

    def add_row(self, skill="末脚", status="ready", tier="super_recommended", file="x1.png", event=None):
        self.sql("INSERT INTO skills (event, race, strategy, tier, extracted_skill, skill, status, source_file, source_csv)"
                 " VALUES (?, ?, '逃げ', ?, ?, ?, ?, ?, 'guide_app')", (event or self.EV, self.RACE, tier, skill, skill, status, file))

    def own(self, event=None):
        """この自動処理が読み取りを終えたイベント、という印を付ける。"""
        with self.app.connect() as conn:
            automation.set_state(conn, f"auto_event:{event or self.EV}", {"at": "x"})

    def posts_with(self, word):
        return [p for p in self.posts if word in p]


class AutoExtractTests(AutomationTestCase):
    def test_everything_is_off_by_default(self):
        cfg = load_config(write(self.base / "plain.toml", 'data_root = "data"\n'))
        self.assertEqual((cfg.auto_extract, cfg.auto_extract_idle_minutes, cfg.auto_publish, cfg.discord_webhook_file, cfg.backup_keep),
                         (False, 10, False, None, 14))
        self.assertEqual(cfg.backup_dir, self.base / "data" / "guide_app" / "backups")
        self.shot()
        self.make(discord_webhook_file=None, backup_keep=0)
        self.add_row()
        self.advance(60)
        self.tick()
        self.assertEqual((self.reader_calls, self.dispatched, self.posts), ([], [], []))
        self.assertFalse(self.app.config.backup_dir.exists())

    def test_waits_until_captures_have_been_idle(self):
        self.shot()
        self.make(auto_extract=True)
        self.tick()
        self.advance(9)
        self.tick()
        self.assertEqual(self.reader_calls, [])   # 撮影中かもしれないので待つ
        self.advance(2)
        self.tick()
        self.assertEqual(sorted(self.reader_calls), [("claude", "a1.png"), ("gemini", "a1.png")])
        self.assertEqual([r["skill"] for r in self.sql("SELECT skill FROM skills")], ["末脚"])
        self.assertEqual(self.app.extractor.job.race, self.RACE)   # コースは画像から
        self.tick()
        self.assertEqual(len(self.reader_calls), 2)   # 読み終えたら、もう呼ばない
        self.assertIn("読み取りを自動で開始", self.app.automation.status()["last_action"]["text"])

    def test_new_file_restarts_the_idle_wait(self):
        self.shot()
        self.make(auto_extract=True)
        self.advance(11)
        new = self.shot("1_nige/a2.png")
        os.utime(new, (self.now, self.now))   # たった今、置かれた
        self.tick()
        self.assertEqual(self.reader_calls, [])
        self.advance(11)
        self.tick()
        self.assertEqual(len(self.reader_calls), 4)

    def test_hidden_events_and_running_jobs_are_left_alone(self):
        self.shot()
        self.make(auto_extract=True)
        self.sql("INSERT INTO events (event, hidden) VALUES (?, 1)", (self.EV,))
        self.advance(11)
        self.tick()
        self.assertEqual(self.reader_calls, [])
        self.sql("UPDATE events SET hidden = 0")
        self.app.extractor.job = extract.Job(event="other", race="")   # 別の読み取りが進行中
        self.tick()
        self.assertEqual(self.reader_calls, [])

    def test_retry_is_capped_spaced_and_reset_by_new_captures(self):
        self.shot()
        self.failing = {("claude", "a1.png")}
        self.make(auto_extract=True)
        self.advance(11)
        self.tick()                                   # 1回目
        self.assertEqual(len(self.reader_calls), 2)
        self.tick()
        self.advance(29)
        self.tick()
        self.assertEqual(len(self.reader_calls), 2)   # 30分たつまではやり直さない
        for expected in (3, 4, 5):                    # やり直しは3回まで(失敗したモデルだけ呼ぶ)
            self.advance(31)
            self.tick()
            self.assertEqual(len(self.reader_calls), expected)
            self.assertEqual(self.posts_with("あきらめました"), [])
        self.make(auto_extract=True)                  # 再起動しても数え直さない
        for _ in range(3):
            self.advance(31)
            self.tick()
        self.assertEqual(len(self.reader_calls), 5)
        self.assertEqual(len(self.posts_with("読み取りのやり直しをあきらめました")), 1)   # あきらめた通知は一度だけ
        self.assertTrue(any("未抽出1枚" in n for n in self.app.automation.status()["notes"]))

        self.shot("1_nige/a2.png")                    # 新しく撮影 → 数え直す
        self.tick()
        self.assertEqual(sorted(self.reader_calls[5:]), [("claude", "a1.png"), ("claude", "a2.png"), ("gemini", "a2.png")])
        self.tick()
        self.assertEqual(len(self.reader_calls), 8)   # 続けては試さない

    def test_given_up_state_survives_until_reader_config_changes(self):
        self.shot()
        self.failing = {("claude", "a1.png")}
        self.make(auto_extract=True)
        for _ in range(6):
            self.advance(31)
            self.tick()
        self.assertEqual(len(self.reader_calls), 5)
        cfg = load_config(self.cfg_path)
        changed = (cfg.readers[0], dataclasses.replace(cfg.readers[1], model="m3"))
        self.make(auto_extract=True, readers=changed)   # モデルを入れ替えた
        self.advance(3)
        self.tick()
        self.assertEqual(len(self.reader_calls), 6)

    def test_waits_after_server_start(self):
        self.shot()
        self.advance(60)
        self.make(auto_extract=True)
        self.tick()
        self.advance(1)
        self.tick()
        self.assertEqual(self.reader_calls, [])   # 再起動の直後は始めない
        self.advance(2)
        self.tick()
        self.assertEqual(len(self.reader_calls), 2)

    def test_readings_without_rows_are_tallied_again(self):
        self.shot()
        self.make(auto_extract=True)
        for reader in ("gemini", "claude"):   # 読み取りは済んだが、行を作る前に止まった
            self.sql("INSERT INTO readings (event, source_file, reader, model, names) VALUES (?, 'a1.png', ?, 'm', ?)",
                     (self.EV, reader, json.dumps(self.fake_call(self.app.config.readers[0], Path("a1.png")), ensure_ascii=False)))
        self.reader_calls.clear()
        self.advance(11)
        self.tick()
        self.assertEqual(self.reader_calls, [])   # モデルは呼び直さない
        self.assertEqual([r["skill"] for r in self.sql("SELECT skill FROM skills")], ["末脚"])
        self.tick()
        with self.app.connect() as conn:
            self.assertEqual(automation.get_state(conn, f"extract:{self.EV}")["attempts"], 1)
            self.assertTrue(automation.get_state(conn, f"auto_event:{self.EV}"))

    def test_auto_confirm_waits_for_the_master_from_github(self):
        self.shot()
        self.make(auto_extract=True, auto_confirm=True)
        self.app.master_info = {"source": "手元のファイル"}
        self.advance(11)
        self.tick()
        self.assertEqual(self.reader_calls, [])
        self.assertTrue(any("スキルマスタ" in n for n in self.app.automation.status()["notes"]))
        self.app.master_info = {"source": "GitHub main"}
        self.tick()
        self.assertEqual(len(self.reader_calls), 2)

    def test_start_failure_counts_as_an_attempt(self):
        self.shot()
        self.make(auto_extract=True)
        (self.base / "key").write_text("", encoding="utf-8")   # APIキーが空
        self.advance(11)
        self.tick()
        self.assertIn("読み取りを始められませんでした", self.app.automation.status()["last_action"]["text"])
        with self.app.connect() as conn:
            self.assertEqual(automation.get_state(conn, f"extract:{self.EV}")["attempts"], 1)
        self.tick()
        with self.app.connect() as conn:
            self.assertEqual(automation.get_state(conn, f"extract:{self.EV}")["attempts"], 1)   # 毎分は試さない


class NotificationTests(AutomationTestCase):
    def test_job_result_is_notified_once(self):
        self.shot()
        self.make(auto_extract=True, auto_confirm=True)
        self.advance(11)
        self.tick()
        self.tick()
        self.tick()
        self.make(auto_extract=True, auto_confirm=True)
        self.tick()
        self.assertEqual(len(self.posts), 1)
        text = self.posts[0]
        for part in ("読み取り完了", self.EV, self.RACE, "画像 1/1枚", "1行", "自動OK 1・自動却下 0",
                     "設定と食い違う画像 0枚", "人の確認が必要: 0行", "http://uma-pi:8090/"):
            self.assertIn(part, text)

    def test_failed_job_is_notified_with_the_reason(self):
        self.shot()
        self.make()
        job = extract.Job(event=self.EV, race="", state="failed")
        job.errors.append("画像からコースを読み取れませんでした")
        self.app.extractor.job = job
        self.tick()
        self.tick()
        self.assertEqual(len(self.posts), 1)
        self.assertIn("エラーで止まりました", self.posts[0])
        self.assertIn("画像からコースを読み取れませんでした", self.posts[0])
        self.app.extractor.job = extract.Job(event=self.EV, race="", state="cancelled")   # 人が中止したものは知らせない
        self.tick()
        self.assertEqual(len(self.posts), 1)

    def test_webhook_failure_is_swallowed_and_never_shows_the_url(self):
        self.make()
        self.app.extractor.job = extract.Job(event=self.EV, race=self.RACE, state="finished")
        for error in (urllib.error.HTTPError(WEBHOOK, 404, "Not Found", {}, None), OSError(f"cannot reach {WEBHOOK}")):
            self.webhook_error = error
            self.app.extractor.job.started_at += "x"   # 別のジョブとして扱わせる
            self.tick()
            status = json.dumps(self.app.automation.status(), ensure_ascii=False)
            self.assertIn("Discordへ送れませんでした", status)
            self.assertNotIn("SECRET-TOKEN", status)
            self.assertNotIn("discord.invalid", status)
        self.webhook_error = None
        self.tick()
        self.assertEqual(self.posts, [])   # 失敗した通知は送り直さない(二重に届けない)

    def test_missing_or_broken_webhook_file_is_explained(self):
        self.make()
        notifier = self.app.automation.notifier
        (self.base / "webhook").write_text("file:///etc/passwd", encoding="utf-8")
        self.assertFalse(notifier.send("x"))
        self.assertIn("URLではありません", notifier.last_error["text"])
        (self.base / "webhook").unlink()
        self.assertFalse(notifier.send("x"))
        self.assertIn("読めません", notifier.last_error["text"])
        write(self.base / "webhook", WEBHOOK)
        self.assertTrue(notifier.send("あ" * 5000))
        self.assertLessEqual(len(self.posts[0]), 2000)
        self.assertIsNone(notifier.last_error)

    def test_publish_request_is_notified_once_and_old_history_is_not(self):
        self.make()
        self.add_row()
        with self.app.connect() as conn:   # 自動処理を入れる前の依頼
            plan = publish.plan_event(conn, self.app.master, self.app.published, self.EV)
            publish.send(conn, plan, self.app.master.names, self.app.config.token_file, dispatch=self.fake_dispatch)
        self.tick()
        self.assertEqual(self.posts, [])
        self.add_row("左回り○")
        with self.app.connect() as conn:   # 画面からの依頼
            plan = publish.plan_event(conn, self.app.master, self.app.published, self.EV)
            publish.send(conn, plan, self.app.master.names, self.app.config.token_file, dispatch=self.fake_dispatch)
        self.tick()
        self.tick()
        self.make()
        self.tick()
        self.assertEqual(len(self.posts), 1)
        for part in ("公開を依頼しました", self.EV, "1行(追加 1・区分変更 0)", "pulls?q=is%3Apr+head%3Adata%2Freviewed-race-" + self.EV):
            self.assertIn(part, self.posts[0])


class AutoPublishTests(AutomationTestCase):
    def ready(self, **flags):
        """公開を依頼できる状態(OKの行が1つ、ほかに引っかかるものなし)。"""
        self.make(auto_publish=True, **flags)
        self.add_row()
        self.own()

    def assert_held(self, word):
        self.tick()
        self.assertEqual(self.dispatched, [])
        self.assertTrue(any(word in n for n in self.app.automation.status()["notes"]), self.app.automation.notes)

    def test_sends_once_when_nothing_needs_a_human(self):
        self.ready()
        self.add_row("左回り○", status="rejected")
        self.tick()
        self.tick()
        self.make(auto_publish=True)
        self.tick()
        self.assertEqual(len(self.dispatched), 1)   # 依頼済みの行は二度と送らない
        self.assertEqual([r["skill"] for r in self.dispatched[0]["rows"]], ["末脚"])
        self.assertEqual(len(self.posts_with("公開を依頼しました")), 1)
        self.assertIn("公開を自動で依頼", self.app.automation.status()["last_action"]["text"])

    def test_off_by_default(self):
        self.make()
        self.add_row()
        self.own()
        self.tick()
        self.assertEqual(self.dispatched, [])

    def test_blocked_by_draft_rows_unless_already_on_the_site(self):
        self.ready()
        self.add_row("左回り○", status="draft")
        self.assert_held("人の確認が必要な行 1件")
        self.app.published_source.current = publish.Published(   # 未確認の行がサイトと同じなら、見直し不要
            {self.RACE: {"逃げ": {"super_recommended": ["左回り○"]}}}, "GitHub main", "2026-01-01 00:00:00")
        self.tick()
        self.assertEqual(len(self.dispatched), 1)

    def test_blocked_by_rows_that_cannot_be_published(self):
        self.ready()
        self.add_row("謎スキル")
        self.assert_held("公開できない行 1件")

    def test_blocked_by_unreviewed_image_warning(self):
        self.ready()
        self.sql("INSERT INTO images (event, source_file, warning) VALUES (?, 'x1.png', '脚質が違う')", (self.EV,))
        self.assert_held("設定と食い違う未確認の画像 1枚")
        self.sql("UPDATE images SET reviewed_at = '2026-01-01'")
        self.tick()
        self.assertEqual(len(self.dispatched), 1)

    def test_blocked_by_missing_cells(self):
        self.ready()
        self.shot("1_nige/super/x1.png")   # 区分フォルダで撮っているのに、ほかの脚質・区分が0枚
        for reader in ("gemini", "claude"):
            self.sql("INSERT INTO readings (event, source_file, reader, model, names) VALUES (?, 'x1.png', ?, 'm', '{}')", (self.EV, reader))
        self.assert_held("撮り忘れの可能性")

    def test_blocked_by_pending_images(self):
        self.ready()
        self.shot("1_nige/x2.png")
        self.assert_held("未抽出の画像 1枚")

    def test_blocked_while_a_job_is_running(self):
        self.ready()
        self.app.extractor.job = extract.Job(event="other", race="")
        self.tick()
        self.assertEqual(self.dispatched, [])
        self.app.extractor.job.state = "cancelled"
        self.tick()
        self.assertEqual(len(self.dispatched), 1)

    def test_hidden_events_are_skipped(self):
        self.ready()
        self.sql("INSERT INTO events (event, hidden) VALUES (?, 1)", (self.EV,))
        self.tick()
        self.assertEqual(self.dispatched, [])

    def test_blocked_until_the_site_content_is_known(self):
        self.ready()
        self.app.published_source.current = publish.Published()   # まだ一度も読めていない
        self.assert_held("サイトの内容をGitHubから読めていない")
        self.app.published_source.current = publish.Published(SITE, "手元のrace_data.json", "2026-01-01 00:00:00")
        self.assert_held("サイトの内容をGitHubから読めていない")   # 手元のファイルは古いかもしれない
        self.app.published_source.current = publish.Published({}, "GitHub main", "2026-01-01 00:00:00")
        self.assert_held("サイトの内容をGitHubから読めていない")   # 空っぽ
        self.app.published_source.current = publish.Published(SITE, "GitHub main", "2026-01-01 00:00:00")
        self.app.published_source.error = "GitHubから取得できませんでした"
        self.assert_held("サイトの内容をGitHubから読めていない")
        self.app.published_source.error = None
        self.tick()
        self.assertEqual(len(self.dispatched), 1)

    def test_only_events_extracted_by_automation_are_published(self):
        self.make(auto_publish=True)
        self.add_row()                       # 人が進めていた昔のイベント
        self.tick()
        self.assertEqual(self.dispatched, [])
        self.add_row(event="2026-12_CM")
        self.own("2026-12_CM")
        self.tick()
        self.assertEqual([d["event"] for d in self.dispatched], ["2026-12_CM"])

    def test_tier_changes_are_left_for_a_human_and_notified_once(self):
        self.ready()
        self.add_row("左回り○")
        self.app.published_source.current = publish.Published(
            {self.RACE: {"逃げ": {"recommended": ["左回り○"]}}}, "GitHub main", "2026-01-01 00:00:00")
        self.assert_held("区分が変わる行 1件")
        self.tick()
        self.assertEqual(len(self.posts_with("自動では公開を依頼しません")), 1)

    def test_blocked_rows_are_notified_once_per_distinct_set(self):
        self.ready()
        self.add_row("謎スキル")
        self.tick()
        self.tick()
        self.assertEqual(len(self.posts_with("公開できない行が1件")), 1)
        self.add_row("謎スキル2")
        self.tick()
        self.tick()
        self.assertEqual(len(self.posts_with("公開できない行が2件")), 1)
        self.assertEqual(self.dispatched, [])

    def test_skipped_while_a_manual_request_holds_the_lock(self):
        self.ready()
        with self.app.publish_lock:
            self.tick()
        self.assertEqual(self.dispatched, [])
        self.tick()
        self.assertEqual(len(self.dispatched), 1)

    def test_failure_is_notified_once_and_retried_with_backoff_then_given_up(self):
        self.ready()
        self.dispatch_error = RuntimeError("network down")
        attempts = lambda: len(publish_history())  # noqa: E731

        def publish_history():
            return self.sql("SELECT id FROM publish_log")
        self.tick()
        self.assertEqual(attempts(), 1)
        self.tick()
        self.advance(29)
        self.tick()
        self.assertEqual(attempts(), 1)             # 30分たつまではやり直さない
        self.assertEqual(len(self.posts_with("自動の公開依頼に失敗しました")), 1)
        self.make(auto_publish=True)                # 再起動しても間隔を守る
        self.tick()
        self.assertEqual(attempts(), 1)
        for expected in (2, 3, 4):
            self.advance(31)
            self.tick()
            self.assertEqual(attempts(), expected)
        self.dispatch_error = None
        for _ in range(3):                          # 上限に達したら、直っても自動では送らない(人が画面から送る)
            self.advance(31)
            self.tick()
        self.assertEqual((attempts(), self.dispatched), (4, []))
        self.assertEqual(len(self.posts_with("自動の公開依頼に失敗しました")), 1)
        self.assertEqual(len(self.posts_with("公開依頼のやり直しをあきらめました")), 1)
        self.assertNotIn("gh-token", "\n".join(self.posts))

        self.add_row("左回り○")                      # 送る内容が変わったら数え直す
        self.tick()
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(len(self.dispatched[0]["rows"]), 2)

    def test_missing_token_fails_without_sending(self):
        self.ready(token_file=self.base / "none")
        self.tick()
        self.tick()
        self.assertEqual(self.dispatched, [])
        self.assertEqual(len(self.posts_with("トークンファイルを読めません")), 1)

    def test_extract_then_publish_end_to_end(self):
        self.shot()
        self.make(auto_extract=True, auto_confirm=True, auto_publish=True)
        self.advance(11)
        self.tick()   # 読み取り
        self.tick()   # 読み取りの通知と公開依頼
        self.tick()
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(len(self.posts_with("読み取り完了")), 1)
        self.assertEqual(len(self.posts_with("公開を依頼しました")), 1)


class BackupTests(AutomationTestCase):
    def test_daily_backup_and_rotation_only_touches_matching_files(self):
        self.make(backup_keep=2)
        folder = self.app.config.backup_dir
        keep_out = ["guide-2020.sqlite3", "notes.txt", "guide-20200101.sqlite3.bak", "other-20200101.sqlite3",
                    "guide-20200101.sqlite3-wal", "xguide-20200101.sqlite3"]
        for name in ["guide-20200101.sqlite3", "guide-20200102.sqlite3", "guide-20200103.sqlite3", *keep_out]:
            write(folder / name, "old")
        (folder / "guide-20190101.sqlite3").mkdir()   # 同じ名前の形でもフォルダは消さない
        self.add_row()
        self.tick()
        today = "guide-" + time.strftime("%Y%m%d", time.localtime(self.now)) + ".sqlite3"
        names = {p.name for p in folder.iterdir()}
        self.assertEqual(names, {today, "guide-20200103.sqlite3", "guide-20190101.sqlite3", *keep_out})
        copy = sqlite3.connect(folder / today)
        self.assertEqual(copy.execute("SELECT skill FROM skills").fetchall(), [("末脚",)])
        copy.close()
        self.assertEqual(self.app.automation.status()["last_backup"]["file"], today)

        before = (folder / today).stat().st_mtime_ns
        self.advance(60)
        self.tick()
        if time.strftime("%Y%m%d", time.localtime(self.now)) in today:   # 同じ日なら作り直さない
            self.assertEqual((folder / today).stat().st_mtime_ns, before)
        self.advance(24 * 60)
        self.tick()
        left = sorted(p.name for p in folder.iterdir() if automation.BACKUP_RE.fullmatch(p.name) and p.is_file())
        self.assertEqual(len(left), 2)
        self.assertEqual(left[0], today)

    def test_backup_failure_does_not_stop_other_steps_and_is_not_retried_every_minute(self):
        self.make(auto_publish=True)
        self.add_row()
        write(self.base / "blocker", "x")
        self.app.config = dataclasses.replace(self.app.config, backup_dir=self.base / "blocker" / "backups")
        self.own()
        with contextlib.redirect_stderr(io.StringIO()):
            self.app.automation.tick()
        self.assertIn("backup", self.app.automation.errors)
        self.assertEqual(len(self.dispatched), 1)   # ほかの処理は続く
        self.app.automation.tick()
        self.assertNotIn("backup", self.app.automation.errors)   # 30分は試さない

    def test_migration_adds_state_table(self):
        self.make()
        with self.app.connect() as conn:
            automation.set_state(conn, "k", {"a": 1})
            self.assertEqual(automation.get_state(conn, "k"), {"a": 1})
            self.assertTrue(automation.claim(conn, "c"))
            self.assertFalse(automation.claim(conn, "c"))


if __name__ == "__main__":
    unittest.main()
