from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.request import Request

from shahaf_sync.github import GistClient, GitHubError
from shahaf_sync.model import Exam
from shahaf_sync.reconcile import ChangeRecord
from shahaf_sync.site import build_wake_data, render_site


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> tuple[int, bytes]:
        self.requests.append(request)
        if request.method == "GET":
            return 200, json.dumps(
                {
                    "updated_at": "2026-08-27T12:00:00Z",
                    "files": {
                        "school.ics": {
                            "content": "BEGIN:VCALENDAR\\r\\nEND:VCALENDAR\\r\\n",
                            "raw_url": "https://gist.githubusercontent.com/example/raw/school.ics",
                            "truncated": False,
                        }
                    },
                }
            ).encode()
        return 200, b"{}"


class FailingTransport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> tuple[int, bytes]:
        self.requests.append(request)
        return 503, b"service unavailable"


class GithubAndSiteTests(unittest.TestCase):
    def test_gist_client_reads_and_patches_only_selected_file(self) -> None:
        transport = FakeTransport()
        client = GistClient("secret-token", transport)
        file = client.read_file("gist-id", "school.ics")
        client.update_file("gist-id", "school.ics", "new calendar")
        self.assertEqual(file.content, "BEGIN:VCALENDAR\\r\\nEND:VCALENDAR\\r\\n")
        self.assertEqual(transport.requests[1].method, "PATCH")
        self.assertEqual(transport.requests[1].headers.get("Authorization"), "Bearer secret-token")
        self.assertIn(b"school.ics", transport.requests[1].data or b"")

    def test_gist_client_refuses_write_without_token(self) -> None:
        client = GistClient(token=None, transport=FakeTransport())
        with self.assertRaises(GitHubError):
            client.update_file("gist-id", "school.ics", "content")

    def test_gist_api_failure_is_reported_without_a_patch(self) -> None:
        transport = FailingTransport()
        client = GistClient("secret-token", transport)
        with self.assertRaises(GitHubError):
            client.read_file("gist-id", "school.ics")
        self.assertEqual([request.method for request in transport.requests], ["GET"])

    def test_site_contains_change_table_and_stale_banner(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="מערכת בדיקה",
                generated_at="2026-08-27T06:30:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[ChangeRecord("cancelled", date(2026, 9, 8), 2, "מתמטיקה", "cancelled")],
                stale=True,
                last_successful_sync="2026-08-27T06:30:00+03:00",
                error="source unavailable",
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("Sync needs attention", html)
            self.assertIn("מתמטיקה", html)
            self.assertIn("2026-08-27T06:30:00+03:00", html)
            self.assertIn("Today’s schedule", html)
            self.assertIn("scheduleAvailable", html)
            self.assertEqual(data["changes"][0]["kind"], "cancelled")
            self.assertEqual(data["last_successful_sync"], "2026-08-27T06:30:00+03:00")

    def test_site_hides_a_change_only_after_its_period_has_finished(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-06T09:11:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[
                    ChangeRecord("cancelled", date(2026, 9, 6), 1, "Math", "cancelled"),
                    ChangeRecord("cancelled", date(2026, 9, 6), 2, "English", "cancelled"),
                ],
                stale=False,
                now=datetime(2026, 9, 6, 9, 11, tzinfo=timezone(timedelta(hours=3))),
            )
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertEqual([item["subject"] for item in data["changes"]], ["English"])

    def test_site_has_full_schedule_control_and_period_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-06T07:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[
                    {
                        "date": "2026-09-06",
                        "period": 1,
                        "subject": "ספרות",
                        "teacher": "בר סבן",
                        "room": "208",
                        "start": "08:30",
                        "end": "09:10",
                    }
                ],
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("Full schedule", html)
            self.assertIn("schedule-periods", html)
            self.assertIn("Free period", html)
            self.assertIn('touchstart', html)
            self.assertIn('touchend', html)
            self.assertIn('Math.abs(dx)', html)
            self.assertIn('id="settings-view"', html)
            self.assertNotIn('id="settings-tab"', html)
            self.assertIn('profile-select', html)
            self.assertIn('skeleton', html)
            self.assertIn('["now", "full", "exams", "settings"]', html)
            self.assertEqual(len(data["periods"]), 14)

    def test_service_worker_caches_data_for_weak_connection(self) -> None:
        service_worker = (Path(__file__).parents[1] / "site" / "sw.js").read_text(encoding="utf-8")
        self.assertIn('"./data.json"', service_worker)
        self.assertIn("CACHE_NAME = \"shahaf-schedule-v3\"", service_worker)
        self.assertIn("cache.put(request, response.clone())", service_worker)

    def test_site_has_exam_view_and_four_day_reminder_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                exams=[Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל מואץ", 4, 6)],
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("Exams", html)
            self.assertIn("4 days before", html)
            self.assertEqual(data["exams"][0]["reminder_date"], "2026-09-02")
            self.assertTrue(data["exams_available"])

    def test_site_embeds_confirmed_additional_profile_data(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                exams=[],
                profiles=[
                    {
                        "id": "ya1-physics-cs10",
                        "label": "יא-1 · Physics + Computer Science 10-point",
                        "mark": "XI·1",
                        "schedule": [
                            {
                                "date": "2026-09-03",
                                "period": 0,
                                "subject": "פיסיקה 1",
                                "teacher": "שגיא גיא",
                                "room": "308 מע׳ פיסיקה",
                                "start": "07:45",
                                "end": "08:25",
                            }
                        ],
                        "schedule_available": True,
                        "changes": [],
                        "exams": [],
                        "exams_available": True,
                    }
                ],
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("ya1-physics-cs10", html)
            self.assertEqual(data["profiles"][1]["mark"], "XI·1")
            self.assertEqual(data["profiles"][1]["schedule"][0]["teacher"], "שגיא גיא")

    def test_wake_data_uses_first_master_lesson_minus_75_minutes(self) -> None:
        wake = build_wake_data(
            [
                {"date": "2026-09-03", "period": 1, "start": "08:30", "subject": "Math"},
                {"date": "2026-09-03", "period": 4, "start": "10:45", "subject": "English"},
            ],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["next_school_day"], "2026-09-03")
        self.assertEqual(wake["wake_time"], "07:15")
        self.assertEqual(wake["subject"], "Math")
        self.assertTrue(wake["enabled"])
        self.assertTrue(wake["alarm_for_today"])
        self.assertEqual(wake["fallback_status"], "none")

    def test_wake_data_skips_a_passed_wake_time_and_handles_no_school(self) -> None:
        wake = build_wake_data(
            [
                {"date": "2026-09-03", "period": 0, "start": "07:45", "subject": "Math"},
                {"date": "2026-09-06", "period": 1, "start": "08:30", "subject": "English"},
            ],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 6, 45, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["next_school_day"], "2026-09-06")
        self.assertFalse(wake["alarm_for_today"])
        self.assertTrue(wake["enabled"])

        no_school = build_wake_data(
            [],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertFalse(no_school["enabled"])
        self.assertEqual(no_school["fallback_status"], "no-lessons")

    def test_wake_data_marks_stale_without_a_destructive_fallback(self) -> None:
        wake = build_wake_data(
            None,
            schedule_available=False,
            stale=True,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertFalse(wake["enabled"])
        self.assertTrue(wake["stale"])
        self.assertEqual(wake["fallback_status"], "stale")

    def test_render_site_writes_public_wake_endpoint(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-03T05:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[
                    {"date": "2026-09-03", "period": 1, "subject": "Math", "start": "08:30", "end": "09:10"}
                ],
                now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
            )
            wake = json.loads((Path(directory) / "wake.json").read_text(encoding="utf-8"))
            self.assertEqual(wake["wake_time"], "07:15")
            self.assertEqual(wake["subject"], "Math")


if __name__ == "__main__":
    unittest.main()
