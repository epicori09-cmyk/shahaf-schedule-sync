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
from shahaf_sync.site import archive_profile_site, build_wake_data, render_site


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
            self.assertNotIn('id="alarm-self-service"', html)
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
            self.assertIn(">Schedule<", html)
            self.assertIn("schedule-periods", html)
            self.assertIn("Free period", html)
            self.assertIn('data-empty-kind=', html)
            self.assertIn('"no-lesson"', html)
            self.assertIn('"gap"', html)
            self.assertIn("Heebo-400.ttf", html)
            self.assertIn('touchstart', html)
            self.assertIn('touchend', html)
            self.assertIn('Math.abs(dx)', html)
            self.assertIn('attachSwipe(document.querySelector(".topbar"), "views")', html)
            self.assertIn('attachSwipe(document.querySelector(".view-switch"), "views")', html)
            self.assertIn('attachSwipe(document.getElementById("full-day-content"), "days")', html)
            self.assertIn('attachSwipe(document.getElementById("day-picker"), "views")', html)
            self.assertIn('attachSwipe(document.getElementById("now-view"), "views")', html)
            self.assertIn('animation:view-in-next .46s cubic-bezier(.2,.8,.2,1)', html)
            self.assertIn('animation:day-in-next .42s cubic-bezier(.2,.8,.2,1)', html)
            self.assertIn('.view-switch button::after', html)
            self.assertIn('transition:background-color .36s cubic-bezier(.2,.8,.2,1)', html)
            self.assertIn('window.setTimeout(() => element.classList.remove(className), 500)', html)
            self.assertIn('isolatePeriodNumerics', html)
            self.assertIn('font-feature-settings:"tnum" 1', html)
            self.assertIn('<bdi dir="ltr">${formatTime(item.start)}<small>–${formatTime(item.end)}</small></bdi>', html)
            self.assertIn('.next-card .lesson-time bdi small{display:inline;margin-top:0}', html)
            self.assertIn('href="shfmobile://"', html)
            self.assertIn('const shahafAppUrl = "shfmobile://"', html)
            self.assertIn('const shahafStoreUrl = "itms-apps://itunes.apple.com/app/id1368425766"', html)
            self.assertIn('footerSource.addEventListener("click", openShahafApp)', html)
            self.assertIn('visibilitychange', html)
            self.assertNotIn("Last successful sync:", html)
            self.assertNotIn('id="source-link"', html)
            self.assertNotIn('settings-view', html)
            self.assertNotIn('profile-select', html)
            self.assertIn('skeleton', html)
            self.assertIn('["now", "full", "exams"]', html)
            self.assertEqual(len(data["periods"]), 14)

    def test_service_worker_caches_data_for_weak_connection(self) -> None:
        service_worker = (Path(__file__).parents[1] / "site" / "sw.js").read_text(encoding="utf-8")
        self.assertIn('"./data.json"', service_worker)
        self.assertIn("CACHE_NAME = \"shahaf-schedule-v3\"", service_worker)
        self.assertIn("cache.put(request, response.clone())", service_worker)

    def test_every_rendered_page_has_installable_pwa_branding(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            render_site(
                output,
                title="Student schedule",
                generated_at="2026-09-04T06:30:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                profile_id="student-profile",
                public_profile=True,
            )
            html = (output / "index.html").read_text(encoding="utf-8")
            manifest = json.loads((output / "manifest.webmanifest").read_text(encoding="utf-8"))
            self.assertIn('rel="icon" href="./icon.svg"', html)
            self.assertIn('sizes="180x180"', html)
            self.assertIn('<img class="mark" src="./header-logo.png" alt="" aria-hidden="true">', html)
            self.assertEqual([item["sizes"] for item in manifest["icons"]], ["192x192", "512x512"])
            self.assertTrue((output / "sw.js").exists())
            self.assertEqual((output / "header-logo.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn('id="alarm-self-service"', html)
            self.assertIn("Cancel / move my next alarm", html)
            self.assertIn('id="alarm-restore"', html)
            self.assertIn("Restore my alarm", html)
            self.assertIn("public/profiles/student-profile/alarm-command", html)
            self.assertIn("This changes only this schedule’s next alarm", html)
            for size in (180, 192, 512):
                self.assertEqual((output / f"icon-{size}.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertTrue((output / "fonts" / "Heebo-400.ttf").exists())
            self.assertIn("fonts/Heebo-400.ttf", (output / "sw.js").read_text(encoding="utf-8"))
            self.assertIn("-v3", (output / "sw.js").read_text(encoding="utf-8"))
            self.assertIn('"./header-logo.png"', (output / "sw.js").read_text(encoding="utf-8"))

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
                exams=[Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל מואץ", 4, 6, room="217")],
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("Exams", html)
            self.assertIn("exam-room", html)
            self.assertNotIn("Reminder: 4 days before", html)
            self.assertEqual(data["exams"][0]["reminder_date"], "2026-09-02")
            self.assertTrue(data["exams_available"])

    def test_async_school_day_remains_selectable_with_notice(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-04T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[
                    {
                        "date": "2026-09-08",
                        "period": 1,
                        "subject": "עברית",
                        "teacher": "מורה",
                        "room": "208",
                        "start": "08:30",
                        "end": "09:10",
                    }
                ],
                events=[
                    {
                        "date": "2026-09-09",
                        "title": "יום למידה א-סינכרוני",
                        "detail": "אין לימודים פרונטליים",
                        "classification": "no_school",
                    }
                ],
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn('id="day-notice"', html)
            self.assertIn('function asyncEventFor', html)
            self.assertIn('events.filter(isAsyncDayEvent)', html)
            self.assertIn("Async learning day", html)
            self.assertEqual(data["events"][0]["date"], "2026-09-09")

    def test_site_keeps_event_data_for_safety_but_hides_events_view(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Schedule",
                generated_at="2026-09-09T10:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                events=[
                    {
                        "date": "2026-09-09",
                        "title": "יום למידה א-סינכרוני",
                        "start_period": 0,
                        "end_period": 14,
                        "classification": "remote_learning",
                        "detail": "No in-person attendance",
                    },
                    {
                        "date": "2026-09-09",
                        "title": "Finished",
                        "start": "08:00",
                        "end": "09:00",
                        "classification": "overlay",
                    },
                ],
                now=datetime(2026, 9, 9, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertNotIn('id="events-tab"', html)
            self.assertNotIn('id="events-view"', html)
            self.assertIn("יום למידה א-סינכרוני", html)
            self.assertEqual([item["title"] for item in data["events"]], ["יום למידה א-סינכרוני"])

    def test_site_can_render_ya1_as_an_isolated_pink_page_without_wake(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Ostrovsky Grade 11-1",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[
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
                exams=[],
                profile_id="ya1",
                profile_label="Ostrovsky Grade 11-1",
                profile_mark="XI·1",
                profile_class_id="61",
                publish_wake=False,
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn("Ostrovsky Grade 11-1", html)
            self.assertIn("theme-pink", html)
            self.assertEqual(data["id"], "ya1")
            self.assertEqual(data["class_id"], "61")
            self.assertNotIn("wake", data)
            self.assertFalse((Path(directory) / "wake.json").exists())

    def test_ya1_site_has_a_simple_phrase_gate_but_master_does_not(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Ostrovsky Grade 11-1",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                profile_id="ya1",
                profile_label="Ostrovsky Grade 11-1",
                profile_mark="XI·1",
                profile_class_id="61",
                publish_wake=False,
            )
            ya1_html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            self.assertIn("site-access-gate", ya1_html)
            self.assertIn("אורי המלך", ya1_html)
            self.assertNotIn("localStorage", ya1_html)
            self.assertNotIn("<script>\n<script>", ya1_html)
            self.assertIn(".site-access-gate[hidden]{display:none}", ya1_html)

            render_site(
                Path(directory) / "master",
                title="Master",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                profile_id="master-ya2",
            )
            master_html = (Path(directory) / "master" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("site-access-gate", master_html)

    def test_managed_profile_site_is_noindex_and_does_not_leak_transit_origin(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Student schedule",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                profile_id="A" * 22,
                profile_label="Student schedule",
                profile_mark="STUDENT",
                public_profile=True,
                transit_wake={
                    "shortcut_action": "set",
                    "route_departure": "07:00",
                    "route_arrival": "08:00",
                    "origin_address": "private home",
                },
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            self.assertIn('name="robots" content="noindex,nofollow,noarchive"', html)
            self.assertNotIn("private home", json.dumps(data, ensure_ascii=False))
            self.assertIn("Student schedule", html)

    def test_site_publishes_only_the_ya1_transit_wake_endpoint(self) -> None:
        transit_wake = {
            "profile": "ya1",
            "alarm_label": "Shahaf Ya1 Wake",
            "shortcut_action": "set",
            "wake_time": "06:05",
            "route_departure": "07:20",
            "route_arrival": "08:25",
            "stale": False,
        }
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Ostrovsky Grade 11-1",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                profile_id="ya1",
                profile_label="Ostrovsky Grade 11-1",
                profile_mark="XI·1",
                profile_class_id="61",
                publish_wake=False,
                transit_wake=transit_wake,
            )
            data = json.loads((Path(directory) / "data.json").read_text(encoding="utf-8"))
            wake = json.loads((Path(directory) / "wake.json").read_text(encoding="utf-8"))
            self.assertEqual(data["transit_wake"]["alarm_label"], "Shahaf Ya1 Wake")
            self.assertEqual(wake["route_arrival"], "08:25")
            self.assertNotIn("wake", data)

    def test_ya1_site_exposes_the_selected_bus_plan(self) -> None:
        with TemporaryDirectory() as directory:
            render_site(
                Path(directory),
                title="Ostrovsky Grade 11-1",
                generated_at="2026-09-02T14:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                schedule=[],
                profile_id="ya1",
                profile_label="Ostrovsky Grade 11-1",
                profile_mark="XI·1",
                profile_class_id="61",
                publish_wake=False,
                transit_wake={
                    "profile": "ya1",
                    "route_departure": "07:15",
                    "route_arrival": "07:34",
                    "route": [
                        {"type": "walk", "minutes": 5, "from": "Home", "to": "Stop"},
                        {
                            "type": "transit",
                            "route": "17",
                            "from_stop": "Stop",
                            "to_stop": "School stop",
                            "departure": "07:18",
                            "arrival": "07:30",
                        },
                    ],
                    "shortcut_action": "set",
                    "stale": False,
                },
            )
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            self.assertIn("transit-wake-card", html)
            self.assertIn("Bus", html)
            self.assertIn("${escapeHtml(leg.from_stop)} ← ${escapeHtml(leg.to_stop)}", html)
            self.assertIn("Earlier buses were considered", html)

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
        self.assertEqual(wake["shortcut_action"], "set")

    def test_wake_data_exposes_the_next_school_day_for_alarm_controls(self) -> None:
        wake = build_wake_data(
            [
                {"date": "2026-09-03", "period": 1, "start": "08:30", "subject": "Today"},
                {"date": "2026-09-04", "period": 1, "start": "08:30", "subject": "Friday"},
                {"date": "2026-09-05", "period": 1, "start": "08:30", "subject": "Saturday"},
                {"date": "2026-09-06", "period": 0, "start": "07:45", "subject": "Sunday"},
            ],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["next_school_day"], "2026-09-03")
        self.assertEqual(wake["next_scheduled_school_day"], "2026-09-06")

    def test_ori_special_request_wakes_at_0645_for_a_0745_start(self) -> None:
        wake = build_wake_data(
            [{"date": "2026-09-06", "period": 0, "start": "07:45", "subject": "First lesson"}],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 5, 5, 0, tzinfo=timezone(timedelta(hours=3))),
            wake_time_by_first_lesson_start={"07:45": "06:45"},
        )
        self.assertEqual(wake["wake_time"], "06:45")
        self.assertEqual(wake["wake_at"], "2026-09-06T06:45:00+03:00")
        self.assertEqual(wake["shortcut_action"], "set")

    def test_wake_data_sets_a_future_alarm_for_tomorrow(self) -> None:
        wake = build_wake_data(
            [{"date": "2026-09-06", "period": 1, "start": "08:30", "subject": "Math"}],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["next_school_day"], "2026-09-06")
        self.assertFalse(wake["alarm_for_today"])
        self.assertEqual(wake["shortcut_action"], "set")

    def test_wake_data_skips_friday_and_saturday_but_keeps_sunday(self) -> None:
        wake = build_wake_data(
            [
                {"date": "2026-09-04", "period": 1, "start": "08:30", "subject": "Friday"},
                {"date": "2026-09-05", "period": 1, "start": "08:30", "subject": "Saturday"},
                {"date": "2026-09-06", "period": 1, "start": "08:30", "subject": "Sunday"},
            ],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["next_school_day"], "2026-09-06")
        self.assertEqual(wake["subject"], "Sunday")
        self.assertEqual(wake["shortcut_action"], "set")

    def test_blocked_alarm_safety_preserves_existing_alarm(self) -> None:
        wake = build_wake_data(
            [],
            schedule_available=True,
            stale=False,
            alarm_safety="blocked",
            alarm_safety_reason="NIM unavailable",
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(wake["shortcut_action"], "leave")
        self.assertEqual(wake["alarm_safety"], "blocked")

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
        self.assertEqual(wake["shortcut_action"], "set")

        no_school = build_wake_data(
            [],
            schedule_available=True,
            stale=False,
            now=datetime(2026, 9, 3, 5, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertFalse(no_school["enabled"])
        self.assertEqual(no_school["fallback_status"], "no-lessons")
        self.assertEqual(no_school["shortcut_action"], "clear")

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
        self.assertEqual(wake["shortcut_action"], "leave")

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

    def test_archive_profile_site_removes_old_payload_and_points_to_new_profile(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            for filename in ("data.json", "wake.json", "manifest.webmanifest", "sw.js", "icon.svg"):
                (output / filename).write_text("obsolete", encoding="utf-8")
            (output / "fonts").mkdir()
            (output / "fonts" / "Heebo-400.ttf").write_text("obsolete", encoding="utf-8")
            archive_profile_site(output, "students/random-id/")
            self.assertFalse((output / "data.json").exists())
            self.assertFalse((output / "wake.json").exists())
            self.assertFalse((output / "sw.js").exists())
            self.assertFalse((output / "fonts").exists())
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("students/random-id/", html)
            self.assertIn("location.replace(\"students/random-id/\")", html)


if __name__ == "__main__":
    unittest.main()
