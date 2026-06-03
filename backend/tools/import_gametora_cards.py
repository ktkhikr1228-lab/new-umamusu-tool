from __future__ import annotations

import argparse
import json
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


TYPE_LABELS = {
    "speed": "スピード",
    "stamina": "スタミナ",
    "power": "パワー",
    "guts": "根性",
    "intelligence": "賢さ",
    "wisdom": "賢さ",
    "friend": "友人",
    "group": "グループ",
}

RARITY_LABELS = {
    1: "R",
    2: "SR",
    3: "SSR",
    "1": "R",
    "2": "SR",
    "3": "SSR",
    "ssr": "SSR",
    "sr": "SR",
    "r": "R",
    "SSR": "SSR",
    "SR": "SR",
    "R": "R",
}

DEFAULT_MANIFEST_URLS = (
    "https://gametora.com/data/manifests/umamusume.json",
)

GAMETORA_DATA_BASE_URL = "https://gametora.com/data/umamusume"

DOWNLOAD_TARGETS = {
    "support_cards": {
        "manifest_key": "support-cards",
        "path": "support-cards",
        "argument": "support_cards",
    },
    "skills": {
        "manifest_key": "skills",
        "path": "skills",
        "argument": "skills",
    },
    "ssr_events": {
        "manifest_key": "training_events/ssr",
        "path": "training_events/ssr",
        "argument": "ssr_events",
    },
    "sr_events": {
        "manifest_key": "training_events/sr",
        "path": "training_events/sr",
        "argument": "sr_events",
    },
}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def request_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://gametora.com/umamusume",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def read_json_url(url: str) -> Any:
    return json.loads(request_url(url).decode("utf-8"))


def download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(request_url(url))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def find_manifest_value(data: Any, manifest_key: str) -> str | None:
    if isinstance(data, dict):
        value = data.get(manifest_key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for nested_key in ("hash", "version", "file", "value"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str):
                    return nested_value

        if "/" in manifest_key:
            current: Any = data
            for part in manifest_key.split("/"):
                if not isinstance(current, dict):
                    break
                current = current.get(part)
            if isinstance(current, str):
                return current
            if isinstance(current, dict):
                for nested_key in ("hash", "version", "file", "value"):
                    nested_value = current.get(nested_key)
                    if isinstance(nested_value, str):
                        return nested_value

        for nested_value in data.values():
            found = find_manifest_value(nested_value, manifest_key)
            if found:
                return found
    return None


def fetch_manifest(manifest_urls: list[str]) -> tuple[Any, str]:
    errors: list[str] = []
    for url in manifest_urls:
        try:
            return read_json_url(url), url
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
            errors.append(f"{url}: {error}")
    raise RuntimeError("Failed to fetch GameTora manifest:\n" + "\n".join(errors))


def build_data_url(relative_path: str, manifest_value: str) -> tuple[str, str]:
    value = manifest_value.strip()
    if value.startswith(("http://", "https://")):
        return value, Path(value.split("?", 1)[0]).name

    if value.endswith(".json"):
        file_path = value.lstrip("/")
        if not file_path.startswith("umamusume/"):
            file_path = f"umamusume/{file_path}"
        return f"https://gametora.com/data/{file_path}", Path(file_path).name

    file_name = f"{Path(relative_path).name}.{value}.json"
    return f"{GAMETORA_DATA_BASE_URL}/{relative_path}.{value}.json", file_name


def download_latest_gametora_files(
    download_dir: Path,
    manifest_urls: list[str],
) -> dict[str, Path]:
    manifest_data, manifest_url = fetch_manifest(manifest_urls)
    downloaded: dict[str, Path] = {}

    for target_name, target in DOWNLOAD_TARGETS.items():
        hash_value = find_manifest_value(manifest_data, target["manifest_key"])
        if not hash_value:
            raise RuntimeError(
                f"Manifest {manifest_url} did not contain {target['manifest_key']}."
            )

        relative_path = target["path"]
        url, file_name = build_data_url(relative_path, hash_value)
        output_path = download_dir / file_name
        download_file(url, output_path)
        downloaded[target["argument"]] = output_path

    return downloaded


def as_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "support_cards", "skills"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [
            {"id": key, **value} if isinstance(value, dict) else {"id": key, "value": value}
            for key, value in data.items()
        ]
    return []


def pick(record: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return default


def make_skill_map(skills_data: Any) -> dict[str, str]:
    skill_map: dict[str, str] = {}
    for skill in as_records(skills_data):
        skill_id = pick(skill, ("id", "skill_id", "skillId"))
        skill_name = pick(
            skill,
            ("jpname", "name_jp", "name_ja", "name_jpn", "name", "title_ja"),
        )
        if skill_id not in (None, "") and skill_name:
            skill_map[str(skill_id)] = str(skill_name)
    return skill_map


def normalize_skill_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            skill_id = pick(item, ("id", "skill_id", "skillId"))
        else:
            skill_id = item
        if skill_id not in (None, ""):
            result.append(str(skill_id))
    return result


def extract_support_hint_skill_ids(card: dict[str, Any]) -> list[str]:
    skill_ids = normalize_skill_ids(
        pick(card, ("hint_skills", "hintSkills", "skills"), [])
    )
    hints = card.get("hints")
    if isinstance(hints, dict):
        skill_ids.extend(
            normalize_skill_ids(
                pick(hints, ("hint_skills", "hintSkills", "skills"), [])
            )
        )
    return skill_ids


def resolve_skills(skill_ids: list[str], skill_map: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for skill_id in skill_ids:
        name = skill_map.get(str(skill_id))
        if name and name not in seen:
            resolved.append(name)
            seen.add(name)
    return resolved


def merge_unique(left: list[str], right: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def normalize_scalar_skill_id(value: Any) -> list[str]:
    if isinstance(value, (str, int)):
        return [str(value)]
    return []


def extract_skill_ids_from_event(value: Any, inside_skill_field: bool = False) -> list[str]:
    skill_ids: list[str] = []

    if inside_skill_field:
        if isinstance(value, list):
            for item in value:
                skill_ids.extend(normalize_skill_ids([item]))
                skill_ids.extend(extract_skill_ids_from_event(item, True))
            return skill_ids
        if isinstance(value, dict):
            direct_id = pick(value, ("id", "skill_id", "skillId"))
            if direct_id not in (None, ""):
                skill_ids.append(str(direct_id))
            for nested_value in value.values():
                skill_ids.extend(extract_skill_ids_from_event(nested_value, True))
            return skill_ids
        return normalize_scalar_skill_id(value)

    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_is_skill = "skill" in str(key).lower()
            skill_ids.extend(extract_skill_ids_from_event(nested_value, key_is_skill))
    elif isinstance(value, list):
        for item in value:
            skill_ids.extend(extract_skill_ids_from_event(item, False))

    return skill_ids


def make_event_skill_map(event_data_list: list[Any], skill_map: dict[str, str]) -> dict[str, list[str]]:
    event_skill_map: dict[str, list[str]] = {}

    for event_data in event_data_list:
        for event_record in as_records(event_data):
            card_id = pick(
                event_record,
                ("support_card_id", "supportCardId", "card_id", "cardId", "support_id", "supportId", "id"),
            )
            if card_id in (None, ""):
                continue

            event_skill_ids = extract_skill_ids_from_event(event_record)
            event_skills = resolve_skills(event_skill_ids, skill_map)
            if not event_skills:
                continue

            key = str(card_id)
            event_skill_map[key] = merge_unique(event_skill_map.get(key, []), event_skills)

    return event_skill_map


def normalize_type(value: Any) -> str:
    text = str(value or "").strip()
    return TYPE_LABELS.get(text.lower(), text)


def normalize_rarity(value: Any) -> str:
    return RARITY_LABELS.get(value, RARITY_LABELS.get(str(value), str(value or "")))


def normalize_card_title(card_title: str) -> str:
    title = card_title.strip()
    if (
        (title.startswith("[") and title.endswith("]"))
        or (title.startswith("［") and title.endswith("］"))
    ):
        return title[1:-1].strip()
    return title


def build_card_name(card_title: str, character_name: str) -> str:
    title = normalize_card_title(card_title)
    character = character_name.strip()
    return f"［{title}］{character}"


def convert_support_cards(
    support_cards_data: Any,
    skill_map: dict[str, str],
    event_skill_map: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    event_skill_map = event_skill_map or {}
    cards: list[dict[str, Any]] = []
    for raw_card in as_records(support_cards_data):
        source_id = pick(
            raw_card,
            ("support_id", "supportId", "id", "support_card_id", "supportCardId", "card_id", "cardId"),
        )
        character = str(
            pick(raw_card, ("name_jp", "name_ja", "name_jpn", "chara_name", "character"))
        ).strip()
        card_title = str(
            pick(raw_card, ("title_ja", "title_jp", "title", "card_name", "name"))
        ).strip()
        if not character or not card_title:
            continue

        hint_skill_ids = extract_support_hint_skill_ids(raw_card)
        rare_skill_ids = normalize_skill_ids(
            pick(raw_card, ("rare_skills", "rareSkills", "event_skills", "eventSkills"), [])
        )
        all_skills = resolve_skills(hint_skill_ids, skill_map)
        all_skills = merge_unique(all_skills, resolve_skills(rare_skill_ids, skill_map))
        if source_id not in (None, ""):
            all_skills = merge_unique(all_skills, event_skill_map.get(str(source_id), []))

        cards.append(
            {
                "id": 0,
                "source_id": str(source_id) if source_id not in (None, "") else "",
                "name": build_card_name(card_title, character),
                "char": character,
                "card": normalize_card_title(card_title),
                "rarity": normalize_rarity(pick(raw_card, ("rarity", "rare"))),
                "type": normalize_type(pick(raw_card, ("type", "support_type", "supportType"))),
                "skills": all_skills,
                "rare_skills": [],
            }
        )
    return cards


def merge_cards(
    existing_cards: list[dict[str, Any]],
    imported_cards: list[dict[str, Any]],
    replace: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    if replace:
        result = []
        for card in imported_cards:
            card_id = card.get("source_id") if str(card.get("source_id", "")).isdigit() else card.get("id", 0)
            result.append({**card, "id": int(card_id) if str(card_id).isdigit() else 0})
        return result, len(result), 0

    result = list(existing_cards)
    existing_by_source = {}
    existing_by_name = {}
    used_ids = set()
    for index, card in enumerate(result):
        card_id = str(card.get("id", ""))
        source_id = str(card.get("source_id") or card.get("support_id") or "")
        name = build_card_name(str(card.get("card", "")), str(card.get("char", "")))
        existing_name = str(card.get("name", ""))
        if card_id:
            used_ids.add(card_id)
            existing_by_source.setdefault(card_id, index)
        if source_id:
            existing_by_source.setdefault(source_id, index)
        if name:
            existing_by_name.setdefault(name, index)
        if existing_name:
            existing_by_name.setdefault(existing_name, index)

    next_id = max(
        [int(card.get("id", 0)) for card in result if str(card.get("id", "")).isdigit()]
        or [0]
    ) + 1

    added = 0
    updated = 0
    for card in imported_cards:
        name = str(card.get("name", ""))
        source_id = str(card.get("source_id", ""))
        index = existing_by_source.get(source_id) if source_id else None
        if index is None:
            index = existing_by_name.get(name)

        if index is not None:
            result[index] = {**result[index], **card, "id": result[index].get("id", next_id)}
            if source_id:
                existing_by_source[source_id] = index
            existing_by_name[name] = index
            updated += 1
            continue

        if source_id.isdigit() and source_id not in used_ids:
            card_id = int(source_id)
        else:
            while str(next_id) in used_ids:
                next_id += 1
            card_id = next_id
            next_id += 1

        result.append({**card, "id": card_id})
        existing_by_name[name] = len(result) - 1
        if source_id:
            existing_by_source[source_id] = len(result) - 1
        used_ids.add(str(card_id))
        added += 1

    return result, added, updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import GameTora support-cards and skills JSON into cards.json."
    )
    parser.add_argument("--support-cards", type=Path)
    parser.add_argument("--skills", type=Path)
    parser.add_argument("--ssr-events", type=Path)
    parser.add_argument("--sr-events", type=Path)
    parser.add_argument(
        "--download-latest",
        action="store_true",
        help="Download latest GameTora JSON files before importing.",
    )
    parser.add_argument(
        "--manifest-url",
        action="append",
        default=[],
        help="Override/add GameTora manifest URL. Can be specified multiple times.",
    )
    parser.add_argument(
        "--download-dir",
        default=Path(__file__).resolve().parents[1] / "data" / "import",
        type=Path,
    )
    parser.add_argument(
        "--event-skills",
        nargs="*",
        default=[],
        type=Path,
        help="Additional GameTora training event JSON files.",
    )
    parser.add_argument(
        "--cards-json",
        default=Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "cards.json",
        type=Path,
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace cards.json instead of merging/updating by card name.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup before writing cards.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    downloaded: dict[str, Path] = {}
    if args.download_latest:
        downloaded = download_latest_gametora_files(
            args.download_dir,
            args.manifest_url or list(DEFAULT_MANIFEST_URLS),
        )
        args.support_cards = args.support_cards or downloaded["support_cards"]
        args.skills = args.skills or downloaded["skills"]
        args.ssr_events = args.ssr_events or downloaded["ssr_events"]
        args.sr_events = args.sr_events or downloaded["sr_events"]

    if not args.support_cards or not args.skills:
        raise SystemExit(
            "--support-cards and --skills are required unless --download-latest is used."
        )

    support_cards_data = read_json(args.support_cards)
    skills_data = read_json(args.skills)
    skill_map = make_skill_map(skills_data)
    event_paths = [path for path in [args.ssr_events, args.sr_events, *args.event_skills] if path]
    event_data_list = [read_json(path) for path in event_paths]
    event_skill_map = make_event_skill_map(event_data_list, skill_map)
    imported_cards = convert_support_cards(support_cards_data, skill_map, event_skill_map)

    existing_cards = [] if args.replace or not args.cards_json.exists() else read_json(args.cards_json)
    if not isinstance(existing_cards, list):
        raise ValueError(f"{args.cards_json} must contain a JSON array.")

    merged_cards, added, updated = merge_cards(existing_cards, imported_cards, args.replace)

    if args.cards_json.exists() and not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = args.cards_json.with_name(f"{args.cards_json.stem}.backup-{timestamp}.json")
        shutil.copy2(args.cards_json, backup_path)

    write_json(args.cards_json, merged_cards)
    print(
        json.dumps(
            {
                "cards_json": str(args.cards_json),
                "skill_map_count": len(skill_map),
                "event_file_count": len(event_paths),
                "event_card_count": len(event_skill_map),
                "imported_count": len(imported_cards),
                "added_count": added,
                "updated_count": updated,
                "total_count": len(merged_cards),
                "downloaded_files": {
                    key: str(path) for key, path in downloaded.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
