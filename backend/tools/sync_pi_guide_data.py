from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PI_TARGET = "uma-pi"
DEFAULT_REMOTE_DIR = "/home/katao/uma-guide-data/extracted"
DEFAULT_LOCAL_DIR = REPO_ROOT / "backend" / "data" / "guide_import" / "extracted"
DEFAULT_CHECKED_CSV = REPO_ROOT / "backend" / "data" / "guide_import" / "checked" / "race_skills_checked.csv"
DEFAULT_RACE_DATA = REPO_ROOT / "frontend" / "src" / "data" / "race_data.json"


def run_command(command: list[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"$ {printable}")
    if dry_run:
        return
    subprocess.run(command, cwd=cwd, check=True)


def sync_from_pi(args: argparse.Namespace) -> None:
    args.local_dir.mkdir(parents=True, exist_ok=True)
    remote_source = f"{args.pi_target}:{args.remote_dir.rstrip('/')}/."
    run_command(
        ["scp", "-r", remote_source, str(args.local_dir)],
        dry_run=args.dry_run,
    )


def check_and_build(args: argparse.Namespace) -> None:
    input_glob = str(args.local_dir / "**" / "*.csv")

    check_command = [
        sys.executable,
        str(REPO_ROOT / "backend" / "tools" / "check_extracted_skills.py"),
        "--input-glob",
        input_glob,
        "--write-fixed",
        str(args.checked_csv),
    ]
    if args.drop_review_unknown:
        check_command.append("--drop-review-unknown")

    run_command(check_command, cwd=REPO_ROOT, dry_run=args.dry_run)

    build_command = [
        sys.executable,
        str(REPO_ROOT / "backend" / "tools" / "build_race_data.py"),
        "--input",
        str(args.checked_csv),
        "--output",
        str(args.race_data),
    ]
    if args.include_draft:
        build_command.append("--include-draft")
    if args.replace:
        build_command.append("--replace")

    run_command(build_command, cwd=REPO_ROOT, dry_run=args.dry_run)

    if args.run_next_build:
        run_command(["npm.cmd", "run", "build"], cwd=REPO_ROOT / "frontend", dry_run=args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync trainer-guide CSV files from Raspberry Pi, then rebuild race_data.json."
    )
    parser.add_argument("--pi-target", default=DEFAULT_PI_TARGET, help="SSH target. Example: uma-pi")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="Remote extracted CSV directory.")
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_DIR, help="Local CSV destination.")
    parser.add_argument("--checked-csv", type=Path, default=DEFAULT_CHECKED_CSV, help="Checked CSV output.")
    parser.add_argument("--race-data", type=Path, default=DEFAULT_RACE_DATA, help="race_data.json output.")
    parser.add_argument("--skip-copy", action="store_true", help="Use local CSV files without scp from Pi.")
    parser.add_argument("--ready-only", action="store_true", help="Only include rows whose status is ready/approved.")
    parser.add_argument("--replace", action="store_true", help="Replace race_data.json instead of merging into it.")
    parser.add_argument("--drop-review-unknown", action="store_true", help="Drop unknown skills when writing the checked CSV.")
    parser.add_argument("--run-next-build", action="store_true", help="Run npm run build after generating JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.include_draft = not args.ready_only

    try:
        if not args.skip_copy:
            sync_from_pi(args)
        check_and_build(args)
    except subprocess.CalledProcessError as error:
        return error.returncode
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
