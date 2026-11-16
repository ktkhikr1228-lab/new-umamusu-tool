"""スクショからスキル名を読み取る(複数モデルの多数決)。

- 撮影フォルダ inbox/<イベント>/<脚質>/<区分>/ の画像を、設定した各モデルに読ませる
- 全モデルが一致して読んだスキルは「一致」、一部のモデルだけが読んだスキルは「要注意」として確認画面に出す
- モデルはOpenAI互換のAPI(chat/completions)で呼ぶ。GeminiもOpenAI互換の入口を持つので同じ仕組みで扱える
- 読み取り結果はモデルごとにDBへ残す。やり直しても、読み取り済みの画像・モデルは呼び直さない
"""
from __future__ import annotations

import base64
import difflib
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .importer import EVENT_RE, normalize_strategy, normalize_tier
from .skill_master import SkillMaster, normalize

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TIERS = ("super_recommended", "recommended")
TRACKS = ("東京", "中山", "阪神", "京都", "中京", "新潟", "札幌", "函館", "福島", "小倉")
RACE_RE = re.compile(rf"({'|'.join(TRACKS)}) (芝|ダート) ([0-9]{{4}})m")
STRATEGY_ORDER = {"逃げ": 0, "先行": 1, "差し": 2, "追込": 3}

PROMPT = (
    "これはゲーム「ウマ娘」のトレーナーガイド画面のスクリーンショットです。次の内容を読み取り、JSONオブジェクトだけを出力してください。\n"
    "- course: 画面上部のコース表記(例: 中山 芝 3600m)。読めなければ空文字\n"
    "- strategy: 選択中(色が付いている)の脚質タブ。逃げ・先行・差し・追込のいずれか。分からなければ空文字\n"
    "- sections: スキル一覧を、画面に写っている見出しごとに分けたもの。heading は見出しの文字"
    "(「超おすすめスキル」「おすすめスキル」)。見出しが写っていない部分のスキルは heading を空文字にする\n"
    "- skills: スキル名を上から順に、画面の表記どおりに。○と◎は区別する。"
    "スキル名以外(レース名、ボタン、説明文)や、文字が切れて読めないものは含めない\n"
    '例: {"course": "中山 芝 3600m", "strategy": "逃げ", '
    '"sections": [{"heading": "超おすすめスキル", "skills": ["スキルA"]}, {"heading": "", "skills": ["スキルB"]}]}'
)
COURSE_RE = re.compile(rf"({'|'.join(TRACKS)})\s*(芝|ダート)\s*([0-9]{{4}})\s*m")
TIER_LABELS = {"super_recommended": "超おすすめ", "recommended": "おすすめ"}


class ExtractError(ValueError):
    """画面へそのまま返してよいエラー。"""


@dataclass(frozen=True)
class Reader:
    """読み取りに使うモデル1つ分の設定。"""
    name: str
    base_url: str
    model: str
    key_file: Path | None = None
    key_env: str = ""
    key_header: str = "Authorization"   # キーを渡すヘッダー名。Authorization以外なら「Bearer 」を付けずにそのまま送る
    min_interval: float = 0.0   # 連続で呼ぶときの最低間隔(秒)。無料枠の回数制限向け
    timeout: int = 120

    def key(self) -> str:
        if self.key_env and os.environ.get(self.key_env):
            return os.environ[self.key_env].strip()
        if self.key_file:
            try:
                value = self.key_file.expanduser().read_text(encoding="utf-8").strip()
            except OSError as error:
                raise ExtractError(f"{self.name}: APIキーのファイルを読めません({self.key_file})") from error
            if value:
                return value
        raise ExtractError(f"{self.name}: APIキーが設定されていません")

    def auth_headers(self) -> dict[str, str]:
        key = self.key()
        if self.key_header.lower() == "authorization":
            return {"Authorization": "Bearer " + key}
        return {self.key_header: key}


@dataclass(frozen=True)
class Shot:
    path: Path
    file: str          # ファイル名(DBのsource_fileと同じ)
    strategy: str      # 逃げ/先行/差し/追込
    tier: str | None   # フォルダで区分が決まっていれば super_recommended / recommended


# ---------- 撮影フォルダ ----------
def list_shots(inbox: Path, event: str) -> list[Shot]:
    """inbox/<イベント>/<脚質>/[<区分>/]画像 を列挙する。"""
    root = Path(inbox) / event
    shots: list[Shot] = []
    if not root.is_dir():
        return shots
    for strategy_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        strategy = normalize_strategy(strategy_dir.name)
        if not strategy:
            continue
        for path in sorted(strategy_dir.rglob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
                continue
            relative = path.relative_to(strategy_dir)
            tier = normalize_tier(relative.parts[0]) if len(relative.parts) > 1 else None
            shots.append(Shot(path, path.name, strategy, tier))
    shots.sort(key=lambda s: (STRATEGY_ORDER.get(s.strategy, 9), TIERS.index(s.tier) if s.tier else 2, s.file))
    return shots


def list_events(inbox: Path) -> list[str]:
    inbox = Path(inbox)
    if not inbox.is_dir():
        return []
    return sorted((p.name for p in inbox.iterdir() if p.is_dir() and EVENT_RE.fullmatch(p.name)), reverse=True)


def captures(conn: sqlite3.Connection, inbox: Path, reader_names: list[str]) -> list[dict]:
    """ホーム画面用: イベントごとの撮影枚数と、まだ読み取っていない枚数。"""
    result = []
    saved_race = {r["event"]: r["race"] for r in conn.execute("SELECT event, race FROM events")}
    for event in list_events(inbox):
        shots = list_shots(inbox, event)
        if not shots:
            continue
        # 以前のCSV取り込みで行がある画像は抽出済みとして扱う。このアプリで読んだ画像は、全モデルが読めて初めて抽出済み
        have_rows = {r["source_file"] for r in conn.execute(
            "SELECT DISTINCT source_file FROM skills WHERE event = ? AND source_csv != 'guide_app'", (event,))}
        read = Counter(r["source_file"] for r in conn.execute(
            "SELECT source_file FROM readings WHERE event = ? AND error = ''", (event,)))
        cells: dict[tuple[str, str], dict] = {}
        pending = 0
        for s in shots:
            done = s.file in have_rows or (reader_names and read[s.file] >= len(reader_names))
            cell = cells.setdefault((s.strategy, s.tier or ""), {"strategy": s.strategy, "tier": s.tier, "images": 0, "pending": 0})
            cell["images"] += 1
            if not done:
                cell["pending"] += 1
                pending += 1
        race = saved_race.get(event) or ""
        if not race:
            row = conn.execute("SELECT race FROM skills WHERE event = ? LIMIT 1", (event,)).fetchone()
            race = row["race"] if row else ""
        result.append({"event": event, "images": len(shots), "pending": pending, "race": race,
                       "cells": list(cells.values()),
                       "missing": missing_cells(cells)})
    return result


def missing_cells(cells: dict) -> list[str]:
    """撮り忘れの疑い: 区分フォルダで撮っているのに、0枚の脚質・区分がある。"""
    if not any(tier for _, tier in cells):
        return []
    labels = {"super_recommended": "超おすすめ", "recommended": "おすすめ"}
    return [f"{strategy} {labels[tier]}" for strategy in STRATEGY_ORDER for tier in TIERS
            if (strategy, tier) not in cells]


# ---------- モデル呼び出し ----------
def _clean(items) -> list[str]:
    seen, out = set(), []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str) and item.strip() and item.strip() not in seen:
            seen.add(item.strip())
            out.append(item.strip())
    return out


def heading_tier(heading: object) -> str:
    text = str(heading or "")
    if "超" in text:
        return "super_recommended"
    return "recommended" if "おすすめ" in text else ""


def normalize_course(value: object) -> str:
    match = COURSE_RE.search(str(value or ""))
    return f"{match[1]} {match[2]} {match[3]}m" if match else ""


def parse_reply(text: str) -> dict:
    """モデルの返答を {"course", "strategy", "sections": [{"tier", "skills"}]} にそろえる。"""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    data = None
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
                break
            except json.JSONDecodeError:
                continue
    result = {"course": "", "strategy": "", "sections": []}
    if isinstance(data, dict):
        result["course"] = normalize_course(data.get("course"))
        result["strategy"] = normalize_strategy(str(data.get("strategy") or "")) or ""
        sections = data.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict) and _clean(section.get("skills")):
                    result["sections"].append({"tier": heading_tier(section.get("heading")), "skills": _clean(section.get("skills"))})
        elif _clean(data.get("skills")):
            result["sections"].append({"tier": "", "skills": _clean(data.get("skills"))})
    elif isinstance(data, list):
        result["sections"].append({"tier": "", "skills": _clean(data)})
    else:   # JSONでない返答は、行ごとにスキル名として読む
        lines = [re.sub(r"^[\s\-・*\d.)]+", "", line).strip().strip('",') for line in text.splitlines()]
        names = _clean([line for line in lines if line and line not in "[]{}"])
        if names:
            result["sections"].append({"tier": "", "skills": names})
    if not result["sections"] and not isinstance(data, (dict, list)):
        raise ExtractError("返答からスキル名を読み取れませんでした")
    return result


def as_reading(value: dict) -> dict:
    """保存した読み取り結果を今の形にそろえる(単純な {区分: [名前]} の形も受け付ける)。"""
    if "sections" in value:
        return value
    return {"course": "", "strategy": "", "sections": [
        {"tier": key if key in TIERS else "", "skills": list(names)} for key, names in value.items() if names]}


def call_reader(reader: Reader, image: Path, opener=urllib.request.urlopen) -> dict:
    """1枚の画像を1つのモデルに読ませる。"""
    mime = mimetypes.guess_type(image.name)[0] or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode('ascii')}"
    body = json.dumps({
        "model": reader.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }).encode("utf-8")
    request = urllib.request.Request(
        reader.base_url.rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={**reader.auth_headers(), "Content-Type": "application/json", "User-Agent": "guide-app-extract"})
    last_error = "不明なエラー"
    for attempt in range(3):
        try:
            with opener(request, timeout=reader.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, list):  # 一部の実装は本文を部品の配列で返す
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return parse_reply(str(content))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200].replace("\n", " ")
            last_error = f"HTTP {error.code}: {detail}"
            if error.code not in (408, 429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = f"接続できません: {getattr(error, 'reason', error)}"
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            last_error = "返答の形式が想定と違います"
            break
        time.sleep(2 * (attempt + 1))
    raise ExtractError(f"{reader.name}: {last_error}")


# ---------- 多数決 ----------
def tally(readings: dict[str, list[str]], master: SkillMaster | None) -> list[dict]:
    """モデルごとの読み取り結果を突き合わせる。

    readings: {モデル名: [スキル名, ...]}(読み取りに成功したモデルだけ)
    戻り値: [{"skill", "votes", "read_by"}]。最初に読まれた順。
    """
    groups: dict[str, dict] = {}
    for reader_name, names in readings.items():
        for position, raw in enumerate(names):
            canonical = master.canonical(raw) if master else None
            key = normalize(canonical or raw)
            group = groups.setdefault(key, {"spellings": Counter(), "canonical": canonical, "read_by": [], "position": position})
            group["spellings"][raw] += 1
            group["position"] = min(group["position"], position)
            if reader_name not in group["read_by"]:
                group["read_by"].append(reader_name)
    # マスタにない読み(誤読の疑い)は、同じ画像で他のモデルが読んだ、よく似たマスタ上のスキルへの1票として数える
    known = {key: g for key, g in groups.items() if g["canonical"]}
    for key in [k for k, g in groups.items() if not g["canonical"]]:
        close = difflib.get_close_matches(key, list(known), n=1, cutoff=0.75)
        if close and not set(groups[key]["read_by"]) & set(known[close[0]]["read_by"]):
            known[close[0]]["read_by"].extend(groups.pop(key)["read_by"])
    rows = []
    for group in sorted(groups.values(), key=lambda g: g["position"]):
        skill = group["canonical"] or group["spellings"].most_common(1)[0][0]
        rows.append({"skill": skill, "votes": len(group["read_by"]), "read_by": group["read_by"]})
    return rows


def save_reading(conn: sqlite3.Connection, event: str, file: str, reader: Reader, names: dict | None, error: str) -> None:
    with conn:
        conn.execute(
            """INSERT INTO readings (event, source_file, reader, model, names, error) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (event, source_file, reader) DO UPDATE SET model = excluded.model, names = excluded.names,
                   error = excluded.error, created_at = datetime('now', 'localtime')""",
            (event, file, reader.name, reader.model, json.dumps(names or {}, ensure_ascii=False), error),
        )


def majority(values: list[str]) -> str:
    """空でない値のうち、過半数を取ったもの。なければ空文字。"""
    values = [v for v in values if v]
    if not values:
        return ""
    value, count = Counter(values).most_common(1)[0]
    return value if count * 2 > len(values) else ""


def detect_race(conn: sqlite3.Connection, event: str) -> str:
    """そのイベントの読み取り結果から、いちばん多く読まれたコース。"""
    courses = [as_reading(json.loads(r["names"])).get("course", "") for r in conn.execute(
        "SELECT names FROM readings WHERE event = ? AND error = ''", (event,))]
    courses = [c for c in courses if c]
    return Counter(courses).most_common(1)[0][0] if courses else ""


def image_warnings(shot: Shot, race: str, readings: list[dict]) -> list[str]:
    """フォルダ(撮影時のホットキー設定)と画像の中身の食い違い。"""
    warnings = []
    strategy = majority([r.get("strategy", "") for r in readings])
    if strategy and strategy != shot.strategy:
        warnings.append(f"フォルダは「{shot.strategy}」ですが、画像の脚質タブは「{strategy}」です")
    course = majority([r.get("course", "") for r in readings])
    if course and course != race:
        warnings.append(f"画像のコースは「{course}」です(このイベントは {race})")
    if shot.tier:
        # 各モデルが見た見出し。フォルダの区分の見出しが写っておらず、反対の区分だけが写っていれば切り替え忘れ
        seen = [{s["tier"] for s in r["sections"] if s["tier"]} for r in readings]
        other = next(t for t in TIERS if t != shot.tier)
        only_other = [s for s in seen if s == {other}]
        if only_other and len(only_other) * 2 > len(readings):
            warnings.append(f"フォルダは「{TIER_LABELS[shot.tier]}」ですが、画像の見出しは「{TIER_LABELS[other]}スキル」です")
    return warnings


def apply_votes(conn: sqlite3.Connection, master: SkillMaster | None, event: str, race: str, shot: Shot,
                reader_count: int, auto_confirm: bool = False) -> dict:
    """その画像の読み取り結果を突き合わせ、確認用の行を作る(作成済みの行は票数だけ更新)。"""
    stored = [(row["reader"], as_reading(json.loads(row["names"]))) for row in conn.execute(
        "SELECT reader, names FROM readings WHERE event = ? AND source_file = ? AND error = ''", (event, shot.file))]
    result = {"rows": 0, "auto_ok": 0, "auto_rejected": 0, "warnings": 0}
    if not stored:
        return result
    by_tier: dict[str, dict[str, list[str]]] = {}
    for reader_name, reading in stored:
        for section in reading["sections"]:
            # 区分はフォルダを優先。フォルダで決まらず見出しも分からないスキルは、超おすすめ側に出して人が決める
            tier = shot.tier or section["tier"] or "super_recommended"
            by_tier.setdefault(tier, {}).setdefault(reader_name, []).extend(section["skills"])
    warnings = image_warnings(shot, race, [reading for _, reading in stored])
    result["warnings"] = len(warnings)
    with conn:
        conn.execute(
            """INSERT INTO images (event, source_file, warning) VALUES (?, ?, ?)
               ON CONFLICT (event, source_file) DO UPDATE SET warning = excluded.warning""",
            (event, shot.file, " / ".join(warnings)))
        for tier, readings in by_tier.items():
            for item in tally(readings, master):
                cursor = conn.execute(
                    """INSERT INTO skills (event, race, strategy, tier, extracted_skill, skill, source_file, source_csv,
                                           votes, readers, read_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'guide_app', ?, ?, ?)
                       ON CONFLICT (event, race, strategy, tier, extracted_skill) DO UPDATE SET
                           votes = excluded.votes, readers = excluded.readers, read_by = excluded.read_by
                       WHERE skills.source_file = excluded.source_file OR excluded.votes > COALESCE(skills.votes, 0)""",
                    (event, race, shot.strategy, tier, item["skill"], item["skill"], shot.file,
                     item["votes"], reader_count, ",".join(item["read_by"])),
                )
                result["rows"] += cursor.rowcount
        if auto_confirm and not warnings and reader_count >= 2:
            ok, rejected = auto_decide(conn, master, event, shot)
            result["auto_ok"], result["auto_rejected"] = ok, rejected
    return result


def auto_decide(conn: sqlite3.Connection, master: SkillMaster | None, event: str, shot: Shot) -> tuple[int, int]:
    """多数決の結果をそのまま採用する。人が触った行(未確認でない行)には手を付けない。

    - 過半数のモデルが読み、マスタにあるスキル → OK
    - 1モデルだけが読み、マスタにないスキル → 却下(誤読とみなす)
    - それ以外(1モデルだけが読んだ実在のスキルなど) → 未確認のまま残して人が見る
    """
    ok = rejected = 0
    rows = conn.execute(
        """SELECT id, skill, votes, readers FROM skills
           WHERE event = ? AND source_file = ? AND source_csv = 'guide_app' AND status = 'draft'""",
        (event, shot.file)).fetchall()
    for row in rows:
        known = master.canonical(row["skill"]) is not None if master else False
        votes, readers = row["votes"] or 0, row["readers"] or 0
        if known and votes * 2 > readers:
            conn.execute("UPDATE skills SET status = 'ready', memo = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                         (f"自動OK({votes}/{readers})", row["id"]))
            ok += 1
        elif not known and votes == 1:
            conn.execute("UPDATE skills SET status = 'rejected', memo = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                         (f"自動却下(1/{readers}・マスタになし)", row["id"]))
            rejected += 1
    left = conn.execute("SELECT COUNT(*) FROM skills WHERE event = ? AND source_file = ? AND status = 'draft'",
                        (event, shot.file)).fetchone()[0]
    if not left:   # 見るものが残っていない画像は確認済みにする
        conn.execute("UPDATE images SET reviewed_at = datetime('now', 'localtime') WHERE event = ? AND source_file = ? AND reviewed_at IS NULL",
                     (event, shot.file))
    return ok, rejected


def reader_stats(conn: sqlite3.Connection, reader_names: list[str]) -> list[dict]:
    """モデルごとの成績。どのモデルが弱いかを見るための集計。"""
    stats = {name: {"name": name, "calls": 0, "errors": 0, "solo": 0, "solo_rejected": 0, "missed": 0} for name in reader_names}
    for r in conn.execute("SELECT reader, COUNT(*) AS calls, SUM(error != '') AS errors FROM readings GROUP BY reader"):
        if r["reader"] in stats:
            stats[r["reader"]].update(calls=r["calls"], errors=r["errors"])
    for r in conn.execute("SELECT status, votes, readers, read_by FROM skills WHERE source_csv = 'guide_app' AND readers >= 2"):
        read_by = [n for n in r["read_by"].split(",") if n]
        if r["votes"] == 1 and read_by and read_by[0] in stats:   # そのモデルだけが読んだ
            stats[read_by[0]]["solo"] += 1
            stats[read_by[0]]["solo_rejected"] += r["status"] == "rejected"
        if r["status"] == "ready":                                 # 採用されたスキルを読めていなかった
            for name in stats:
                if name not in read_by:
                    stats[name]["missed"] += 1
    return list(stats.values())


# ---------- ジョブ ----------
@dataclass
class Job:
    event: str
    race: str
    total: int = 0            # 画像の枚数
    done: int = 0
    requests: int = 0         # モデルを呼んだ回数
    rows: int = 0
    auto_ok: int = 0
    auto_rejected: int = 0
    warnings: int = 0         # フォルダと中身が食い違う画像の数
    errors: list[str] = field(default_factory=list)
    state: str = "running"    # running / finished / cancelled / failed
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    finished_at: str = ""
    current: str = ""

    def to_dict(self) -> dict:
        keys = ("event", "race", "total", "done", "requests", "rows", "auto_ok", "auto_rejected", "warnings",
                "state", "started_at", "finished_at", "current")
        return {k: getattr(self, k) for k in keys} | {"errors": self.errors[-20:]}


def plan(conn: sqlite3.Connection, inbox: Path, event: str, readers: list[Reader], force: bool = False) -> list[tuple[Shot, list[Reader]]]:
    """読み取りが必要な (画像, 呼ぶモデル) の一覧。読み取り済みの組み合わせは省く。"""
    done = {(r["source_file"], r["reader"]) for r in conn.execute(
        "SELECT source_file, reader FROM readings WHERE event = ? AND error = ''", (event,))}
    imported = {r["source_file"] for r in conn.execute(
        "SELECT DISTINCT source_file FROM skills WHERE event = ? AND source_csv != 'guide_app'", (event,))}
    work = []
    for shot in list_shots(inbox, event):
        if shot.file in imported and not force:   # 以前のCSV取り込みで行がある画像は触らない
            continue
        todo = [r for r in readers if force or (shot.file, r.name) not in done]
        if todo:
            work.append((shot, todo))
    return work


def validate_race(race: str) -> str:
    match = RACE_RE.fullmatch(race.strip())
    if not match or not 1000 <= int(match[3]) <= 4000 or int(match[3]) % 100:
        raise ExtractError("レースは「京都 芝 3000m」の形で指定してください")
    return race.strip()


class Extractor:
    """抽出ジョブを1つずつ裏で動かす。"""

    def __init__(self, connect, inbox: Path, readers: list[Reader], master: SkillMaster | None,
                 call=call_reader, auto_confirm: bool = False):
        self.connect, self.inbox, self.readers, self.master, self.call = connect, Path(inbox), list(readers), master, call
        self.auto_confirm = auto_confirm
        self.job: Job | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._last_call: dict[str, float] = {}
        self._thread: threading.Thread | None = None

    def estimate(self, event: str, force: bool = False) -> dict:
        with self.connect() as conn:
            work = plan(conn, self.inbox, event, self.readers, force)
        return {"event": event, "images": len(work), "requests": sum(len(todo) for _, todo in work),
                "readers": [{"name": r.name, "model": r.model} for r in self.readers], "auto_confirm": self.auto_confirm}

    def start(self, event: str, race: str = "", force: bool = False, wait: bool = False) -> Job:
        """race を空にすると、画像から読み取ったコースを使う。"""
        if not self.readers:
            raise ExtractError("読み取りに使うモデルが設定されていません(config.toml の [[readers]])")
        if not EVENT_RE.fullmatch(event):
            raise ExtractError("イベント名が不正です")
        race = validate_race(race) if race.strip() else ""
        for reader in self.readers:
            reader.key()   # キーがなければ始める前に知らせる
        with self._lock:
            if self.job and self.job.state == "running":
                raise ExtractError(f"{self.job.event} の抽出が進行中です")
            with self.connect() as conn:
                work = plan(conn, self.inbox, event, self.readers, force)
            if not list_shots(self.inbox, event):
                raise ExtractError("このイベントの撮影画像がありません")
            self.job = Job(event=event, race=race, total=len(work))
            self._cancel.clear()
            job = self.job
        self._thread = threading.Thread(target=self._run, args=(job, work), name="extract", daemon=True)
        self._thread.start()
        if wait:
            self._thread.join()
        return job

    def cancel(self) -> None:
        self._cancel.set()

    def status(self) -> dict | None:
        return self.job.to_dict() if self.job else None

    def _read(self, reader: Reader, shot: Shot) -> tuple[Reader, dict | None, str]:
        wait = reader.min_interval - (time.monotonic() - self._last_call.get(reader.name, 0.0))
        if wait > 0:
            self._cancel.wait(wait)
        self._last_call[reader.name] = time.monotonic()
        try:
            return reader, as_reading(self.call(reader, shot.path)), ""
        except ExtractError as error:
            return reader, None, str(error)
        except Exception as error:  # noqa: BLE001 - 1モデルの失敗でジョブ全体は止めない
            return reader, None, f"{reader.name}: {error}"

    def _run(self, job: Job, work: list[tuple[Shot, list[Reader]]]) -> None:
        try:
            with self.connect() as conn:
                with ThreadPoolExecutor(max_workers=max(1, len(self.readers))) as pool:
                    for shot, todo in work:
                        if self._cancel.is_set():
                            job.state = "cancelled"
                            break
                        job.current = f"{shot.strategy} {shot.file}"
                        for reader, names, error in pool.map(lambda r: self._read(r, shot), todo):
                            job.requests += 1
                            save_reading(conn, job.event, shot.file, reader, names, error)
                            if error:
                                job.errors.append(f"{shot.file}: {error}")
                        job.done += 1
                # 読み取りが終わってから行を作る(コースをイベント全体の多数決で決めるため)。読み取り済みの分だけなら呼び出しなしで済む
                job.current = "結果を突き合わせています"
                job.race = job.race or detect_race(conn, job.event)
                if not job.race:
                    raise ExtractError("画像からコースを読み取れませんでした。レースを選んで、もう一度「読み取りを開始」を押してください(読み取り済みの画像は呼び直しません)")
                with conn:
                    conn.execute(
                        "INSERT INTO events (event, race) VALUES (?, ?) ON CONFLICT (event) DO UPDATE SET race = excluded.race",
                        (job.event, job.race))
                for shot in list_shots(self.inbox, job.event):
                    result = apply_votes(conn, self.master, job.event, job.race, shot, len(self.readers), self.auto_confirm)
                    job.rows += result["rows"]
                    job.auto_ok += result["auto_ok"]
                    job.auto_rejected += result["auto_rejected"]
                    job.warnings += bool(result["warnings"])
            if job.state == "running":
                job.state = "finished"
        except ExtractError as error:
            job.state = "failed"
            job.errors.append(str(error))
        except Exception as error:  # noqa: BLE001
            job.state = "failed"
            job.errors.append(f"抽出が止まりました: {error}")
        finally:
            job.current = ""
            job.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
