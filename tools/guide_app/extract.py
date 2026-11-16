"""スクショからスキル名を読み取る(複数モデルの多数決)。

- 撮影フォルダ inbox/<イベント>/<脚質>/<区分>/ の画像を、設定した各モデルに読ませる
- 全モデルが一致して読んだスキルは「一致」、一部のモデルだけが読んだスキルは「要注意」として確認画面に出す
- モデルはOpenAI互換のAPI(chat/completions)で呼ぶ。GeminiもOpenAI互換の入口を持つので同じ仕組みで扱える
- 読み取り結果はモデルごとにDBへ残す。やり直しても、読み取り済みの画像・モデルは呼び直さない
"""
from __future__ import annotations

import base64
import hashlib
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    primary: bool = False       # 2段階の読み取りで、最初に全画像を読むモデル
    timeout: int = 120

    def key(self) -> str:
        if self.key_env and os.environ.get(self.key_env):
            return self._checked(os.environ[self.key_env].strip())
        if self.key_file:
            try:
                value = self.key_file.expanduser().read_text(encoding="utf-8").strip()
            except OSError as error:
                raise ExtractError(f"{self.name}: APIキーのファイルを読めません({self.key_file})") from error
            if value:
                return self._checked(value)
        raise ExtractError(f"{self.name}: APIキーが設定されていません")

    def _checked(self, value: str) -> str:
        # 改行や空白が混ざったキーをそのまま送ると、通信ライブラリのエラー文にキーが丸ごと出てしまう
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ExtractError(f"{self.name}: APIキーに改行や空白が混ざっています(キー1行だけにしてください)")
        return value

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


def primary_name(readers) -> str:
    """2段階の読み取りで最初に読むモデルの名前。2段階でなければ空文字。"""
    names = [r.name for r in readers if r.primary]
    return names[0] if names and len(readers) >= 2 else ""


def required_readers(file: str, names: list[str], primary: str, ok: set, council: dict) -> list[str]:
    """その画像を読むべきモデル。2段階のときは、まず1次のモデルだけ。会議に回すと決まった画像は全モデル。"""
    if not primary:
        return list(names)
    if (file, primary) not in ok or council.get(file) != 1:
        return [primary]
    return list(names)


def read_state(conn: sqlite3.Connection, event: str) -> tuple[set, dict]:
    ok = {(r["source_file"], r["reader"]) for r in conn.execute(
        "SELECT source_file, reader FROM readings WHERE event = ? AND error = ''", (event,))}
    council = {r["source_file"]: r["council"] for r in conn.execute(
        "SELECT source_file, council FROM images WHERE event = ?", (event,))}
    return ok, council


def captures(conn: sqlite3.Connection, inbox: Path, reader_names: list[str], primary: str = "") -> list[dict]:
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
        ok, council = read_state(conn, event)
        cells: dict[tuple[str, str], dict] = {}
        pending = 0
        for s in shots:
            done = s.file in have_rows or (reader_names and all(
                (s.file, name) in ok for name in required_readers(s.file, reader_names, primary, ok, council)))
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
            # 認証エラーの返答には、送ったキーの一部が含まれることがあるので本文は残さない
            detail = "" if error.code in (401, 403) else ": " + error.read().decode("utf-8", "replace")[:200].replace("\n", " ")
            last_error = f"HTTP {error.code}{detail}"
            if error.code not in (408, 429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = f"接続できません: {getattr(error, 'reason', error)}"
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            last_error = "返答の形式が想定と違います"
            break
        except ValueError:   # ヘッダーに使えない文字など。例外の文にはキーが混ざりうるので出さない
            last_error = "送信内容を組み立てられませんでした(APIキーの形式を確認してください)"
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
    seen = [{s["tier"] for s in r["sections"] if s["tier"]} for r in readings]
    if shot.tier:
        # フォルダと反対の区分の見出しが写っている画像は、フォルダの区分にまとめてよいか機械では決められない
        other = next(t for t in TIERS if t != shot.tier)
        with_other = [s for s in seen if other in s]
        if len(with_other) * 2 > len(readings):
            both = any(shot.tier in s for s in with_other)
            warnings.append(
                f"フォルダは「{TIER_LABELS[shot.tier]}」ですが、画像に「{TIER_LABELS[other]}スキル」の見出しが写っています"
                + ("(両方の区分が1枚に写っています)" if both else ""))
    elif any(not s["tier"] for r in readings for s in r["sections"]):
        warnings.append("区分のフォルダがなく、見出しも写っていないスキルがあります(超おすすめ側に仮置きしています)")
    return warnings


def apply_votes(conn: sqlite3.Connection, master: SkillMaster | None, event: str, race: str, shot: Shot,
                reader_names: list[str]) -> dict:
    """その画像の読み取り結果を突き合わせ、確認用の行を作る(作成済みの行は票数だけ更新)。"""
    # 今の設定にあるモデルの読み取りだけを数える(名前を変える前の読み取りが二重に票を入れないように)
    stored = [(row["reader"], as_reading(json.loads(row["names"]))) for row in conn.execute(
        "SELECT reader, names FROM readings WHERE event = ? AND source_file = ? AND error = ''", (event, shot.file))
        if row["reader"] in reader_names]
    reader_count = len(reader_names)
    result = {"rows": 0, "warnings": 0}
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
                # 人が区分を変えた行が別の区分にあるときは、元の区分に行を作り直さず、その行の票数だけ更新する
                moved = conn.execute(
                    """SELECT id FROM skills WHERE event = ? AND race = ? AND strategy = ? AND extracted_skill = ?
                       AND tier != ? AND source_file = ? AND touched = 1""",
                    (event, race, shot.strategy, item["skill"], tier, shot.file)).fetchone()
                if moved:
                    conn.execute("UPDATE skills SET votes = ?, readers = ?, read_by = ? WHERE id = ?",
                                 (item["votes"], reader_count, ",".join(item["read_by"]), moved["id"]))
                    continue
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
    return result


def auto_decide(conn: sqlite3.Connection, master: SkillMaster | None, event: str, published=None) -> tuple[int, int]:
    """多数決の結果をそのまま採用する。イベントの全画像を突き合わせたあとに1回呼ぶ。

    - 過半数のモデルが読み、マスタにあり、ほかに気になる点がないスキル → OK
    - 1モデルだけが読み、マスタにないスキル → 却下(誤読とみなす)
    - それ以外 → 未確認のまま残して人が見る
      (1モデルだけが読んだ実在のスキル、サイトと区分が違う、両方の区分にある、設定と食い違う画像の行)
    人が触った行(touched)と、未確認でない行には手を付けない。
    """
    from . import review   # reviewはこのモジュールを使わないので、循環しない

    ok = rejected = 0
    warned = {r["source_file"] for r in conn.execute("SELECT source_file FROM images WHERE event = ? AND warning != ''", (event,))}
    passed = {r["source_file"] for r in conn.execute("SELECT source_file FROM images WHERE event = ? AND council = 0", (event,))}
    groups = conn.execute("SELECT DISTINCT race, strategy FROM skills WHERE event = ? AND source_csv = 'guide_app'", (event,)).fetchall()
    for g in groups:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM skills WHERE event = ? AND race = ? AND strategy = ?", (event, g["race"], g["strategy"]))]
        reasons = review.attention_reasons(rows, master, published) if master else {}
        for row in rows:
            if row["status"] != "draft" or row["touched"] or row["source_csv"] != "guide_app" or row["source_file"] in warned:
                continue
            known = master.canonical(row["skill"]) is not None if master else False
            votes, readers = row["votes"] or 0, row["readers"] or 0
            concerns = [r for r in reasons.get(row["id"], []) if "モデルだけが読んだ" not in r]
            if readers < 2:
                # 2段階の読み取りで、1次のモデルだけで通した画像の行。会議に回す条件(マスタにない名前・食い違い)に
                # 当たらなかった画像なので、マスタにあればOKにする。○と◎の読み分けは1モデルでは確かめられないが、
                # 因子周回では◎を○として扱うので影響は小さい(抜き取り検査で食い違いの量は測る)
                concerns = [r for r in concerns if "◎" not in r]
                if row["source_file"] in passed and known and not concerns:
                    conn.execute("UPDATE skills SET status = 'ready', memo = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                                 ("自動OK(1次の読み取りのみ)", row["id"]))
                    ok += 1
                continue
            if known and votes * 2 > readers and not concerns:
                conn.execute("UPDATE skills SET status = 'ready', memo = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                             (f"自動OK({votes}/{readers})", row["id"]))
                ok += 1
            elif not known and votes == 1:
                conn.execute("UPDATE skills SET status = 'rejected', memo = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                             (f"自動却下(1/{readers}・マスタになし)", row["id"]))
                rejected += 1
    # 見るものが残っていない画像は確認済みにする
    conn.execute(
        """UPDATE images SET reviewed_at = datetime('now', 'localtime')
           WHERE event = ? AND reviewed_at IS NULL AND warning = ''
             AND EXISTS (SELECT 1 FROM skills s WHERE s.event = images.event AND s.source_file = images.source_file)
             AND NOT EXISTS (SELECT 1 FROM skills s WHERE s.event = images.event AND s.source_file = images.source_file AND s.status = 'draft')""",
        (event,))
    conn.commit()
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
    council: int = 0          # 2段階の読み取りで、会議(全モデル)に回した画像の数
    stage: str = ""           # いまの段階(画面に出す)
    errors: list[str] = field(default_factory=list)
    state: str = "running"    # running / finished / cancelled / failed
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    finished_at: str = ""
    current: str = ""

    def to_dict(self) -> dict:
        keys = ("event", "race", "total", "done", "requests", "rows", "auto_ok", "auto_rejected", "warnings", "council", "stage",
                "state", "started_at", "finished_at", "current")
        return {k: getattr(self, k) for k in keys} | {"errors": self.errors[-20:]}


def plan(conn: sqlite3.Connection, inbox: Path, event: str, readers: list[Reader], force: bool = False) -> list[tuple[Shot, list[Reader]]]:
    """読み取りが必要な (画像, 呼ぶモデル) の一覧。読み取り済みの組み合わせは省く。

    2段階のときは、1次のモデルの分と、すでに会議に回すと決まっている画像の残りだけが入る。
    """
    ok, council = read_state(conn, event)
    primary = primary_name(readers)
    names = [r.name for r in readers]
    by_name = {r.name: r for r in readers}
    imported = {r["source_file"] for r in conn.execute(
        "SELECT DISTINCT source_file FROM skills WHERE event = ? AND source_csv != 'guide_app'", (event,))}
    work = []
    for shot in list_shots(inbox, event):
        if shot.file in imported and not force:   # 以前のCSV取り込みで行がある画像は触らない
            continue
        if force:
            wanted = [primary] if primary else names
        else:
            wanted = [n for n in required_readers(shot.file, names, primary, ok, council) if (shot.file, n) not in ok]
        if wanted:
            work.append((shot, [by_name[n] for n in wanted]))
    return work


def spot_checked(file: str, every: int) -> bool:
    """抜き取り検査の対象か。ファイル名で決めるので、やり直しても同じ画像が選ばれる。"""
    return every > 0 and int(hashlib.sha1(file.encode("utf-8")).hexdigest(), 16) % every == 0


def council_reason(shot: Shot, race: str, reading: dict | None, master: SkillMaster | None, spot_check: int) -> str:
    """1次の読み取りだけで通さず、会議(全モデル)に回す理由。空文字なら1次だけで通す。"""
    if reading is None:
        return "1次のモデルが読めなかった"
    names = [n for s in reading["sections"] for n in s["skills"]]
    if not names:
        return "スキルが1つも読めていない"
    if master and any(master.canonical(n) is None for n in names):
        return "マスタにない名前がある"
    if image_warnings(shot, race, [reading]):
        return "撮影時の設定と食い違う"
    if spot_checked(shot.file, spot_check):
        return "抜き取り検査"
    return ""


def validate_race(race: str) -> str:
    match = RACE_RE.fullmatch(race.strip())
    if not match or not 1000 <= int(match[3]) <= 4000 or int(match[3]) % 100:
        raise ExtractError("レースは「京都 芝 3000m」の形で指定してください")
    return race.strip()


class Extractor:
    """抽出ジョブを1つずつ裏で動かす。"""

    def __init__(self, connect, inbox: Path, readers: list[Reader], master: SkillMaster | None,
                 call=call_reader, auto_confirm: bool = False, get_published=None,
                 parallel_images: int = 3, spot_check: int = 5):
        self.connect, self.inbox, self.readers, self.master, self.call = connect, Path(inbox), list(readers), master, call
        self.auto_confirm = auto_confirm
        self.get_published = get_published or (lambda: None)
        self.parallel_images = max(1, parallel_images)
        self.spot_check = max(0, spot_check)
        self.primary = primary_name(self.readers)
        self._reader_locks = {r.name: threading.Lock() for r in self.readers}
        self.job: Job | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._last_call: dict[str, float] = {}
        self._thread: threading.Thread | None = None

    def estimate(self, event: str, force: bool = False) -> dict:
        with self.connect() as conn:
            work = plan(conn, self.inbox, event, self.readers, force)
        return {"event": event, "images": len(work), "requests": sum(len(todo) for _, todo in work),
                "readers": [{"name": r.name, "model": r.model} for r in self.readers], "auto_confirm": self.auto_confirm,
                "primary": self.primary, "spot_check": self.spot_check}

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

    def _read(self, reader: Reader, shot: Shot) -> tuple[Shot, Reader, dict | None, str]:
        if self._cancel.is_set():
            return shot, reader, None, "中止しました"
        with self._reader_locks[reader.name]:   # 同じモデルへの呼び出しは、決めた間隔を空けて順に始める
            wait = reader.min_interval - (time.monotonic() - self._last_call.get(reader.name, 0.0))
            if wait > 0:
                self._cancel.wait(wait)
            self._last_call[reader.name] = time.monotonic()
        try:
            return shot, reader, as_reading(self.call(reader, shot.path)), ""
        except ExtractError as error:
            return shot, reader, None, str(error)
        except Exception as error:  # noqa: BLE001 - 1モデルの失敗でジョブ全体は止めない
            return shot, reader, None, f"{reader.name}: 想定外のエラー({type(error).__name__})"

    def _read_all(self, conn, job: Job, work: list[tuple[Shot, list[Reader]]]) -> None:
        """(画像, モデル) の組を並行で読む。DBへの書き込みは、このスレッドだけで行う。"""
        left = {shot.file: len(todo) for shot, todo in work}
        pairs = [(shot, reader) for shot, todo in work for reader in todo]
        if not pairs:
            return
        workers = self.parallel_images * max(1, max(len(todo) for _, todo in work))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._read, reader, shot) for shot, reader in pairs]
            for future in as_completed(futures):
                shot, reader, names, error = future.result()
                if error == "中止しました":
                    continue
                job.requests += 1
                save_reading(conn, job.event, shot.file, reader, names, error)
                if error:
                    job.errors.append(f"{shot.file}: {error}")
                left[shot.file] -= 1
                if not left[shot.file]:
                    job.done += 1
                job.current = f"{shot.strategy} {shot.file}"
        if self._cancel.is_set():
            job.state = "cancelled"

    def _race(self, conn, job: Job) -> str:
        # 一度決めたコースは変えない(あとから読んだ画像でコースが入れ替わり、同じスキルが二重に登録されるのを防ぐ)
        saved = conn.execute("SELECT race FROM events WHERE event = ?", (job.event,)).fetchone()
        return job.race or (saved["race"] if saved and saved["race"] else "") or detect_race(conn, job.event)

    def _decide_council(self, conn, job: Job) -> list[tuple[Shot, list[Reader]]]:
        """1次の読み取りを見て、会議に回す画像を決める。決めた内容はDBに残す(やり直しても変わらない)。"""
        ok, council = read_state(conn, job.event)
        others = [r for r in self.readers if r.name != self.primary]
        imported = {r["source_file"] for r in conn.execute(
            "SELECT DISTINCT source_file FROM skills WHERE event = ? AND source_csv != 'guide_app'", (job.event,))}
        attempted = {r["source_file"]: r for r in conn.execute(
            "SELECT source_file, names, error FROM readings WHERE event = ? AND reader = ?", (job.event, self.primary))}
        work = []
        for shot in list_shots(self.inbox, job.event):
            row = attempted.get(shot.file)
            if shot.file in imported or row is None:
                continue
            if council.get(shot.file) is None:
                reading = as_reading(json.loads(row["names"])) if not row["error"] else None
                reason = council_reason(shot, job.race, reading, self.master, self.spot_check)
                council[shot.file] = int(bool(reason))
                with conn:
                    conn.execute(
                        """INSERT INTO images (event, source_file, council, council_reason) VALUES (?, ?, ?, ?)
                           ON CONFLICT (event, source_file) DO UPDATE SET council = excluded.council, council_reason = excluded.council_reason""",
                        (job.event, shot.file, council[shot.file], reason))
            if council[shot.file] == 1:
                job.council += 1
                todo = [r for r in others if (shot.file, r.name) not in ok]
                if todo:
                    work.append((shot, todo))
        return work

    def _run(self, job: Job, work: list[tuple[Shot, list[Reader]]]) -> None:
        try:
            with self.connect() as conn:
                job.stage = "1次の読み取り" if self.primary else "読み取り"
                self._read_all(conn, job, work)
                if self.primary and job.state == "running":
                    job.race = self._race(conn, job)   # 食い違いの判定にコースを使う。読めていなければ後段で止まる
                    more = self._decide_council(conn, job)
                    job.stage = f"会議(全モデル)で読み取り: {len(more)}枚"
                    job.total += len(more)
                    self._read_all(conn, job, more)
                # 読み取りが終わってから行を作る(コースをイベント全体の多数決で決めるため)。読み取り済みの分だけなら呼び出しなしで済む
                job.current, job.stage = "", "結果の突き合わせ"
                job.race = self._race(conn, job)
                if not job.race:
                    raise ExtractError("画像からコースを読み取れませんでした。レースを選んで、もう一度「読み取りを開始」を押してください(読み取り済みの画像は呼び直しません)")
                with conn:
                    conn.execute(
                        "INSERT INTO events (event, race) VALUES (?, ?) ON CONFLICT (event) DO UPDATE SET race = excluded.race",
                        (job.event, job.race))
                names = [r.name for r in self.readers]
                ok, council = read_state(conn, job.event)
                for shot in list_shots(self.inbox, job.event):
                    # 1次だけで通した画像は、1次のモデルの読み取りだけで行を作る
                    voters = names if not self.primary or council.get(shot.file) == 1 else [self.primary]
                    result = apply_votes(conn, self.master, job.event, job.race, shot, voters)
                    job.rows += result["rows"]
                    job.warnings += bool(result["warnings"])
                if self.auto_confirm and len(self.readers) >= 2 and job.state == "running":
                    job.auto_ok, job.auto_rejected = auto_decide(conn, self.master, job.event, self.get_published())
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
