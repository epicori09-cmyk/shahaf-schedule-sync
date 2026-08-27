from __future__ import annotations

from datetime import datetime
import unittest

from shahaf_sync.ics import CalendarFormatError, parse_calendar


ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
CALSCALE:GREGORIAN\r
METHOD:PUBLISH\r
X-WR-CALNAME:מערכת בדיקה\r
X-WR-TIMEZONE:Asia/Jerusalem\r
BEGIN:VEVENT\r
UID:lesson-1@example\r
DTSTAMP:20260827T111842Z\r
DTSTART;TZID=Asia/Jerusalem:20260906T083000\r
DTEND;TZID=Asia/Jerusalem:20260906T091000\r
RRULE:FREQ=WEEKLY;UNTIL=20270618T205959Z\r
SUMMARY:ספרות — שעה 1\r
DESCRIPTION:מורה: בר סבן\\nשעה במערכת: 1\\nחדר: 208 — י״א 8\r
LOCATION:208 — י״א 8\r
EXDATE;TZID=Asia/Jerusalem:20260913T083000,20260920T083000\r
STATUS:CONFIRMED\r
TRANSP:OPAQUE\r
END:VEVENT\r
END:VCALENDAR\r
"""


class IcsTests(unittest.TestCase):
    def test_round_trip_preserves_untouched_calendar(self) -> None:
        calendar = parse_calendar(ICS)
        self.assertEqual(calendar.render(), ICS)
        self.assertEqual(len(calendar.events), 1)
        self.assertEqual(calendar.events[0].uid, "lesson-1@example")
        self.assertEqual(calendar.events[0].subject, "ספרות")

    def test_subject_normalization_handles_teacher_in_summary(self) -> None:
        text = ICS.replace("SUMMARY:ספרות — שעה 1", "SUMMARY:ספרות — בר סבן — שעה 1")
        self.assertEqual(parse_calendar(text).events[0].subject, "ספרות")

    def test_expands_weekly_series_and_excludes_dates(self) -> None:
        event = parse_calendar(ICS).events[0]
        occurrences = event.occurrences(
            datetime(2026, 9, 6), datetime(2026, 9, 27, 23, 59)
        )
        self.assertEqual(
            [item.date() for item in occurrences],
            [datetime(2026, 9, 6).date(), datetime(2026, 9, 27).date()],
        )

    def test_add_exdate_is_idempotent_and_folded_safely(self) -> None:
        calendar = parse_calendar(ICS)
        event = calendar.events[0]
        event.add_exdate(datetime(2026, 9, 27, 8, 30))
        event.add_exdate(datetime(2026, 9, 27, 8, 30))
        rendered = calendar.render()
        self.assertEqual(rendered.count("20260927T083000"), 1)
        self.assertIn("EXDATE;TZID=Asia/Jerusalem:", rendered)

    def test_add_recurrence_override_uses_same_uid(self) -> None:
        calendar = parse_calendar(ICS)
        base = calendar.events[0]
        calendar.add_override(
            base,
            original_start=datetime(2026, 9, 6, 8, 30),
            new_start=datetime(2026, 9, 6, 9, 10),
            new_end=datetime(2026, 9, 6, 9, 50),
            summary="ספרות — שעה 2",
            description="מורה: מחליף\\nשעה במערכת: 2",
            location="208 — י״א 8",
        )
        rendered = calendar.render()
        self.assertIn("RECURRENCE-ID;TZID=Asia/Jerusalem:20260906T083000", rendered)
        self.assertIn("DTSTART;TZID=Asia/Jerusalem:20260906T091000", rendered)
        self.assertEqual(rendered.count("UID:lesson-1@example"), 2)

    def test_rejects_non_ics_content(self) -> None:
        with self.assertRaises(CalendarFormatError):
            parse_calendar("from datetime import date\nprint('not an ics')\n")


if __name__ == "__main__":
    unittest.main()
