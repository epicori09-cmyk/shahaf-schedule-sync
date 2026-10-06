import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class AlarmAcknowledgementTests(unittest.TestCase):
    def test_inactive_profiles_are_never_acknowledged(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "ack_alarm_commands.py"
        with TemporaryDirectory() as directory:
            bundle = Path(directory) / "profiles.json"
            bundle.write_text(json.dumps({"profiles": [{"active": False, "alarm_override": {"id": "must-not-publish"}}, {"active": False, "alarm_overrides": [{"id": "also-not-published"}]}]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(script), "--profiles-file", str(bundle)], env={**os.environ, "PROFILE_SYNC_URL": "https://invalid.example/internal/profiles", "PROFILE_SYNC_TOKEN": "test-only"}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No managed alarm overrides to acknowledge", result.stdout)
