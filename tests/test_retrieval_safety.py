from __future__ import annotations

from datetime import datetime, date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from shahaf_sync import cli
from shahaf_sync.github import GistFile
from shahaf_sync.model import EventSnapshot, ExamSnapshot, SourceSnapshot


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


def snapshot_tree(root: Path) -> list[tuple[str, str, bytes | None]]:
    entries: list[tuple[str, str, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_dir():
            entries.append((relative, "dir", None))
        elif path.is_file():
            entries.append((relative, "file", path.read_bytes()))
    return entries


class RetrievalSafetyTests(unittest.TestCase):
    def test_truncated_live_lists_fail_before_parsing(self) -> None:
        from test_shahaf import CHANGES_HTML, EVENTS_HTML
        from test_exams import EXAMS_HTML
        config = cli.Config("Asia/Jerusalem", "https://example.invalid/", "11", "gist", "school.ics", 21, "Schedule", "site", class_number=2)
        for fetcher, html in ((cli.fetch_source, CHANGES_HTML), (cli.fetch_events, EVENTS_HTML), (cli.fetch_exams, EXAMS_HTML)):
            with self.subTest(fetcher=fetcher.__name__), patch.object(cli, "fetch_text", return_value=html.split('</body>')[0]):
                with self.assertRaisesRegex(cli.SyncFailure, "document is incomplete"):
                    fetcher(config, date(2026, 10, 6))
        self.assertEqual(cli._complete_source_document(EVENTS_HTML), EVENTS_HTML)

    def test_missing_or_malformed_bundle_is_not_an_empty_authoritative_list(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            with self.assertRaises(cli.SyncFailure):
                cli._managed_specs(path)
            for records in ([None], [{"public_id": "../../invalid-profile-path-name", "package": {}}]):
                path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
                with self.assertRaises(cli.SyncFailure):
                    cli._managed_specs(path)

    def test_fetch_text_timeout_retries_three_times_with_bounded_backoff(self) -> None:
        with patch.object(cli, "urlopen", side_effect=TimeoutError("source timed out")) as open_mock, patch.object(
            cli.system_time, "sleep"
        ) as sleep_mock:
            with self.assertRaisesRegex(cli.SyncFailure, r"after 3 attempt\(s\)"):
                cli.fetch_text("https://example.invalid/source")

        self.assertEqual(open_mock.call_count, 3)
        self.assertEqual([call.args for call in sleep_mock.call_args_list], [(1,), (2,)])
        self.assertEqual(
            [call.kwargs for call in open_mock.call_args_list],
            [{"timeout": 20}, {"timeout": 20}, {"timeout": 20}],
        )

    def test_fetch_text_recovers_on_second_attempt(self) -> None:
        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return "recovered source".encode("utf-8")

        with patch.object(cli, "urlopen", side_effect=[TimeoutError("temporary"), Response()]) as open_mock, patch.object(
            cli.system_time, "sleep"
        ) as sleep_mock:
            self.assertEqual(cli.fetch_text("https://example.invalid/source"), "recovered source")

        self.assertEqual(open_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)
        request = open_mock.call_args.args[0]
        self.assertEqual(request.get_header("Cache-control"), "no-cache")
        self.assertEqual(request.get_header("Pragma"), "no-cache")

    def test_invalid_managed_bundle_preserves_existing_tree_without_gist_access(self) -> None:
        config = cli.Config(
            "Asia/Jerusalem",
            "https://example.invalid/source",
            "11",
            "gist-id",
            "school.ics",
            21,
            "Schedule",
            "site",
            class_number=2,
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            known = site / "students" / "known-profile"
            known.mkdir(parents=True)
            (site / "data.json").write_text('{"known": true}\n', encoding="utf-8")
            (site / "students" / "index.json").write_text('{"profiles": ["known-profile"]}\n', encoding="utf-8")
            (known / "data.json").write_text('{"generated_at": "old"}\n', encoding="utf-8")
            (known / "keep.txt").write_text("existing profile artifact\n", encoding="utf-8")
            before = snapshot_tree(site)

            bundle = root / "managed.json"
            bundle.write_text(
                json.dumps(
                    {
                        "profiles": [
                            {
                                "active": True,
                                "public_id": "profile-" + "a" * 22,
                                "package": {"schema_version": 99},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            gist_calls: list[str] = []

            class NoAccessGist:
                def __init__(self, token: str | None = None) -> None:
                    self.token = token

                def read_file(self, gist_id: str, filename: str) -> GistFile:
                    gist_calls.append(f"read:{gist_id}:{filename}")
                    raise AssertionError("invalid managed bundle must fail before reading the Gist")

                def update_file(self, gist_id: str, filename: str, content: str) -> None:
                    gist_calls.append(f"write:{gist_id}:{filename}")

            with patch.object(cli, "GistClient", NoAccessGist):
                with self.assertRaises(cli.SyncFailure):
                    cli.execute(root, config, managed_profiles_path=bundle)

            self.assertEqual(gist_calls, [])
            self.assertEqual(snapshot_tree(site), before)

    def test_staging_render_failure_preserves_existing_students_tree(self) -> None:
        config = cli.Config(
            "Asia/Jerusalem",
            "https://example.invalid/source",
            "11",
            "gist-id",
            "school.ics",
            21,
            "Schedule",
            "site",
            class_number=2,
        )
        managed_spec = {
            "id": "known-profile",
            "public_id": "known-profile",
            "managed_profile": True,
            "class_id": "11",
            "class_number": 2,
            "package": {},
        }
        rendered_profile = {
            "id": "known-profile",
            "schedule": [],
            "schedule_available": True,
            "changes": [],
            "exams": [],
            "exams_available": True,
            "events": [],
            "events_available": True,
            "source_url": "https://example.invalid/source",
            "source_updated": "fresh",
            "stale": False,
            "last_successful_sync": "",
            "error": "",
        }

        with TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            known = site / "students" / "known-profile"
            known.mkdir(parents=True)
            (site / "keep-at-root.txt").write_text("keep\n", encoding="utf-8")
            (known / "data.json").write_text('{"generated_at": "old"}\n', encoding="utf-8")
            (known / "keep.txt").write_text("existing profile artifact\n", encoding="utf-8")
            before = snapshot_tree(site)
            gist_writes = []

            class ReadOnlyGist:
                def __init__(self, token: str | None = None) -> None:
                    self.updated: list[str] = []

                def read_file(self, gist_id: str, filename: str) -> GistFile:
                    return GistFile(ICS, "", "")

                def update_file(self, gist_id: str, filename: str, content: str) -> None:
                    self.updated.append(content)
                    gist_writes.append(content)

            with patch.object(cli, "GistClient", ReadOnlyGist), patch.object(
                cli, "_managed_specs", return_value=[managed_spec]
            ), patch.object(
                cli,
                "fetch_source",
                return_value=(SourceSnapshot([], set(), "fresh", "changes", []), []),
            ), patch.object(
                cli,
                "fetch_exams",
                return_value=ExamSnapshot([], "fresh", "exams"),
            ), patch.object(
                cli,
                "fetch_events",
                return_value=EventSnapshot([], "fresh", "events"),
            ), patch.object(cli, "_build_public_profile", return_value=rendered_profile), patch.object(
                cli, "render_site", side_effect=ValueError("staged render failed")
            ):
                with self.assertRaisesRegex(cli.SyncFailure, "staged render failed"):
                    cli.execute(
                        root,
                        config,
                        now=datetime(2026, 9, 4, 5, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
                        managed_profiles_path=root / "mocked-bundle.json",
                    )

            self.assertEqual(snapshot_tree(site), before)
            self.assertEqual(gist_writes, [], "A failed staged render must not publish the Gist")
            self.assertEqual(list(root.glob(".shahaf-stage-*")), [])


if __name__ == "__main__":
    unittest.main()
