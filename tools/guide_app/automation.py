"""自動処理: 人が触らなくても進む部分をまとめる。どれも config.toml で有効にしたものだけが動く(既定はオフ)。

- 自動読み取り(auto_extract): 撮影が止まってしばらくしたら、読み取りを始める
- 通知(discord_webhook_file): 読み取りの完了・失敗、公開依頼の送信、あきらめたときをDiscordへ知らせる
- 自動公開依頼(auto_publish): 人が見る行が残っていなければ、公開を依頼する(PRを作るところまで。マージはしない)
- 日次バックアップ(backup_keep): 1日1回、DBのコピーを作る

約60秒おきに tick() が呼ばれる。外部への通信は失敗するものとして扱い、やり直しには上限と間隔を付ける。
やり直しの回数・通知済みの印はDB(automation_state)に置くので、再起動しても数え直さない。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from . import extract, publish

TICK_SECONDS = 60
EXTRACT_RETRIES = 3            # 読めない画像が残ったときにやり直す回数(最初の1回とは別)
PUBLISH_RETRIES = 3            # 公開依頼が失敗したときにやり直す回数(最初の1回とは別)
RETRY_INTERVAL = 30 * 60       # やり直しの間隔(秒)
STARTUP_WAIT = 2 * 60          # 起動直後は自動読み取りを始めない(再起動のたびに、人の作業中にジョブが走らないように)
SITE_SOURCE = "GitHub main"    # サイトの内容・スキルマスタをGitHubから読めたときの source
BACKUP_RE = re.compile(r"guide-\d{8}\.sqlite3")
DISCORD_LIMIT = 1900           # Discordの本文は2000文字まで


# ---------- 覚え書き(DB) ----------
def get_state(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM automation_state WHERE key = ?", (key,)).fetchone()
    try:
        return json.loads(row["value"]) if row else None
    except json.JSONDecodeError:
        return None


def set_state(conn: sqlite3.Connection, key: str, value) -> None:
    with conn:
        conn.execute(
            """INSERT INTO automation_state (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = datetime('now', 'localtime')""",
            (key, json.dumps(value, ensure_ascii=False)))


def clear_state(conn: sqlite3.Connection, key: str) -> None:
    with conn:
        conn.execute("DELETE FROM automation_state WHERE key = ?", (key,))


def claim(conn: sqlite3.Connection, key: str) -> bool:
    """その印をまだ付けていなければ付けてTrue。二重通知を防ぐために、送る前に付ける。"""
    with conn:
        return conn.execute("INSERT OR IGNORE INTO automation_state (key, value) VALUES (?, '1')", (key,)).rowcount == 1


# ---------- 通知 ----------
class Notifier:
    """Discordのwebhookへ短い文を送る。失敗しても例外を出さず、最後の失敗だけ覚えておく。

    URLはファイルから毎回読み、ログ・エラー文・画面には出さない。
    """

    def __init__(self, url_file: Path | None, opener=urllib.request.urlopen, timeout: int = 10, clock=time.time):
        self.url_file, self.opener, self.timeout, self.clock = url_file, opener, timeout, clock
        self.last_error: dict | None = None
        self.last_sent_at = ""

    @property
    def enabled(self) -> bool:
        return self.url_file is not None

    def _fail(self, text: str) -> bool:
        self.last_error = {"at": stamp(self.clock()), "text": text}
        return False

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            url = Path(self.url_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            return self._fail(f"webhookのファイルを読めません({self.url_file})。ファイルを作り直してください")
        if not url.startswith(("https://", "http://")):
            return self._fail(f"webhookのファイルの中身がURLではありません({self.url_file})")
        if len(text) > DISCORD_LIMIT:
            text = text[:DISCORD_LIMIT] + "…"
        request = urllib.request.Request(
            url, data=json.dumps({"content": text}, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "guide-app-notify/1"})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as error:   # エラー文にURLが混ざらないよう、番号だけ残す
            return self._fail(f"Discordへ送れませんでした(HTTP {error.code})。webhookのURLが有効か確認してください")
        except Exception as error:  # noqa: BLE001 - 通知の失敗でほかの処理は止めない
            return self._fail(f"Discordへ送れませんでした({type(error).__name__})。ネットワークを確認してください")
        self.last_error = None
        self.last_sent_at = stamp(self.clock())
        return True


def stamp(now: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))


def newest_change(inbox: Path, event: str) -> int | None:
    """そのイベントの画像のうち、いちばん新しい更新時刻(ナノ秒)。

    転送ツールが撮影時刻(mtime)を保ったままコピーしても「置かれたばかり」と分かるよう、ctimeも見る。
    """
    newest = None
    for shot in extract.list_shots(inbox, event):
        try:
            st = shot.path.stat()
        except OSError:
            continue
        value = max(st.st_mtime_ns, st.st_ctime_ns)
        newest = value if newest is None else max(newest, value)
    return newest


def needs_human(conn: sqlite3.Connection, published, event: str) -> int:
    """人の確認が必要な行の数 = 未確認のうち、サイトに同じ区分で出ていないもの(ホームの「要確認」と同じ数え方)。"""
    count = 0
    for r in conn.execute("SELECT race, strategy, tier, skill FROM skills WHERE event = ? AND status = 'draft'", (event,)):
        if not published or published.status(r["race"], r["strategy"], r["skill"], r["tier"]) != "same":
            count += 1
    return count


def untallied(conn: sqlite3.Connection, inbox: Path, event: str) -> int:
    """読み取りは済んでいるのに、行になっていない画像の数(途中で止まった・コースを読めなかった場合に残る)。"""
    files = {s.file for s in extract.list_shots(inbox, event)}
    read = {r["source_file"] for r in conn.execute(
        "SELECT DISTINCT source_file FROM readings WHERE event = ? AND error = ''", (event,))}
    have = {r["source_file"] for r in conn.execute("SELECT DISTINCT source_file FROM skills WHERE event = ?", (event,))}
    have |= {r["source_file"] for r in conn.execute("SELECT source_file FROM images WHERE event = ?", (event,))}
    return len((files & read) - have)


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def hidden_events(conn: sqlite3.Connection) -> set[str]:
    return {r["event"] for r in conn.execute("SELECT event FROM events WHERE hidden = 1")}


# ---------- バックアップ ----------
def backup_db(db_path: Path, backup_dir: Path, keep: int, now: float) -> Path | None:
    """今日の分がなければ guide-YYYYMMDD.sqlite3 を作り、古いものを消す。作ったらそのパスを返す。"""
    backup_dir = Path(backup_dir)
    target = backup_dir / f"guide-{time.strftime('%Y%m%d', time.localtime(now))}.sqlite3"
    if target.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")   # 途中で止まっても、できかけを本物と間違えない
    partial.unlink(missing_ok=True)
    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(partial)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    os.replace(partial, target)
    rotate_backups(backup_dir, keep)
    return target


def rotate_backups(backup_dir: Path, keep: int) -> list[Path]:
    """新しい順に keep 個を残して消す。消すのは guide-YYYYMMDD.sqlite3 という名前のファイルだけ。"""
    files = sorted((p for p in Path(backup_dir).iterdir() if BACKUP_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink()),
                   key=lambda p: p.name, reverse=True)
    removed = []
    for path in files[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


# ---------- 本体 ----------
class Automation:
    """app は server.App(config / connect / extractor / master / published / published_source / publish_lock を使う)。

    clock・notifier・dispatch はテストで差し替えられる。
    """

    def __init__(self, app, clock=time.time, notifier: Notifier | None = None, dispatch=None):
        self.app, self.clock, self.dispatch = app, clock, dispatch
        self.notifier = notifier or Notifier(app.config.discord_webhook_file, clock=clock)
        self.notes: list[str] = []          # いま止まっている理由(画面に出す)
        self.errors: dict[str, str] = {}    # 処理ごとの最後の失敗
        self._lock = threading.Lock()
        self._backup_retry_at = 0.0
        self.started = clock()

    # ---- 共通 ----
    @property
    def url(self) -> str:
        return f"http://uma-pi:{self.app.config.port}/"

    def _job_running(self) -> bool:
        job = self.app.extractor.job
        return bool(job and job.state == "running")

    def _action(self, conn: sqlite3.Connection, text: str, now: float) -> None:
        set_state(conn, "last_action", {"at": stamp(now), "text": text})

    def _notify_once(self, conn: sqlite3.Connection, key: str, text: str) -> bool:
        """同じ key の通知は一度だけ。送信に失敗しても送り直さない(二重に届くよりは、画面の表示で気付けるほうを選ぶ)。"""
        if not self.notifier.enabled or not claim(conn, "notified:" + key):
            return False
        return self.notifier.send(text)

    def tick(self) -> None:
        """1回分の見回り。どの処理が失敗しても、ほかの処理とサーバは止めない。"""
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = self.clock()
            notes: list[str] = []
            for name, step in (("init", self._init), ("backup", self._backup), ("track_job", self._track_job),
                               ("notify_job", self._notify_job),
                               ("extract", self._auto_extract), ("publish", self._auto_publish),
                               ("notify_publish", self._notify_published)):
                try:
                    with self.app.connect() as conn:
                        step(conn, now, notes)
                    self.errors.pop(name, None)
                except Exception as error:  # noqa: BLE001
                    traceback.print_exc()
                    self.errors[name] = f"{type(error).__name__}: {error}"[:200]
            self.notes = notes
        finally:
            self._lock.release()

    def _init(self, conn, now: float, notes: list[str]) -> None:
        # 公開依頼の通知は「ここから先」の分だけ。初回に、これまでの履歴をまとめて通知しない
        if not isinstance(get_state(conn, "publish_notified_id"), int):
            last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM publish_log").fetchone()[0]
            set_state(conn, "publish_notified_id", last)

    # ---- バックアップ ----
    def _backup(self, conn, now: float, notes: list[str]) -> None:
        cfg = self.app.config
        if cfg.backup_keep <= 0 or now < self._backup_retry_at:
            return
        try:
            made = backup_db(cfg.db_path, cfg.backup_dir, cfg.backup_keep, now)
        except Exception:
            self._backup_retry_at = now + RETRY_INTERVAL   # 置き場所に書けないときなどに、毎分は試さない
            raise
        if made:
            set_state(conn, "last_backup", {"at": stamp(now), "file": made.name})

    # ---- 自動で始めた読み取りが終わったら、そのイベントを「自動公開の対象」として覚える ----
    def _track_job(self, conn, now: float, notes: list[str]) -> None:
        job = self.app.extractor.job
        mine = get_state(conn, "auto_job")
        if job and mine and job.state == "finished" and [job.event, job.started_at] == mine:
            set_state(conn, f"auto_event:{job.event}", {"at": stamp(now)})
            clear_state(conn, "auto_job")

    # ---- 読み取りの結果を知らせる ----
    def _notify_job(self, conn, now: float, notes: list[str]) -> None:
        job = self.app.extractor.job
        if not job or job.state not in ("finished", "failed") or not self.notifier.enabled:
            return
        todo = needs_human(conn, self.app.published, job.event)
        head = "読み取り完了" if job.state == "finished" else "読み取りがエラーで止まりました"
        lines = [f"【ガイド確認】{head}: {job.event}" + (f"({job.race})" if job.race else ""),
                 f"画像 {job.done}/{job.total}枚・{job.rows}行(自動OK {job.auto_ok}・自動却下 {job.auto_rejected})",
                 f"設定と食い違う画像 {job.warnings}枚・読めなかった呼び出し {len(job.errors)}件",
                 f"人の確認が必要: {todo}行"]
        if job.state == "failed" and job.errors:
            lines.append(f"理由: {job.errors[-1][:200]}")
        lines.append(self.url)
        self._notify_once(conn, f"extract:{job.event}:{job.started_at}", "\n".join(lines))

    # ---- 自動読み取り ----
    def _auto_extract(self, conn, now: float, notes: list[str]) -> None:
        cfg = self.app.config
        if not cfg.auto_extract:
            return
        names = [r.name for r in cfg.readers]
        if not names:
            notes.append("自動読み取り: 読み取りに使うモデル([[readers]])が未設定のため動きません")
            return
        if cfg.auto_confirm and self.app.master_info.get("source") != SITE_SOURCE:
            # 手元の古いマスタで自動確定すると、新しいスキルを誤読として却下してしまう
            notes.append("自動読み取り: スキルマスタをGitHubから読めていないため、保留しています")
            return
        if self._job_running() or now - self.started < STARTUP_WAIT:
            return
        hidden = hidden_events(conn)
        readers = digest([[r.name, r.model] for r in cfg.readers])
        started = False
        for cap in extract.captures(conn, cfg.inbox_dir, names, extract.primary_name(cfg.readers)):
            event = cap["event"]
            if event in hidden:
                continue
            # 未抽出の画像のほか、読み取り済みなのに行になっていない画像(途中で止まった分)も対象。後者は呼び出しなしで突き合わせだけ行う
            pending = [cap["pending"], untallied(conn, cfg.inbox_dir, event)]
            if not any(pending):
                continue
            left = f"未抽出{pending[0]}枚・行になっていない画像{pending[1]}枚"
            newest = newest_change(cfg.inbox_dir, event)
            if newest is None or now - newest / 1e9 < cfg.auto_extract_idle_minutes * 60:
                continue   # まだ撮影中かもしれない
            key = f"extract:{event}"
            st = get_state(conn, key) or {}
            if st.get("newest") != newest or st.get("readers") != readers:   # 新しい撮影・モデルの設定変更 → 数え直す
                st = {"pending": pending, "newest": newest, "readers": readers, "attempts": 0, "last": 0, "gave_up": False}
            elif st.get("pending") != pending:  # 枚数が変わった(一部は読めた) → 回数は数え直すが、間隔は空ける
                st.update(pending=pending, attempts=0, gave_up=False)
            if st["attempts"] > EXTRACT_RETRIES:
                notes.append(f"{event}: 読み取りが終わっていません({left})。自動のやり直しは終了。ホームの「読み取りを開始」で再開できます")
                if not st["gave_up"]:
                    st["gave_up"] = True
                    set_state(conn, key, st)
                    self._action(conn, f"{event}: 読み取りのやり直しをあきらめました({left})", now)
                    self._notify_once(conn, f"extract-giveup:{event}:{digest(pending, newest, readers)}", "\n".join([
                        f"【ガイド確認】読み取りのやり直しをあきらめました: {event}",
                        f"{EXTRACT_RETRIES}回やり直しても終わりませんでした({left})",
                        "モデルの設定(APIキー・利用枠)を確認し、ホームの「読み取りを開始」を押してください",
                        self.url]))
                continue
            if started or (st["last"] and now - st["last"] < RETRY_INTERVAL):
                continue
            st["attempts"] += 1
            st["last"] = now
            set_state(conn, key, st)   # 始める前に数える(始められなかった場合も1回と数え、毎分は試さない)
            try:
                job = self.app.extractor.start(event, "")
            except extract.ExtractError as error:
                self._action(conn, f"{event}: 読み取りを始められませんでした({error})", now)
            else:
                set_state(conn, "auto_job", [job.event, job.started_at])
                self._action(conn, f"{event}: 読み取りを自動で開始({left}・{st['attempts']}回目)", now)
            started = True   # 読み取りは1つずつ。残りのイベントは次の見回りで

    # ---- 自動公開依頼 ----
    def publish_blockers(self, conn, event: str, plan, capture: dict | None) -> list[str]:
        """自動で公開を依頼しない理由。空なら依頼してよい。"""
        reasons = []
        if plan.blocked:
            reasons.append(f"公開できない行 {len(plan.blocked)}件")
        todo = needs_human(conn, self.app.published, event)
        if todo:
            reasons.append(f"人の確認が必要な行 {todo}件")
        warned = conn.execute(
            "SELECT COUNT(*) FROM images WHERE event = ? AND warning != '' AND reviewed_at IS NULL", (event,)).fetchone()[0]
        if warned:
            reasons.append(f"設定と食い違う未確認の画像 {warned}枚")
        if capture and capture["missing"]:
            reasons.append("撮り忘れの可能性(" + "、".join(capture["missing"]) + ")")
        if capture and capture["pending"]:
            reasons.append(f"未抽出の画像 {capture['pending']}枚")
        return reasons

    def _auto_publish(self, conn, now: float, notes: list[str]) -> None:
        cfg, app = self.app.config, self.app
        if not cfg.auto_publish or self._job_running():
            return
        if app.published.source != SITE_SOURCE or not app.published.size or app.published_source.error:
            # サイトの内容が分からない・古いまま送ると、公開済みの行まで送ってしまう
            notes.append("自動公開: サイトの内容をGitHubから読めていないため、保留しています")
            return
        captures = {c["event"]: c for c in extract.captures(conn, cfg.inbox_dir, [r.name for r in cfg.readers],
                                                            extract.primary_name(cfg.readers))}
        hidden = hidden_events(conn)
        events = [r["event"] for r in conn.execute("SELECT DISTINCT event FROM skills ORDER BY event DESC")]
        for event in events:
            # 対象は、この自動処理が読み取りを終えたイベントだけ。昔のイベントのOK行を勝手に送ると、新しいイベントの区分を戻してしまう
            if event in hidden or not get_state(conn, f"auto_event:{event}"):
                continue
            plan = publish.plan_event(conn, app.master, app.published, event)
            if plan.blocked:   # 同じ顔ぶれの「公開できない行」は一度だけ知らせる
                self._notify_once(conn, f"publish-blocked:{event}:{digest(sorted(r['id'] for r in plan.blocked))}", "\n".join([
                    f"【ガイド確認】公開できない行が{len(plan.blocked)}件あります: {event}",
                    "確認画面で直す(名前を直す・片方を却下する)と、自動で公開を依頼します", self.url]))
            if not plan.rows:
                continue
            reasons = self.publish_blockers(conn, event, plan, captures.get(event))
            if plan.moved:   # サイトに出ているスキルの区分を変える依頼は、人が見てから送る
                reasons.append(f"区分が変わる行 {len(plan.moved)}件(公開画面で確かめて、人が依頼する)")
                self._notify_once(conn, f"publish-moved:{event}:{digest(sorted(r['id'] for r in plan.moved))}", "\n".join([
                    f"【ガイド確認】自動では公開を依頼しません: {event}",
                    f"サイトに出ているスキルの区分が変わる行が{len(plan.moved)}件あります。公開画面で確かめて「公開を依頼する」を押してください",
                    self.url + "#/publish"]))
            if reasons:
                notes.append(f"{event}: 公開依頼は保留({'・'.join(reasons)})")
                continue
            key = f"publish_fail:{event}"
            sig = digest([r["id"] for r in plan.rows])
            st = get_state(conn, key) or {}
            if st.get("sig") != sig:   # 送る内容が変わったら数え直す
                st = {"sig": sig, "count": 0, "at": 0, "gave_up": False}
            if st["count"] > PUBLISH_RETRIES:
                notes.append(f"{event}: 公開依頼が続けて失敗したため止めています(公開画面の「公開を依頼する」で再開できます)")
                if not st["gave_up"]:
                    st["gave_up"] = True
                    set_state(conn, key, st)
                    self._action(conn, f"{event}: 公開依頼のやり直しをあきらめました", now)
                    self._notify_once(conn, f"publish-giveup:{event}:{sig}", "\n".join([
                        f"【ガイド確認】公開依頼のやり直しをあきらめました: {event}",
                        f"{PUBLISH_RETRIES}回やり直しても送れませんでした。GitHubのトークンを確認し、公開画面の「公開を依頼する」を押してください",
                        self.url + "#/publish"]))
                continue
            if st["count"] and now - st["at"] < RETRY_INTERVAL:
                notes.append(f"{event}: 公開依頼に失敗したため、30分あけてやり直します")
                continue
            if not app.publish_lock.acquire(blocking=False):
                continue   # 画面からの依頼を処理中。次の見回りで
            try:
                extra = {"dispatch": self.dispatch} if self.dispatch else {}
                # 公開はGitHub Actionsへの依頼(PR作成)まで。マージはここでは行わない
                result = publish.send(conn, plan, app.master.names, cfg.token_file, **extra)
            except Exception as error:  # noqa: BLE001 - PublishError以外(想定外)も同じ扱いで間隔を空ける
                st.update(count=st["count"] + 1, at=now)
                set_state(conn, key, st)
                message = str(error) if isinstance(error, publish.PublishError) else f"想定外のエラー({type(error).__name__})"
                self._action(conn, f"{event}: 公開依頼に失敗({message})", now)
                self._notify_once(conn, f"publish-fail:{event}:{sig}", "\n".join([
                    f"【ガイド確認】自動の公開依頼に失敗しました: {event}", message[:300],
                    f"30分おきに{PUBLISH_RETRIES}回までやり直します", self.url + "#/publish"]))
            else:
                clear_state(conn, key)
                self._action(conn, f"{event}: 公開を自動で依頼({result['rows']}行)", now)
            finally:
                app.publish_lock.release()

    # ---- 公開依頼を知らせる(画面からの依頼も、自動の依頼も) ----
    def _notify_published(self, conn, now: float, notes: list[str]) -> None:
        last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM publish_log").fetchone()[0]
        mark = get_state(conn, "publish_notified_id")
        if not isinstance(mark, int) or last <= mark:
            return
        rows = conn.execute("SELECT id, event, rows, result FROM publish_log WHERE id > ? ORDER BY id", (mark,)).fetchall()
        set_state(conn, "publish_notified_id", last)   # 送る前に進める(二重に送らない)
        for row in rows:
            try:
                result = json.loads(row["result"])
            except json.JSONDecodeError:
                continue
            if not result.get("sent"):   # 失敗した依頼は、画面か「自動の公開依頼に失敗」で知らせている
                continue
            self._notify_once(conn, f"publish:{row['id']}", "\n".join([
                f"【ガイド確認】公開を依頼しました: {row['event']}",
                f"{row['rows']}行(追加 {result.get('added', 0)}・区分変更 {result.get('moved', 0)})",
                "数分でPRができます。内容を確かめてマージしてください",
                f"PR: {result.get('pr_url', '')}"]))

    # ---- 画面用 ----
    def status(self) -> dict:
        cfg = self.app.config
        with self.app.connect() as conn:
            last_action = get_state(conn, "last_action")
            last_backup = get_state(conn, "last_backup")
        return {
            "auto_extract": cfg.auto_extract, "idle_minutes": cfg.auto_extract_idle_minutes,
            "auto_confirm": cfg.auto_confirm, "auto_publish": cfg.auto_publish,
            "notify": self.notifier.enabled, "backup_keep": cfg.backup_keep,
            "last_action": last_action, "last_backup": last_backup,
            "notify_error": self.notifier.last_error, "notified_at": self.notifier.last_sent_at,
            "notes": self.notes[:10], "errors": dict(self.errors),
        }


def start_automation(app, interval: int = TICK_SECONDS) -> threading.Thread:
    """自動処理の見回りを裏で始める。何が起きてもサーバは止めない。"""

    def loop():
        while True:
            try:
                app.automation.tick()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="automation", daemon=True)
    thread.start()
    return thread
