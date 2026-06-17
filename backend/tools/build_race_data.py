from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "backend" / "data" / "guide_import" / "checked" / "race_skills_checked.csv"
DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "src" / "data" / "race_data.json"
TIERS = {
    "super": "super_recommended",
    "super_recommended": "super_recommended",
    "超おすすめ": "super_recommended",
    "超おすすめスキル": "super_recommended",
    "recommended": "recommended",
    "normal": "recommended",
    "おすすめ": "recommended",
    "おすすめスキル": "recommended",
}
READY_STATUSES = {"ready", "approved", "ok", "公開", "確認済み"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_tier(value: str) -> str | None:
    return TIERS.get(value.strip())


def clean_value(value: str | None) -> str:
    return (value or "").strip()


def append_unique(values: list[str], skill: str) -> None:
    if skill and skill not in values:
        values.append(skill)


def set_skill_tier(strategy_detail: dict[str, Any], tier: str, skill: str) -> None:
    for existing_tier in ("super_recommended", "recommended"):
        existing_values = strategy_detail.setdefault(existing_tier, [])
        if not isinstance(existing_values, list):
            strategy_detail[existing_tier] = []
            existing_values = strategy_detail[existing_tier]
        if existing_tier != tier:
            strategy_detail[existing_tier] = [
                value for value in existing_values if value != skill
            ]

    target = strategy_detail.setdefault(tier, [])
    if not isinstance(target, list):
        strategy_detail[tier] = []
        target = strategy_detail[tier]
    append_unique(target, skill)


def empty_strategy() -> dict[str, list[str]]:
    return {"super_recommended": [], "recommended": []}


def should_include(status: str, include_draft: bool) -> bool:
    if include_draft:
        return True
    return status.strip().lower() in READY_STATUSES


def apply_csv(
    data: dict[str, Any],
    csv_path: Path,
    *,
    include_draft: bool,
    replace: bool,
) -> tuple[dict[str, Any], int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV was not found: {csv_path}")

    if replace:
        data = {}

    count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_columns = {"race", "strategy", "tier", "skill"}
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            race = clean_value(row.get("race"))
            strategy = clean_value(row.get("strategy"))
            tier = normalize_tier(clean_value(row.get("tier")))
            skill = clean_value(row.get("skill"))
            status = clean_value(row.get("status"))

            if not race or not strategy or not tier or not skill:
                continue
            if not should_include(status, include_draft):
                continue

            if race not in data or not isinstance(data[race], dict):
                data[race] = {}
            if strategy not in data[race] or not isinstance(data[race][strategy], dict):
                data[race][strategy] = empty_strategy()

            set_skill_tier(data[race][strategy], tier, skill)
            count += 1

    return data, count


def build(args: argparse.Namespace) -> int:
    data = {} if args.replace else read_json(args.output)
    data, count = apply_csv(
        data,
        args.input,
        include_draft=args.include_draft,
        replace=args.replace,
    )

    if args.dry_run:
        print(json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "included_rows": count,
                "race_count": len(data),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    write_json(args.output, data)
    print(f"Wrote {count} rows into {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build frontend/src/data/race_data.json from checked trainer guide CSV."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true", help="Replace output JSON instead of merging into it.")
    parser.add_argument("--include-draft", action="store_true", help="Include rows even when status is not ready.")
    parser.add_argument("--dry-run", action="store_true", help="Validate input and print a summary without writing.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return build(args)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
