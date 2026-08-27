from __future__ import annotations

from datetime import date, datetime, time
import unittest

from shahaf_sync.ics import parse_calendar
from shahaf_sync.model import PublishedChange, SourceSnapshot
from shahaf_sync.reconcile import reconcile_calendar
from shahaf_sync.site import build_schedule


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


MATH_ICS = ICS.replace(
    "lesson-1@example",
    "math-1@example",
).replace(
    "20260906T083000",
    "20260901T083000",
).replace(
    "20260906T091000",
    "20260901T091000",
).replace(
    "ספרות — שעה 1",
    "מתמטיקה — שעה 1",
).replace(
    "מורה: בר סבן",
    "מורה: אפי כהן",
)


class ReconcileTests(unittest.TestCase):
    def snapshot(self, changes: list[PublishedChange]) -> SourceSnapshot:
        return SourceSnapshot(
            lessons=[],
            covered_dates={item.date for item in changes},
            update_text="fresh",
            source_url="test",
            changes=changes,
        )

    def test_cancellation_adds_exception(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
                self.snapshot([PublishedChange(date(2026, 9, 6), 1, "ספרות", "cancelled")]),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual([change.kind for change in changes], ["cancelled"])
        self.assertIn("20260906T083000", calendar.render())

    def test_cancellation_is_limited_to_one_recurring_occurrence(self) -> None:
        calendar = parse_calendar(ICS)
        reconcile_calendar(
            calendar,
            self.snapshot([PublishedChange(date(2026, 9, 6), 1, "ספרות", "cancelled")]),
            date(2026, 9, 6),
            date(2026, 9, 20),
        )
        event = calendar.events[0]
        occurrences = event.occurrences(
            datetime(2026, 9, 6), datetime(2026, 9, 20, 23, 59)
        )
        self.assertEqual([item.date() for item in occurrences], [date(2026, 9, 13), date(2026, 9, 20)])

    def test_tuesday_first_hour_math_cancellation_does_not_remove_other_tuesdays(self) -> None:
        calendar = parse_calendar(MATH_ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([PublishedChange(date(2026, 9, 1), 1, "מתמטיקה", "cancelled")]),
            date(2026, 9, 1),
            date(2026, 9, 15),
        )
        self.assertEqual([change.kind for change in changes], ["cancelled"])
        event = calendar.events[0]
        occurrences = event.occurrences(
            datetime(2026, 9, 1), datetime(2026, 9, 15, 23, 59)
        )
        self.assertEqual([item.date() for item in occurrences], [date(2026, 9, 8), date(2026, 9, 15)])
        self.assertIn("20260901T083000", calendar.render())

    def test_teacher_or_room_change_creates_override(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([
                PublishedChange(
                    date(2026, 9, 6), 1, "ספרות", "changed", teacher="מורה מחליף", room="208"
                )
            ]),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual([change.kind for change in changes], ["changed"])
        self.assertIn("מורה מחליף", calendar.render())
        self.assertIn("RECURRENCE-ID;TZID=Asia/Jerusalem:20260906T083000", calendar.render())

    def test_time_change_creates_date_scoped_override(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([
                PublishedChange(
                    date(2026, 9, 6), 1, "ספרות", "changed", start=time(8, 45), end=time(9, 25)
                )
            ]),
            date(2026, 9, 6),
            date(2026, 9, 20),
        )
        self.assertEqual([change.kind for change in changes], ["changed"])
        rendered = calendar.render()
        self.assertIn("DTSTART;TZID=Asia/Jerusalem:20260906T084500", rendered)
        self.assertIn("DTEND;TZID=Asia/Jerusalem:20260906T092500", rendered)
        self.assertIn("RECURRENCE-ID;TZID=Asia/Jerusalem:20260906T083000", rendered)
        self.assertEqual(len(calendar.events[0].exdates()), 0)

    def test_reordered_teacher_and_room_are_not_changes(self) -> None:
        calendar = parse_calendar(ICS.replace("DESCRIPTION:מורה: בר סבן", "LOCATION:208 — י״א 8\r\nDESCRIPTION:מורה: בר סבן"))
        changes = reconcile_calendar(
            calendar,
            self.snapshot([
                PublishedChange(date(2026, 9, 6), 1, "ספרות", "changed", teacher="סבן בר", room="י״א 8 - 208")
            ]),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual(changes, [])

    def test_build_schedule_expands_recurring_lesson_for_live_view(self) -> None:
        calendar = parse_calendar(ICS)
        schedule = build_schedule(calendar, "2026-09-06", "2026-09-06")
        self.assertEqual(len(schedule), 1)
        self.assertEqual(schedule[0]["subject"], "ספרות")
        self.assertEqual(schedule[0]["start"], "08:30")
        self.assertEqual(schedule[0]["end"], "09:10")
        self.assertEqual(schedule[0]["teacher"], "בר סבן")

    def test_move_and_added_lesson_are_handled(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([
                PublishedChange(date(2026, 9, 6), 1, "ספרות", "changed", new_period=2),
                PublishedChange(date(2026, 9, 6), 3, "ספרות", "added", start=time(10, 5), end=time(10, 45)),
            ]),
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
            self.snapshot([]),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual(changes, [])

    def test_explicit_changes_do_not_cancel_unmentioned_events(self) -> None:
        calendar = parse_calendar(ICS)
        changes = reconcile_calendar(
            calendar,
            self.snapshot([PublishedChange(date(2026, 9, 6), 2, "מתמטיקה", "cancelled")]),
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        self.assertEqual(changes, [])
        self.assertNotIn("EXDATE", calendar.render())


if __name__ == "__main__":
    unittest.main()
