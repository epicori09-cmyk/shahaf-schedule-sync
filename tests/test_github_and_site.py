from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.request import Request

from shahaf_sync.github import GistClient, GitHubError
from shahaf_sync.reconcile import ChangeRecord
from shahaf_sync.site import render_site


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


if __name__ == "__main__":
    unittest.main()
