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
    "https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json",
)
ZONE = ZoneInfo("Asia/Jerusalem")
MARKER = "School schedule wake-up."


def response(text: str, reprompt: str | None = None, should_end: bool = False) -> dict:
    speech = {"type": "SSML", "ssml": f"<speak>{escape(text)}</speak>"}
    result = {"outputSpeech": speech, "shouldEndSession": should_end}
    if reprompt:
        result["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return {"version": "1.0", "response": result}


def fetch_schedule() -> dict:
    if SCHEDULE_URL != EFFECTIVE_WAKE_URL:
        raise ValueError("Alexa requires the effective Worker wake endpoint")
    request = Request(SCHEDULE_URL, headers={"User-Agent": "school-schedule-alexa/1.0"})
    with urlopen(request, timeout=15) as source:
        data = json.loads(source.read().decode("utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("stale") is not False
    ):
        raise ValueError("schedule is not currently confirmed")
    return data


PROFILE_ID = "d1yQtOSfobdzGs0XfzJlNw"
EFFECTIVE_WAKE_URL = f"https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/{PROFILE_ID}/wake.json"


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return instant


def select_effective_wake(data: dict, now: datetime, *, profile_id: str = PROFILE_ID,
                          expected_generated_at: str | None = None) -> tuple[datetime | None, dict]:
    """Validate an effective Worker envelope before authorizing any Alexa change."""
    if now.tzinfo is None or not isinstance(data, dict):
        raise ValueError("invalid wake envelope or current time")
    zone = ZoneInfo("Asia/Jerusalem")
    today = now.astimezone(zone).date()
    generated = _instant(data.get("generated_at"))
    age = now - generated
    if age > timedelta(hours=3) or age < -timedelta(minutes=5):
        raise ValueError("wake feed generation is outside the freshness window")
    if expected_generated_at is not None and generated != _instant(expected_generated_at):
        raise ValueError("Worker generation does not match the deployed artifact")

    def validate(envelope: dict) -> None:
        if not isinstance(envelope, dict) or envelope.get("profile_id") != profile_id:
            raise ValueError("wake profile identity mismatch")
        if _instant(envelope.get("generated_at")) != generated:
            raise ValueError("wake preview generation mismatch")
        if envelope.get("stale") is not False:
            raise ValueError("wake feed is stale or unconfirmed")
        target = envelope.get("next_school_day")
        if not isinstance(target, str):
            raise ValueError("wake target date is missing")
        target_date = datetime.strptime(target, "%Y-%m-%d").date()
        if target_date.isoformat() != target or target_date < today:
            raise ValueError("wake target date is invalid or elapsed")
        if envelope.get("shortcut_action") not in ("set", "clear", "leave"):
            raise ValueError("wake action is malformed")
        if envelope.get("wake_at") is not None:
            instant = _instant(envelope["wake_at"]).astimezone(zone)
            if instant.date() != target_date:
                raise ValueError("wake instant target date mismatch")
            if envelope.get("wake_time") != instant.strftime("%H:%M"):
                raise ValueError("wake time and instant disagree")

    validate(data)
    deferred = data.get("fallback_status") in {"future-alarm-deferred", "elapsed-wake", "current-weekend"}
    if data.get("shortcut_action") == "leave" and not deferred:
        raise ValueError("wake action preserves existing reminders")
    root_unsafe = {"stale", "unavailable", "no-safe-route", "wake-time-bound",
                   "unsafe-override-blocked", "restore-reconcile", "invalid-clock-time"}
    if data.get("fallback_status") in root_unsafe:
        raise ValueError("wake action is unsafe")
    root_set = data.get("shortcut_action") == "set"
    root_at = _instant(data.get("wake_at")) if root_set else None
    use_preview = deferred or (root_at is not None and root_at <= now)
    if data.get("next_alarm") is not None and not (
        root_at is not None and root_at > now and data["next_school_day"] == today.isoformat()
    ):
        use_preview = True
    if use_preview:
        candidate = data.get("next_alarm")
        validate(candidate)
        if candidate["next_school_day"] <= today.isoformat():
            raise ValueError("wake preview must target a future date")
    else:
        candidate = data
    validate(candidate)
    unsafe = {"stale", "unavailable", "no-safe-route", "wake-time-bound",
              "unsafe-override-blocked", "restore-reconcile", "invalid-clock-time",
              "future-alarm-deferred", "elapsed-wake"}
    if candidate.get("fallback_status") in unsafe:
        raise ValueError("wake action is unsafe")
    action = candidate.get("shortcut_action")
    if action == "leave":
        raise ValueError("wake action preserves existing reminders")
    if action == "clear":
        if (candidate.get("enabled") is not False or candidate.get("wake_at") is not None
                or candidate.get("wake_time") is not None):
            raise ValueError("clear envelope is inconsistent")
        return None, candidate
    if action != "set" or candidate.get("enabled") is not True:
        raise ValueError("wake action is not confirmed")
    wake_at = _instant(candidate.get("wake_at")).astimezone(zone)
    if wake_at.date().isoformat() != candidate["next_school_day"] or wake_at <= now:
        raise ValueError("wake instant does not match a future target")
    if candidate.get("wake_time") != wake_at.strftime("%H:%M"):
        raise ValueError("wake time and instant disagree")
    return wake_at, candidate


def reminder_payload(wake_at: datetime, lesson: dict) -> dict:
    text = f"{MARKER} Your alarm is at {wake_at.strftime('%H:%M')}."
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


def clear_existing_wakeups(event: dict, keep_token: str | None = None) -> None:
    reminders = alexa_api(event, "GET", "/v1/alerts/reminders")
    alerts = reminders.get("alerts") if isinstance(reminders, dict) else None
    if not isinstance(alerts, list):
        raise ValueError("Alexa returned an invalid reminders list")
    for reminder in alerts:
        try:
            text = reminder["alertInfo"]["spokenInfo"]["content"][0].get("text", "")
            managed = isinstance(text, str) and text.startswith(MARKER)
        except (AttributeError, KeyError, IndexError, TypeError):
            continue
        if not managed:
            continue
        token = reminder.get("alertToken") if isinstance(reminder, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("Alexa returned a managed reminder without an alert token")
        if token != keep_token:
            alexa_api(event, "DELETE", f"/v1/alerts/reminders/{token}")


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

    replacement_created = False
    clearing = False
    try:
        data = fetch_schedule()
        wake_at, lesson = select_effective_wake(data, datetime.now(ZONE))
        if wake_at is None:
            if intent == "SetWakeUpIntent":
                clearing = True
                clear_existing_wakeups(event)
            return response("The confirmed alarm action is clear.", should_end=True)
        if intent == "NextLessonIntent":
            return response(f"Your school alarm is at {wake_at.strftime('%H:%M')}.", should_end=True)
        created = alexa_api(event, "POST", "/v1/alerts/reminders", reminder_payload(wake_at, lesson))
        replacement_token = created.get("alertToken") if isinstance(created, dict) else None
        if not isinstance(replacement_token, str) or not replacement_token:
            raise ValueError("Alexa did not confirm the replacement reminder")
        replacement_created = True
        clear_existing_wakeups(event, keep_token=replacement_token)
        return response(f"Done. I will remind you at {wake_at.strftime('%H:%M')}.", should_end=True)
    except Exception:
        if replacement_created:
            return response("I created the new reminder, but could not remove every older managed reminder.", should_end=True)
        if clearing:
            return response("I could not remove every managed reminder. Some may remain.", should_end=True)
        return response("I could not safely create the new reminder, so I did not change your existing reminder.", should_end=True)
