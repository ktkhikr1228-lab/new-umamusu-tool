from __future__ import annotations

import argparse
import csv
import difflib
import glob
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXTRACTED_GLOB = REPO_ROOT / "backend" / "data" / "guide_import" / "extracted" / "*.csv"
DEFAULT_REPORT = REPO_ROOT / "backend" / "data" / "guide_import" / "reports" / "skill_check_report.csv"
CARDS_JSON = REPO_ROOT / "frontend" / "src" / "data" / "cards.json"
NON_FACTOR_JSON = REPO_ROOT / "frontend" / "src" / "data" / "non_factor_skills.json"
RACE_DATA_JSON = REPO_ROOT / "frontend" / "src" / "data" / "race_data.json"
CSV_COLUMNS = ["race", "strategy", "tier", "skill", "source_file", "status", "memo"]
REPORT_COLUMNS = [
    "skill",
    "result",
    "suggestions",
    "tiers",
    "row_count",
    "source_files",
    "csv_files",
]
TIER_PRIORITY = {
    "recommended": 1,
    "super_recommended": 2,
}
GUIDE_ONLY_SKILLS = {
    "\u7cbe\u795e\u529b",
}

# High-confidence OCR fixes seen in trainer-guide screenshots.
COMMON_FIXES = {
    "\u661f\u306e\u8f1d\u304d": "\u661f\u306e\u714c\u304d",
    "\u5e9c\u4e2d\u25ce\u306e\u7533\u3057\u5b50": "\u5e9c\u4e2d\u306e\u7533\u3057\u5b50",
    "\u30b3\u30fc\u30ca\u30fc\u5de7\u8005\u25ce": "\u30b3\u30fc\u30ca\u30fc\u5de7\u8005\u25cb",
    "\u5f3e\u307f\u3092\u4ed8\u3051\u3066": "\u5f3e\u307f\u3092\u3064\u3051\u3066",
    "\u5f71\u8e0f\u7834": "\u5f71\u5f93\u6253\u7834",
    "\u63fa\u308b\u304c\u306c\u81ea\u4fe1": "\u63fa\u308b\u304c\u306c\u4fe1\u5ff5",
    "\u6602\u308b\u8db3\u53d6\u308a": "\u9038\u308b\u8db3\u53d6\u308a",
    "\u661f\u306e\u714c\u3081\u304d": "\u661f\u306e\u714c\u304d",
    "\u9023\u8987\u53cd\u5fdc": "\u9023\u9396\u53cd\u5fdc",
    "\u601c\u60a7\u72e1\u733e": "\u601c\u60a7\u6e05\u6f84",
    "\u5343\u4e21\u4e07\u92ad": "\u5343\u921e\u4e07\u9460",
    "\u66c7\u308a\u306a\u3057": "\u6182\u3044\u306a\u3057",
    "\u66c7\u71d5\u7adc\u5909": "\u96f2\u84b8\u7adc\u5909",
}


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def normalize_skill(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.strip()
    value = value.replace("〇", "○")
    return "".join(value.split())


def collect_strings(value: Any, result: set[str]) -> None:
    if isinstance(value, str):
        cleaned = normalize_skill(value)
        if cleaned:
            result.add(cleaned)
        return
    if isinstance(value, list):
        for item in value:
            collect_strings(item, result)
        return
    if isinstance(value, dict):
        for item in value.values():
            collect_strings(item, result)


def collect_known_skills() -> tuple[set[str], set[str]]:
    known: set[str] = set()
    non_factor: set[str] = set()

    cards = read_json(CARDS_JSON)
    if isinstance(cards, list):
        for card in cards:
            if not isinstance(card, dict):
                continue
            collect_strings(card.get("skills", []), known)
            collect_strings(card.get("rare_skills", []), known)

    non_factor_data = read_json(NON_FACTOR_JSON)
    collect_strings(non_factor_data, non_factor)
    known.update(non_factor)

    race_data = read_json(RACE_DATA_JSON)
    collect_strings(race_data, known)

    return known, non_factor


def resolve_input_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    if args.input:
        paths.extend(path.resolve() for path in args.input)
    if args.input_glob:
        paths.extend(Path(path).resolve() for path in glob.glob(args.input_glob))
    if not paths:
        paths.extend(Path(path).resolve() for path in glob.glob(str(DEFAULT_EXTRACTED_GLOB)))

    unique_paths = sorted(dict.fromkeys(paths))
    missing = [path for path in unique_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing CSV files: " + ", ".join(str(path) for path in missing))
    return unique_paths


def read_csv_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            missing = set(CSV_COLUMNS[:4]) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
            for row in reader:
                normalized = {column: row.get(column, "") for column in CSV_COLUMNS}
                normalized["_csv_file"] = str(path)
                normalized["skill"] = normalize_skill(normalized["skill"])
                rows.append(normalized)
    return rows


def is_double_circle_variant(skill: str, known: set[str]) -> bool:
    if not skill.endswith("◎"):
        return False
    circle_variant = skill[:-1] + "○"
    return circle_variant in known or skill[:-1] in known


def suggestions_for(skill: str, known: set[str]) -> list[str]:
    if skill in COMMON_FIXES:
        return [COMMON_FIXES[skill]]
    return difflib.get_close_matches(skill, sorted(known), n=4, cutoff=0.55)


def classify_skill(skill: str, known: set[str], non_factor: set[str]) -> str:
    if skill in COMMON_FIXES:
        return "common_fix"
    if skill in non_factor:
        return "ok_non_factor"
    if skill in GUIDE_ONLY_SKILLS:
        return "ok_guide_only"
    if is_double_circle_variant(skill, known):
        return "ok_factor_excluded_double_circle"
    if skill in known:
        return "ok_known"
    return "review_unknown"


def build_skill_report(
    rows: list[dict[str, str]],
    *,
    known: set[str],
    non_factor: set[str],
) -> tuple[list[dict[str, str]], dict[tuple[str, str], set[str]]]:
    by_skill: dict[str, list[dict[str, str]]] = defaultdict(list)
    tiers_by_context: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        skill = row.get("skill", "")
        if skill:
            by_skill[skill].append(row)
        context = (row.get("race", ""), row.get("strategy", ""), skill)
        tiers_by_context[context].add(row.get("tier", ""))

    tier_conflicts = {
        (race, strategy, skill): tiers
        for (race, strategy, skill), tiers in tiers_by_context.items()
        if len(tiers) > 1 and skill
    }

    report_rows: list[dict[str, str]] = []
    for skill, skill_rows in sorted(by_skill.items()):
        result = classify_skill(skill, known, non_factor)
        suggestions = suggestions_for(skill, known)
        report_rows.append(
            {
                "skill": skill,
                "result": result,
                "suggestions": " / ".join(suggestions),
                "tiers": " / ".join(sorted({row.get("tier", "") for row in skill_rows})),
                "row_count": str(len(skill_rows)),
                "source_files": " / ".join(sorted({row.get("source_file", "") for row in skill_rows})),
                "csv_files": " / ".join(sorted({row.get("_csv_file", "") for row in skill_rows})),
            }
        )

    return report_rows, tier_conflicts


def append_memo(memo: str, addition: str) -> str:
    memo = (memo or "").strip()
    return f"{memo}; {addition}" if memo else addition


def resolve_tier_conflicts(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    index_by_key: dict[tuple[str, str, str], int] = {}

    for row in rows:
        key = (
            row.get("race", ""),
            row.get("strategy", ""),
            row.get("skill", ""),
        )
        if key not in index_by_key:
            index_by_key[key] = len(result)
            result.append(row)
            continue

        current_index = index_by_key[key]
        current_row = result[current_index]
        current_score = TIER_PRIORITY.get(current_row.get("tier", ""), 0)
        new_score = TIER_PRIORITY.get(row.get("tier", ""), 0)

        if new_score > current_score:
            row["memo"] = append_memo(
                row.get("memo", ""),
                f"tier_conflict:kept_{row.get('tier', '')}_over_{current_row.get('tier', '')}",
            )
            result[current_index] = row
            continue

        if new_score < current_score:
            current_row["memo"] = append_memo(
                current_row.get("memo", ""),
                f"tier_conflict:dropped_{row.get('tier', '')}_duplicate",
            )

    return result


def fixed_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        new_row = {column: row.get(column, "") for column in CSV_COLUMNS}
        old_skill = new_row["skill"]
        if old_skill in COMMON_FIXES:
            new_row["skill"] = COMMON_FIXES[old_skill]
            new_row["memo"] = append_memo(
                new_row.get("memo", ""),
                f"auto_fix:{old_skill}->{new_row['skill']}",
            )
        key = (
            new_row.get("race", ""),
            new_row.get("strategy", ""),
            new_row.get("tier", ""),
            new_row.get("skill", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(new_row)
    return resolve_tier_conflicts(result)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def print_summary(
    rows: list[dict[str, str]],
    report_rows: list[dict[str, str]],
    tier_conflicts: dict[tuple[str, str, str], set[str]],
) -> None:
    result_counts = Counter(row["result"] for row in report_rows)
    print(f"Rows: {len(rows)}")
    print(f"Unique skills: {len(report_rows)}")
    for key in (
        "ok_known",
        "ok_non_factor",
        "ok_guide_only",
        "ok_factor_excluded_double_circle",
        "common_fix",
        "review_unknown",
    ):
        print(f"{key}: {result_counts.get(key, 0)}")
    print(f"tier_conflicts: {len(tier_conflicts)}")

    review_rows = [row for row in report_rows if row["result"] in {"common_fix", "review_unknown"}]
    if review_rows:
        print("")
        print("Review candidates:")
        for row in review_rows[:30]:
            suggestion_text = f" -> {row['suggestions']}" if row["suggestions"] else ""
            print(f"- {row['skill']} [{row['result']}]{suggestion_text}")
        if len(review_rows) > 30:
            print(f"... and {len(review_rows) - 30} more")

    if tier_conflicts:
        print("")
        print("Tier conflicts:")
        for (race, strategy, skill), tiers in sorted(tier_conflicts.items()):
            print(f"- {race} / {strategy} / {skill}: {' / '.join(sorted(tiers))}")


def run(args: argparse.Namespace) -> int:
    paths = resolve_input_paths(args)
    if not paths:
        raise FileNotFoundError(f"No CSV files matched: {DEFAULT_EXTRACTED_GLOB}")

    known, non_factor = collect_known_skills()
    rows = read_csv_rows(paths)
    report_rows, tier_conflicts = build_skill_report(rows, known=known, non_factor=non_factor)
    print_summary(rows, report_rows, tier_conflicts)

    if args.report:
        write_csv(args.report, REPORT_COLUMNS, report_rows)
        print(f"Wrote report: {args.report}")

    if args.write_fixed:
        write_csv(args.write_fixed, CSV_COLUMNS, fixed_rows(rows))
        print(f"Wrote fixed CSV: {args.write_fixed}")

    return 1 if args.fail_on_review and any(row["result"] == "review_unknown" for row in report_rows) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check extracted trainer-guide CSV files against known skill names."
    )
    parser.add_argument("--input", action="append", type=Path, help="CSV file. Can be passed more than once.")
    parser.add_argument("--input-glob", help="Glob for extracted CSV files.")
    parser.add_argument("--report", type=Path, help=f"Output report CSV path. Example: {DEFAULT_REPORT}")
    parser.add_argument("--write-fixed", type=Path, help="Write a copy with common OCR fixes applied.")
    parser.add_argument("--fail-on-review", action="store_true", help="Exit with 1 when unknown skills remain.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
