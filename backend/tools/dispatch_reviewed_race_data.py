"""Send a validated reviewed-data request to GitHub Actions, never merge a PR."""
from __future__ import annotations
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from publish_reviewed_race_data import read, event_name, MAX_INPUT_BYTES

REPO = "ktkhikr1228-lab/new-umamusu-tool"
WORKFLOW = "publish-reviewed-race-data.yml"
API = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"


def dispatch(payload, token, ref="main", opener=urllib.request.urlopen):
    # Full master validation also runs inside the workflow on main.
    if not isinstance(payload, dict) or set(payload) != {"event", "rows"}:
        raise ValueError("Expected a prepared request with event and rows")
    event_name(payload["event"])
    rows = payload["rows"]
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or r.get("status") != "ready" for r in rows):
        raise ValueError("Only nonempty reviewed requests may be sent")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode()) > MAX_INPUT_BYTES:
        raise ValueError("Request exceeds 48KB")
    if not token:
        return {"event": payload["event"], "rows": len(rows), "payload_bytes": len(serialized.encode()), "sent": False}
    request = urllib.request.Request(API, data=json.dumps({"ref": ref, "inputs": {"payload": serialized}}, ensure_ascii=False).encode(),
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "uma-reviewed-race-dispatch"}, method="POST")
    with opener(request, timeout=30) as response:
        if response.status != 204:
            raise RuntimeError(f"Unexpected GitHub status {response.status}")
    return {"event": payload["event"], "rows": len(rows), "sent": True,
            "workflow": f"https://github.com/{REPO}/actions/workflows/{WORKFLOW}",
            "note": "Request accepted; PR creation and build completion are not yet confirmed"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--token-file", type=Path, default=Path.home()/".config/uma-tool/github_token")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        payload = read(args.input)
        token = None if args.dry_run else args.token_file.read_text().strip()
        if token == "":
            raise ValueError("Configured GitHub token is empty")
        print(json.dumps(dispatch(payload, token), ensure_ascii=False, indent=2))
        return 0
    except urllib.error.HTTPError as error:
        print(f"GitHub dispatch rejected: HTTP {error.code}. Check workflow is on main and Actions write access is configured.", file=sys.stderr)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Dispatch failed: {error}", file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
