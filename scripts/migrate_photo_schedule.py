from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shahaf_sync.github import GistClient
from shahaf_sync.ics import parse_calendar
from shahaf_sync.photo_schedule import rebuild_calendar


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace the recurring Gist timetable with the Shahaf screenshot baseline."
    )
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument(
        "--write",
        action="store_true",
        help="Patch the configured Gist; without this flag only show the migration summary.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config_path = args.config if args.config.is_absolute() else root / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    client = GistClient(token=os.environ.get("GIST_TOKEN"))
    original = client.read_file(config["gist_id"], config["gist_filename"])
    calendar = parse_calendar(original.content)
    rebuilt = rebuild_calendar(calendar)
    updated = rebuilt.render()

    old_recurring = sum(event.is_recurring for event in calendar.events)
    new_recurring = sum(event.is_recurring for event in rebuilt.events)
    print(
        f"Photo baseline: recurring {old_recurring} -> {new_recurring}; "
        f"total events {len(calendar.events)} -> {len(rebuilt.events)}; "
        f"changed={'yes' if updated != original.content else 'no'}"
    )
    if args.write:
        client.update_file(config["gist_id"], config["gist_filename"], updated)
        print("Gist updated: only the configured ICS file was patched.")
    else:
        print("Dry run only: pass --write to patch the Gist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
