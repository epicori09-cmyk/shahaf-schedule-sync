from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from shahaf_sync.site import render_site
from shahaf_sync import alexa
from alexa import lambda_function


class ShortcutWireTests(unittest.TestCase):
    def test_published_preserve_is_text_false_without_changing_internal_actions(self):
        current = datetime(2026, 10, 6, 18, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
        for stale, schedule, expected in (
            (True, [], "false"),
            (False, [], "clear"),
            (False, [{"date": "2026-10-07", "start": "07:45", "end": "08:25", "period": 0, "subject": "Math"}], "set"),
        ):
            with self.subTest(expected=expected), TemporaryDirectory() as directory:
                output = Path(directory)
                render_site(output, title="Fixture", generated_at=current.isoformat(), source_url="https://example.invalid",
                            source_updated="fixture", changes=[], stale=stale, schedule=schedule, now=current,
                            profile_id="fixture_student", public_profile=True)
                wire = json.loads((output / "wake.json").read_text(encoding="utf-8"))
                internal = json.loads((output / "data.json").read_text(encoding="utf-8"))["wake"]
                self.assertEqual(wire["shortcut_action"], expected)
                self.assertIsInstance(wire["shortcut_action"], str)
                self.assertEqual(internal["shortcut_action"], "leave" if expected == "false" else expected)

    def test_alexa_false_means_preserve_not_create_or_clear(self):
        current = datetime(2026, 10, 6, 5, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
        wake = dict(profile_id=alexa.PROFILE_ID, generated_at=current.isoformat(), stale=False,
                    next_school_day="2026-10-06", wake_time=None, wake_at=None, enabled=False,
                    shortcut_action="false", fallback_status="none")
        for module in (alexa, lambda_function):
            with self.subTest(module=module.__name__), self.assertRaisesRegex(ValueError, "preserves existing"):
                module.select_effective_wake(wake, current)
        self.assertEqual(wake["shortcut_action"], "false")
