"""SQLiteの保存先。テーブル定義と小さな操作関数だけを置く。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

STATUSES = ("draft", "ready", "rejected")

# PRAGMA user_version で版を管理する。列を増やすときは MIGRATIONS に足す。
MIGRATIONS = [
    """
    CREATE TABLE skills (
        id              INTEGER PRIMARY KEY,
        event           TEXT NOT NULL,
        race            TEXT NOT NULL,
        strategy        TEXT NOT NULL,
        tier            TEXT NOT NULL,
        extracted_skill TEXT NOT NULL,          -- Geminiが読んだ名前(変更しない)
        skill           TEXT NOT NULL,          -- 確認後の名前(画面で修正する)
        status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'ready', 'rejected')),
        source_file     TEXT NOT NULL DEFAULT '',   -- 元画像のファイル名
        source_csv      TEXT NOT NULL DEFAULT '',   -- 取り込んだCSV(抽出フォルダからの相対パス)
        memo            TEXT NOT NULL DEFAULT '',
        published_at    TEXT,                       -- 公開依頼に含めた日時
        created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        UNIQUE (event, race, strategy, tier, extracted_skill)
    );
    CREATE INDEX skills_group ON skills (event, race, strategy);
    CREATE INDEX skills_status ON skills (status);

    CREATE TABLE imported_files (
        path         TEXT PRIMARY KEY,   -- 抽出フォルダからの相対パス
        size         INTEGER NOT NULL,
        mtime_ns     INTEGER NOT NULL,
        rows_added   INTEGER NOT NULL,
        rows_skipped INTEGER NOT NULL,
        imported_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    # v2: 画像ごとの確認状態
    """
    CREATE TABLE images (
        event       TEXT NOT NULL,
        source_file TEXT NOT NULL,
        reviewed_at TEXT,
        PRIMARY KEY (event, source_file)
    );
    """,
    # v3: イベントの表示設定(テスト用イベントを隠す)
    """
    CREATE TABLE events (
        event  TEXT PRIMARY KEY,
        hidden INTEGER NOT NULL DEFAULT 0
    );
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # 画面表示中の書き込みでも固まりにくくする
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        with conn:
            conn.executescript(MIGRATIONS[index])
            conn.execute(f"PRAGMA user_version = {index + 1}")


def status_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT event,
               COUNT(*) AS total,
               SUM(status = 'draft') AS draft,
               SUM(status = 'ready') AS ready,
               SUM(status = 'rejected') AS rejected,
               SUM(status = 'ready' AND published_at IS NULL) AS unpublished
        FROM skills GROUP BY event ORDER BY event
        """
    ).fetchall()
