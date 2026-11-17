"""スキルマスタの更新が、人の確認なしでマージしてよいほど安全かを判定する。

使い方:
  python backend/tools/check_skill_master_change.py --before 更新前.json --after 更新後.json

終了コード:
  0 = 安全(変更なし、または追加だけで、数も名前の形も問題なし)
  2 = 人の確認が必要(理由を表示する)
  1 = ファイルを読めない・形式が違う

「安全」の条件(すべて満たすこと):
  - 削除・名前の変更が0件(追加だけ)
  - 追加が --max-added 件以内(取得データの形式が変わって、おかしな名前が大量に入ることへの歯止め)
  - 名前が空でない、前後に空白がない、制御文字がない、長すぎない、重複がない
.github/workflows/update-skill-master.yml が、自動マージの前に呼ぶ。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_names(path: Path) -> list:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: スキル名の配列ではありません")
    return data


def problems(before: list, after: list, max_added: int = 400, max_length: int = 60) -> list[str]:
    """人の確認が必要な理由の一覧。空なら安全。"""
    found: list[str] = []
    bad_type = [n for n in after if not isinstance(n, str)]
    if bad_type:
        return [f"文字列でない要素が {len(bad_type)} 件あります"]
    empty = [n for n in after if not n.strip()]
    if empty:
        found.append(f"空の名前が {len(empty)} 件あります")
    padded = [n for n in after if n != n.strip()]
    if padded:
        found.append(f"前後に空白のある名前が {len(padded)} 件あります(例: {padded[0]!r})")
    control = [n for n in after if any(ord(c) < 32 for c in n)]
    if control:
        found.append(f"制御文字を含む名前が {len(control)} 件あります")
    long_names = [n for n in after if len(n) > max_length]
    if long_names:
        found.append(f"{max_length}文字を超える名前が {len(long_names)} 件あります(例: {long_names[0][:30]!r}…)")
    if len(set(after)) != len(after):
        found.append(f"重複した名前が {len(after) - len(set(after))} 件あります")
    removed = sorted(set(before) - set(after))
    if removed:
        found.append(f"削除または名前の変更が {len(removed)} 件あります(例: {', '.join(removed[:5])})")
    added = set(after) - set(before)
    if len(added) > max_added:
        found.append(f"追加が {len(added)} 件で、上限の {max_added} 件を超えています")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--max-added", type=int, default=400)
    parser.add_argument("--max-length", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        before, after = load_names(args.before), load_names(args.after)
    except (OSError, ValueError) as error:
        print(f"読み込みに失敗しました: {error}", file=sys.stderr)
        return 1
    found = problems(before, after, args.max_added, args.max_length)
    added = len(set(after) - set(before)) if all(isinstance(n, str) for n in after) else 0
    if found:
        print(f"人の確認が必要です(追加 {added} 件)")
        for reason in found:
            print(f"- {reason}")
        return 2
    if added == 0:
        print("変更なし")
    else:
        print(f"安全: 追加 {added} 件のみ(削除・名前の変更なし)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
