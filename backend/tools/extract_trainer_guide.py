from __future__ import annotations

import argparse
import base64
import csv
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from io import StringIO
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "guide_import" / "extracted"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
CSV_COLUMNS = ["race", "strategy", "tier", "skill", "source_file", "status", "memo"]
STRATEGY_SLUGS = {
    "逃げ": "nige",
    "先行": "senkou",
    "差し": "sashi",
    "追込": "oikomi",
}
TIER_ALIASES = {
    "super": "super_recommended",
    "super_recommended": "super_recommended",
    "超おすすめ": "super_recommended",
    "超おすすめスキル": "super_recommended",
    "recommended": "recommended",
    "normal": "recommended",
    "おすすめ": "recommended",
    "おすすめスキル": "recommended",
}


class GeminiRateLimitError(RuntimeError):
    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        quota_scope: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.quota_scope = quota_scope


def list_images(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory was not found: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def sanitize_file_part(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value.strip())
    value = re.sub(r"\s+", "_", value)
    return value or "race"


def default_output_path(race: str, strategy: str) -> Path:
    strategy_part = STRATEGY_SLUGS.get(strategy, sanitize_file_part(strategy))
    return DEFAULT_OUTPUT_DIR / f"{sanitize_file_part(race)}_{strategy_part}.csv"


def make_prompt(race: str, strategy: str) -> str:
    return f"""
この画像はウマ娘 プリティーダービーのトレーナーガイドです。

対象レース: {race}
対象脚質: {strategy}

画像内に表示されているスキル名だけを抽出してください。

抽出対象:
- 「超おすすめスキル」欄のスキル
- 「おすすめスキル」欄のスキル

抽出しないもの:
- レース条件
- 脚質タブ
- ボタンや説明文
- アイコン名
- 画面外で見えていないスキル

重要:
- 画像に見えているスキル名は省略しないでください。
- 「◎」「○」などの記号は画像の表記どおり残してください。
- 金スキルかどうかの判断や除外はしないでください。
- tier は必ず super_recommended または recommended のどちらかにしてください。

返答はJSONのみで、次の形式にしてください。
[
  {{"tier":"super_recommended","skill":"左回り◎"}},
  {{"tier":"recommended","skill":"地固め"}}
]
""".strip()


def extract_retry_after_seconds(body: str) -> float | None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        details = data.get("error", {}).get("details", [])
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                retry_delay = detail.get("retryDelay")
                if isinstance(retry_delay, str):
                    match = re.search(r"([\d.]+)s", retry_delay)
                    if match:
                        return float(match.group(1))

    match = re.search(r"retry in ([\d.]+)s", body, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def extract_quota_scope(body: str) -> str | None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = None

    quota_ids: list[str] = []
    if isinstance(data, dict):
        details = data.get("error", {}).get("details", [])
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                violations = detail.get("violations")
                if not isinstance(violations, list):
                    continue
                for violation in violations:
                    if isinstance(violation, dict):
                        quota_id = violation.get("quotaId")
                        if isinstance(quota_id, str):
                            quota_ids.append(quota_id)

    if any("PerDay" in quota_id for quota_id in quota_ids):
        return "day"
    if any("PerMinute" in quota_id for quota_id in quota_ids):
        return "minute"
    return None


def call_gemini_for_image(
    image_path: Path,
    *,
    api_key: str,
    model: str,
    race: str,
    strategy: str,
) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    model_name = urllib.parse.quote(model, safe="")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": make_prompt(race, strategy)},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_data,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        if error.code == 429:
            raise GeminiRateLimitError(
                f"Gemini API error {error.code}: {body}",
                retry_after=extract_retry_after_seconds(body),
                quota_scope=extract_quota_scope(body),
            ) from error
        raise RuntimeError(f"Gemini API error {error.code}: {body}") from error

    parts = (
        response_data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    text = "\n".join(part for part in text_parts if part).strip()
    if not text:
        raise RuntimeError(f"Gemini returned no text for {image_path.name}.")
    return text


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|csv)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def normalize_tier(value: str) -> str | None:
    normalized = value.strip()
    return TIER_ALIASES.get(normalized)


def clean_skill(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^[・\-\s]+", "", value)
    value = re.sub(r"\s+", "", value)
    return value


def parse_json_rows(text: str) -> list[dict[str, str]]:
    cleaned = strip_code_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", cleaned)
        if not match:
            raise
        data = json.loads(match.group(1))

    if isinstance(data, dict):
        for key in ("skills", "items", "data", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError("Gemini response JSON must be an array or contain a skills array.")

    rows: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tier = normalize_tier(str(item.get("tier") or item.get("category") or ""))
        skill = clean_skill(str(item.get("skill") or item.get("skill_name") or ""))
        if tier and skill:
            rows.append({"tier": tier, "skill": skill})
    return rows


def parse_csv_rows(text: str) -> list[dict[str, str]]:
    cleaned = strip_code_fence(text)
    reader = csv.DictReader(StringIO(cleaned))
    rows: list[dict[str, str]] = []
    for item in reader:
        category = item.get("tier") or item.get("カテゴリ") or item.get("category") or ""
        skill_name = item.get("skill") or item.get("スキル名") or item.get("skill_name") or ""
        tier = normalize_tier(category)
        skill = clean_skill(skill_name)
        if tier and skill:
            rows.append({"tier": tier, "skill": skill})
    return rows


def parse_model_rows(text: str) -> list[dict[str, str]]:
    try:
        return parse_json_rows(text)
    except (json.JSONDecodeError, ValueError):
        return parse_csv_rows(text)


def read_existing_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        key = (
            row.get("race", ""),
            row.get("strategy", ""),
            row.get("tier", ""),
            row.get("skill", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def processed_source_files(rows: list[dict[str, str]], race: str, strategy: str) -> set[str]:
    return {
        row.get("source_file", "")
        for row in rows
        if row.get("race") == race and row.get("strategy") == strategy and row.get("source_file")
    }


def call_gemini_with_retries(
    image_path: Path,
    *,
    api_key: str,
    model: str,
    race: str,
    strategy: str,
    max_retries: int,
    delay_seconds: float,
) -> str:
    for attempt in range(max_retries + 1):
        try:
            return call_gemini_for_image(
                image_path,
                api_key=api_key,
                model=model,
                race=race,
                strategy=strategy,
            )
        except GeminiRateLimitError as error:
            if error.quota_scope == "day":
                raise RuntimeError(
                    "Gemini daily free-tier quota is exhausted for this model. "
                    "Try again after the daily quota resets, use another API key/project, "
                    "or enable billing. Completed images have already been saved."
                ) from error
            if attempt >= max_retries:
                raise
            wait_seconds = max(error.retry_after or 0, delay_seconds, 15)
            print(f"Rate limited. Waiting {wait_seconds:.0f}s before retry...")
            time.sleep(wait_seconds)

    raise RuntimeError(f"Gemini retry loop failed for {image_path.name}.")


def extract(args: argparse.Namespace) -> int:
    input_dir = args.input_dir.resolve()
    images = list_images(input_dir)
    if args.limit:
        images = images[: args.limit]

    output_path = args.output or default_output_path(args.race, args.strategy)

    if args.dry_run:
        print(json.dumps(
            {
                "input_dir": str(input_dir),
                "image_count": len(images),
                "images": [str(path.relative_to(input_dir)) for path in images],
                "output": str(output_path),
                "model": args.model,
                "delay_seconds": args.delay_seconds,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Pass --api-key or set the environment variable.")

    rows = read_existing_rows(output_path) if args.append else []
    processed_sources = processed_source_files(rows, args.race, args.strategy) if args.append else set()
    request_count = 0

    for image_path in images:
        source_file = str(image_path.relative_to(input_dir))
        if source_file in processed_sources and not args.force:
            print(f"Skipping already processed image: {source_file}")
            continue

        if request_count > 0 and args.delay_seconds > 0:
            print(f"Waiting {args.delay_seconds:.0f}s to avoid rate limits...")
            time.sleep(args.delay_seconds)

        print(f"Extracting: {image_path.name}")
        response_text = call_gemini_with_retries(
            image_path,
            api_key=api_key,
            model=args.model,
            race=args.race,
            strategy=args.strategy,
            max_retries=args.max_retries,
            delay_seconds=args.delay_seconds,
        )
        request_count += 1
        extracted_rows = parse_model_rows(response_text)
        for row in extracted_rows:
            rows.append(
                {
                    "race": args.race,
                    "strategy": args.strategy,
                    "tier": row["tier"],
                    "skill": row["skill"],
                    "source_file": source_file,
                    "status": args.status,
                    "memo": "",
                }
            )
        rows = dedupe_rows(rows)
        write_rows(output_path, rows)
        processed_sources.add(source_file)
        print(f"Saved progress: {len(rows)} rows")

    rows = dedupe_rows(rows)
    write_rows(output_path, rows)
    print(f"Wrote {len(rows)} rows: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Uma Musume trainer guide skills from local screenshots with Gemini."
    )
    parser.add_argument("--input-dir", required=True, type=Path, help="Screenshot directory.")
    parser.add_argument("--race", required=True, help="Race label, for example: 東京 芝 2400m")
    parser.add_argument("--strategy", required=True, help="Strategy: 逃げ / 先行 / 差し / 追込")
    parser.add_argument("--output", type=Path, help="Output CSV path.")
    parser.add_argument("--append", action="store_true", help="Append to an existing CSV before de-duping.")
    parser.add_argument("--status", default="draft", help="CSV status value for extracted rows.")
    parser.add_argument("--api-key", help="Gemini API key. Defaults to GEMINI_API_KEY.")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--limit", type=int, help="Process only the first N images.")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=float(os.environ.get("GEMINI_REQUEST_DELAY_SECONDS", "13")),
        help="Seconds to wait between Gemini requests. Use 13+ for the free tier.",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Retry count for Gemini 429 rate limits.")
    parser.add_argument("--force", action="store_true", help="Reprocess images even when --append finds them in the output CSV.")
    parser.add_argument("--dry-run", action="store_true", help="List images and output path without calling Gemini.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return extract(args)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
