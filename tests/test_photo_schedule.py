from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.ics import parse_calendar
from shahaf_sync.photo_schedule import PHOTO_WEEKLY_SCHEDULE, rebuild_calendar


OLD_ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
X-WR-TIMEZONE:Asia/Jerusalem\r
BEGIN:VEVENT\r
UID:old-sunday-period-1@example\r
DTSTAMP:20260827T111842Z\r
DTSTART;TZID=Asia/Jerusalem:20260906T083000\r
DTEND;TZID=Asia/Jerusalem:20260906T091000\r
RRULE:FREQ=WEEKLY;UNTIL=20270618T205959Z\r
EXDATE;TZID=Asia/Jerusalem:20260913T083000\r
SUMMARY:old — שעה 1\r
DESCRIPTION:מורה: old\r
STATUS:CONFIRMED\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:memorial@example\r
DTSTAMP:20260827T111842Z\r
DTSTART;TZID=Asia/Jerusalem:20270511T113500\r
DTEND;TZID=Asia/Jerusalem:20270511T120000\r
SUMMARY:Memorial\r
DESCRIPTION:Special school day\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


class PhotoScheduleTests(unittest.TestCase):
    def test_photo_timetable_contains_the_two_sport_corrections(self) -> None:
        self.assertEqual(len(PHOTO_WEEKLY_SCHEDULE), 50)
        self.assertIn((6, 2, "חינוך גופני", "יונתן דנישבסקי", ""), PHOTO_WEEKLY_SCHEDULE)
        self.assertIn((2, 5, "חינוך גופני", "יונתן דנישבסקי", ""), PHOTO_WEEKLY_SCHEDULE)

    def test_rebuild_replaces_recurring_slots_and_preserves_special_records(self) -> None:
        calendar = rebuild_calendar(parse_calendar(OLD_ICS))
        recurring = [event for event in calendar.events if event.is_recurring]
        self.assertEqual(len(recurring), 50)
        sunday_period_1 = next(event for event in recurring if event.start.weekday() == 6 and event.period == 1)
        self.assertEqual(sunday_period_1.uid, "old-sunday-period-1@example")
        self.assertEqual(sunday_period_1.subject, "עברית")
        self.assertIn(date(2026, 9, 13), {item.date() for item in sunday_period_1.exdates()})
        self.assertTrue(any(event.uid == "memorial@example" and not event.is_recurring for event in calendar.events))


if __name__ == "__main__":
    unittest.main()
