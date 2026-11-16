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
    # v4: 公開依頼の記録
    """
    CREATE TABLE publish_log (
        id      INTEGER PRIMARY KEY,
        event   TEXT NOT NULL,
        rows    INTEGER NOT NULL,
        result  TEXT NOT NULL,      -- 送信結果(JSON)
        sent_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    # v5: 複数モデルでの読み取り(多数決)
    """
    ALTER TABLE skills ADD COLUMN votes INTEGER;                     -- そのスキルを読んだモデルの数
    ALTER TABLE skills ADD COLUMN readers INTEGER;                   -- 読み取りに使ったモデルの数
    ALTER TABLE skills ADD COLUMN read_by TEXT NOT NULL DEFAULT '';  -- 読んだモデル名(カンマ区切り)
    ALTER TABLE events ADD COLUMN race TEXT NOT NULL DEFAULT '';     -- 抽出時に選んだレース
    CREATE TABLE readings (
        event       TEXT NOT NULL,
        source_file TEXT NOT NULL,
        reader      TEXT NOT NULL,
        model       TEXT NOT NULL,
        names       TEXT NOT NULL,              -- 読み取ったスキル名(JSON)
        error       TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (event, source_file, reader)
    );
    """,
    # v6: フォルダ(撮影時の設定)と画像の中身の食い違い
    """
    ALTER TABLE images ADD COLUMN warning TEXT NOT NULL DEFAULT '';
    """,
    # v7: 自動処理(automation.py)の覚え書き。再起動しても、やり直しの回数や通知済みの印を忘れないため
    """
    CREATE TABLE automation_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL DEFAULT '',   -- JSON
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    """,
    # v8: 人が触った行の印。自動確定は、この印のある行に手を付けない
    """
    ALTER TABLE skills ADD COLUMN touched INTEGER NOT NULL DEFAULT 0;
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


def _statements(script: str) -> list[str]:
    out, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                out.append(buffer.strip())
            buffer = ""
    return out + ([buffer.strip()] if buffer.strip() else [])


def migrate(conn: sqlite3.Connection) -> None:
    """版を1つずつ上げる。途中で止まった版をやり直しても進めるよう、適用済みの文(列・表がもうある)は飛ばす。"""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        for statement in _statements(MIGRATIONS[index]):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error) and "already exists" not in str(error):
                    raise
        conn.execute(f"PRAGMA user_version = {index + 1}")
        conn.commit()


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
