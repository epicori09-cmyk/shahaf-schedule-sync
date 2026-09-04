from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


parser = argparse.ArgumentParser(description="Mark managed alarm overrides as published after Pages deploy")
parser.add_argument("--profiles-file", type=Path, required=True)
args = parser.parse_args()
profile_url = os.environ.get("PROFILE_SYNC_URL", "")
parts = urlsplit(profile_url)
url = f"{parts.scheme}://{parts.netloc}/internal/alarm-commands/ack" if parts.scheme and parts.netloc else ""
token = os.environ.get("PROFILE_SYNC_TOKEN", "")
if not url or not token:
    raise SystemExit("PROFILE_SYNC_URL and PROFILE_SYNC_TOKEN must be configured")
try:
    payload = json.loads(args.profiles_file.read_text(encoding="utf-8"))
    profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
    ids = [str(item["alarm_override"]["id"]) for item in profiles if isinstance(item, dict) and isinstance(item.get("alarm_override"), dict) and item["alarm_override"].get("id")]
except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
    raise SystemExit(f"could not read managed profile bundle: {exc}") from exc
if not ids:
    print("No managed alarm overrides to acknowledge")
    raise SystemExit(0)
request = Request(
    url,
    method="POST",
    data=json.dumps({"ids": ids}).encode("utf-8"),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "shahaf-schedule-sync/1.0"},
)
try:
    with urlopen(request, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"profile service returned HTTP {response.status}")
        result = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    raise SystemExit(f"could not acknowledge managed alarm overrides: {exc}") from exc
print(f"Marked {result.get('acknowledged', 0)} managed alarm override(s) as published")
