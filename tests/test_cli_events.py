from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo
import json
import unittest

from shahaf_sync import cli
from shahaf_sync.github import GistFile
from shahaf_sync.model import EventSnapshot, ExamSnapshot, ShahafEvent, SourceSnapshot
from shahaf_sync.nim import EventSafetyDecision


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
DESCRIPTION:מורה: Teacher\\nשעה במערכת: 1\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


class FakeGistClient:
    updated: str | None = None

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def read_file(self, gist_id: str, filename: str) -> GistFile:
        return GistFile(ICS, "", "")

    def update_file(self, gist_id: str, filename: str, content: str) -> None:
        self.updated = content


class FakeNim:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def classify_event(self, context):
        return EventSafetyDecision("remote_learning", True, "low", "No in-person attendance.")

    def classify(self, context):
        return type("Decision", (), {"safe_to_delete_alarm": True, "risk_level": "low", "reason": "safe"})()


class CliEventIntegrationTests(unittest.TestCase):
    def test_approved_async_event_updates_only_its_occurrence(self) -> None:
        event = ShahafEvent(
            date(2026, 9, 9),
            "יום למידה א-סינכרוני",
            start_period=0,
            end_period=14,
            class_numbers=(2,),
            class_scope="יא-2",
        )
        config = cli.Config(
            "Asia/Jerusalem",
            "https://example.invalid/",
            "11",
            "gist",
            "school.ics",
            21,
            "Schedule",
            "site",
            class_number=2,
        )
        fake_client = FakeGistClient()
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}, clear=False), patch.object(cli, "GistClient", lambda token=None: fake_client), patch.object(cli, "NimSafetyClient", FakeNim), patch.object(cli, "fetch_source", return_value=(SourceSnapshot([], set(), "fresh", "changes", []), [])), patch.object(cli, "fetch_exams", return_value=ExamSnapshot([], "fresh", "exams")), patch.object(cli, "fetch_events", return_value=EventSnapshot([event], "fresh", "events")):
            cli.execute(
                Path(directory),
                config,
                now=datetime(2026, 9, 4, 5, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
            )
            self.assertIsNotNone(fake_client.updated)
            self.assertIn("X-SHAHAF-EVENT:1", fake_client.updated or "")
            self.assertIn("X-SHAHAF-EVENT-EXDATE", fake_client.updated or "")
            data = json.loads((Path(directory) / "site" / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["events"][0]["title"], "יום למידה א-סינכרוני")
            self.assertEqual([item["date"] for item in data["schedule"]], ["2026-09-16", "2026-09-23"])

    def test_event_feed_failure_preserves_gist_and_marks_site_stale(self) -> None:
        config = cli.Config(
            "Asia/Jerusalem",
            "https://example.invalid/",
            "11",
            "gist",
            "school.ics",
            21,
            "Schedule",
            "site",
            class_number=2,
        )
        fake_client = FakeGistClient()
        with TemporaryDirectory() as directory, patch.object(cli, "GistClient", lambda token=None: fake_client), patch.object(cli, "fetch_source", return_value=(SourceSnapshot([], set(), "fresh", "changes", []), [])), patch.object(cli, "fetch_exams", return_value=ExamSnapshot([], "fresh", "exams")), patch.object(cli, "fetch_events", side_effect=cli.SyncFailure("event source unavailable")):
            with self.assertRaises(cli.SyncFailure):
                cli.execute(
                    Path(directory),
                    config,
                    now=datetime(2026, 9, 4, 5, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
                )
            self.assertIsNone(fake_client.updated)
            data = json.loads((Path(directory) / "site" / "data.json").read_text(encoding="utf-8"))
            self.assertTrue(data["stale"])


if __name__ == "__main__":
    unittest.main()
