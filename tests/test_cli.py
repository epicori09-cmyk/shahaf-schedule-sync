from __future__ import annotations

from pathlib import Path
import unittest

from shahaf_sync.cli import Config, _now, load_config


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


if __name__ == "__main__":
    unittest.main()
