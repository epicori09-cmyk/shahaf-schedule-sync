from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import re

from .ics import Calendar, IcsEvent, format_datetime, unescape
from .model import Lesson, SourceSnapshot


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
        and _teacher(event).strip() == lesson.teacher.strip()
        and event.location.strip() == lesson.room.strip()
    )


def _compatible_reference(event: IcsEvent, lesson: Lesson) -> bool:
    teacher = _teacher(event).strip()
    room = event.location.strip()
    if teacher and lesson.teacher and teacher == lesson.teacher:
        return True
    if room and lesson.room and room == lesson.room:
        return True
    return not teacher and not room


def _deterministic_uid(lesson: Lesson) -> str:
    material = "|".join(
        [lesson.date.isoformat(), str(lesson.period), subject_key(lesson.subject), lesson.teacher, lesson.room]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"auto-{digest}@ostrovsky.shahaf-sync"


def _select_candidate(candidates: list[Lesson], event: IcsEvent) -> Lesson:
    teacher = _teacher(event).strip()
    room = event.location.strip()
    return sorted(
        candidates,
        key=lambda item: (
            0 if teacher and item.teacher.strip() == teacher else 1,
            0 if room and item.room.strip() == room else 1,
            item.teacher,
            item.room,
        ),
    )[0]


def reconcile_calendar(
    calendar: Calendar,
    snapshot: SourceSnapshot,
    window_start: date,
    window_end: date,
) -> list[ChangeRecord]:
    """Apply only dates covered by a complete, timestamped source snapshot."""
    if not snapshot.covered_dates:
        return []
    by_slot: dict[tuple[date, int], list[Lesson]] = {}
    by_date_subject: dict[tuple[date, str], list[Lesson]] = {}
    for lesson in snapshot.lessons:
        by_slot.setdefault((lesson.date, lesson.period), []).append(lesson)
        by_date_subject.setdefault((lesson.date, subject_key(lesson.subject)), []).append(lesson)

    base_events = [event for event in calendar.events if event.is_recurring]
    changes: list[ChangeRecord] = []
    handled_source_ids: set[int] = set()
    baseline_subjects = {subject_key(event.subject) for event in base_events}

    for event in base_events:
        for occurrence in event.occurrences(
            datetime.combine(window_start, time.min),
            datetime.combine(window_end, time.max),
            include_exdates=True,
        ):
            occurrence_date = occurrence.date()
            if occurrence_date not in snapshot.covered_dates:
                continue
            period = event.period
            if period is None:
                continue
            candidates = [
                item
                for item in by_slot.get((occurrence_date, period), [])
                if subject_key(item.subject) == subject_key(event.subject)
            ]
            moved_candidates = by_date_subject.get((occurrence_date, subject_key(event.subject)), [])
            selected = _select_candidate(candidates, event) if candidates else None
            if selected is None and moved_candidates:
                selected = min(
                    moved_candidates,
                    key=lambda item: (abs(item.period - period), item.period, item.teacher, item.room),
                )
            if selected is not None:
                handled_source_ids.add(id(selected))
                if occurrence in event.auto_exdates():
                    event.remove_auto_exdate(occurrence)
                    changes.append(ChangeRecord("restored", occurrence_date, period, event.subject, "source restored the lesson"))
                existing_override = next(
                    (
                        item
                        for item in calendar.events
                        if item.uid == event.uid and item.recurrence_id == occurrence
                    ),
                    None,
                )
                if not _same_details(event, selected) or selected.period != period:
                    already_current = existing_override is not None and _same_details(existing_override, selected)
                    if not already_current:
                        calendar.add_override(
                            event,
                            occurrence,
                            datetime.combine(selected.date, selected.start),
                            datetime.combine(selected.date, selected.end),
                            _summary(selected.subject, selected.period),
                            _description(selected),
                            selected.room,
                        )
                        changes.append(
                            ChangeRecord("changed", occurrence_date, period, selected.subject, f"updated to period {selected.period}")
                        )
                elif existing_override is not None and existing_override.get("X-SHAHAF-AUTO") == "1":
                    calendar.remove_auto_override(event.uid, occurrence)
                    changes.append(ChangeRecord("restored", occurrence_date, period, event.subject, "source matches the base schedule"))
                continue

            if len(moved_candidates) > 1:
                continue
            if occurrence not in event.exdates():
                calendar.remove_auto_override(event.uid, occurrence)
                event.add_exdate(occurrence, automatic=True)
                changes.append(ChangeRecord("cancelled", occurrence_date, period, event.subject, "no matching lesson published"))

    for lesson in snapshot.lessons:
        if id(lesson) in handled_source_ids or not (window_start <= lesson.date <= window_end):
            continue
        key = subject_key(lesson.subject)
        if key not in baseline_subjects or lesson.date not in snapshot.covered_dates:
            continue
        references = [event for event in base_events if subject_key(event.subject) == key]
        if not any(_compatible_reference(event, lesson) for event in references):
            continue
        uid = _deterministic_uid(lesson)
        if any(event.uid == uid for event in calendar.events):
            continue
        calendar.add_generated_event(
            uid,
            datetime.combine(lesson.date, lesson.start),
            datetime.combine(lesson.date, lesson.end),
            _summary(lesson.subject, lesson.period),
            _description(lesson),
            lesson.room,
        )
        changes.append(ChangeRecord("added", lesson.date, lesson.period, lesson.subject, "new published lesson"))

    source_keys = {
        (item.date, item.period, subject_key(item.subject))
        for item in snapshot.lessons
        if item.date in snapshot.covered_dates
    }
    for event in list(calendar.events):
        if event.get("X-SHAHAF-AUTO") != "1" or event.recurrence_id or event.is_recurring:
            continue
        if not (window_start <= event.start.date() <= window_end):
            continue
        period = event.period
        if period is None:
            continue
        key = (event.start.date(), period, subject_key(event.subject))
        if event.start.date() in snapshot.covered_dates and key not in source_keys:
            calendar.remove_auto_event(event.uid)
            changes.append(ChangeRecord("removed", event.start.date(), period, event.subject, "no longer published"))

    return sorted(changes, key=lambda item: (item.date, item.period, item.kind, item.subject))
