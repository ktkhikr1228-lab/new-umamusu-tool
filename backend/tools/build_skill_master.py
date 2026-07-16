"""GameToraのskillsデータから全スキル名のマスターリストを作る。

使い方(backendディレクトリで):

  # GameToraから最新を取得して skill_master.json を生成
  python tools/build_skill_master.py --download-latest

  # 手動ダウンロードしたJSONから生成
  python tools/build_skill_master.py --input data/import/skills.XXXX.json

  # race_data.json のスキル名がマスターに存在するか照合(誤認識チェック)
  python tools/build_skill_master.py --check

出力: frontend/src/data/skill_master.json (スキル名のソート済み配列)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_gametora_cards import (  # noqa: E402
    DEFAULT_MANIFEST_URLS,
    as_records,
    build_data_url,
    fetch_manifest,
    find_manifest_value,
    pick,
    read_json_url,
    write_json,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "src" / "data" / "skill_master.json"
RACE_DATA_PATH = REPO_ROOT / "frontend" / "src" / "data" / "race_data.json"

NAME_KEYS = ("jpname", "name_jp", "name_ja", "name_jpn", "name", "title_ja")


def extract_skill_names(skills_data) -> list[str]:
    names: set[str] = set()
    for skill in as_records(skills_data):
        name = pick(skill, NAME_KEYS)
        if name:
            names.add(str(name).strip())
    return sorted(names)


def download_skills_data() -> object:
    manifest_data, _ = fetch_manifest(list(DEFAULT_MANIFEST_URLS))
    hash_value = find_manifest_value(manifest_data, "skills")
    if not hash_value:
        raise RuntimeError("manifestに 'skills' が見つかりません。")
    url, _ = build_data_url("skills", hash_value)
    print(f"downloading: {url}")
    return read_json_url(url)


def normalize_name(value: str) -> str:
    """照合用の正規化。半角記号を全角へ、空白を除去する。"""
    table = str.maketrans({"!": "！", "?": "？", "(": "（", ")": "）", "~": "〜"})
    return value.translate(table).replace(" ", "").replace("　", "")


def find_closest(name: str, master: list[str], limit: int = 2) -> list[str]:
    import difflib

    return difflib.get_close_matches(name, master, n=limit, cutoff=0.6)


def check_against_master(master: set[str]) -> int:
    if not RACE_DATA_PATH.exists():
        print(f"race_data.json が見つかりません: {RACE_DATA_PATH}", file=sys.stderr)
        return 1

    race_data = json.loads(RACE_DATA_PATH.read_text(encoding="utf-8"))
    normalized_master = {normalize_name(name): name for name in master}
    master_list = sorted(master)

    notation: dict[str, str] = {}  # 表記ゆれ: 誤 -> 正
    unknown: dict[str, list[str]] = {}
    for race, strategies in race_data.items():
        for strategy, detail in strategies.items():
            if not isinstance(detail, dict):
                continue
            for tier, skills in detail.items():
                if not isinstance(skills, list):
                    continue
                for skill in skills:
                    if skill in master:
                        continue
                    canonical = normalized_master.get(normalize_name(skill))
                    if canonical:
                        notation[skill] = canonical
                    else:
                        unknown.setdefault(skill, []).append(
                            f"{race}/{strategy}/{tier}"
                        )

    if not notation and not unknown:
        print("OK: race_data.json のスキル名はすべてマスターに存在します。")
        return 0

    if notation:
        print(f"表記ゆれ(正規化で一致): {len(notation)}件")
        for wrong, correct in sorted(notation.items()):
            print(f"- {wrong} -> {correct}")
        print()

    if unknown:
        print(f"マスターに存在しないスキル名: {len(unknown)}件(誤認識の可能性)")
        for skill, places in sorted(unknown.items()):
            suggestions = find_closest(skill, master_list)
            hint = f"  もしかして: {' / '.join(suggestions)}" if suggestions else ""
            print(f"- {skill}  ({places[0]}{' ほか' if len(places) > 1 else ''}){hint}")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-latest", action="store_true")
    parser.add_argument("--input", type=Path, help="手動取得したskills JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="race_data.jsonのスキル名をマスターと照合する",
    )
    args = parser.parse_args()

    if args.check and not args.download_latest and not args.input:
        if not args.output.exists():
            print("マスターがまだありません。--download-latest を先に実行してください。", file=sys.stderr)
            return 1
        master = set(json.loads(args.output.read_text(encoding="utf-8")))
        return check_against_master(master)

    if args.input:
        skills_data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    elif args.download_latest:
        skills_data = download_skills_data()
    else:
        parser.print_help()
        return 1

    names = extract_skill_names(skills_data)
    if not names:
        print("スキル名を抽出できませんでした。JSONの形式を確認してください。", file=sys.stderr)
        return 1

    write_json(args.output, names)
    print(f"{len(names)} 件のスキル名を {args.output} に書き出しました。")

    if args.check:
        return check_against_master(set(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
