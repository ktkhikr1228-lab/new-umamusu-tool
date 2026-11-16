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

PROMPT_LIST = (
    "これはゲーム「ウマ娘」のトレーナーガイド画面です。画像に写っているスキル名を、上から順にすべて書き出してください。\n"
    "- 画面の表記どおりに書く。○と◎は区別する\n"
    "- スキル名以外(見出し、レース名、ボタン、説明文)は含めない\n"
    "- 文字が途中で切れて読めないスキルは含めない\n"
    '出力はJSONの配列だけにしてください。例: ["スキルA", "スキルB"]'
)
PROMPT_TIERED = (
    "これはゲーム「ウマ娘」のトレーナーガイド画面です。画像に写っているスキル名を、見出しの区分ごとにすべて書き出してください。\n"
    "- 「超おすすめスキル」の見出しの下にあるものは super_recommended、「おすすめスキル」の下にあるものは recommended\n"
    "- 見出しが写っていないスキルは unknown\n"
    "- 画面の表記どおりに書く。○と◎は区別する。スキル名以外は含めない\n"
    '出力はJSONオブジェクトだけにしてください。例: {"super_recommended": ["スキルA"], "recommended": ["スキルB"], "unknown": []}'
)


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
def parse_names(text: str, tiered: bool) -> dict[str, list[str]]:
    """モデルの返答からスキル名を取り出す。区分なしの場合は {"": [...]}。"""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    def clean(items) -> list[str]:
        seen, out = set(), []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str) and item.strip() and item.strip() not in seen:
                seen.add(item.strip())
                out.append(item.strip())
        return out

    opener, closer = ("{", "}") if tiered else ("[", "]")
    start, end = text.find(opener), text.rfind(closer)
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            data = None
        if tiered and isinstance(data, dict):
            return {tier: clean(data.get(tier)) for tier in (*TIERS, "unknown")}
        if not tiered and isinstance(data, list):
            return {"": clean(data)}
    if tiered:
        raise ExtractError("返答を区分ごとのJSONとして読めませんでした")
    lines = [re.sub(r"^[\s\-・*\d.)]+", "", line).strip().strip('",') for line in text.splitlines()]
    names = clean([line for line in lines if line and line not in "[]"])
    if not names:
        raise ExtractError("返答からスキル名を読み取れませんでした")
    return {"": names}


def call_reader(reader: Reader, image: Path, tiered: bool, opener=urllib.request.urlopen) -> dict[str, list[str]]:
    """1枚の画像を1つのモデルに読ませる。"""
    mime = mimetypes.guess_type(image.name)[0] or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode('ascii')}"
    body = json.dumps({
        "model": reader.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT_TIERED if tiered else PROMPT_LIST},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }).encode("utf-8")
    request = urllib.request.Request(
        reader.base_url.rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Authorization": "Bearer " + reader.key(), "Content-Type": "application/json",
                 "User-Agent": "guide-app-extract"})
    last_error = "不明なエラー"
    for attempt in range(3):
        try:
            with opener(request, timeout=reader.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, list):  # 一部の実装は本文を部品の配列で返す
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return parse_names(str(content), tiered)
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


def apply_votes(conn: sqlite3.Connection, master: SkillMaster | None, event: str, race: str, shot: Shot,
                reader_count: int) -> int:
    """その画像の読み取り結果を突き合わせ、確認用の行を作る(作成済みの行は票数だけ更新)。"""
    stored = conn.execute(
        "SELECT reader, names FROM readings WHERE event = ? AND source_file = ? AND error = ''", (event, shot.file)).fetchall()
    by_tier: dict[str, dict[str, list[str]]] = {}
    for row in stored:
        for tier_key, names in json.loads(row["names"]).items():
            tier = shot.tier or (tier_key if tier_key in TIERS else None)
            if tier is None:   # 区分の分からないスキルは、人が区分を決められるよう超おすすめ側に要注意で出す
                tier = "super_recommended"
            by_tier.setdefault(tier, {}).setdefault(row["reader"], []).extend(names)
    added = 0
    with conn:
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
                added += cursor.rowcount
    return added


# ---------- ジョブ ----------
@dataclass
class Job:
    event: str
    race: str
    total: int = 0            # 画像の枚数
    done: int = 0
    requests: int = 0         # モデルを呼んだ回数
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    state: str = "running"    # running / finished / cancelled / failed
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    finished_at: str = ""
    current: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("event", "race", "total", "done", "requests", "rows", "state",
                                                "started_at", "finished_at", "current")} | {"errors": self.errors[-20:]}


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

    def __init__(self, connect, inbox: Path, readers: list[Reader], master: SkillMaster | None, call=call_reader):
        self.connect, self.inbox, self.readers, self.master, self.call = connect, Path(inbox), list(readers), master, call
        self.job: Job | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._last_call: dict[str, float] = {}
        self._thread: threading.Thread | None = None

    def estimate(self, event: str, force: bool = False) -> dict:
        with self.connect() as conn:
            work = plan(conn, self.inbox, event, self.readers, force)
        return {"event": event, "images": len(work), "requests": sum(len(todo) for _, todo in work),
                "readers": [{"name": r.name, "model": r.model} for r in self.readers]}

    def start(self, event: str, race: str, force: bool = False, wait: bool = False) -> Job:
        if not self.readers:
            raise ExtractError("読み取りに使うモデルが設定されていません(config.toml の [[readers]])")
        if not EVENT_RE.fullmatch(event):
            raise ExtractError("イベント名が不正です")
        race = validate_race(race)
        for reader in self.readers:
            reader.key()   # キーがなければ始める前に知らせる
        with self._lock:
            if self.job and self.job.state == "running":
                raise ExtractError(f"{self.job.event} の抽出が進行中です")
            with self.connect() as conn:
                work = plan(conn, self.inbox, event, self.readers, force)
                with conn:
                    conn.execute(
                        "INSERT INTO events (event, race) VALUES (?, ?) ON CONFLICT (event) DO UPDATE SET race = excluded.race",
                        (event, race))
            if not work:
                raise ExtractError("読み取る画像がありません(すべて読み取り済みです)")
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
            return reader, self.call(reader, shot.path, shot.tier is None), ""
        except ExtractError as error:
            return reader, None, str(error)
        except Exception as error:  # noqa: BLE001 - 1モデルの失敗でジョブ全体は止めない
            return reader, None, f"{reader.name}: {error}"

    def _run(self, job: Job, work: list[tuple[Shot, list[Reader]]]) -> None:
        try:
            with self.connect() as conn, ThreadPoolExecutor(max_workers=max(1, len(self.readers))) as pool:
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
                    job.rows += apply_votes(conn, self.master, job.event, job.race, shot, len(self.readers))
                    job.done += 1
            if job.state == "running":
                job.state = "finished"
        except Exception as error:  # noqa: BLE001
            job.state = "failed"
            job.errors.append(f"抽出が止まりました: {error}")
        finally:
            job.current = ""
            job.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
