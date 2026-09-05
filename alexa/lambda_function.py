"""Alexa-hosted skill for creating the first school wake-up reminder.

This file intentionally uses only the Python standard library so it can be
uploaded directly to an Alexa-hosted skill.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SCHEDULE_URL = os.environ.get(
    "SCHEDULE_DATA_URL",
    "https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/d1yQtOSfobdzGs0XfzJlNw/data.json",
)
ZONE = ZoneInfo("Asia/Jerusalem")
BUFFER_MINUTES = 75
MARKER = "School schedule wake-up."


def response(text: str, reprompt: str | None = None, should_end: bool = False) -> dict:
    speech = {"type": "SSML", "ssml": f"<speak>{escape(text)}</speak>"}
    result = {"outputSpeech": speech, "shouldEndSession": should_end}
    if reprompt:
        result["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return {"version": "1.0", "response": result}


def fetch_schedule() -> dict:
    request = Request(SCHEDULE_URL, headers={"User-Agent": "school-schedule-alexa/1.0"})
    with urlopen(request, timeout=15) as source:
        data = json.loads(source.read().decode("utf-8"))
    if not isinstance(data, dict) or data.get("stale") or data.get("schedule_available") is False:
        raise ValueError("schedule is not currently confirmed")
    if not isinstance(data.get("schedule"), list):
        raise ValueError("schedule data is malformed")
    return data


def next_lesson(data: dict) -> tuple[datetime, dict] | None:
    now = datetime.now(ZONE)
    candidates = []
    for item in data["schedule"]:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(f"{item['date']}T{item['start']}:00").replace(tzinfo=ZONE)
            datetime.fromisoformat(f"{item['date']}T{item['end']}:00")
        except (KeyError, TypeError, ValueError):
            continue
        if start > now:
            candidates.append((start, item))
    return min(candidates, key=lambda pair: pair[0]) if candidates else None


def first_lesson_of_next_school_day(data: dict) -> tuple[datetime, dict] | None:
    now = datetime.now(ZONE)
    candidates = []
    for item in data["schedule"]:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(f"{item['date']}T{item['start']}:00").replace(tzinfo=ZONE)
            datetime.fromisoformat(f"{item['date']}T{item['end']}:00")
        except (KeyError, TypeError, ValueError):
            continue
        if start.date() < now.date():
            continue
        candidates.append((start, item))
    if not candidates:
        return None
    first_date = min(start.date() for start, _ in candidates)
    same_day = [(start, item) for start, item in candidates if start.date() == first_date]
    return min(same_day, key=lambda pair: pair[0])


def reminder_payload(wake_at: datetime, lesson: dict) -> dict:
    subject = str(lesson.get("subject") or "your first lesson")
    start = str(lesson.get("start") or "the start time")
    text = f"{MARKER} Your first lesson is {subject} at {start}."
    return {
        "requestTime": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "trigger": {
            "type": "SCHEDULED_ABSOLUTE",
            "scheduledTime": wake_at.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZoneId": "Asia/Jerusalem",
        },
        "alertInfo": {"spokenInfo": {"content": [{"locale": "en-US", "text": text}]}},
        "pushNotification": {"status": "ENABLED"},
    }


def alexa_api(event: dict, method: str, path: str, payload: dict | None = None) -> dict:
    system = event["context"]["System"]
    endpoint = system["apiEndpoint"].rstrip("/")
    token = system["apiAccessToken"]
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(endpoint + path, data=body, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=15) as result:
        raw = result.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def clear_existing_wakeups(event: dict) -> None:
    reminders = alexa_api(event, "GET", "/v1/alerts/reminders")
    alerts = reminders.get("alerts", []) if isinstance(reminders, dict) else []
    for reminder in alerts:
        try:
            text = reminder["alertInfo"]["spokenInfo"]["content"][0].get("text", "")
            token = reminder["alertToken"]
            if text.startswith(MARKER):
                alexa_api(event, "DELETE", f"/v1/alerts/reminders/{token}")
        except (KeyError, IndexError, TypeError):
            continue


def lambda_handler(event: dict, context: object) -> dict:
    request = event.get("request", {})
    if request.get("type") == "LaunchRequest":
        return response("You can say, set my school wake-up, or when should I wake up?", "Say set my school wake-up.")
    if request.get("type") != "IntentRequest":
        return response("I can help with your school wake-up reminder.", should_end=True)

    intent = request.get("intent", {}).get("name", "")
    if intent in {"AMAZON.StopIntent", "AMAZON.CancelIntent"}:
        return response("Okay.", should_end=True)
    if intent in {"AMAZON.HelpIntent", "AMAZON.FallbackIntent"}:
        return response("Say, set my school wake-up, and I will use your first confirmed lesson.", "Say set my school wake-up.")
    if intent not in {"SetWakeUpIntent", "NextLessonIntent"}:
        return response("Try saying, set my school wake-up.", should_end=True)

    try:
        data = fetch_schedule()
        lesson_info = first_lesson_of_next_school_day(data) if intent == "SetWakeUpIntent" else next_lesson(data)
        if lesson_info is None:
            return response("There are no upcoming lessons in the confirmed schedule.", should_end=True)
        lesson_start, lesson = lesson_info
        wake_at = lesson_start - timedelta(minutes=BUFFER_MINUTES)
        if intent == "NextLessonIntent":
            return response(f"Your next lesson is {lesson.get('subject', 'unknown')} at {lesson.get('start', 'an unknown time')}.", should_end=True)
        clear_existing_wakeups(event)
        alexa_api(event, "POST", "/v1/alerts/reminders", reminder_payload(wake_at, lesson))
        return response(f"Done. I will remind you at {wake_at.strftime('%H:%M')} for {lesson.get('subject', 'your first lesson')}.", should_end=True)
    except Exception:
        return response("I could not safely confirm the school schedule, so I did not change your reminder.", should_end=True)
