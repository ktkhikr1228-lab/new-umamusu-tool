"""Validate reviewed CSV requests and merge them into the static race JSON.

No network access, database changes, arbitrary deletions, or draft publishing.
"""
from __future__ import annotations
import argparse
import copy
import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = ROOT / "frontend/src/data/skill_master.json"
TIERS = ("super_recommended", "recommended")
STRATEGIES = {"逃げ", "先行", "差し", "追込"}
TRACKS = "東京|中山|阪神|京都|中京|新潟|札幌|函館|福島|小倉"
READY = {"ready", "approved", "ok", "公開", "確認済み"}
MAX_INPUT_BYTES = 48000
MAX_ROWS = 4000


def unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError(f"Duplicate JSON key: {k}")
        result[k] = v
    return result


def loads(text):
    return json.loads(text, object_pairs_hook=unique_object)


def read(path):
    return loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize(name):
    return name.strip().translate(str.maketrans({"◯": "○", "〇": "○"}))


def event_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("Event must be 1-64 ASCII letters, digits, underscores or hyphens")
    return value


def validate(payload, master):
    if not isinstance(payload, dict) or set(payload) != {"event", "rows"}:
        raise ValueError("Request must contain only event and rows")
    event = event_name(payload["event"])
    if not isinstance(master, list) or not master or not all(isinstance(x, str) and x for x in master):
        raise ValueError("Invalid skill master")
    names = {}
    for name in master:
        canonical = normalize(name)
        if canonical in names and names[canonical] != name:
            raise ValueError("Ambiguous skill names in master")
        names[canonical] = name
    rows = payload["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError(f"Request must have 1-{MAX_ROWS} reviewed rows")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"race", "strategy", "tier", "skill", "status"}:
            raise ValueError("Invalid row fields")
        if not all(isinstance(v, str) for v in row.values()):
            raise ValueError("Row values must be strings")
        if row["status"] != "ready":
            raise ValueError("Only ready rows may be published")
        race, strategy, tier = row["race"], row["strategy"], row["tier"]
        match = re.fullmatch(rf"({TRACKS}) (芝|ダート) ([0-9]{{4}})m", race)
        if not match or not 1000 <= int(match[3]) <= 4000 or int(match[3]) % 100:
            raise ValueError(f"Invalid race condition: {race}")
        if strategy not in STRATEGIES or tier not in TIERS:
            raise ValueError("Unknown strategy or tier")
        skill = names.get(normalize(row["skill"]))
        if skill is None:
            raise ValueError(f"Unknown skill; update/review skill_master.json first: {row['skill']}")
        key = (race, strategy, skill)
        canonical = {**row, "skill": skill}
        if key in result and result[key]["tier"] != tier:
            raise ValueError(f"Conflicting tiers in the same request: {skill}")
        result[key] = canonical
    return {"event": event, "rows": [result[k] for k in sorted(result)]}


def combine(previous, incoming, master):
    current = validate(incoming, master)
    if previous is None:
        return current
    previous = validate(previous, master)
    if previous["event"] != current["event"]:
        raise ValueError("Pending request belongs to another event")
    keyed = {(r["race"], r["strategy"], r["skill"]): r for r in previous["rows"]}
    keyed.update({(r["race"], r["strategy"], r["skill"]): r for r in current["rows"]})
    return validate({"event": current["event"], "rows": list(keyed.values())}, master)


def merge(base, payload):
    if not isinstance(base, dict):
        raise ValueError("Existing race data must be an object")
    data = copy.deepcopy(base)
    added = moved = 0
    for row in payload["rows"]:
        race, strategy, tier, skill = (row[k] for k in ("race", "strategy", "tier", "skill"))
        race_data = data.setdefault(race, {})
        if not isinstance(race_data, dict):
            raise ValueError("Invalid existing race data")
        detail = race_data.setdefault(strategy, {t: [] for t in TIERS})
        if not isinstance(detail, dict):
            raise ValueError("Invalid existing strategy data")
        for t in TIERS:
            detail.setdefault(t, [])
            if not isinstance(detail[t], list) or not all(isinstance(x, str) for x in detail[t]):
                raise ValueError("Invalid existing skill list")
        other = next(t for t in TIERS if t != tier)
        # Preserve all unrelated skills. Only move the explicitly reviewed skill.
        # Match circle variants too, avoiding cross-tier duplicates in legacy data.
        was_other = any(normalize(x) == normalize(skill) for x in detail[other])
        was_target = any(normalize(x) == normalize(skill) for x in detail[tier])
        if not was_other and detail[tier].count(skill) == 1 and sum(normalize(x) == normalize(skill) for x in detail[tier]) == 1:
            continue
        detail[other] = [x for x in detail[other] if normalize(x) != normalize(skill)]
        detail[tier] = [x for x in detail[tier] if normalize(x) != normalize(skill)]
        detail[tier].append(skill)
        added += int(not was_other and not was_target)
        moved += int(was_other)
    return data, {"added": added, "moved": moved, "changed": data != base}


def prepare_csv(path, event, master):
    rows = []
    skipped = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not {"race", "strategy", "tier", "skill", "status"} <= set(reader.fieldnames or []):
            raise ValueError("CSV must contain race, strategy, tier, skill and status")
        for row in reader:
            if row.get("status", "").strip().lower() not in READY:
                skipped += 1
                continue
            rows.append({k: row[k].strip() for k in ("race", "strategy", "tier", "skill") } | {"status": "ready"})
    return validate({"event": event, "rows": rows}, master), skipped


def receive(text, master):
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Request exceeds 48KB; submit smaller reviewed batches")
    return validate(loads(text), master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("prepare")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = subs.add_parser("receive")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--github-output", type=Path)
    p = subs.add_parser("apply")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--pending", type=Path)
    p.add_argument("--data", type=Path, default=ROOT / "frontend/src/data/race_data.json")
    p.add_argument("--pending-output", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        master = read(args.master)
        if args.command == "prepare":
            payload, skipped = prepare_csv(args.input, args.event, master)
            if len((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()) > MAX_INPUT_BYTES:
                raise ValueError("Request exceeds 48KB; submit smaller reviewed batches")
            write(args.output, payload)
            print(json.dumps({"event": payload["event"], "ready_rows": len(payload["rows"]), "skipped_rows": skipped}, ensure_ascii=False))
        elif args.command == "receive":
            payload = receive(os.environ.get("REVIEWED_RACE_PAYLOAD", ""), master)
            write(args.output, payload)
            if args.github_output:
                with args.github_output.open("a") as f:
                    f.write(f"event={payload['event']}\nbranch=data/reviewed-race-{payload['event']}\n")
        else:
            incoming = validate(read(args.input), master)
            pending = read(args.pending) if args.pending and args.pending.exists() else None
            payload = combine(pending, incoming, master)
            data, result = merge(read(args.data), payload)
            args.summary.write_text(
                f"確認済みレーススキル更新: {payload['event']}\n\n"
                f"確認済み行: {len(payload['rows'])} / 追加: {result['added']} / 区分移動: {result['moved']}\n\n"
                "未確認・除外行は含めていません。既存の無関係なレース・スキルは保持します。\n"
                "マージ後にVercelの自動デプロイで反映されます。自動マージはしません。\n", encoding="utf-8")
            if result["changed"]:
                write(args.data, data)
                write(args.pending_output, payload)
            if args.github_output:
                with args.github_output.open("a") as f:
                    f.write(f"changed={str(result['changed']).lower()}\n")
            print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Publication validation failed: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
