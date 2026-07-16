"""GameToraのスキルデータ更新を監視し、更新があればマスターを再生成してDiscord通知する。

ラズパイ用(自己完結・リポジトリ不要)。配置先: /home/katao/uma-tool-automation/

cron例(15分おき):
  */15 * * * * cd /home/katao/uma-tool-automation && /usr/bin/python3 gametora_skills_watch.py >> logs/gametora_skills_watch.log 2>&1

動作:
  1. manifestを取得し、skillsのハッシュを前回(state/gametora_skills_state.json)と比較
  2. 変化がなければ何もせず終了(通信はmanifest数KBのみ)
  3. 変化があればskills JSONを取得し、skill_master.jsonを再生成
  4. 追加/削除されたスキル名をDiscordに通知

PCへの反映:
  scp katao@uma-pi:/home/katao/uma-guide-data/skill_master.json frontend/src/data/
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

MANIFEST_URL = "https://gametora.com/data/manifests/umamusume.json"
DATA_BASE_URL = "https://gametora.com/data/umamusume"
USER_AGENT = "Mozilla/5.0 uma-tool-skills-watch"

AUTOMATION_DIR = Path("/home/katao/uma-tool-automation")
STATE_PATH = AUTOMATION_DIR / "state" / "gametora_skills_state.json"
OUTPUT_PATH = Path("/home/katao/uma-guide-data/skill_master.json")

NAME_KEYS = ("jpname", "name_jp", "name_ja", "name_jpn", "name", "title_ja")

try:
    from discord_sender import send_discord
except Exception:
    send_discord = None


def notify(content: str) -> None:
    if send_discord:
        send_discord(content)
    else:
        print(content)


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def as_records(data) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "skills"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def extract_skill_names(skills_data) -> list[str]:
    names: set[str] = set()
    for skill in as_records(skills_data):
        for key in NAME_KEYS:
            value = skill.get(key)
            if value:
                names.add(str(value).strip())
                break
    return sorted(names)


def format_diff(label: str, values: list[str], limit: int = 20) -> str:
    if not values:
        return ""
    shown = "\n".join(f"- {value}" for value in values[:limit])
    more = f"\n(ほか{len(values) - limit}件)" if len(values) > limit else ""
    return f"\n**{label} {len(values)}件**\n{shown}{more}"


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    try:
        manifest = fetch_json(MANIFEST_URL)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
        # ネットワーク一時障害で毎回通知するとうるさいので、ログのみ
        print(f"manifest取得失敗: {error}")
        return 1

    current_hash = manifest.get("skills")
    if not isinstance(current_hash, str) or not current_hash:
        notify("**【スキル監視】manifestに 'skills' が見つかりません**")
        return 1

    state = load_state()
    previous_hash = state.get("skills_hash")

    if current_hash == previous_hash:
        print(f"変化なし (hash={current_hash})")
        return 0

    if dry_run:
        print(f"変化検知 (dry-run): {previous_hash} -> {current_hash}")
        return 0

    try:
        skills_data = fetch_json(f"{DATA_BASE_URL}/skills.{current_hash}.json")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
        notify(f"**【スキル監視】skillsデータの取得に失敗**\n`{error}`")
        return 1

    names = extract_skill_names(skills_data)
    if not names:
        notify("**【スキル監視】スキル名を抽出できませんでした**\nJSON形式が変わった可能性があります。")
        return 1

    previous_names: set[str] = set()
    if OUTPUT_PATH.exists():
        try:
            previous_names = set(json.loads(OUTPUT_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    added = sorted(set(names) - previous_names)
    removed = sorted(previous_names - set(names))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    state["skills_hash"] = current_hash
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)

    is_first_run = previous_hash is None
    if is_first_run:
        notify(
            "**【スキル監視】初回実行**\n"
            f"- スキル総数: `{len(names)}`\n"
            f"- 出力: `{OUTPUT_PATH}`\n"
            "次回からはデータ更新時のみ通知します。"
        )
    else:
        notify(
            "**【スキル監視】GameToraのスキルデータが更新されました**\n"
            f"- スキル総数: `{len(names)}`"
            f"{format_diff('追加', added)}"
            f"{format_diff('削除', removed)}\n\n"
            "**PCへの反映**\n"
            "```\nscp katao@uma-pi:/home/katao/uma-guide-data/skill_master.json frontend/src/data/\n```"
        )

    print(f"更新: hash {previous_hash} -> {current_hash}, 追加{len(added)} 削除{len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
