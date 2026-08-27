from __future__ import annotations

from datetime import date, datetime, time
import unittest

from shahaf_sync.ics import parse_calendar
from shahaf_sync.model import Lesson, SourceSnapshot
from shahaf_sync.reconcile import reconcile_calendar


ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
X-WR-TIMEZONE:Asia/Jerusalem\r
BEGIN:VEVENT\r
UID:lesson-1@example\r
DTSTAMP:20260827T111842Z\r
DTSTART;TZID=Asia/Jerusalem:20260906T083000\r
DTEND;TZID=Asia/Jerusalem:20260906T091000\r
RRULE:FREQ=WEEKLY;UNTIL=20270618T205959Z\r
SUMMARY:ספרות — שעה 1\r
DESCRIPTION:מורה: בר סבן\\nשעה במערכת: 1\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


def lesson(day: date, period: int, subject: str, teacher: str = "בר סבן", room: str = "") -> Lesson:
    starts = {1: time(8, 30), 2: time(9, 10), 3: time(10, 5)}
    ends = {1: time(9, 10), 2: time(9, 50), 3: time(10, 45)}
    return Lesson(day, period, starts[period], ends[period], subject, teacher, room)


class ReconcileTests(unittest.TestCase):
    def snapshot(self, lessons: list[Lesson], dates: set[date]) -> SourceSnapshot:
        return SourceSnapshot(lessons=lessons, covered_dates=dates, update_text="fresh", source_url="test")

    def test_cancellation_adds_exception(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([], {date(2026, 9, 6)}),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual([change.kind for change in changes], ["cancelled"])
        self.assertIn("20260906T083000", calendar.render())

    def test_cancellation_is_limited_to_one_recurring_occurrence(self) -> None:
        calendar = parse_calendar(ICS)
        reconcile_calendar(
            calendar,
            self.snapshot([], {date(2026, 9, 6)}),
            date(2026, 9, 6),
            date(2026, 9, 20),
        )
        event = calendar.events[0]
        occurrences = event.occurrences(
            datetime(2026, 9, 6), datetime(2026, 9, 20, 23, 59)
        )
        self.assertEqual([item.date() for item in occurrences], [date(2026, 9, 13), date(2026, 9, 20)])

    def test_teacher_or_room_change_creates_override(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot(
                [lesson(date(2026, 9, 6), 1, "ספרות", "מורה מחליף", "208")],
                {date(2026, 9, 6)},
            ),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual([change.kind for change in changes], ["changed"])
        self.assertIn("מורה מחליף", calendar.render())
        self.assertIn("RECURRENCE-ID;TZID=Asia/Jerusalem:20260906T083000", calendar.render())

    def test_move_and_added_lesson_are_handled(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot(
                [
                    lesson(date(2026, 9, 6), 2, "ספרות"),
                    lesson(date(2026, 9, 6), 3, "ספרות"),
                ],
                {date(2026, 9, 6)},
            ),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual([change.kind for change in changes], ["changed", "added"])
        rendered = calendar.render()
        self.assertIn("DTSTART;TZID=Asia/Jerusalem:20260906T091000", rendered)
        self.assertIn("X-SHAHAF-AUTO:1", rendered)

    def test_uncovered_source_does_not_infer_cancellations(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([], set()),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
