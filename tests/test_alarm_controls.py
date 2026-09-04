from __future__ import annotations

from datetime import datetime, timezone, timedelta
import unittest

from shahaf_sync.alarm_controls import (
    apply_alarm_controls,
    normalize_alarm_settings,
    resolve_alarm_settings,
)
from shahaf_sync.site import build_wake_data


ISRAEL = timezone(timedelta(hours=3))


class AlarmControlTests(unittest.TestCase):
    def test_profile_overrides_win_and_label_template_is_resolved(self) -> None:
        settings = resolve_alarm_settings(
            {"wake_buffer_minutes": 75, "label_template": "Shahaf {public_id}"},
            {"wake_buffer_minutes": 90, "alarm_label": "Main {profile_id}"},
            "ABC123",
        )
        self.assertEqual(settings["wake_buffer_minutes"], 90)
        self.assertEqual(settings["alarm_label"], "Main ABC123")

    def test_settings_reject_invalid_rounding_and_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "round_to_minutes"):
            normalize_alarm_settings({"round_to_minutes": 7})
        with self.assertRaisesRegex(ValueError, "min_wake_time"):
            normalize_alarm_settings({"min_wake_time": "09:00", "max_wake_time": "08:00"})

    def test_buffer_rounding_and_label_are_applied_to_managed_wake(self) -> None:
        wake = build_wake_data(
            [{"date": "2026-09-06", "period": 1, "start": "08:30", "subject": "Math"}],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 4, 5, 0, tzinfo=ISRAEL),
            buffer_minutes=80,
            round_to_minutes=5,
        )
        controlled = apply_alarm_controls(
            wake,
            resolve_alarm_settings({}, {"alarm_label": "Shahaf Test"}, "profile-1"),
            now=datetime(2026, 9, 4, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(controlled["wake_time"], "07:10")
        self.assertEqual(controlled["alarm_label"], "Shahaf Test")
        self.assertEqual(controlled["shortcut_action"], "set")

    def test_stale_default_leaves_and_no_lessons_can_leave(self) -> None:
        stale = apply_alarm_controls(
            {"stale": True, "shortcut_action": "leave", "fallback_status": "stale"},
            resolve_alarm_settings({}, {}, "profile-1"),
        )
        self.assertEqual(stale["shortcut_action"], "leave")
        no_lessons = apply_alarm_controls(
            {"stale": False, "shortcut_action": "clear", "fallback_status": "no-lessons", "enabled": False},
            resolve_alarm_settings({}, {"no_lessons_policy": "leave"}, "profile-1"),
        )
        self.assertEqual(no_lessons["shortcut_action"], "leave")

    def test_non_force_override_cannot_replace_on_stale_or_unsafe_data(self) -> None:
        settings = resolve_alarm_settings({}, {}, "profile-1")
        for wake in (
            {"stale": True, "fallback_status": "stale", "shortcut_action": "leave"},
            {"stale": False, "fallback_status": "no-safe-route", "shortcut_action": "leave"},
        ):
            result = apply_alarm_controls(
                wake,
                settings,
                override={
                    "target_date": "2026-09-06",
                    "action": "set",
                    "wake_at": "2026-09-06T06:10:00+03:00",
                    "expires_at": "2026-09-06T20:59:59Z",
                    "force": False,
                },
                now=datetime(2026, 9, 4, 5, 0, tzinfo=ISRAEL),
            )
            self.assertEqual(result["shortcut_action"], "leave")
            self.assertEqual(result["fallback_status"], "unsafe-override-blocked")

    def test_force_override_can_bypass_unsafe_data(self) -> None:
        result = apply_alarm_controls(
            {"stale": True, "fallback_status": "stale", "shortcut_action": "leave"},
            resolve_alarm_settings({}, {}, "profile-1"),
            override={
                "target_date": "2026-09-06",
                "action": "set",
                "wake_at": "2026-09-06T06:10:00+03:00",
                "expires_at": "2026-09-06T20:59:59Z",
                "force": True,
            },
            now=datetime(2026, 9, 4, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["fallback_status"], "manual-set")

    def test_non_integer_numeric_strings_are_rejected(self) -> None:
        for value in ("7.5", "Infinity", "NaN"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_alarm_settings({"wake_buffer_minutes": value})

    def test_expiring_override_controls_only_this_profile(self) -> None:
        now = datetime(2026, 9, 4, 5, 0, tzinfo=ISRAEL)
        settings = resolve_alarm_settings({}, {}, "profile-1")
        override = {
            "target_date": "2026-09-06",
            "action": "set",
            "wake_at": "2026-09-06T06:10:00+03:00",
            "expires_at": "2026-09-06T20:59:59Z",
        }
        result = apply_alarm_controls({"shortcut_action": "leave", "enabled": False}, settings, override=override, now=now)
        self.assertEqual(result["wake_time"], "06:10")
        self.assertEqual(result["shortcut_action"], "set")
        self.assertTrue(result["alarm_control"]["override_active"])


if __name__ == "__main__":
    unittest.main()
