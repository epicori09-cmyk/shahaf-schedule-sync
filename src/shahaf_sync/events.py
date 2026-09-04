from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import re
from typing import Any, Mapping

from .model import PERIOD_TIMES, ShahafEvent


EVENT_REVIEW_TERMS = (
    "סינכרוני",
    "א-סינכרוני",
    "אסינכרוני",
    "למידה מרחוק",
    "למידה מקוונת",
    "אין לימודים",
    "ללא לימודים",
    "השבתה",
    "חופשה",
    "remote",
    "online learning",
    "async",
    "no school",
    "school closed",
)

EXPLICIT_NO_SCHOOL_TERMS = (
    "יום למידה א-סינכרוני",
    "יום למידה אסינכרוני",
    "יום למידה א סינכרוני",
)


def event_key(event: ShahafEvent) -> tuple[object, ...]:
    return (
        event.date,
        event.title,
        event.start_period,
        event.end_period,
        event.start,
        event.end,
        event.class_scope,
    )


def event_requires_review(event: ShahafEvent) -> bool:
    """Return true only for titles that may remove normal attendance."""
    text = f"{event.title} {event.detail}".casefold()
    return any(term.casefold() in text for term in EVENT_REVIEW_TERMS)


def is_explicit_no_school(event: ShahafEvent) -> bool:
    """Recognize Shahaf's exact asynchronous-learning-day announcement."""
    text = f"{event.title} {event.detail}".casefold()
    return any(term.casefold() in text for term in EXPLICIT_NO_SCHOOL_TERMS)


def event_periods(event: ShahafEvent) -> set[int]:
    if event.start_period is None or event.end_period is None:
        return set()
    end = min(event.end_period, max(PERIOD_TIMES))
    return set(range(event.start_period, end + 1))


def event_overlaps_lesson(event: ShahafEvent, lesson: Mapping[str, Any]) -> bool:
    if str(lesson.get("date", "")) != event.date.isoformat():
        return False
    if event.start_period is not None:
        try:
            return int(lesson.get("period")) in event_periods(event)
        except (TypeError, ValueError):
            return False
    if event.start is None or event.end is None:
        return False
    try:
        lesson_start = time.fromisoformat(str(lesson["start"]))
        lesson_end = time.fromisoformat(str(lesson["end"]))
    except (KeyError, TypeError, ValueError):
        return False
    return lesson_start < event.end and lesson_end > event.start


def decision_value(decision: object, name: str, default: Any = None) -> Any:
    if isinstance(decision, Mapping):
        return decision.get(name, default)
    return getattr(decision, name, default)


def decision_allows_suppression(decision: object | None) -> bool:
    if decision is None:
        return False
    classification = str(decision_value(decision, "classification", "uncertain"))
    safe = decision_value(decision, "safe_to_delete_alarm", False)
    risk = str(decision_value(decision, "risk_level", "high"))
    return bool(safe) and risk == "low" and classification in {"no_school", "remote_learning"}


def apply_event_decisions(
    schedule: list[dict[str, Any]],
    events: list[ShahafEvent],
    decisions: Mapping[tuple[object, ...], object],
) -> list[dict[str, Any]]:
    """Remove lessons only for explicitly AI-approved school-replacing events."""
    result: list[dict[str, Any]] = []
    for lesson in schedule:
        suppressed = any(
            event_overlaps_lesson(event, lesson)
            and decision_allows_suppression(decisions.get(event_key(event)))
            for event in events
        )
        if not suppressed:
            result.append(lesson)
    return result


def event_to_dict(event: ShahafEvent, decision: object | None = None) -> dict[str, Any]:
    classification = str(decision_value(decision, "classification", "overlay"))
    return {
        "id": event_uid(event),
        "date": event.date.isoformat(),
        "title": event.title,
        "detail": event.detail,
        "class_scope": event.class_scope,
        "start_period": event.start_period,
        "end_period": event.end_period,
        "start": event.start.strftime("%H:%M") if event.start else None,
        "end": event.end.strftime("%H:%M") if event.end else None,
        "classification": classification,
        "safe_to_delete_alarm": decision_value(decision, "safe_to_delete_alarm", None),
        "risk_level": decision_value(decision, "risk_level", None),
        "decision_reason": decision_value(decision, "reason", "Ordinary event overlay; normal lessons remain scheduled."),
        "suppresses_lessons": decision_allows_suppression(decision),
    }


def event_uid(event: ShahafEvent) -> str:
    material = "|".join(
        (
            event.date.isoformat(),
            event.title,
            str(event.start_period),
            str(event.end_period),
            event.start.isoformat() if event.start else "",
            event.end.isoformat() if event.end else "",
            event.class_scope,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"event-{digest}@ostrovsky.shahaf-sync"


def event_window(event: ShahafEvent) -> tuple[time, time] | None:
    if event.start and event.end:
        return event.start, event.end
    if event.start_period is None or event.end_period is None:
        return None
    start = PERIOD_TIMES.get(event.start_period)
    if start is not None:
        end = PERIOD_TIMES.get(min(event.end_period, max(PERIOD_TIMES)))
        return (start[0], end[1]) if end is not None else None
    # Administrative events can use Shahaf's post-school period numbers. A
    # precise clock time is not published for those rows, so use a bounded
    # display interval after the final lesson rather than inventing a route or
    # lesson time.
    if event.start_period > max(PERIOD_TIMES):
        start_time = PERIOD_TIMES[max(PERIOD_TIMES)][1]
        duration = max(1, event.end_period - event.start_period + 1) * 40
        end_time = (datetime.combine(date(2000, 1, 1), start_time) + timedelta(minutes=duration)).time()
        return start_time, end_time
    return None


def event_is_past(event: Mapping[str, Any], now: datetime | None) -> bool:
    if now is None:
        return False
    try:
        event_date = date.fromisoformat(str(event.get("date", "")))
    except ValueError:
        return False
    if event_date < now.date():
        return True
    if event_date > now.date():
        return False
    end_value = event.get("end")
    if end_value:
        try:
            return now.time().replace(tzinfo=None) >= time.fromisoformat(str(end_value))
        except ValueError:
            return False
    end_period = event.get("end_period")
    if end_period is not None:
        try:
            period_end = PERIOD_TIMES[min(int(end_period), max(PERIOD_TIMES))][1]
            return now.time().replace(tzinfo=None) >= period_end
        except (TypeError, ValueError, KeyError):
            return False
    return False
