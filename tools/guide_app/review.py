"""確認画面のためのデータ操作。HTTPから切り離してテストできるようにしている。

確認の流れ:
- マスタにない名前・◎付き・両区分に出ている行は「要注意」として1行ずつ確認する
- それ以外(マスタと合致)は折りたたみ、「この画像OK」を押した時点でOKにする
  → 人が一度も見ていない画像の行は公開対象にならない
"""
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from . import db
from .skill_master import SkillMaster, normalize

TIER_LABELS = {"super_recommended": "超おすすめ", "recommended": "おすすめ"}
STRATEGY_ORDER = {"逃げ": 0, "先行": 1, "差し": 2, "追込": 3}
EDITABLE = {"skill", "tier", "status"}


class ReviewError(ValueError):
    """画面へそのまま返してよい入力エラー。"""


def _base_name(skill: str) -> str:
    """「左回り◎」「左回り○」を同じグループにまとめるための名前。"""
    return normalize(skill).rstrip("○◎")


def attention_reasons(rows: list[dict], master: SkillMaster) -> dict[int, list[str]]:
    """行ごとの要注意理由。rowsは同じ (イベント, コース, 脚質) の全行。"""
    reasons: dict[int, list[str]] = defaultdict(list)
    live = [r for r in rows if r["status"] != "rejected"]

    by_image_base: dict[tuple[str, str], list[dict]] = defaultdict(list)
    tiers_by_skill: dict[str, set[str]] = defaultdict(set)
    for r in live:
        by_image_base[(r["source_file"], _base_name(r["skill"]))].append(r)
        tiers_by_skill[normalize(r["skill"])].add(r["tier"])

    for r in live:
        if master.canonical(r["skill"]) is None:
            reasons[r["id"]].append("スキルマスタにない名前")
        elif r["skill"].endswith("◎"):
            reasons[r["id"]].append("◎は○との読み違いが多い")
        group = by_image_base[(r["source_file"], _base_name(r["skill"]))]
        if r["skill"][-1:] in "○◎" and {g["skill"][-1:] for g in group} >= {"○", "◎"}:
            reasons[r["id"]].append("同じ画像に○と◎の両方がある")
        if len(tiers_by_skill[normalize(r["skill"])]) > 1:
            reasons[r["id"]].append("超おすすめ・おすすめの両方にある")
    return dict(reasons)


def overview(conn: sqlite3.Connection) -> list[dict]:
    """ホーム画面用: イベント → コース → 脚質ごとの件数。"""
    rows = conn.execute(
        """
        SELECT s.event, s.race, s.strategy,
               COUNT(*) AS total,
               SUM(s.status = 'draft') AS draft,
               SUM(s.status = 'ready') AS ready,
               SUM(s.status = 'rejected') AS rejected,
               COUNT(DISTINCT s.source_file) AS images,
               COUNT(DISTINCT CASE WHEN i.reviewed_at IS NOT NULL THEN s.source_file END) AS images_reviewed,
               MAX(s.created_at) AS latest
        FROM skills s
        LEFT JOIN images i ON i.event = s.event AND i.source_file = s.source_file
        GROUP BY s.event, s.race, s.strategy
        """
    ).fetchall()
    hidden = {r["event"] for r in conn.execute("SELECT event FROM events WHERE hidden = 1")}
    events: dict[str, dict] = {}
    for r in rows:
        ev = events.setdefault(r["event"], {"event": r["event"], "races": {}, "latest": ""})
        ev["latest"] = max(ev["latest"], r["latest"] or "")
        race = ev["races"].setdefault(r["race"], {"race": r["race"], "strategies": []})
        race["strategies"].append({k: r[k] for k in r.keys() if k not in ("event", "race", "latest")})
    result = []
    # 表示中を先に、新しく取り込んだイベントほど上に。同時刻ならイベント名の新しい順
    ordered = sorted(events.values(), key=lambda e: (e["latest"], e["event"]), reverse=True)
    ordered.sort(key=lambda e: e["event"] in hidden)
    for ev in ordered:
        races = []
        for race in sorted(ev["races"].values(), key=lambda x: x["race"]):
            race["strategies"].sort(key=lambda s: STRATEGY_ORDER.get(s["strategy"], 9))
            races.append(race)
        totals = {k: sum(s[k] for race in races for s in race["strategies"])
                  for k in ("total", "draft", "ready", "rejected", "images", "images_reviewed")}
        result.append({"event": ev["event"], "races": races, "hidden": ev["event"] in hidden,
                       "latest": ev["latest"], **totals})
    return result


def set_event_hidden(conn: sqlite3.Connection, event: str, hidden: bool) -> None:
    """イベントをホームで隠す/戻す。データは消さない。"""
    if not conn.execute("SELECT 1 FROM skills WHERE event = ? LIMIT 1", (event,)).fetchone():
        raise ReviewError("イベントが見つかりません")
    with conn:
        conn.execute(
            "INSERT INTO events (event, hidden) VALUES (?, ?) ON CONFLICT (event) DO UPDATE SET hidden = excluded.hidden",
            (event, int(bool(hidden))),
        )


def group(conn: sqlite3.Connection, master: SkillMaster, event: str, race: str, strategy: str) -> dict:
    """確認画面用: 1つの (イベント, コース, 脚質) を画像ごとにまとめて返す。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM skills WHERE event = ? AND race = ? AND strategy = ? ORDER BY source_file, id",
        (event, race, strategy),
    )]
    if not rows:
        raise ReviewError("該当するデータがありません")
    reviewed = {r["source_file"]: r["reviewed_at"] for r in conn.execute(
        "SELECT source_file, reviewed_at FROM images WHERE event = ?", (event,))}
    reasons = attention_reasons(rows, master)

    images: dict[str, dict] = {}
    for r in rows:
        r["attention"] = reasons.get(r["id"], [])
        r["known"] = master.canonical(r["skill"]) is not None
        r["suggestions"] = [] if r["known"] else master.suggest(r["skill"])
        image = images.setdefault(r["source_file"], {
            "file": r["source_file"], "reviewed_at": reviewed.get(r["source_file"]), "rows": []})
        image["rows"].append(r)
    for image in images.values():
        tiers = {r["tier"] for r in image["rows"] if r["status"] != "rejected"}
        image["tier"] = tiers.pop() if len(tiers) == 1 else None
        image["attention"] = sum(1 for r in image["rows"] if r["attention"])
    return {"event": event, "race": race, "strategy": strategy, "images": list(images.values())}


def update_row(conn: sqlite3.Connection, row_id: int, changes: dict) -> dict:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ReviewError(f"変更できない項目です: {', '.join(sorted(unknown))}")
    values = {}
    if "skill" in changes:
        skill = str(changes["skill"]).strip()
        if not skill:
            raise ReviewError("スキル名が空です")
        values["skill"] = skill
    if "tier" in changes:
        if changes["tier"] not in TIER_LABELS:
            raise ReviewError("区分が不正です")
        values["tier"] = changes["tier"]
    if "status" in changes:
        if changes["status"] not in db.STATUSES:
            raise ReviewError("状態が不正です")
        values["status"] = changes["status"]
    if not values:
        raise ReviewError("変更内容がありません")
    sets = ", ".join(f"{k} = ?" for k in values)
    try:
        with conn:
            cursor = conn.execute(
                f"UPDATE skills SET {sets}, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (*values.values(), row_id),
            )
    except sqlite3.IntegrityError as error:
        raise ReviewError("同じスキルが変更先の区分にすでにあります。片方を却下してください") from error
    if not cursor.rowcount:
        raise ReviewError("行が見つかりません")
    return dict(conn.execute("SELECT * FROM skills WHERE id = ?", (row_id,)).fetchone())


def review_image(conn: sqlite3.Connection, master: SkillMaster, event: str, source_file: str,
                 race: str, strategy: str) -> dict:
    """「この画像OK」。合致していて要注意でない未確認行をOKにし、画像を確認済みにする。"""
    data = group(conn, master, event, race, strategy)
    image = next((i for i in data["images"] if i["file"] == source_file), None)
    if image is None:
        raise ReviewError("画像が見つかりません")
    ids = [r["id"] for r in image["rows"] if r["status"] == "draft" and r["known"] and not r["attention"]]
    pending = [r for r in image["rows"] if r["status"] == "draft" and (not r["known"] or r["attention"])]
    already = image["reviewed_at"] is not None
    with conn:
        conn.executemany(
            "UPDATE skills SET status = 'ready', updated_at = datetime('now', 'localtime') WHERE id = ?",
            [(i,) for i in ids],
        )
        conn.execute(
            """INSERT INTO images (event, source_file, reviewed_at) VALUES (?, ?, datetime('now', 'localtime'))
               ON CONFLICT (event, source_file) DO UPDATE SET reviewed_at = excluded.reviewed_at""",
            (event, source_file),
        )
    return {"approved": len(ids), "pending": len(pending), "already_reviewed": already}


def set_images_tier(conn: sqlite3.Connection, event: str, race: str, strategy: str,
                    files: list[str], tier: str) -> dict:
    """選んだ画像の行の区分をまとめて変える(撮影時の区分切り替え忘れの修正用)。

    変更先の区分に同じスキルがすでにある行は、区分を変えずに「却下(重複)」にする。
    """
    if tier not in TIER_LABELS:
        raise ReviewError("区分が不正です")
    if not files:
        raise ReviewError("画像が選ばれていません")
    marks = ",".join("?" * len(files))
    rows = conn.execute(
        f"""SELECT s.id, EXISTS (
                SELECT 1 FROM skills t WHERE t.event = s.event AND t.race = s.race AND t.strategy = s.strategy
                AND t.tier = ? AND t.extracted_skill = s.extracted_skill) AS dup
            FROM skills s
            WHERE s.event = ? AND s.race = ? AND s.strategy = ? AND s.tier != ? AND s.source_file IN ({marks})""",
        (tier, event, race, strategy, tier, *files),
    ).fetchall()
    moved = [(tier, r["id"]) for r in rows if not r["dup"]]
    duplicates = [(r["id"],) for r in rows if r["dup"]]
    with conn:
        conn.executemany(
            "UPDATE skills SET tier = ?, updated_at = datetime('now', 'localtime') WHERE id = ?", moved)
        conn.executemany(
            """UPDATE skills SET status = 'rejected', memo = trim(memo || ' 区分変更時に重複'),
               updated_at = datetime('now', 'localtime') WHERE id = ?""", duplicates)
    return {"changed": len(moved), "duplicates": len(duplicates)}


class ImageIndex:
    """スクショのファイル名 → 実ファイルの対応。CSVのsource_fileはファイル名だけのことがあるため。"""

    SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

    REFRESH_INTERVAL = 30  # 見つからない画像のたびにフォルダ全体を読み直さないための間隔(秒)

    def __init__(self, root: Path):
        self.root = Path(root)
        self._by_name: dict[str, list[Path]] = {}
        self._loaded_at: float | None = None

    def refresh(self) -> None:
        index: dict[str, list[Path]] = defaultdict(list)
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.suffix.lower() in self.SUFFIXES and path.is_file():
                    index[path.name].append(path)
        self._by_name = dict(index)
        self._loaded_at = time.monotonic()

    def find(self, event: str, source_file: str) -> Path | None:
        name = Path(source_file.replace("\\", "/")).name
        stale = self._loaded_at is None or time.monotonic() - self._loaded_at > self.REFRESH_INTERVAL
        if name not in self._by_name and stale:
            self.refresh()
        candidates = self._by_name.get(name, [])
        for path in candidates:  # 同名ファイルが複数あるときはイベント名を含む方を優先
            if event in path.parts:
                return path
        return candidates[0] if candidates else None
