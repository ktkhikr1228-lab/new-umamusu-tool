"""公開まわり: サイトに出ている内容(race_data.json)との比較と、GitHub Actionsへの公開依頼。

- サイトの内容はGitHubのmainにある race_data.json を取得して使う(取得できなければ手元のファイル)
- 依頼に含めるのは「OK」かつ「サイトにない / 区分が違う」行だけ
- 検証と送信は既存の backend/tools/publish_reviewed_race_data.py・dispatch_reviewed_race_data.py を使う
- PRのマージは人が行う。このアプリはマージしない
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import REPO_ROOT
from .skill_master import SkillMaster, normalize

sys.path.insert(0, str(REPO_ROOT / "backend" / "tools"))
import dispatch_reviewed_race_data as dispatcher  # noqa: E402
import publish_reviewed_race_data as publisher  # noqa: E402

REPO = dispatcher.REPO
RACE_DATA_URL = f"https://raw.githubusercontent.com/{REPO}/main/frontend/src/data/race_data.json"
LOCAL_RACE_DATA = REPO_ROOT / "frontend" / "src" / "data" / "race_data.json"
CHUNK_BYTES = 46_000  # 1回の依頼の上限(48KB)より少し小さく
TIERS = ("super_recommended", "recommended")


class PublishError(ValueError):
    """画面へそのまま返してよいエラー。"""


class Published:
    """サイトに出ている内容。(コース, 脚質, スキル) → 区分。"""

    def __init__(self, data: dict | None = None, source: str = "", loaded_at: str = ""):
        self.source = source
        self.loaded_at = loaded_at
        self._tiers: dict[tuple[str, str, str], str] = {}
        for race, strategies in (data or {}).items():
            if not isinstance(strategies, dict):
                continue
            for strategy, detail in strategies.items():
                if not isinstance(detail, dict):
                    continue
                for tier in TIERS:
                    for skill in detail.get(tier) or []:
                        if isinstance(skill, str):
                            self._tiers.setdefault((race, strategy, normalize(skill)), tier)

    def tier(self, race: str, strategy: str, skill: str) -> str | None:
        return self._tiers.get((race, strategy, normalize(skill)))

    @property
    def size(self) -> int:
        return len(self._tiers)

    def status(self, race: str, strategy: str, skill: str, tier: str) -> str:
        """new(サイトにない) / same(同じ区分で公開済み) / moved(区分が違う)"""
        current = self.tier(race, strategy, skill)
        if current is None:
            return "new"
        return "same" if current == tier else "moved"


class PublishedSource:
    """サイトの内容を取得して保持する。取得に失敗しても前回の内容で動き続ける。"""

    def __init__(self, url: str | None = RACE_DATA_URL, local: Path = LOCAL_RACE_DATA, opener=urllib.request.urlopen):
        self.url, self.local, self.opener = url, Path(local), opener
        self.current = Published()
        self.error: str | None = None
        self._lock = threading.Lock()

    def refresh(self) -> Published:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        data, source, error = None, "", None
        if self.url:
            try:
                with self.opener(self.url, timeout=20) as response:
                    data, source = json.loads(response.read().decode("utf-8")), "GitHub main"
            except Exception as exc:  # noqa: BLE001 - ネットワーク不調でも手元のファイルで続ける
                error = f"GitHubから取得できませんでした: {exc}"
        if data is None and self.local.exists():
            data, source = json.loads(self.local.read_text(encoding="utf-8")), "手元のrace_data.json"
        with self._lock:
            if data is not None:
                self.current = Published(data, source, now)
            self.error = error
        return self.current


@dataclass
class EventPlan:
    event: str
    added: list[dict] = field(default_factory=list)      # サイトにない
    moved: list[dict] = field(default_factory=list)      # 区分が変わる
    unchanged: int = 0                                    # 同じ区分で公開済み
    requested: int = 0                                    # 依頼済みでマージ待ち
    draft: int = 0                                        # 未確認(含めない)
    blocked: list[dict] = field(default_factory=list)    # 公開できない行

    @property
    def rows(self) -> list[dict]:
        return self.added + self.moved

    def to_dict(self) -> dict:
        return {"event": self.event, "added": self.added, "moved": self.moved, "unchanged": self.unchanged,
                "requested": self.requested, "draft": self.draft, "blocked": self.blocked}


def plan_event(conn: sqlite3.Connection, master: SkillMaster, published: Published, event: str) -> EventPlan:
    """そのイベントで公開依頼に含める行を決める。"""
    plan = EventPlan(event)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM skills WHERE event = ? AND status != 'rejected' ORDER BY race, strategy, tier, id", (event,))]
    ready_tiers: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r["status"] == "ready":
            ready_tiers[(r["race"], r["strategy"], normalize(r["skill"]))].add(r["tier"])
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        if r["status"] == "draft":
            plan.draft += 1
            continue
        canonical = master.canonical(r["skill"])
        key = (r["race"], r["strategy"], normalize(r["skill"]))
        item = {"id": r["id"], "race": r["race"], "strategy": r["strategy"], "tier": r["tier"],
                "skill": canonical or r["skill"], "current_tier": published.tier(*key)}
        if canonical is None:
            plan.blocked.append({**item, "reason": "スキルマスタにない名前"})
            continue
        if len(ready_tiers[key]) > 1:
            plan.blocked.append({**item, "reason": "超おすすめ・おすすめの両方でOKになっている(片方を却下)"})
            continue
        if key in seen:  # 同じスキルが別の画像にも写っていた(同じ区分)
            continue
        seen.add(key)
        state = published.status(r["race"], r["strategy"], canonical, r["tier"])
        if state == "same":
            plan.unchanged += 1
        elif r["published_at"]:
            plan.requested += 1
        elif state == "new":
            plan.added.append(item)
        else:
            plan.moved.append(item)
    return plan


def build_requests(event: str, rows: list[dict], master_names: list[str]) -> list[dict]:
    """既存スクリプトと同じ検証をかけ、48KB以下の依頼に分ける。"""
    if not rows:
        raise PublishError("公開する行がありません")
    payload_rows = [{"race": r["race"], "strategy": r["strategy"], "tier": r["tier"], "skill": r["skill"],
                     "status": "ready"} for r in rows]
    try:
        publisher.validate({"event": event, "rows": payload_rows}, master_names)
    except ValueError as error:
        raise PublishError(f"公開データの検証で止まりました: {error}") from error

    requests, chunk = [], []
    for row in payload_rows:
        trial = chunk + [row]
        if chunk and len(json.dumps({"event": event, "rows": trial}, ensure_ascii=False, separators=(",", ":")).encode()) > CHUNK_BYTES:
            requests.append({"event": event, "rows": chunk})
            trial = [row]
        chunk = trial
    requests.append({"event": event, "rows": chunk})
    return [publisher.validate(r, master_names) for r in requests]


def read_token(path: Path) -> str:
    try:
        token = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PublishError(f"GitHubのトークンファイルを読めません: {path}") from error
    if not token:
        raise PublishError(f"GitHubのトークンファイルが空です: {path}")
    return token


def send(conn: sqlite3.Connection, plan: EventPlan, master_names: list[str], token_file: Path,
         dry_run: bool = False, dispatch=dispatcher.dispatch) -> dict:
    """公開依頼を送る。dry_runなら送らずに件数とサイズだけ返す。"""
    if plan.blocked:
        raise PublishError(f"公開できない行が{len(plan.blocked)}件あります。確認画面で直してください")
    requests = build_requests(plan.event, plan.rows, master_names)
    sizes = [len(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode()) for r in requests]
    summary = {"event": plan.event, "rows": len(plan.rows), "added": len(plan.added), "moved": len(plan.moved),
               "requests": len(requests), "bytes": sizes, "sent": False}
    if dry_run:
        return summary
    token = read_token(token_file)
    sent_ids: list[int] = []
    try:
        for request, part in zip(requests, _split_ids(plan.rows, requests)):
            dispatch(request, token)
            sent_ids.extend(part)
    except Exception as error:  # noqa: BLE001 - 途中まで送れた分は記録してから知らせる
        _record(conn, plan.event, sent_ids, summary | {"error": str(error)})
        detail = f"HTTP {error.code}" if hasattr(error, "code") else str(error)
        raise PublishError(f"GitHubへの依頼に失敗しました({detail})。送れたのは{len(sent_ids)}行です") from error
    summary |= {"sent": True, "actions_url": f"https://github.com/{REPO}/actions/workflows/{dispatcher.WORKFLOW}",
                "pr_url": f"https://github.com/{REPO}/pulls?q=is%3Apr+head%3Adata%2Freviewed-race-{plan.event}"}
    _record(conn, plan.event, sent_ids, summary)
    return summary


def _split_ids(rows: list[dict], requests: list[dict]) -> list[list[int]]:
    parts, start = [], 0
    for request in requests:
        parts.append([r["id"] for r in rows[start:start + len(request["rows"])]])
        start += len(request["rows"])
    return parts


def _record(conn: sqlite3.Connection, event: str, ids: list[int], summary: dict) -> None:
    with conn:
        conn.executemany("UPDATE skills SET published_at = datetime('now', 'localtime') WHERE id = ?", [(i,) for i in ids])
        conn.execute("INSERT INTO publish_log (event, rows, result) VALUES (?, ?, ?)",
                     (event, len(ids), json.dumps(summary, ensure_ascii=False)))


def reset_requested(conn: sqlite3.Connection, event: str) -> int:
    """PRを閉じた場合などに「依頼済み」を取り消し、もう一度依頼できるようにする。"""
    with conn:
        return conn.execute("UPDATE skills SET published_at = NULL WHERE event = ? AND published_at IS NOT NULL",
                            (event,)).rowcount


def history(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [{**dict(r), "result": json.loads(r["result"])} for r in conn.execute(
        "SELECT * FROM publish_log ORDER BY id DESC LIMIT ?", (limit,))]
