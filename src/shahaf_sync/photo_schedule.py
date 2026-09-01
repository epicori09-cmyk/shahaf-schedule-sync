from __future__ import annotations

"""The recurring timetable transcribed from the Shahaf screenshots.

This is intentionally a one-time baseline migration.  The normal sync still
applies date-scoped Shahaf changes on top of these recurring events.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, time
import hashlib

from .ics import Calendar, IcsEvent, _escape, format_datetime
from .model import PERIOD_TIMES


# (Python weekday, period, subject, teacher, room)
PHOTO_WEEKLY_SCHEDULE: tuple[tuple[int, int, str, str, str], ...] = (
    # Sunday
    (6, 0, "חינוך", "ירון דור", "217 — י״א 2"),
    (6, 1, "עברית", "לימור חן", "217 — י״א 2"),
    (6, 2, "חינוך גופני", "יונתן דנישבסקי", ""),
    (6, 3, "עברית", "לימור חן", "217 — י״א 2"),
    (6, 4, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (6, 5, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (6, 6, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (6, 7, "היסטוריה", "ירון דור", "217 — י״א 2"),
    (6, 8, "היסטוריה", "ירון דור", "217 — י״א 2"),
    (6, 9, "דיפלומטיה", "אורית גרינברג", "217 — י״א 2"),
    (6, 10, "דיפלומטיה", "אורית גרינברג", "217 — י״א 2"),
    (6, 11, "הערכה חלופית — מדעי המחשב 1", "רועי ויסברט", "152 — מעבדת מחשבים"),
    (6, 12, "הערכה חלופית — מדעי המחשב 1", "רועי ויסברט", "152 — מעבדת מחשבים"),
    (6, 13, "הערכה חלופית — מדעי המחשב 1", "רועי ויסברט", "152 — מעבדת מחשבים"),
    # Monday
    (0, 0, "תנ״ך", "דוד לוי", "217 — י״א 2"),
    (0, 1, "תנ״ך", "דוד לוי", "217 — י״א 2"),
    (0, 2, "חינוך", "ירון דור", "217 — י״א 2"),
    (0, 3, "ספרות", "דנה לילקובסקי", "217 — י״א 2"),
    (0, 4, "ספרות", "דנה לילקובסקי", "217 — י״א 2"),
    (0, 5, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (0, 6, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (0, 7, "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "214 — י״א 7"),
    (0, 8, "אנגלית 5 יח״ל מואץ", "אירין שפינל", "217 — י״א 2"),
    (0, 9, "אנגלית 5 יח״ל מואץ", "אירין שפינל", "217 — י״א 2"),
    # Tuesday
    (1, 4, "מדעי המחשב 1", "שמרת מן", ""),
    (1, 5, "מדעי המחשב 1", "שמרת מן", ""),
    (1, 6, "מדעי המחשב 1", "שמרת מן", ""),
    (1, 7, "תנ״ך", "דוד לוי", "217 — י״א 2"),
    (1, 10, "עברית", "לימור חן", "217 — י״א 2"),
    (1, 11, "עברית", "לימור חן", "מקוון אינטרנטי"),
    # Wednesday
    (2, 0, "היסטוריה", "ירון דור", "217 — י״א 2"),
    (2, 1, "אנגלית 5 יח״ל מואץ", "אירין שפינל", "217 — י״א 2"),
    (2, 2, "אנגלית 5 יח״ל מואץ", "אירין שפינל", "217 — י״א 2"),
    (2, 3, "עברית", "לימור חן", "217 — י״א 2"),
    (2, 4, "עברית", "לימור חן", "217 — י״א 2"),
    (2, 5, "חינוך גופני", "יונתן דנישבסקי", ""),
    (2, 6, "היסטוריה", "ירון דור", "217 — י״א 2"),
    (2, 7, "היסטוריה", "ירון דור", "217 — י״א 2"),
    (2, 10, "סייבר — טלפונים חכמים", "רועי ויסברט", "152 — מעבדת מחשבים"),
    (2, 11, "סייבר — טלפונים חכמים", "רועי ויסברט", "152 — מעבדת מחשבים"),
    (2, 12, "סייבר — טלפונים חכמים", "רועי ויסברט", "152 — מעבדת מחשבים"),
    (2, 13, "סייבר — טלפונים חכמים", "רועי ויסברט", "152 — מעבדת מחשבים"),
    # Thursday
    (3, 1, "מדעי המחשב 1", "שמרת מן", ""),
    (3, 2, "מדעי המחשב 1", "שמרת מן", ""),
    (3, 3, "מדעי המחשב 1", "שמרת מן", ""),
    (3, 4, "דיפלומטיה", "אורית גרינברג", "217 — י״א 2"),
    (3, 5, "דיפלומטיה", "אורית גרינברג", "217 — י״א 2"),
    (3, 7, "ספרות", "דנה לילקובסקי", "217 — י״א 2"),
    (3, 10, "עברית", "לימור חן", "217 — י״א 2"),
    (3, 11, "עברית", "לימור חן", "מקוון אינטרנטי"),
)


PHOTO_FIRST_DATES: dict[int, date] = {
    0: date(2026, 9, 7),
    1: date(2026, 9, 1),
    2: date(2026, 9, 2),
    3: date(2026, 9, 3),
    6: date(2026, 9, 6),
}

_RRULE = "FREQ=WEEKLY;UNTIL=20270618T205959Z"


def _event_teacher(event: IcsEvent) -> str:
    for line in event.description.splitlines():
        if line.strip().startswith("מורה:"):
            return line.split(":", 1)[1].strip()
    return ""


def _occurrence(day: date, period: int) -> datetime:
    start, _end = PERIOD_TIMES[period]
    return datetime.combine(day, start)


def _uid(weekday: int, period: int, subject: str, teacher: str, room: str) -> str:
    key = "|".join((str(weekday), str(period), subject, teacher, room)).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()[:24]
    return f"photo-{digest}@ostrovsky.shahaf-sync"


def _new_event(
    uid: str,
    start: datetime,
    end: datetime,
    subject: str,
    teacher: str,
    period: int,
    room: str,
    dtstamp: str | None,
) -> IcsEvent:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp or '19700101T000000Z'}",
        f"DTSTART;TZID=Asia/Jerusalem:{format_datetime(start)}",
        f"DTEND;TZID=Asia/Jerusalem:{format_datetime(end)}",
        f"RRULE:{_RRULE}",
        f"SUMMARY:{_escape(f'{subject} — {teacher} — שעה {period}')}",
        f"DESCRIPTION:{_escape(f'מורה: {teacher}\nשעה במערכת: {period}')}",
    ]
    if room:
        lines.append(f"LOCATION:{_escape(room)}")
    lines.extend(["STATUS:CONFIRMED", "TRANSP:OPAQUE", "END:VEVENT"])
    return IcsEvent(lines)


def _prepare_event(
    old: IcsEvent | None,
    weekday: int,
    period: int,
    subject: str,
    teacher: str,
    room: str,
) -> IcsEvent:
    first_day = PHOTO_FIRST_DATES[weekday]
    start_time, end_time = PERIOD_TIMES[period]
    start = datetime.combine(first_day, start_time)
    end = datetime.combine(first_day, end_time)
    if old is None:
        event = _new_event(
            _uid(weekday, period, subject, teacher, room),
            start,
            end,
            subject,
            teacher,
            period,
            room,
            None,
        )
    else:
        event = IcsEvent(list(old.lines))
        event._set("DTSTART", format_datetime(start), {"TZID": "Asia/Jerusalem"})
        event._set("DTEND", format_datetime(end), {"TZID": "Asia/Jerusalem"})
        event._set("RRULE", _RRULE)
        event._set_escaped("SUMMARY", f"{subject} — {teacher} — שעה {period}")
        event._set_escaped(
            "DESCRIPTION", f"מורה: {teacher}\nשעה במערכת: {period}"
        )
        if room:
            event._set_escaped("LOCATION", room)
        else:
            event._remove("LOCATION")
        event._set("STATUS", "CONFIRMED")

    # EXDATEs are rebuilt below from the old records, so the migration cannot
    # accidentally keep an exclusion attached to the wrong weekly timetable.
    event._remove("EXDATE")
    event._remove("X-SHAHAF-AUTO-EXDATE")
    return event


def rebuild_calendar(calendar: Calendar) -> Calendar:
    """Replace recurring weekly lessons with the screenshot timetable.

    Existing recurring UIDs are reused by slot where possible.  One-off events
    (including special days) are kept byte-for-byte.  Full-day exclusions are
    copied to every lesson on that weekday; a smaller manual exclusion stays on
    its original period, while automatic Shahaf exclusions transfer only when
    the teacher still matches.
    """

    old_recurring = [event for event in calendar.events if event.is_recurring]
    old_by_slot: dict[tuple[int, int], IcsEvent] = {}
    old_slot_counts: Counter[int] = Counter()
    manual_by_slot: defaultdict[tuple[int, int], set[date]] = defaultdict(set)
    auto_by_slot_teacher: defaultdict[tuple[int, int, str], set[date]] = defaultdict(set)
    manual_date_counts: Counter[date] = Counter()

    for event in old_recurring:
        if event.period is None:
            continue
        slot = (event.start.weekday(), event.period)
        old_by_slot.setdefault(slot, event)
        old_slot_counts[event.start.weekday()] += 1
        manual_dates = {item.date() for item in event.exdates() - event.auto_exdates()}
        for item in manual_dates:
            manual_by_slot[slot].add(item)
            manual_date_counts[item] += 1
        teacher = _event_teacher(event)
        for item in event.auto_exdates():
            auto_by_slot_teacher[(slot[0], slot[1], teacher)].add(item.date())

    global_dates_by_weekday: defaultdict[int, set[date]] = defaultdict(set)
    for item, count in manual_date_counts.items():
        weekday = item.weekday()
        if count == old_slot_counts[weekday]:
            global_dates_by_weekday[weekday].add(item)

    rebuilt: list[IcsEvent] = []
    for weekday, period, subject, teacher, room in PHOTO_WEEKLY_SCHEDULE:
        old = old_by_slot.get((weekday, period))
        event = _prepare_event(old, weekday, period, subject, teacher, room)

        exclusions = set(global_dates_by_weekday[weekday])
        exclusions.update(manual_by_slot[(weekday, period)])
        for item in sorted(exclusions):
            event.add_exdate(_occurrence(item, period), automatic=False)

        matching_auto = auto_by_slot_teacher[(weekday, period, teacher)]
        for item in sorted(matching_auto):
            event.add_exdate(_occurrence(item, period), automatic=True)
        rebuilt.append(event)

    preserved = [event for event in calendar.events if not event.is_recurring]
    return Calendar(
        original_text=calendar.original_text,
        header_lines=calendar.header_lines,
        footer_lines=calendar.footer_lines,
        events=rebuilt + preserved,
        dirty=True,
    )
