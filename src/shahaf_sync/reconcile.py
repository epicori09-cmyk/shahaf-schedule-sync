from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import re

from .ics import Calendar, IcsEvent, unescape
from .events import decision_allows_suppression, decision_value, event_key, event_overlaps_lesson, event_uid, event_window
from .model import PERIOD_TIMES, Lesson, PublishedChange, ShahafEvent, SourceSnapshot


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    kind: str
    date: date
    period: int
    subject: str
    detail: str


def subject_key(value: str) -> str:
    value = re.sub(r"(?:—|-)?\s*(?:שעה|hour)\s*\d+\s*$", "", value, flags=re.IGNORECASE)
    tokens = re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    return " ".join(sorted(tokens))


def _detail_key(value: str) -> str:
    """Normalize teacher/room text whose word order is not semantically meaningful."""
    tokens = re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    return " ".join(sorted(tokens))


def _teacher(event: IcsEvent) -> str:
    for line in event.description.splitlines():
        if line.strip().startswith("מורה:"):
            return line.split(":", 1)[1].strip()
    return ""


def _summary(subject: str, period: int) -> str:
    return f"{subject} — שעה {period}"


def _description(lesson: Lesson) -> str:
    result = f"מורה: {lesson.teacher}\nשעה במערכת: {lesson.period}"
    if lesson.room:
        result += f"\nחדר: {lesson.room}"
    return result


def _same_details(event: IcsEvent, lesson: Lesson) -> bool:
    return (
        subject_key(event.subject) == subject_key(lesson.subject)
        and event.start.time() == lesson.start
        and event.end.time() == lesson.end
        and _detail_key(_teacher(event)) == _detail_key(lesson.teacher)
        and _detail_key(event.location) == _detail_key(lesson.room)
    )


def _find_base_event(
    calendar: Calendar, change: PublishedChange
) -> tuple[IcsEvent, datetime] | None:
    start = datetime.combine(change.date, time.min)
    end = datetime.combine(change.date, time.max)
    candidates: list[tuple[IcsEvent, datetime]] = []
    for event in calendar.events:
        if not event.is_recurring:
            continue
        if change.subject and subject_key(event.subject) != subject_key(change.subject):
            continue
        if not change.subject and change.teacher and _detail_key(_teacher(event)) != _detail_key(change.teacher):
            continue
        for occurrence in event.occurrences(start, end, include_exdates=True):
            if occurrence.date() == change.date and event.period == change.period:
                candidates.append((event, occurrence))
    if not candidates:
        return None

    def score(item: tuple[IcsEvent, datetime]) -> tuple[int, int, str, str]:
        event = item[0]
        teacher = _detail_key(_teacher(event))
        room = _detail_key(event.location)
        wanted_teacher = _detail_key(change.teacher or "")
        wanted_room = _detail_key(change.room or "")
        return (
            0 if wanted_teacher and teacher == wanted_teacher else 1,
            0 if wanted_room and room == wanted_room else 1,
            event.start.hour * 60 + event.start.minute,
            event.uid,
        )

    return sorted(candidates, key=score)[0]


def _target_times(change: PublishedChange, event: IcsEvent | None = None) -> tuple[time, time]:
    target_period = change.new_period or change.period
    default_times = PERIOD_TIMES.get(target_period)
    if event is not None and change.new_period is None and change.start is None and change.end is None:
        return event.start.time(), event.end.time()
    if default_times is None and (change.start is None or change.end is None):
        if event is None:
            raise ValueError(f"No time mapping for Shahaf period {target_period}")
        return change.start or event.start.time(), change.end or event.end.time()
    start = change.start or default_times[0]
    end = change.end or default_times[1]
    return start, end


def _change_detail(change: PublishedChange, fallback: str) -> str:
    return change.detail or fallback


def _generated_uid(change: PublishedChange) -> str:
    material = "|".join([change.date.isoformat(), str(change.period), subject_key(change.subject)])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"auto-{digest}@ostrovsky.shahaf-sync"


def _existing_generated_matches(event: IcsEvent, change: PublishedChange) -> bool:
    start, end = _target_times(change)
    teacher = change.teacher or ""
    room = change.room or ""
    return (
        event.start.time() == start
        and event.end.time() == end
        and subject_key(event.subject) == subject_key(change.subject)
        and _detail_key(_teacher(event)) == _detail_key(teacher)
        and _detail_key(event.location) == _detail_key(room)
    )


def reconcile_calendar(
    calendar: Calendar,
    snapshot: SourceSnapshot,
    window_start: date,
    window_end: date,
) -> list[ChangeRecord]:
    """Apply only explicit, date-scoped changes published by Shahaf.

    Absence from the changes feed is deliberately not interpreted as a
    cancellation. This is what keeps an empty or partial feed from deleting a
    whole personal schedule.
    """
    if not snapshot.changes:
        return []
    changes: list[ChangeRecord] = []
    for change in sorted(snapshot.changes, key=lambda item: (item.date, item.period, item.kind, item.subject)):
        if not (window_start <= change.date <= window_end):
            continue
        base = _find_base_event(calendar, change)
        if change.kind == "cancelled":
            if base is None:
                continue
            event, occurrence = base
            calendar.remove_auto_override(event.uid, occurrence)
            if occurrence not in event.exdates():
                event.add_exdate(occurrence, automatic=True)
            changes.append(ChangeRecord("cancelled", change.date, change.period, change.subject or event.subject, _change_detail(change, "published cancellation")))
            continue

        if change.kind == "added":
            start, end = _target_times(change)
            uid = _generated_uid(change)
            existing = next((item for item in calendar.events if item.uid == uid), None)
            if existing is None or not _existing_generated_matches(existing, change):
                generated_lesson = Lesson(
                    change.date,
                    change.period,
                    start,
                    end,
                    change.subject,
                    change.teacher or "",
                    change.room or "",
                )
                calendar.add_generated_event(
                    uid,
                    datetime.combine(change.date, start),
                    datetime.combine(change.date, end),
                    _summary(change.subject, change.period),
                    _description(generated_lesson),
                    change.room or "",
                )
            changes.append(ChangeRecord("added", change.date, change.period, change.subject, _change_detail(change, "published added lesson")))
            continue

        if base is None:
            continue
        event, occurrence = base
        subject = change.subject or event.subject
        if occurrence in event.auto_exdates():
            event.remove_auto_exdate(occurrence)
        target_period = change.new_period or change.period
        start, end = _target_times(change, event)
        teacher = change.teacher if change.teacher is not None else _teacher(event)
        room = change.room if change.room is not None else event.location
        target = Lesson(change.date, target_period, start, end, subject, teacher, room)
        existing_override = next(
            (item for item in calendar.events if item.uid == event.uid and item.recurrence_id == occurrence),
            None,
        )
        if existing_override is None and _same_details(event, target):
            continue
        if existing_override is None or not _same_details(existing_override, target):
            calendar.add_override(
                event,
                occurrence,
                datetime.combine(change.date, start),
                datetime.combine(change.date, end),
                _summary(subject, target_period),
                _description(target),
                room,
            )
        detail = _change_detail(change, f"updated to period {target_period}")
        changes.append(ChangeRecord("changed", change.date, change.period, subject, detail))

    return sorted(changes, key=lambda item: (item.date, item.period, item.kind, item.subject))


def _event_lesson_data(event: IcsEvent, occurrence: datetime) -> dict[str, object]:
    return {
        "date": occurrence.date().isoformat(),
        "period": event.period,
        "start": occurrence.strftime("%H:%M"),
        "end": (occurrence + (event.end - event.start)).strftime("%H:%M"),
    }


def reconcile_event_entries(
    calendar: Calendar,
    events: list[ShahafEvent],
    decisions: dict[tuple[object, ...], object],
    class_number: int,
    window_start: date,
    window_end: date,
) -> None:
    """Overlay Shahaf events and apply only approved school closures.

    Event VEVENTs are additive and deterministic. Lesson exclusions are kept
    under a separate marker so they can never erase an ordinary cancellation.
    """
    for event in sorted(events, key=lambda item: (item.date, item.title)):
        if not (window_start <= event.date <= window_end) or not event.applies_to_class(class_number):
            continue
        decision = decisions.get(event_key(event))
        for base in list(calendar.events):
            if base.recurrence_id is not None or base.period is None:
                continue
            occurrences = base.occurrences(
                datetime.combine(event.date, time.min),
                datetime.combine(event.date, time.max),
                include_exdates=True,
            )
            for occurrence in occurrences:
                if occurrence.date() != event.date:
                    continue
                if decision_allows_suppression(decision) and event_overlaps_lesson(
                    event, _event_lesson_data(base, occurrence)
                ):
                    base.add_event_exdate(occurrence)
                elif (
                    decision is not None
                    and str(decision_value(decision, "classification", "")) == "normal_school"
                    and event_overlaps_lesson(event, _event_lesson_data(base, occurrence))
                ):
                    base.remove_event_exdate(occurrence)

        window = event_window(event)
        if window is None:
            continue
        start, end = window
        description = event.detail or event.title
        if event.class_scope:
            description += f"\nכיתות: {event.class_scope}"
        if decision is not None:
            classification = str(decision_value(decision, "classification", "uncertain"))
            description += f"\nסיווג: {classification}"
            reason = str(decision_value(decision, "reason", "")).strip()
            if reason:
                description += f"\nהחלטת בטיחות: {reason}"
        calendar.add_generated_event(
            event_uid(event),
            datetime.combine(event.date, start),
            datetime.combine(event.date, end),
            event.title,
            description,
            "",
            properties={"X-SHAHAF-EVENT": "1"},
        )
