from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from shahaf_sync.alarm_controls import protect_clock_occurrence


ZONE = ZoneInfo("Asia/Jerusalem")


class ClockOccurrenceTests(unittest.TestCase):
    def check(self, current, target, expected, **extra):
        wake = {"next_school_day": target[:10], "wake_at": target, "wake_time": target[11:16],
                "shortcut_action": "set", "enabled": True, "stale": False, **extra}
        result = protect_clock_occurrence(wake, now=datetime.fromisoformat(current).replace(tzinfo=ZONE))
        self.assertEqual(result["shortcut_action"], expected)
        return result

    def test_both_daily_automations_cannot_create_tomorrow_alarm_this_morning(self):
        for clock in ("05:00", "06:40"):
            with self.subTest(clock=clock):
                self.check("2026-10-06T" + clock, "2026-10-07T06:45:00+03:00", "clear")

    def test_same_day_and_true_next_clock_occurrence_are_allowed(self):
        self.check("2026-10-06T05:00", "2026-10-06T06:45:00+03:00", "set")
        self.check("2026-10-06T06:40", "2026-10-07T06:30:00+03:00", "set")
        self.check("2026-10-06T14:00", "2026-10-07T06:45:00+03:00", "set")

    def test_long_school_gap_cannot_create_friday_alarm_on_thursday(self):
        self.check("2026-10-08T20:00", "2026-10-11T06:45:00+03:00", "clear")

    def test_stale_or_preserve_policy_never_authorizes_deferred_clear(self):
        self.check("2026-10-06T05:00", "2026-10-07T06:45:00+03:00", "leave", stale=True)
        wake = {"next_school_day": "2026-10-07", "wake_at": "2026-10-07T06:45:00+03:00", "shortcut_action": "set"}
        result = protect_clock_occurrence(wake, now=datetime(2026, 10, 6, 5, tzinfo=ZONE), no_lessons_policy="leave")
        self.assertEqual(result["shortcut_action"], "leave")
        for status in ("unavailable", "no-safe-route", "wake-time-bound", "stale"):
            with self.subTest(status=status):
                self.check("2026-10-06T05:00", "2026-10-07T06:45:00+03:00", "leave", fallback_status=status)

    def test_exact_clock_boundary_never_rolls_elapsed_alarm_into_tomorrow(self):
        self.check("2026-10-06T06:45", "2026-10-06T06:45:00+03:00", "leave")
        self.check("2026-10-06T06:45", "2026-10-07T06:45:00+03:00", "set")

    def test_invalid_date_offset_and_elapsed_time_preserve(self):
        for target in ("2026-10-06T04:00:00+03:00", "2026-10-07T06:45:00", "2026-10-07T06:45:30+03:00", "bad"):
            with self.subTest(target=target):
                self.check("2026-10-06T05:00", target, "leave")

    def test_winter_uses_local_clock_not_utc_date(self):
        self.check("2027-01-03T05:00", "2027-01-03T06:45:00+02:00", "set")
        self.check("2027-01-03T05:00", "2027-01-04T06:45:00+02:00", "clear")


if __name__ == "__main__":
    unittest.main()
