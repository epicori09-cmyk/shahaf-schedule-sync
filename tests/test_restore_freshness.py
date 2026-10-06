from datetime import datetime
from zoneinfo import ZoneInfo
import json
import unittest

from shahaf_sync.alarm_controls import apply_alarm_controls


class RestoreFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.original = {"next_school_day": "2026-10-07", "wake_time": "06:45", "wake_at": "2026-10-07T06:45:00+03:00", "shortcut_action": "set", "enabled": True, "fallback_status": "none"}
        self.command = {"target_date": "2026-10-07", "action": "set", "wake_at": self.original["wake_at"], "restore_json": json.dumps(self.original), "expires_at": "2026-10-07T20:59:59Z"}
        self.current = datetime(2026, 10, 6, 14, tzinfo=ZoneInfo("Asia/Jerusalem"))
        self.command["reason"] = "Student restored the current alarm baseline"

    def test_restore_tracks_new_unmodified_first_lesson(self):
        fresh = {**self.original, "wake_time": "08:15", "wake_at": "2026-10-07T08:15:00+03:00"}
        actual = apply_alarm_controls(fresh, {}, override=self.command, now=self.current)
        self.assertEqual(actual["wake_time"], "08:15")
        self.assertEqual(actual["wake_at"], fresh["wake_at"])

    def test_manual_move_equal_to_old_baseline_is_not_a_restore(self):
        fresh = {**self.original, "wake_time": "08:15", "wake_at": "2026-10-07T08:15:00+03:00"}
        command = {**self.command, "reason": "Student self-service alarm change"}
        actual = apply_alarm_controls(fresh, {}, override=command, now=self.current)
        self.assertEqual(actual["wake_time"], "06:45")
        self.assertEqual(actual["fallback_status"], "manual-set")

    def test_restore_cannot_resurrect_removed_lessons_or_uncertain_source(self):
        for action, status, stale in [("clear", "no-lessons", False), ("leave", "no-lessons", False), ("leave", "stale", True)]:
            with self.subTest(action=action, status=status):
                fresh = {**self.original, "shortcut_action": action, "fallback_status": status, "wake_at": None, "wake_time": None, "stale": stale}
                actual = apply_alarm_controls(fresh, {}, override=self.command, now=self.current)
                self.assertEqual(actual["shortcut_action"], action)
                self.assertIsNone(actual["wake_at"])
                self.assertFalse(actual["enabled"])
