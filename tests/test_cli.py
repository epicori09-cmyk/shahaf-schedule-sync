from __future__ import annotations

from pathlib import Path
import unittest

from shahaf_sync.cli import Config, _now, _stale_transit_payload, load_config


class CliTests(unittest.TestCase):
    def test_timezone_aware_clock_handles_israel_dst(self) -> None:
        config = Config("Asia/Jerusalem", "https://example.invalid", "17", "gist", "school.ics", 21, "title", "site")
        current = _now(config)
        self.assertIsNotNone(current.tzinfo)
        self.assertEqual(str(current.tzinfo), "Asia/Jerusalem")

    def test_config_points_to_final_gist_file(self) -> None:
        config = load_config(Path("config.json"))
        self.assertEqual(config.class_id, "11")
        self.assertEqual(config.gist_id, "a5891b76daf585d0953bc96958819fdf")
        self.assertEqual(config.gist_filename, "school.ics")
        self.assertEqual(len(config.additional_profiles), 1)
        self.assertEqual(config.additional_profiles[0]["class_id"], "61")
        self.assertEqual(config.transit["origin_address"], "מרדכי זעירא 5, רעננה")
        self.assertEqual(config.transit["destination_address"], "אוסטרובסקי 26, רעננה")
        self.assertEqual(config.special_requests["wake_time_by_first_lesson_start"]["07:45"], "06:45")

    def test_main_failure_payload_cannot_touch_the_master_alarm(self) -> None:
        config = load_config(Path("config.json"))
        payload = _stale_transit_payload(config, _now(config), "main source unavailable")
        self.assertEqual(payload["profile"], "ya1")
        self.assertEqual(payload["alarm_label"], "Shahaf Ya1 Wake")
        self.assertEqual(payload["shortcut_action"], "leave")
        self.assertTrue(payload["stale"])


if __name__ == "__main__":
    unittest.main()
