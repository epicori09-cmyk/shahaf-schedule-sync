from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


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


class AlexaScheduleError(ValueError):
    """The published schedule cannot safely authorize a reminder change."""


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


def build_wake_plan(data: dict[str, Any], now: datetime, *, timezone_name: str = "Asia/Jerusalem",
                    buffer_minutes: int = DEFAULT_BUFFER_MINUTES,
                    profile_id: str = PROFILE_ID, expected_generated_at: str | None = None) -> WakePlan | None:
    """Use the effective published alarm; never recompute personalized wake times.

    Legacy timezone/buffer keywords are retained for call compatibility; the
    profile feed supplies the actual Israel alarm instant.
    """
    try:
        wake_at, envelope = select_effective_wake(
            data, now, profile_id=profile_id, expected_generated_at=expected_generated_at)
    except (ValueError, TypeError, KeyError) as exc:
        raise AlexaScheduleError(str(exc)) from exc
    if wake_at is None:
        return None
    return WakePlan(date=wake_at.date(), wake_time=wake_at, first_start=None,
                    first_subject=envelope.get("subject") if isinstance(envelope.get("subject"), str) else None)


def reminder_id(plan: WakePlan) -> str:
    return f"school-wake-{plan.date.isoformat()}"


def build_reminder_payload(plan: WakePlan, *, timezone_name: str = "Asia/Jerusalem", request_time: datetime | None = None) -> dict[str, Any]:
    request_at = request_time or datetime.now(timezone.utc)
    if request_at.tzinfo is None:
        raise ValueError("request_time must be timezone-aware")
    if plan.first_subject and plan.first_start:
        lesson_text = f"School schedule wake-up. Your first lesson is {plan.first_subject} at {plan.first_start.strftime('%H:%M')}"
    else:
        lesson_text = f"School schedule wake-up. Your alarm is at {plan.wake_time.strftime('%H:%M')}."
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


def list_reminders(endpoint: str, access_token: str) -> list[dict[str, Any]]:
    if not endpoint.startswith("https://"):
        raise AlexaApiError("Alexa endpoint must use HTTPS")
    if not access_token:
        raise AlexaApiError("Alexa access token is required")
    request = Request(
        endpoint.rstrip("/") + "/v1/alerts/reminders",
        method="GET",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            reminders = body.get("alerts", body) if isinstance(body, dict) else body
            if not isinstance(reminders, list):
                raise AlexaApiError("Alexa returned an invalid reminders list")
            return reminders
    except (HTTPError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlexaApiError(f"Alexa reminder list request failed: {exc}") from exc


def delete_reminder(endpoint: str, access_token: str, alert_token: str) -> None:
    if not alert_token:
        raise AlexaApiError("Alexa reminder token is required")
    request = Request(
        endpoint.rstrip("/") + f"/v1/alerts/reminders/{alert_token}",
        method="DELETE",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20):
            return
    except (HTTPError, URLError) as exc:
        raise AlexaApiError(f"Alexa reminder delete failed: {exc}") from exc
