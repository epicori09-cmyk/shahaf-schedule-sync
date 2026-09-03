from __future__ import annotations

from datetime import date, datetime
import unittest

from shahaf_sync.events import apply_event_decisions, event_requires_review, event_to_dict
from shahaf_sync.ics import parse_calendar
from shahaf_sync.model import ShahafEvent
from shahaf_sync.nim import EventSafetyDecision
from shahaf_sync.reconcile import reconcile_event_entries
from shahaf_sync.site import build_schedule


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
DESCRIPTION:מורה: Teacher\nשעה במערכת: 1\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


class EventProcessingTests(unittest.TestCase):
    def test_async_event_suppresses_only_its_date_and_periods(self) -> None:
        event = ShahafEvent(
            date(2026, 9, 9),
            "יום למידה א-סינכרוני",
            start_period=0,
            end_period=14,
            class_numbers=(2,),
            class_scope="יא-2",
        )
        schedule = [
            {"date": "2026-09-09", "period": 1, "start": "08:30", "end": "09:10", "subject": "Math"},
            {"date": "2026-09-09", "period": 8, "start": "14:05", "end": "14:45", "subject": "English"},
            {"date": "2026-09-10", "period": 1, "start": "08:30", "end": "09:10", "subject": "Math"},
        ]
        decision = EventSafetyDecision("remote_learning", True, "low", "No in-person attendance.")
        filtered = apply_event_decisions(schedule, [event], {(
            event.date, event.title, event.start_period, event.end_period, event.start, event.end, event.class_scope
        ): decision})
        self.assertEqual([item["date"] for item in filtered], ["2026-09-10"])

    def test_ordinary_trip_is_overlay_only(self) -> None:
        event = ShahafEvent(
            date(2026, 9, 7),
            "טיול פתיחת שנה",
            start_period=0,
            end_period=14,
            class_numbers=(2,),
            class_scope="יא-2",
        )
        self.assertFalse(event_requires_review(event))
        schedule = [{"date": "2026-09-07", "period": 1, "start": "08:30", "end": "09:10"}]
        self.assertEqual(apply_event_decisions(schedule, [event], {}), schedule)
        rendered = event_to_dict(event)
        self.assertEqual(rendered["classification"], "overlay")
        self.assertFalse(rendered["suppresses_lessons"])

    def test_event_scope_is_profile_specific(self) -> None:
        event = ShahafEvent(date(2026, 9, 9), "אין לימודים", start_period=0, end_period=14, class_numbers=(1,))
        self.assertFalse(event.applies_to_class(2))
        self.assertTrue(event.applies_to_class(1))

    def test_event_reconciliation_hides_one_occurrence_and_adds_overlay_entry(self) -> None:
        event = ShahafEvent(
            date(2026, 9, 9),
            "יום למידה א-סינכרוני",
            start_period=0,
            end_period=14,
            class_numbers=(2,),
            class_scope="יא-2",
        )
        calendar = parse_calendar(ICS)
        decision = EventSafetyDecision("remote_learning", True, "low", "No in-person attendance.")
        reconcile_event_entries(
            calendar,
            [event],
            {(event.date, event.title, event.start_period, event.end_period, event.start, event.end, event.class_scope): decision},
            2,
            date(2026, 9, 9),
            date(2026, 9, 23),
        )
        schedule = build_schedule(calendar, "2026-09-09", "2026-09-23")
        self.assertEqual([item["date"] for item in schedule], ["2026-09-16", "2026-09-23"])
        self.assertEqual(len([item for item in calendar.events if item.get("X-SHAHAF-EVENT") == "1"]), 1)
        self.assertIn("X-SHAHAF-EVENT-EXDATE", calendar.render())


if __name__ == "__main__":
    unittest.main()
