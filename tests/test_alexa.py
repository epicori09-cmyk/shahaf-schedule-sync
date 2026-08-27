from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from shahaf_sync.alexa import (
    build_reminder_payload,
    build_wake_plan,
    reminder_id,
)


class AlexaWakePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zone = ZoneInfo("Asia/Jerusalem")
        self.schedule = [
            {"date": "2026-09-01", "period": 1, "subject": "Math", "start": "08:30", "end": "09:10"},
            {"date": "2026-09-01", "period": 2, "subject": "English", "start": "09:10", "end": "09:50"},
            {"date": "2026-09-02", "period": 4, "subject": "Computer Science", "start": "10:45", "end": "11:25"},
        ]

    def test_normal_first_lesson_uses_75_minute_buffer(self) -> None:
        plan = build_wake_plan(
            {"schedule": self.schedule, "schedule_available": True, "stale": False},
            datetime(2026, 9, 1, 6, 0, tzinfo=self.zone),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.date.isoformat(), "2026-09-01")
        self.assertEqual(plan.wake_time.strftime("%H:%M"), "07:15")
        self.assertEqual(plan.first_subject, "Math")

    def test_later_first_lesson_moves_wake_time_later(self) -> None:
        plan = build_wake_plan(
            {"schedule": self.schedule, "schedule_available": True, "stale": False},
            datetime(2026, 9, 2, 6, 0, tzinfo=self.zone),
        )
        self.assertEqual(plan.wake_time.strftime("%H:%M"), "09:30")

    def test_no_school_day_has_no_reminder(self) -> None:
        plan = build_wake_plan(
            {"schedule": self.schedule, "schedule_available": True, "stale": False},
            datetime(2026, 9, 5, 6, 0, tzinfo=self.zone),
        )
        self.assertIsNone(plan)

    def test_stale_schedule_falls_back_to_default_time(self) -> None:
        plan = build_wake_plan(
            {"schedule": self.schedule, "schedule_available": True, "stale": True},
            datetime(2026, 9, 1, 6, 0, tzinfo=self.zone),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.wake_time.strftime("%H:%M"), "07:15")
        self.assertTrue(plan.used_default)

    def test_invalid_schedule_falls_back_without_using_untrusted_lessons(self) -> None:
        plan = build_wake_plan(
            {"schedule": "not-a-list", "schedule_available": False, "stale": True},
            datetime(2026, 9, 1, 6, 0, tzinfo=self.zone),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.wake_time.strftime("%H:%M"), "07:15")
        self.assertIsNone(plan.first_subject)

    def test_reminder_id_and_payload_are_deterministic_and_timezone_aware(self) -> None:
        plan = build_wake_plan(
            {"schedule": self.schedule, "schedule_available": True, "stale": False},
            datetime(2026, 9, 1, 6, 0, tzinfo=self.zone),
        )
        self.assertEqual(reminder_id(plan), "school-wake-2026-09-01")
        payload = build_reminder_payload(plan)
        self.assertEqual(payload["trigger"]["type"], "SCHEDULED_ABSOLUTE")
        self.assertEqual(payload["trigger"]["scheduledTime"], "2026-09-01T07:15:00")
        self.assertEqual(payload["trigger"]["timeZoneId"], "Asia/Jerusalem")
        self.assertIn("Math", payload["alertInfo"]["spokenInfo"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
