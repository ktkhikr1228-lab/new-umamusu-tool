from __future__ import annotations

import argparse
import json
import shutil
import sys
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
    "friend_events": {
        "manifest_key": "training_events/friend",
        "path": "training_events/friend",
        "argument": "friend_events",
    },
    "event_rewards": {
        "manifest_key": "dict/evrew",
        "path": "dict/evrew",
        "argument": "event_rewards",
    },
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


def make_factor_skill_aliases(skills_data: Any) -> dict[str, str]:
    records = as_records(skills_data)
    skills_by_id = {
        str(skill_id): skill
        for skill in records
        if (skill_id := pick(skill, ("id", "skill_id", "skillId"))) not in (None, "")
    }
    aliases: dict[str, str] = {}

    for skill in records:
        if str(skill.get("rarity", "")) != "2":
            continue

        source_name = str(
            pick(
                skill,
                ("jpname", "name_jp", "name_ja", "name_jpn", "name", "title_ja"),
            )
        ).strip()
        if not source_name:
            continue

        candidates: list[str] = []
        for version_id in normalize_skill_ids(skill.get("versions", [])):
            version = skills_by_id.get(version_id)
            if not version or str(version.get("rarity", "")) != "1":
                continue
            target_name = str(
                pick(
                    version,
                    ("jpname", "name_jp", "name_ja", "name_jpn", "name", "title_ja"),
                )
            ).strip()
            if (
                target_name
                and target_name != source_name
                and not target_name.endswith(("×", "✕"))
                and target_name not in candidates
            ):
                candidates.append(target_name)

        if not candidates:
            continue

        # 「○」「◎」の両方がある場合は、因子として扱う「○」を優先する。
        aliases[source_name] = next(
            (name for name in candidates if name.endswith("○")),
            candidates[0],
        )

    return dict(sorted(aliases.items()))


def make_rare_skill_names(skills_data: Any, skill_map: dict[str, str]) -> set[str]:
    # GameTora skill rarity 2 uses the gold style; support rarity is unrelated.
    return set(resolve_skills([
        str(skill["id"]) for skill in as_records(skills_data)
        if str(skill.get("rarity")) == "2" and "id" in skill
    ], skill_map))


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


# GameTora module 41374 decodes reward references by subtracting
# tasty (5) + sushi (31). See backend/tests/fixtures/README.md.
EVENT_REWARD_OFFSET = 36


def extract_array_event_skill_ids(events: Any, rewards: Any) -> list[str]:
    """Decode current JP outcomes only; numeric references index dict/evrew.

    Event: [name_ref, [[choice_ref, [reward_ref, ...]], ...], story_id, ...].
    Extra fields contain history/metadata, not additional current outcomes.
    """
    if not isinstance(rewards, list):
        raise ValueError("Array training events require --event-rewards (dict/evrew).")
    result: list[str] = []
    for event in events:
        if not isinstance(event, list) or len(event) < 2 or not isinstance(event[1], list):
            raise ValueError("Invalid GameTora array event.")
        for choice in event[1]:
            if not isinstance(choice, list) or len(choice) < 2 or not isinstance(choice[1], list):
                raise ValueError("Invalid GameTora array choice.")
            for reference in choice[1]:
                if type(reference) is not int or not 0 <= reference - EVENT_REWARD_OFFSET < len(rewards):
                    raise ValueError(f"Invalid GameTora reward reference: {reference!r}")
                reward = rewards[reference - EVENT_REWARD_OFFSET]
                if isinstance(reward, list) and len(reward) >= 3 and reward[0] == "sk":
                    result.extend(normalize_scalar_skill_id(reward[2]))
    return result


def make_event_skill_map(
    event_data_list: list[Any],
    skill_map: dict[str, str],
    event_rewards: Any = None,
) -> dict[str, list[str]]:
    event_skill_map: dict[str, list[str]] = {}

    for event_data in event_data_list:
        array_records = []
        if isinstance(event_data, list):
            array_records = [record for record in event_data if isinstance(record, list)]
        for record in array_records:
            if len(record) != 2 or not isinstance(record[1], list):
                raise ValueError("Invalid GameTora card event record.")
            key = str(record[0])
            names = resolve_skills(extract_array_event_skill_ids(record[1], event_rewards), skill_map)
            if names:
                event_skill_map[key] = merge_unique(event_skill_map.get(key, []), names)
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


def select_friend_event(event: Any, card_id: str) -> Any:
    """Apply GameTora module 41374's card override (2) and disabled flag (14).

    History (9) is not traversed. A disabled parent stays disabled after an
    override, matching GameTora's decoded-object merge.
    """
    if not isinstance(event, list) or len(event) < 2:
        raise ValueError("Invalid GameTora friend event.")
    disabled = False
    replacement = None
    for metadata in event[3:]:
        if not isinstance(metadata, list) or not metadata:
            raise ValueError("Invalid GameTora friend event metadata.")
        if metadata[0] == 14:
            disabled = True
        elif metadata[0] == 2:
            if len(metadata) < 2 or not isinstance(metadata[1], list):
                raise ValueError("Invalid GameTora friend event replacement.")
            for variant in metadata[1]:
                if not isinstance(variant, list) or len(variant) != 2:
                    raise ValueError("Invalid GameTora friend event replacement.")
                if str(variant[0]) == card_id and replacement is None:
                    replacement = variant[1]
    if disabled:
        return None
    if replacement is not None:
        return select_friend_event(replacement, card_id)
    return event


def make_friend_event_skill_map(
    friend_data: Any,
    support_cards_data: Any,
    skill_map: dict[str, str],
    event_rewards: Any,
) -> dict[str, list[str]]:
    """Friend records are [char_id, milestones, random_events, outings]."""
    if not isinstance(friend_data, list):
        raise ValueError("Invalid GameTora friend event file.")
    by_character: dict[str, list[Any]] = {}
    for record in friend_data:
        if (not isinstance(record, list) or len(record) != 4
                or not all(isinstance(group, list) for group in record[1:])):
            raise ValueError("Invalid GameTora friend event record.")
        if record[0] is None:
            if any(record[1:]):
                raise ValueError("Nonempty GameTora friend placeholder.")
            continue
        by_character.setdefault(str(record[0]), []).extend(
            event for index, group in enumerate(record[1:]) for event in group
            if not (index == 0 and event is None)
        )

    result: dict[str, list[str]] = {}
    for card in as_records(support_cards_data):
        if normalize_type(pick(card, ("type", "support_type", "supportType"))) != "友人":
            continue
        card_id = str(pick(card, ("support_id", "supportId", "id", "support_card_id", "supportCardId", "card_id", "cardId")))
        character_id = str(pick(card, ("char_id",)))
        if not card_id or character_id not in by_character:
            continue
        names: list[str] = []
        for event in by_character[character_id]:
            selected = select_friend_event(event, card_id)
            if selected is None or selected[1] == "no":
                continue
            names = merge_unique(names, resolve_skills(
                extract_array_event_skill_ids([selected], event_rewards), skill_map
            ))
        # Preserve empty entries to distinguish a present record with no hints.
        result[card_id] = names
    return result


def find_missing_skill_cards(
    cards: list[dict[str, Any]],
    friend_event_skill_map: dict[str, list[str]] | None = None,
) -> list[dict[str, str]]:
    missing = []
    for card in cards:
        if card["skills"]:
            continue
        source_id = card["source_id"]
        reason = "no_resolved_skills"
        if (card["type"] == "友人" and friend_event_skill_map is not None
                and source_id not in friend_event_skill_map):
            reason = "friend_events_not_in_source"
        missing.append({"source_id": source_id, "name": card["name"], "reason": reason})
    return missing


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
    rare_skill_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    event_skill_map = event_skill_map or {}
    rare_skill_names = rare_skill_names or set()
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
                "rare_skills": [name for name in all_skills if name in rare_skill_names],
            }
        )
    return cards


def apply_reviewed_skill_supplements(
    cards: list[dict[str, Any]],
    supplements: Any,
    skill_map: dict[str, str],
    rare_skill_names: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply reviewed records only while the upstream card has no skills.

    This file is maintained through reviewable PRs, never generated from search.
    Nonempty upstream skills take precedence and differences are reported.
    """
    if (not isinstance(supplements, dict) or supplements.get("schema_version") != 1
            or not isinstance(supplements.get("cards"), list)):
        raise ValueError("Invalid reviewed skill supplements file.")
    result = [{**card} for card in cards]
    by_id = {card["source_id"]: card for card in result}
    seen = set()
    report = []
    for entry in supplements["cards"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("source_id"), str):
            raise ValueError("Invalid reviewed skill supplement record.")
        card_id = entry["source_id"]
        if card_id in seen:
            raise ValueError(f"Duplicate skill supplement: {card_id}")
        seen.add(card_id)
        card = by_id.get(card_id)
        if card is None:
            continue
        if any(entry.get(key) != card.get(key) for key in ("char", "card", "rarity", "type")):
            raise ValueError(f"Skill supplement card identity mismatch: {card_id}")
        sources = entry.get("sources")
        if (not entry.get("reviewed_on") or not isinstance(sources, list) or not sources
                or any(not isinstance(url, str) or not url.startswith("https://") for url in sources)):
            raise ValueError(f"Skill supplement requires review provenance: {card_id}")
        if not isinstance(entry.get("skills"), list) or not entry["skills"]:
            raise ValueError(f"Empty reviewed skill supplement: {card_id}")
        names = []
        for skill in entry["skills"]:
            if (not isinstance(skill, dict) or not isinstance(skill.get("id"), str)
                    or not skill.get("name") or skill_map.get(skill["id"]) != skill["name"]):
                raise ValueError(f"Unknown/mismatched supplement skill: {card_id}")
            if skill["name"] in names:
                raise ValueError(f"Duplicate supplement skill: {card_id}")
            names.append(skill["name"])
        if card["skills"]:
            status = "source_matches" if set(card["skills"]) == set(names) else "source_differs"
            report.append({"source_id": card_id, "status": status,
                           "only_in_supplement": sorted(set(names) - set(card["skills"])),
                           "only_in_source": sorted(set(card["skills"]) - set(names))})
            continue
        card["skills"] = names
        card["rare_skills"] = [name for name in names if name in rare_skill_names]
        report.append({"source_id": card_id, "status": "applied", "skills": names})
    return result, report


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
    parser.add_argument("--skill-supplements", type=Path,
        default=Path(__file__).resolve().parents[1] / "data/reviewed_skill_supplements.json",
        help="Reviewed fallback skills; applied only to upstream-empty cards.")
    parser.add_argument("--support-cards", type=Path)
    parser.add_argument("--skills", type=Path)
    parser.add_argument("--ssr-events", type=Path)
    parser.add_argument("--sr-events", type=Path)
    parser.add_argument("--friend-events", type=Path, help="GameTora training_events/friend JSON.")
    parser.add_argument("--event-rewards", type=Path, help="GameTora dict/evrew JSON for array events.")
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
        "--factor-skill-aliases-json",
        default=Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "data"
        / "factor_skill_aliases.json",
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
        args.friend_events = args.friend_events or downloaded["friend_events"]
        args.event_rewards = args.event_rewards or downloaded["event_rewards"]

    if not args.support_cards or not args.skills:
        raise SystemExit(
            "--support-cards and --skills are required unless --download-latest is used."
        )

    support_cards_data = read_json(args.support_cards)
    skills_data = read_json(args.skills)
    skill_map = make_skill_map(skills_data)
    factor_skill_aliases = make_factor_skill_aliases(skills_data)
    event_paths = [path for path in [args.ssr_events, args.sr_events, *args.event_skills] if path]
    event_data_list = [read_json(path) for path in event_paths]
    event_rewards = read_json(args.event_rewards) if args.event_rewards else None
    event_skill_map = make_event_skill_map(event_data_list, skill_map, event_rewards)
    friend_event_skill_map = None
    if args.friend_events:
        friend_event_skill_map = make_friend_event_skill_map(
            read_json(args.friend_events), support_cards_data, skill_map, event_rewards
        )
        for card_id, names in friend_event_skill_map.items():
            event_skill_map[card_id] = merge_unique(event_skill_map.get(card_id, []), names)
    rare_skill_names = make_rare_skill_names(skills_data, skill_map)
    imported_cards = convert_support_cards(
        support_cards_data, skill_map, event_skill_map, rare_skill_names
    )

    missing_skill_cards = find_missing_skill_cards(imported_cards, friend_event_skill_map)
    for card in missing_skill_cards:
        print(f"WARNING: GameTora has no resolved skills: {card['source_id']} {card['name']} "
              f"({card['reason']})", file=sys.stderr)

    # Keep missing_skill_cards based on raw GameTora data, so research continues
    # even while reviewed supplements make the frontend usable.
    imported_cards, supplement_report = apply_reviewed_skill_supplements(
        imported_cards, read_json(args.skill_supplements), skill_map, rare_skill_names
    )
    for item in supplement_report:
        if item["status"] == "source_differs":
            print(f"WARNING: Upstream skills differ from supplement: {item['source_id']}", file=sys.stderr)

    existing_cards = [] if args.replace or not args.cards_json.exists() else read_json(args.cards_json)
    if not isinstance(existing_cards, list):
        raise ValueError(f"{args.cards_json} must contain a JSON array.")

    merged_cards, added, updated = merge_cards(existing_cards, imported_cards, args.replace)

    if args.cards_json.exists() and not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = args.cards_json.with_name(f"{args.cards_json.stem}.backup-{timestamp}.json")
        shutil.copy2(args.cards_json, backup_path)

    write_json(args.cards_json, merged_cards)
    write_json(args.factor_skill_aliases_json, factor_skill_aliases)
    print(
        json.dumps(
            {
                "cards_json": str(args.cards_json),
                "factor_skill_aliases_json": str(args.factor_skill_aliases_json),
                "skill_map_count": len(skill_map),
                "factor_skill_alias_count": len(factor_skill_aliases),
                "event_file_count": len(event_paths) + int(args.friend_events is not None),
                "event_card_count": len(event_skill_map),
                "friend_event_card_count": len(friend_event_skill_map or {}),
                "missing_skill_card_count": len(missing_skill_cards),
                "missing_skill_cards": missing_skill_cards,
                "skill_supplement_count": sum(item["status"] == "applied" for item in supplement_report),
                "skill_supplements": supplement_report,
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
