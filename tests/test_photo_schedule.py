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
    def test_partial_old_weekday_does_not_broaden_manual_exclusion(self) -> None:
        calendar = rebuild_calendar(parse_calendar(OLD_ICS))
        excluded = [event.period for event in calendar.events if event.is_recurring
                    and event.start.weekday() == 6 and event.exdates()]
        self.assertEqual(excluded, [1])

    def test_reordered_teacher_preserves_automatic_cancellation(self) -> None:
        text = OLD_ICS.replace("מורה: old", "מורה: חן לימור").replace(
            "EXDATE;TZID=Asia/Jerusalem:20260913T083000",
            "EXDATE;TZID=Asia/Jerusalem:20260913T083000\r\nX-SHAHAF-AUTO-EXDATE;TZID=Asia/Jerusalem:20260913T083000")
        calendar = rebuild_calendar(parse_calendar(text))
        event = next(item for item in calendar.events if item.is_recurring
                     and item.start.weekday() == 6 and item.period == 1)
        self.assertEqual({item.date() for item in event.auto_exdates()}, {date(2026, 9, 13)})

    def test_duplicate_recurring_slot_fails_before_mutating_input(self) -> None:
        calendar = parse_calendar(OLD_ICS)
        calendar.events.append(parse_calendar(OLD_ICS.replace(
            "old-sunday-period-1@example", "duplicate@example")).events[0])
        original_lines = [list(event.lines) for event in calendar.events]
        with self.assertRaisesRegex(ValueError, "Duplicate recurring"):
            rebuild_calendar(calendar)
        self.assertEqual([event.lines for event in calendar.events], original_lines)

    def test_photo_timetable_contains_the_two_sport_corrections(self) -> None:
        self.assertEqual(len(PHOTO_WEEKLY_SCHEDULE), 48)
        self.assertIn((6, 2, "חינוך גופני", "יונתן דנישבסקי", ""), PHOTO_WEEKLY_SCHEDULE)
        self.assertIn((2, 5, "חינוך גופני", "יונתן דנישבסקי", ""), PHOTO_WEEKLY_SCHEDULE)
        self.assertNotIn((1, 10, "עברית", "לימור חן", "217 — י״א 2"), PHOTO_WEEKLY_SCHEDULE)
        self.assertNotIn((1, 11, "עברית", "לימור חן", "מקוון אינטרנטי"), PHOTO_WEEKLY_SCHEDULE)

    def test_rebuild_replaces_recurring_slots_and_preserves_special_records(self) -> None:
        calendar = rebuild_calendar(parse_calendar(OLD_ICS))
        recurring = [event for event in calendar.events if event.is_recurring]
        self.assertEqual(len(recurring), 48)
        sunday_period_1 = next(event for event in recurring if event.start.weekday() == 6 and event.period == 1)
        self.assertEqual(sunday_period_1.uid, "old-sunday-period-1@example")
        self.assertEqual(sunday_period_1.subject, "עברית")
        self.assertIn(date(2026, 9, 13), {item.date() for item in sunday_period_1.exdates()})
        self.assertTrue(any(event.uid == "memorial@example" and not event.is_recurring for event in calendar.events))


if __name__ == "__main__":
    unittest.main()
