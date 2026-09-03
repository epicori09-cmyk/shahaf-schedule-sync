from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import re

from .ics import Calendar, IcsEvent, _escape, format_datetime
from .model import Exam, PERIOD_TIMES
from .reconcile import subject_key


EXAM_MARKER = "1"
EXAM_REMINDER_DAYS = 4
EXAM_REMINDER_TIME = time(19, 0)


def _exam_uid(exam: Exam) -> str:
    material = "|".join(
        (
            exam.date.isoformat(),
            subject_key(exam.subject),
            str(exam.start_period),
            str(exam.end_period),
            exam.teacher or exam.group,
            exam.room,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"exam-{digest}@ostrovsky.shahaf-sync"


def _exam_event(exam: Exam) -> IcsEvent:
    start_time = PERIOD_TIMES[exam.start_period][0]
    end_time = PERIOD_TIMES[exam.end_period][1]
    start = datetime.combine(exam.date, start_time)
    end = datetime.combine(exam.date, end_time)
    reminder = datetime.combine(exam.date - timedelta(days=EXAM_REMINDER_DAYS), EXAM_REMINDER_TIME)
    summary = f"מבחן — {exam.subject}"
    detail = exam.detail or f"{exam.subject}, שיעורים {exam.start_period}–{exam.end_period}"
    if exam.teacher and exam.teacher not in detail:
        detail += f"\nקבוצה: {exam.teacher}"
    if exam.room and exam.room not in detail:
        detail += f"\nחדר: {exam.room}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{_exam_uid(exam)}",
        "DTSTAMP:19700101T000000Z",
        f"DTSTART;TZID=Asia/Jerusalem:{format_datetime(start)}",
        f"DTEND;TZID=Asia/Jerusalem:{format_datetime(end)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(f'{detail}\nהתראה: 4 ימים לפני בשעה 19:00')}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "X-SHAHAF-EXAM:1",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(f'תזכורת למבחן: {exam.subject}')}",
        f"TRIGGER;VALUE=DATE-TIME;TZID=Asia/Jerusalem:{format_datetime(reminder)}",
        "END:VALARM",
        "END:VEVENT",
    ]
    return IcsEvent(lines)


def _matches(left: IcsEvent, right: IcsEvent) -> bool:
    return left.render() == right.render()


def reconcile_exam_events(calendar: Calendar, exams: list[Exam]) -> None:
    """Make managed ICS exam events exactly match a trusted Shahaf result."""
    desired = {_exam_uid(exam): exam for exam in exams}
    for event in list(calendar.events):
        if event.get("X-SHAHAF-EXAM") == EXAM_MARKER and event.uid not in desired:
            calendar.events.remove(event)
            calendar.dirty = True

    for uid, exam in desired.items():
        generated = _exam_event(exam)
        existing = next((event for event in calendar.events if event.uid == uid), None)
        if existing is not None and _matches(existing, generated):
            continue
        if existing is None:
            calendar.events.append(generated)
        else:
            calendar.events[calendar.events.index(existing)] = generated
        calendar.dirty = True
