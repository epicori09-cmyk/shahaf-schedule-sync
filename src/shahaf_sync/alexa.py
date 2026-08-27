from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_WAKE_TIME = time(7, 15)
DEFAULT_BUFFER_MINUTES = 75


@dataclass(frozen=True, slots=True)
class WakePlan:
    date: date
    wake_time: datetime
    first_start: time | None
    first_subject: str | None
    used_default: bool = False


class AlexaApiError(RuntimeError):
    """A safe-to-report Alexa API failure."""


def _valid_lesson(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("date"), str)
        and isinstance(item.get("start"), str)
        and len(item["start"]) == 5
        and item["start"][2] == ":"
    )


def _lesson_time(item: dict[str, Any]) -> time:
    hour, minute = (int(value) for value in item["start"].split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("lesson time is out of range")
    return time(hour, minute)


def _next_weekday(start: date) -> date:
    candidate = start
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _default_plan(now: datetime, zone: ZoneInfo) -> WakePlan:
    local_now = now.astimezone(zone)
    target_date = _next_weekday(local_now.date())
    if target_date == local_now.date() and local_now.time() >= DEFAULT_WAKE_TIME:
        target_date = _next_weekday(target_date + timedelta(days=1))
    return WakePlan(
        date=target_date,
        wake_time=datetime.combine(target_date, DEFAULT_WAKE_TIME, tzinfo=zone),
        first_start=None,
        first_subject=None,
        used_default=True,
    )


def build_wake_plan(data: dict[str, Any], now: datetime, *, timezone_name: str = "Asia/Jerusalem", buffer_minutes: int = DEFAULT_BUFFER_MINUTES) -> WakePlan | None:
    """Build the next wake-up plan from published schedule JSON.

    Invalid or stale schedule data deliberately falls back to the configured
    default weekday wake-up rather than trusting unverified lesson times.
    """
    zone = ZoneInfo(timezone_name)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(data, dict) or data.get("stale") or data.get("schedule_available") is False:
        return _default_plan(now, zone)

    raw_schedule = data.get("schedule")
    if not isinstance(raw_schedule, list):
        return _default_plan(now, zone)

    local_now = now.astimezone(zone)
    candidates: list[tuple[date, time, dict[str, Any]]] = []
    try:
        for item in raw_schedule:
            if not _valid_lesson(item):
                continue
            lesson_date = date.fromisoformat(item["date"])
            lesson_time = _lesson_time(item)
            if lesson_date < local_now.date():
                continue
            if lesson_date == local_now.date() and lesson_time <= local_now.time():
                continue
            candidates.append((lesson_date, lesson_time, item))
    except (TypeError, ValueError):
        return _default_plan(now, zone)

    if not candidates:
        return None

    lesson_date, lesson_time, item = min(candidates, key=lambda value: (value[0], value[1]))
    wake_time = datetime.combine(lesson_date, lesson_time, tzinfo=zone) - timedelta(minutes=buffer_minutes)
    return WakePlan(
        date=lesson_date,
        wake_time=wake_time,
        first_start=lesson_time,
        first_subject=str(item.get("subject") or "your first lesson"),
    )


def reminder_id(plan: WakePlan) -> str:
    return f"school-wake-{plan.date.isoformat()}"


def build_reminder_payload(plan: WakePlan, *, timezone_name: str = "Asia/Jerusalem", request_time: datetime | None = None) -> dict[str, Any]:
    request_at = request_time or datetime.now(timezone.utc)
    if request_at.tzinfo is None:
        raise ValueError("request_time must be timezone-aware")
    if plan.first_subject:
        lesson_text = f"Wake up. Your first lesson is {plan.first_subject} at {plan.first_start.strftime('%H:%M')}"
    else:
        lesson_text = "Wake up for school. Your schedule could not be confirmed, so this is the default wake-up time."
    return {
        "requestTime": request_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "trigger": {
            "type": "SCHEDULED_ABSOLUTE",
            "scheduledTime": plan.wake_time.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZoneId": timezone_name,
        },
        "alertInfo": {
            "spokenInfo": {
                "content": [{"locale": "en-US", "text": lesson_text}]
            }
        },
        "pushNotification": {"status": "ENABLED"},
    }


def send_reminder_request(endpoint: str, access_token: str, plan: WakePlan, *, alert_token: str | None = None) -> dict[str, Any]:
    """Create or update one Alexa reminder without ever logging credentials."""
    if not endpoint.startswith("https://"):
        raise AlexaApiError("Alexa endpoint must use HTTPS")
    if not access_token:
        raise AlexaApiError("Alexa access token is required")
    payload = json.dumps(build_reminder_payload(plan)).encode("utf-8")
    path = "/v1/alerts/reminders" + (f"/{alert_token}" if alert_token else "")
    method = "PUT" if alert_token else "POST"
    request = Request(
        endpoint.rstrip("/") + path,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except (HTTPError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlexaApiError(f"Alexa reminder request failed: {exc}") from exc
