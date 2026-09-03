from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
url = os.environ.get("PROFILE_SYNC_URL", "")
token = os.environ.get("PROFILE_SYNC_TOKEN", "")
args.output.parent.mkdir(parents=True, exist_ok=True)
if not url and not token:
    args.output.write_text('{"profiles": []}\n', encoding="utf-8")
    raise SystemExit(0)
if not url or not token:
    raise SystemExit("PROFILE_SYNC_URL and PROFILE_SYNC_TOKEN must be configured together")
request = Request(
    url,
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "shahaf-schedule-sync/1.0",
    },
)
try:
    with urlopen(request, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"profile service returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
except (HTTPError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"could not fetch managed profiles: {exc}") from exc
if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
    raise SystemExit("profile service returned an invalid bundle")
args.output.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
