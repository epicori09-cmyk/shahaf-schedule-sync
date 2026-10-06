from datetime import date, datetime
import unittest

from shahaf_sync.ics import parse_calendar
from shahaf_sync.model import ShahafEvent
from shahaf_sync.nim import EventSafetyDecision
from shahaf_sync.reconcile import reconcile_event_entries


ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
X-WR-TIMEZONE:Asia/Jerusalem\r
BEGIN:VEVENT\r
UID:lesson@example\r
DTSTAMP:20260827T111842Z\r
DTSTART;TZID=Asia/Jerusalem:20260909T083000\r
DTEND;TZID=Asia/Jerusalem:20260909T091000\r
RRULE:FREQ=WEEKLY;UNTIL=20260923T205959Z\r
SUMMARY:Math — שעה 1\r
DESCRIPTION:מורה: Teacher\\nשעה במערכת: 1\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


WINDOW_START = date(2026, 9, 9)
WINDOW_END = date(2026, 9, 23)
OCCURRENCE = datetime(2026, 9, 9, 8, 30)


class EventSuppressionRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = ShahafEvent(
            date(2026, 9, 9),
            "יום למידה א-סינכרוני",
            start_period=0,
            end_period=14,
            class_numbers=(2,),
            class_scope="יא-2",
        )
        self.decisions = {
            (
                self.event.date,
                self.event.title,
                self.event.start_period,
                self.event.end_period,
                self.event.start,
                self.event.end,
                self.event.class_scope,
            ): EventSafetyDecision(
                "remote_learning", True, "low", "No in-person attendance."
            )
        }

    def _calendar_with_confirmed_suppression(self):
        calendar = parse_calendar(ICS)
        reconcile_event_entries(
            calendar,
            [self.event],
            self.decisions,
            2,
            WINDOW_START,
            WINDOW_END,
        )
        return calendar

    def test_absent_event_releases_only_its_owned_exclusion(self) -> None:
        calendar = self._calendar_with_confirmed_suppression()
        lesson = calendar.events[0]
        self.assertIn(OCCURRENCE, lesson.event_exdates())

        reconcile_event_entries(
            calendar,
            [],
            {},
            2,
            WINDOW_START,
            WINDOW_END,
        )

        self.assertNotIn(OCCURRENCE, lesson.event_exdates())
        self.assertNotIn(OCCURRENCE, lesson.exdates())
        self.assertNotIn("X-SHAHAF-EVENT-EXDATE", calendar.render())

    def test_recovery_preserves_cancellation_and_manual_exdates(self) -> None:
        calendar = self._calendar_with_confirmed_suppression()
        lesson = calendar.events[0]
        cancellation_occurrence = datetime(2026, 9, 16, 8, 30)
        lesson.add_exdate(OCCURRENCE, automatic=False)
        lesson.add_exdate(cancellation_occurrence)

        reconcile_event_entries(
            calendar,
            [],
            {},
            2,
            WINDOW_START,
            WINDOW_END,
        )

        self.assertNotIn(OCCURRENCE, lesson.event_exdates())
        self.assertIn(OCCURRENCE, lesson.exdates())
        self.assertIn(OCCURRENCE, lesson.manual_exdates())
        self.assertIn(cancellation_occurrence, lesson.exdates())
        self.assertIn(cancellation_occurrence, lesson.auto_exdates())
        self.assertNotIn(cancellation_occurrence, lesson.event_exdates())

    def test_legacy_raw_exdate_at_same_occurrence_survives_recovery(self) -> None:
        legacy_ics = ICS.replace(
            "STATUS:CONFIRMED",
            "EXDATE;TZID=Asia/Jerusalem:20260909T083000\r\nSTATUS:CONFIRMED",
        )
        calendar = parse_calendar(legacy_ics)
        lesson = calendar.events[0]

        reconcile_event_entries(
            calendar,
            [self.event],
            self.decisions,
            2,
            WINDOW_START,
            WINDOW_END,
        )
        self.assertIn(OCCURRENCE, lesson.event_exdates())
        self.assertIn(OCCURRENCE, lesson.manual_exdates())

        reconcile_event_entries(
            calendar,
            [],
            {},
            2,
            WINDOW_START,
            WINDOW_END,
        )

        self.assertNotIn(OCCURRENCE, lesson.event_exdates())
        self.assertIn(OCCURRENCE, lesson.exdates())
        self.assertIn(OCCURRENCE, lesson.manual_exdates())

    def test_uncertain_current_event_keeps_existing_exclusion(self) -> None:
        calendar = self._calendar_with_confirmed_suppression()
        uncertain = {
            next(iter(self.decisions)): EventSafetyDecision(
                "uncertain", False, "high", "The event retrieval/classification is uncertain."
            )
        }

        reconcile_event_entries(
            calendar,
            [self.event],
            uncertain,
            2,
            WINDOW_START,
            WINDOW_END,
        )

        self.assertIn(OCCURRENCE, calendar.events[0].event_exdates())
        self.assertIn(OCCURRENCE, calendar.events[0].exdates())


if __name__ == "__main__":
    unittest.main()
