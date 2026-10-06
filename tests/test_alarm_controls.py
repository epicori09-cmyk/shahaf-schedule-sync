from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import unittest

from shahaf_sync.alarm_controls import (
    apply_alarm_controls,
    normalize_alarm_settings,
    resolve_alarm_settings,
)
from shahaf_sync.site import build_wake_data


ISRAEL = timezone(timedelta(hours=3))


class AlarmControlTests(unittest.TestCase):
    def test_clear_with_original_snapshot_never_restores_it(self) -> None:
        original = {"next_school_day": "2026-10-07", "wake_time": "06:45", "wake_at": "2026-10-07T06:45:00+03:00", "shortcut_action": "set", "enabled": True}
        result = apply_alarm_controls(original, {}, override={"target_date": "2026-10-07", "action": "clear", "restore_json": json.dumps(original), "expires_at": "2026-10-07T20:59:59Z"}, now=datetime(2026, 10, 6, 5, tzinfo=ISRAEL))
        self.assertEqual(result["shortcut_action"], "clear")
        self.assertIsNone(result["wake_at"])
        self.assertFalse(result["enabled"])

    def test_weekend_cannot_be_bypassed_by_force_or_restore(self) -> None:
        original = {"next_school_day": "2026-10-11", "wake_time": "06:45", "wake_at": "2026-10-11T06:45:00+03:00", "shortcut_action": "set", "enabled": True}
        for current_day in (9, 10):
            for restore in (False, True):
                override = {"target_date": "2026-10-11", "action": "set", "wake_at": original["wake_at"], "force": True, "expires_at": "2026-10-11T20:59:59Z"}
                if restore:
                    override["restore_json"] = json.dumps(original)
                with self.subTest(day=current_day, restore=restore):
                    result = apply_alarm_controls(original, {}, override=override, now=datetime(2026, 10, current_day, 5, tzinfo=ISRAEL))
                    self.assertEqual(result["shortcut_action"], "clear")
                    self.assertEqual(result["fallback_status"], "weekend")

    def test_winter_fallback_and_override_use_israel_offset(self) -> None:
        from zoneinfo import ZoneInfo
        current = datetime(2027, 1, 3, 5, tzinfo=ZoneInfo("Asia/Jerusalem"))
        base = {"next_school_day": "2027-01-04", "stale": True, "shortcut_action": "leave"}
        result = apply_alarm_controls(base, {"stale_policy": "set_fixed", "fallback_wake_time": "07:15"}, now=current)
        self.assertEqual(result["wake_at"], "2027-01-04T07:15:00+02:00")
        for timestamp in ("2027-01-04T06:45:00", "2027-01-05T06:45:00+02:00"):
            result = apply_alarm_controls({**base, "stale": False}, {}, now=current, override={"target_date": "2027-01-04", "action": "set", "wake_at": timestamp, "expires_at": "2027-01-04T21:59:59Z"})
            self.assertEqual(result["shortcut_action"], "leave")

    def test_future_command_does_not_mask_current_cancellation(self) -> None:
        commands = [{"id": "current", "target_date": "2026-10-06", "action": "clear", "created_at": "2026-10-05T12:00:00Z", "expires_at": "2026-10-06T20:59:59Z"}, {"id": "new-future", "target_date": "2026-10-07", "action": "set", "wake_at": "2026-10-07T06:25:00+03:00", "created_at": "2026-10-06T01:00:00Z", "expires_at": "2026-10-07T20:59:59Z"}]
        result = apply_alarm_controls({"next_school_day": "2026-10-06", "shortcut_action": "set", "wake_time": "06:45"}, {}, overrides=commands, now=datetime(2026, 10, 6, 5, tzinfo=ISRAEL))
        self.assertEqual(result["shortcut_action"], "clear")
        self.assertTrue(result["alarm_control"]["override_pending"])

    def test_bad_schedule_preserves_alarm_and_exact_rule_is_not_rounded(self) -> None:
        current = datetime(2026, 10, 6, 5, tzinfo=ISRAEL)
        bad = build_wake_data([{"date": "2026-10-07", "start": "bad"}], schedule_available=True, stale=False, now=current)
        self.assertEqual(bad["shortcut_action"], "leave")
        self.assertTrue(bad["stale"])
        exact = build_wake_data([{"date": "2026-10-07", "start": "07:45", "subject": "Math"}], schedule_available=True, stale=False, now=current, round_to_minutes=10, wake_time_by_first_lesson_start={"07:45": "06:45"})
        self.assertEqual(exact["wake_time"], "06:45")

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
            now=datetime(2026, 9, 3, 5, 0, tzinfo=ISRAEL),
            buffer_minutes=80,
            round_to_minutes=5,
        )
        controlled = apply_alarm_controls(
            wake,
            resolve_alarm_settings({}, {"alarm_label": "Shahaf Test"}, "profile-1"),
            now=datetime(2026, 9, 3, 5, 0, tzinfo=ISRAEL),
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
            {"next_school_day": "2026-09-06", "stale": True, "fallback_status": "stale", "shortcut_action": "leave"},
            {"next_school_day": "2026-09-06", "stale": False, "fallback_status": "no-safe-route", "shortcut_action": "leave"},
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
            {"next_school_day": "2026-09-06", "stale": True, "fallback_status": "stale", "shortcut_action": "leave"},
            resolve_alarm_settings({}, {}, "profile-1"),
            override={
                "target_date": "2026-09-06",
                "action": "set",
                "wake_at": "2026-09-06T06:10:00+03:00",
                "expires_at": "2026-09-06T20:59:59Z",
                "force": True,
            },
            now=datetime(2026, 9, 3, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["fallback_status"], "manual-set")

    def test_non_integer_numeric_strings_are_rejected(self) -> None:
        for value in ("7.5", "Infinity", "NaN"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_alarm_settings({"wake_buffer_minutes": value})

    def test_expiring_override_controls_only_this_profile(self) -> None:
        now = datetime(2026, 9, 3, 5, 0, tzinfo=ISRAEL)
        settings = resolve_alarm_settings({}, {}, "profile-1")
        override = {
            "target_date": "2026-09-06",
            "action": "set",
            "wake_at": "2026-09-06T06:10:00+03:00",
            "expires_at": "2026-09-06T20:59:59Z",
        }
        result = apply_alarm_controls(
            {"next_school_day": "2026-09-06", "shortcut_action": "leave", "enabled": False},
            settings,
            override=override,
            now=now,
        )
        self.assertEqual(result["wake_time"], "06:10")
        self.assertEqual(result["shortcut_action"], "set")
        self.assertTrue(result["alarm_control"]["override_active"])

    def test_future_override_waits_for_its_target_day(self) -> None:
        now = datetime(2026, 9, 2, 5, 0, tzinfo=ISRAEL)
        result = apply_alarm_controls(
            {"next_school_day": "2026-09-03", "shortcut_action": "set", "wake_time": "07:15"},
            resolve_alarm_settings({}, {}, "profile-1"),
            override={
                "target_date": "2026-09-06",
                "action": "set",
                "wake_at": "2026-09-06T06:10:00+03:00",
                "expires_at": "2026-09-06T20:59:59Z",
            },
            now=now,
        )
        self.assertEqual(result["wake_time"], "07:15")
        self.assertEqual(result["shortcut_action"], "set")
        self.assertFalse(result["alarm_control"]["override_active"])
        self.assertTrue(result["alarm_control"]["override_pending"])

    def test_clear_window_applies_inclusively_and_expires_after_end_date(self) -> None:
        settings = resolve_alarm_settings({}, {}, "profile-1")
        override = {
            "target_date": "2026-09-21",
            "target_date_end": "2026-10-04",
            "action": "clear",
            "expires_at": "2026-10-04T20:59:59Z",
        }
        for school_day in ("2026-09-21", "2026-10-04"):
            result = apply_alarm_controls(
                {"next_school_day": school_day, "wake_time": "06:45", "shortcut_action": "set"},
                settings,
                override=override,
                now=datetime(2026, 9, 21, 5, 0, tzinfo=ISRAEL),
            )
            self.assertEqual(result["shortcut_action"], "clear")
            self.assertTrue(result["alarm_control"]["override_active"])
            self.assertEqual(result["next_school_day"], school_day)

        expired = apply_alarm_controls(
            {"next_school_day": "2026-10-05", "wake_time": "06:45", "shortcut_action": "set"},
            settings,
            override=override,
            now=datetime(2026, 10, 5, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(expired["shortcut_action"], "set")
        self.assertFalse(expired["alarm_control"]["override_active"])
        self.assertTrue(expired["alarm_control"]["override_pending"] is False)

    def test_restore_snapshot_returns_alarm_to_original_correct_time(self) -> None:
        result = apply_alarm_controls(
            {
                "next_school_day": "2026-09-06",
                "wake_time": "06:10",
                "wake_at": "2026-09-06T06:10:00+03:00",
                "subject": "Moved lesson",
                "enabled": True,
                "shortcut_action": "set",
                "fallback_status": "manual-set",
            },
            resolve_alarm_settings({}, {}, "profile-1"),
            override={
                "target_date": "2026-09-06",
                "action": "set",
                "wake_at": "2026-09-06T06:45:00+03:00",
                "restore_json": json.dumps(
                    {
                        "next_school_day": "2026-09-06",
                        "wake_time": "06:45",
                        "wake_at": "2026-09-06T06:45:00+03:00",
                        "subject": "First lesson",
                        "enabled": True,
                        "shortcut_action": "set",
                        "fallback_status": "none",
                        "alarm_for_today": False,
                    }
                ),
                "expires_at": "2026-09-06T20:59:59Z",
            },
            now=datetime(2026, 9, 3, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(result["wake_time"], "06:45")
        self.assertEqual(result["wake_at"], "2026-09-06T06:45:00+03:00")
        self.assertEqual(result["subject"], "First lesson")
        self.assertTrue(result["enabled"])
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["fallback_status"], "restored-default")
        self.assertTrue(result["alarm_control"]["override_active"])

    def test_manual_set_with_restore_snapshot_keeps_requested_time(self) -> None:
        result = apply_alarm_controls(
            {
                "next_school_day": "2026-09-07",
                "wake_time": "08:05",
                "wake_at": "2026-09-07T08:05:00+03:00",
                "subject": "First lesson",
                "enabled": True,
                "shortcut_action": "set",
                "fallback_status": "none",
            },
            resolve_alarm_settings({}, {}, "profile-1"),
            override={
                "target_date": "2026-09-07",
                "action": "set",
                "wake_at": "2026-09-07T06:25:00+03:00",
                "restore_json": json.dumps(
                    {
                        "next_school_day": "2026-09-07",
                        "wake_time": "08:05",
                        "wake_at": "2026-09-07T08:05:00+03:00",
                        "subject": "First lesson",
                        "enabled": True,
                        "shortcut_action": "set",
                        "fallback_status": "none",
                    }
                ),
                "expires_at": "2026-09-07T20:59:59Z",
            },
            now=datetime(2026, 9, 6, 5, 0, tzinfo=ISRAEL),
        )
        self.assertEqual(result["wake_time"], "06:25")
        self.assertEqual(result["fallback_status"], "manual-set")


if __name__ == "__main__":
    unittest.main()
