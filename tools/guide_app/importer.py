"""抽出CSVをSQLiteへ取り込む。

- 抽出フォルダを再帰的に探す。サブフォルダ名をイベント名として使う(CSVに event 列があればそちらを優先)
- 前回から変わっていないCSVは読み飛ばす
- 同じ (イベント, コース, 脚質, 区分, 抽出名) の行は追加しない。画面で直した内容を上書きしないため
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .skill_master import SkillMaster

# 列名のゆれ。左が内部名
COLUMN_ALIASES = {
    "event": ("event", "イベント"),
    "race": ("race", "レース", "コース", "レース条件"),
    "strategy": ("strategy", "脚質"),
    "tier": ("tier", "区分"),
    "skill": ("skill", "スキル", "スキル名"),
    "source_file": ("source_file", "source", "image", "file", "画像", "ファイル"),
    "status": ("status", "状態"),
    "memo": ("memo", "備考", "メモ"),
}
REQUIRED = ("race", "strategy", "tier", "skill")

STRATEGIES = {
    "逃げ": "逃げ", "nige": "逃げ",
    "先行": "先行", "senkou": "先行", "senko": "先行",
    "差し": "差し", "sashi": "差し",
    "追込": "追込", "追い込み": "追込", "追込み": "追込", "oikomi": "追込",
}
TIERS = {
    "super_recommended": "super_recommended", "super": "super_recommended",
    "超おすすめ": "super_recommended", "超おすすめスキル": "super_recommended",
    "recommended": "recommended", "normal": "recommended",
    "おすすめ": "recommended", "おすすめスキル": "recommended",
}
READY = {"ready", "approved", "ok", "公開", "確認済み"}
REJECTED = {"rejected", "reject", "ng", "却下", "除外"}

EVENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
UNKNOWN_EVENT = "unknown"


@dataclass
class FileResult:
    path: str
    event: str
    added: int = 0
    skipped: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    files: list[FileResult] = field(default_factory=list)
    unchanged: int = 0

    @property
    def added(self) -> int:
        return sum(f.added for f in self.files)

    @property
    def problems(self) -> list[str]:
        return [f"{f.path}: {p}" for f in self.files for p in f.problems]


def normalize_strategy(value: str) -> str | None:
    value = value.strip()
    # "1_nige" のような撮影フォルダ名にも対応
    return STRATEGIES.get(value) or STRATEGIES.get(value.lower().split("_")[-1])


def normalize_tier(value: str) -> str | None:
    return TIERS.get(value.strip()) or TIERS.get(value.strip().lower())


def normalize_status(value: str) -> str:
    value = value.strip()
    if value.lower() in READY or value in READY:
        return "ready"
    if value.lower() in REJECTED or value in REJECTED:
        return "rejected"
    return "draft"


def event_from_path(relative: Path) -> str:
    """extracted/<イベント>/.../x.csv のイベント部分。直下のCSVは unknown。"""
    if len(relative.parts) >= 2 and EVENT_RE.fullmatch(relative.parts[0]):
        return relative.parts[0]
    return UNKNOWN_EVENT


def _header_map(fieldnames: list[str]) -> dict[str, str]:
    lowered = {name.strip().lstrip("﻿").lower(): name for name in fieldnames}
    mapping = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lowered:
                mapping[key] = lowered[alias.lower()]
                break
    return mapping


def import_file(conn: sqlite3.Connection, csv_path: Path, root: Path, master: SkillMaster | None) -> FileResult:
    relative = csv_path.relative_to(root)
    result = FileResult(path=relative.as_posix(), event=event_from_path(relative))
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = _header_map(reader.fieldnames or [])
        missing = [c for c in REQUIRED if c not in columns]
        if missing:
            result.problems.append(f"必要な列がありません: {', '.join(missing)} (見つかった列: {reader.fieldnames})")
            return result
        unknown_columns = set(reader.fieldnames or []) - set(columns.values())
        if unknown_columns:
            result.problems.append(f"使わない列: {', '.join(sorted(unknown_columns))}")

        for line_no, row in enumerate(reader, start=2):
            def get(key: str) -> str:
                return (row.get(columns[key]) or "").strip() if key in columns else ""

            strategy = normalize_strategy(get("strategy"))
            tier = normalize_tier(get("tier"))
            extracted = get("skill")
            if not (get("race") and strategy and tier and extracted):
                result.problems.append(f"{line_no}行目を読めません: {dict(row)}")
                result.skipped += 1
                continue
            event = get("event") if EVENT_RE.fullmatch(get("event")) else result.event
            skill = (master.canonical(extracted) if master else None) or extracted
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO skills
                    (event, race, strategy, tier, extracted_skill, skill, status, source_file, source_csv, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event, get("race"), strategy, tier, extracted, skill, normalize_status(get("status")),
                 get("source_file"), result.path, get("memo")),
            )
            if cursor.rowcount:
                result.added += 1
            else:
                result.skipped += 1
    return result


def import_all(conn: sqlite3.Connection, root: Path, master: SkillMaster | None = None, force: bool = False) -> ImportReport:
    """抽出フォルダ以下のCSVを取り込む。force=Trueなら未変更のCSVも読み直す。"""
    report = ImportReport()
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"抽出フォルダが見つかりません: {root}")
    for csv_path in sorted(root.rglob("*.csv")):
        relative = csv_path.relative_to(root).as_posix()
        stat = csv_path.stat()
        seen = conn.execute("SELECT size, mtime_ns FROM imported_files WHERE path = ?", (relative,)).fetchone()
        if not force and seen and (seen["size"], seen["mtime_ns"]) == (stat.st_size, stat.st_mtime_ns):
            report.unchanged += 1
            continue
        with conn:  # 1ファイル単位で確定。途中で失敗しても他のファイルに影響しない
            result = import_file(conn, csv_path, root, master)
            conn.execute(
                """
                INSERT INTO imported_files (path, size, mtime_ns, rows_added, rows_skipped)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (path) DO UPDATE SET size = excluded.size, mtime_ns = excluded.mtime_ns,
                    rows_added = excluded.rows_added, rows_skipped = excluded.rows_skipped,
                    imported_at = datetime('now', 'localtime')
                """,
                (relative, stat.st_size, stat.st_mtime_ns, result.added, result.skipped),
            )
        report.files.append(result)
    return report
