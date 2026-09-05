from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from shahaf_sync.alexa import (
    AlexaApiError,
    build_wake_plan,
    delete_reminder,
    list_reminders,
    send_reminder_request,
)


MARKER = "School schedule wake-up."


def fetch_schedule(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "shahaf-schedule-sync/0.1"})
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("schedule endpoint did not return an object")
    return data


def find_managed_reminder(reminders: list[dict]) -> dict | None:
    matches = []
    for reminder in reminders:
        try:
            content = reminder["alertInfo"]["spokenInfo"]["content"]
            text = content[0].get("text", "")
            if text.startswith(MARKER):
                matches.append(reminder)
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
    return sorted(matches, key=lambda item: item.get("updatedTime", ""), reverse=True)[0] if matches else None


def main() -> int:
    schedule_url = os.environ.get("SCHEDULE_DATA_URL", "https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/d1yQtOSfobdzGs0XfzJlNw/data.json")
    endpoint = os.environ.get("ALEXA_API_ENDPOINT", "https://api.eu.amazonalexa.com")
    access_token = os.environ.get("ALEXA_LWA_ACCESS_TOKEN", "")
    if not access_token:
        print("Alexa update skipped: ALEXA_LWA_ACCESS_TOKEN is not configured")
        return 0

    try:
        data = fetch_schedule(schedule_url)
        now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        plan = build_wake_plan(data, now)
        existing = find_managed_reminder(list_reminders(endpoint, access_token))
        token = existing.get("alertToken") if existing else None
        if plan is None:
            if token:
                delete_reminder(endpoint, access_token, token)
                print("Alexa reminder removed: no school day")
            else:
                print("Alexa reminder unchanged: no school day")
            return 0
        if not token:
            print("Alexa update skipped: create the first reminder from the Alexa skill, then configure ALEXA_LWA_ACCESS_TOKEN")
            return 0
        send_reminder_request(endpoint, access_token, plan, alert_token=token)
        print(f"Alexa reminder updated for {plan.date.isoformat()} at {plan.wake_time.strftime('%H:%M')}")
        return 0
    except (OSError, ValueError, AlexaApiError) as exc:
        print(f"Alexa update failed safely: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
