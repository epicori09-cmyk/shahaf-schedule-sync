from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from shahaf_sync.alexa import (
    AlexaApiError,
    EFFECTIVE_WAKE_URL,
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
    matches = find_managed_reminders(reminders)
    return matches[0] if matches else None


def find_managed_reminders(reminders: list[dict]) -> list[dict]:
    matches = []
    for reminder in reminders:
        try:
            content = reminder["alertInfo"]["spokenInfo"]["content"]
            text = content[0].get("text", "")
            if isinstance(text, str) and text.startswith(MARKER):
                matches.append(reminder)
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
    return sorted(matches, key=lambda item: str(item.get("updatedTime") or ""), reverse=True)


def _managed_token(reminder: dict) -> str:
    token = reminder.get("alertToken")
    if not isinstance(token, str) or not token:
        raise AlexaApiError("Alexa returned a managed reminder without an alert token")
    return token


def main() -> int:
    schedule_url = os.environ.get("SCHEDULE_DATA_URL", EFFECTIVE_WAKE_URL)
    endpoint = os.environ.get("ALEXA_API_ENDPOINT") or "https://api.eu.amazonalexa.com"
    access_token = os.environ.get("ALEXA_LWA_ACCESS_TOKEN", "")
    if not access_token:
        print("Alexa update skipped: ALEXA_LWA_ACCESS_TOKEN is not configured")
        return 0

    stage = "feed validation"
    try:
        if schedule_url != EFFECTIVE_WAKE_URL:
            raise ValueError("Alexa requires the effective Worker wake endpoint")
        data = fetch_schedule(schedule_url)
        now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        plan = build_wake_plan(data, now, expected_generated_at=os.environ.get("SCHEDULE_GENERATED_AT"))
        stage = "reminder listing"
        managed = find_managed_reminders(list_reminders(endpoint, access_token))
        if plan is None:
            tokens = list(dict.fromkeys(_managed_token(reminder) for reminder in managed))
            if tokens:
                stage = "managed reminder clear (some deletions may have succeeded)"
                for token in tokens:
                    delete_reminder(endpoint, access_token, token)
                print(f"Alexa reminders removed: {len(tokens)} managed no-school reminders")
            else:
                print("Alexa reminder unchanged: no school day")
            return 0
        if not managed:
            print("Alexa update skipped: create the first reminder from the Alexa skill, then configure ALEXA_LWA_ACCESS_TOKEN")
            return 0
        tokens = list(dict.fromkeys(_managed_token(reminder) for reminder in managed))
        token = tokens[0]
        stage = "reminder update"
        send_reminder_request(endpoint, access_token, plan, alert_token=token)
        stage = "duplicate cleanup after successful reminder update"
        for duplicate in tokens[1:]:
            delete_reminder(endpoint, access_token, duplicate)
        print(f"Alexa reminder updated for {plan.date.isoformat()} at {plan.wake_time.strftime('%H:%M')}")
        return 0
    except (OSError, ValueError, AlexaApiError) as exc:
        print(f"Alexa update failed during {stage}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
