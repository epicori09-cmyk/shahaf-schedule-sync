from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
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
payload = None
last_error: Exception | None = None
for attempt in range(1, 5):
    try:
        with urlopen(request, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"profile service returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        break
    except HTTPError as exc:
        last_error = exc
        # Authentication and request errors will not heal with a retry.
        if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
            break
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        try:
            delay = min(30, max(1, int(retry_after))) if retry_after else min(2 ** (attempt - 1), 8)
        except ValueError:
            delay = min(2 ** (attempt - 1), 8)
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        last_error = exc
        # A malformed response is usually transient at this boundary; the
        # schema check below still fails closed after all attempts.
        delay = min(2 ** (attempt - 1), 8)
    if attempt < 4:
        print(f"Managed profile fetch attempt {attempt}/4 failed; retrying in {delay}s.")
        time.sleep(delay)
if payload is None:
    raise SystemExit(f"could not fetch managed profiles after 4 attempts: {last_error}") from last_error
if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
    raise SystemExit("profile service returned an invalid bundle")
args.output.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
