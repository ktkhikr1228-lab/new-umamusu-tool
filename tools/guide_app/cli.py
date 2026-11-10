"""コマンド入口。画面ができるまでは取り込みと件数確認だけ。

    python3 tools/guide_app import     # 抽出CSVをSQLiteへ取り込む
    python3 tools/guide_app status     # イベントごとの件数
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import db
from .config import load_config
from .importer import import_all
from .skill_master import SkillMaster


def cmd_import(config, args) -> int:
    conn = db.connect(config.db_path)
    master = SkillMaster.load(config.skill_master_path) if config.skill_master_path.exists() else None
    report = import_all(conn, config.extracted_dir, master, force=args.force)
    for f in report.files:
        print(f"{f.path}  イベント={f.event}  追加={f.added}  既存/スキップ={f.skipped}")
    print(f"取り込み: {len(report.files)}ファイル / 追加 {report.added}行 / 変更なしで省略 {report.unchanged}ファイル")
    if report.problems:
        print("\n確認が必要な点:")
        for problem in report.problems:
            print(f"  - {problem}")
    if master is None:
        print(f"\n注意: スキルマスタが見つからないため表記の自動補正をしていません: {config.skill_master_path}")
    return 0


def cmd_status(config, args) -> int:
    conn = db.connect(config.db_path)
    rows = db.status_counts(conn)
    if not rows:
        print("まだデータがありません。先に import を実行してください。")
        return 0
    print(f"{'イベント':<20}{'合計':>6}{'未確認':>8}{'OK':>6}{'却下':>6}{'未公開OK':>10}")
    for r in rows:
        print(f"{r['event']:<20}{r['total']:>6}{r['draft']:>8}{r['ready']:>6}{r['rejected']:>6}{r['unpublished']:>10}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guide_app", description="トレーナーガイドの確認・公開アプリ")
    parser.add_argument("--config", type=Path, help="設定ファイル(既定: tools/guide_app/config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import", help="抽出CSVを取り込む")
    p.add_argument("--force", action="store_true", help="変更のないCSVも読み直す(既存行は上書きしない)")
    sub.add_parser("status", help="イベントごとの件数を表示する")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    return {"import": cmd_import, "status": cmd_status}[args.command](config, args)
