from __future__ import annotations

"""Track-aware selectors for additional public Shahaf schedule profiles.

The public class timetable contains parallel major groups.  A profile must
therefore select only the confirmed group(s), while retaining subjects that
are shared by the whole class.  This module intentionally keeps the selector
explicit rather than guessing from a subject name alone.
"""

from dataclasses import replace
from datetime import time
import re
from typing import Any

from .model import Exam, Lesson, PERIOD_TIMES, PublishedChange


def _text(value: str) -> str:
    value = value.replace("״", '"').replace("׳", "'")
    value = value.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _matches(value: str, expected: str) -> bool:
    return _text(value) == _text(expected)


def _selector_matches(lesson: Lesson, selector: dict[str, Any]) -> bool:
    periods = selector.get("periods")
    weekdays = selector.get("weekdays")
    if periods and lesson.period not in {int(value) for value in periods}:
        return False
    if weekdays and lesson.date.weekday() not in {int(value) for value in weekdays}:
        return False
    subject = selector.get("subject")
    teacher = selector.get("teacher")
    room = selector.get("room")
    return (
        (not subject or _matches(lesson.subject, str(subject)))
        and (not teacher or _matches(lesson.teacher, str(teacher)))
        and (not room or _matches(lesson.room, str(room)))
    )


def select_lessons(lessons: list[Lesson], spec: dict[str, Any]) -> list[Lesson]:
    """Select one profile's lessons from a whole-class Shahaf timetable."""

    shared = {_text(str(value)) for value in spec.get("shared_subjects", [])}
    selectors = [item for item in spec.get("selectors", []) if isinstance(item, dict)]
    selected: list[Lesson] = []
    for lesson in lessons:
        if _text(lesson.subject) in shared or any(
            _selector_matches(lesson, selector) for selector in selectors
        ):
            selected.append(lesson)

    # Physical education and a few other shared rows can be repeated for
    # parallel groups.  One period must produce one personal lesson.
    deduped: dict[tuple[Any, ...], Lesson] = {}
    for lesson in selected:
        key = (lesson.date, lesson.period, _text(lesson.subject))
        previous = deduped.get(key)
        if previous is None or (not previous.teacher and lesson.teacher):
            deduped[key] = lesson
    return sorted(
        deduped.values(), key=lambda item: (item.date, item.period, _text(item.subject))
    )


def _change_matches(change: PublishedChange, spec: dict[str, Any]) -> bool:
    shared = {_text(str(value)) for value in spec.get("shared_subjects", [])}
    if change.subject and _text(change.subject) in shared:
        return True
    selectors = [item for item in spec.get("selectors", []) if isinstance(item, dict)]
    for selector in selectors:
        periods = selector.get("periods")
        weekdays = selector.get("weekdays")
        if periods and change.period not in {int(value) for value in periods}:
            continue
        if weekdays and change.date.weekday() not in {int(value) for value in weekdays}:
            continue
        subject = str(selector.get("subject", ""))
        teacher = str(selector.get("teacher", ""))
        room = str(selector.get("room", ""))
        if subject and not _matches(change.subject, subject):
            continue
        if change.teacher and teacher and not _matches(change.teacher, teacher):
            continue
        if change.room and room and not _matches(change.room, room):
            continue
        if change.subject or change.teacher or change.room:
            return True
    return not change.subject and not change.teacher and not change.room


def select_changes(changes: list[PublishedChange], spec: dict[str, Any]) -> list[PublishedChange]:
    return [change for change in changes if _change_matches(change, spec)]


def apply_changes(lessons: list[Lesson], changes: list[PublishedChange]) -> list[Lesson]:
    """Apply selected, date-scoped changes to dated public timetable rows."""

    result = list(lessons)
    for change in sorted(changes, key=lambda item: (item.date, item.period, item.kind)):
        matches = [
            index
            for index, lesson in enumerate(result)
            if lesson.date == change.date and lesson.period == change.period
        ]
        if change.kind == "cancelled":
            result = [
                lesson
                for index, lesson in enumerate(result)
                if index not in matches
            ]
            continue
        if change.kind == "added":
            start, end = _change_times(change)
            result.append(
                Lesson(
                    change.date,
                    change.period,
                    start,
                    end,
                    change.subject,
                    change.teacher or "",
                    change.room or "",
                )
            )
            continue
        if not matches:
            continue
        index = matches[0]
        old = result[index]
        target_period = change.new_period or old.period
        default_start, default_end = PERIOD_TIMES.get(target_period, (old.start, old.end))
        result[index] = replace(
            old,
            period=target_period,
            start=change.start or default_start,
            end=change.end or default_end,
            subject=change.subject or old.subject,
            teacher=change.teacher if change.teacher is not None else old.teacher,
            room=change.room if change.room is not None else old.room,
        )
    return sorted(result, key=lambda item: (item.date, item.period, _text(item.subject)))


def _change_times(change: PublishedChange) -> tuple[time, time]:
    default_start, default_end = PERIOD_TIMES.get(change.new_period or change.period, (time(0), time(0)))
    return change.start or default_start, change.end or default_end


def select_exams(exams: list[Exam], spec: dict[str, Any]) -> list[Exam]:
    terms = [_text(str(value)) for value in spec.get("exam_terms", [])]
    exact_terms = {_text(str(value)) for value in spec.get("exam_exact_terms", [])}
    return [
        exam
        for exam in exams
        if (not exact_terms or _text(exam.subject) in exact_terms)
        and any(term and (term in _text(exam.subject) or term in _text(exam.group)) for term in terms)
    ]


def lesson_to_dict(lesson: Lesson) -> dict[str, Any]:
    return {
        "date": lesson.date.isoformat(),
        "period": lesson.period,
        "subject": lesson.subject,
        "teacher": lesson.teacher,
        "room": lesson.room,
        "start": lesson.start.strftime("%H:%M"),
        "end": lesson.end.strftime("%H:%M"),
    }
