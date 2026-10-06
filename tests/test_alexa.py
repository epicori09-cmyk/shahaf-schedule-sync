from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from alexa import lambda_function as skill
from scripts import update_alexa_reminder as updater
from shahaf_sync import alexa

NOW = datetime(2026, 10, 6, 5, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
GENERATED = NOW.isoformat()


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def wake(**changes):
    data = dict(profile_id=alexa.PROFILE_ID, generated_at=GENERATED,
                next_school_day="2026-10-06", wake_at="2026-10-06T06:45:00+03:00",
                wake_time="06:45", enabled=True, stale=False,
                shortcut_action="set", fallback_status="none", subject="Math")
    data.update(changes)
    return data


def reminder(token, managed=True, updated=""):
    text = "School schedule wake-up. Alarm." if managed else "Medicine."
    return dict(alertToken=token, updatedTime=updated,
                alertInfo={"spokenInfo": {"content": [{"text": text}]}})


class AlexaEffectiveTests(unittest.TestCase):
    def consume(self, consumer, data, failure=None, expected=None, reminders=None):
        calls = []
        if reminders is None:
            reminders = [reminder("old", updated="1"), reminder("newest", updated="2"),
                         reminder("unrelated", False), reminder("replacement", False)]

        def transport(request, **kwargs):
            method, url = request.get_method(), request.full_url
            calls.append((method, url, json.loads(request.data) if request.data else None))
            if url == alexa.EFFECTIVE_WAKE_URL:
                return io.BytesIO(json.dumps(data).encode())
            if failure == method:
                raise HTTPError(url, 500, "fixture failure", {}, None)
            body = {"alerts": reminders} if method == "GET" else (
                {"alertToken": "replacement"} if method == "POST" else {})
            if failure == "unconfirmed-post" and method == "POST":
                body = {}
            return io.BytesIO(json.dumps(body).encode())

        with ExitStack() as stack:
            env = {"ALEXA_LWA_ACCESS_TOKEN": "fixture", "ALEXA_API_ENDPOINT": "https://alexa.test"}
            if expected is not None:
                env["SCHEDULE_GENERATED_AT"] = expected
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            for module in (skill, updater, alexa):
                stack.enter_context(patch.object(module, "datetime", FrozenDatetime))
                stack.enter_context(patch.object(module, "urlopen", side_effect=transport))
            stack.enter_context(patch.object(skill, "SCHEDULE_URL", alexa.EFFECTIVE_WAKE_URL))
            stack.enter_context(patch("builtins.print"))
            if consumer == "updater":
                result = updater.main()
            else:
                result = skill.lambda_handler({
                    "request": {"type": "IntentRequest", "intent": {"name": "SetWakeUpIntent"}},
                    "context": {"System": {"apiEndpoint": "https://alexa.test", "apiAccessToken": "fixture"}}
                }, None)
        return result, calls

    def test_both_consumers_fetch_worker_and_send_effective_0645(self):
        self.assertEqual(skill.SCHEDULE_URL, alexa.EFFECTIVE_WAKE_URL)
        for consumer, method in (("updater", "PUT"), ("skill", "POST")):
            with self.subTest(consumer=consumer):
                result, calls = self.consume(consumer, wake())
                self.assertEqual(calls[0][:2], ("GET", alexa.EFFECTIVE_WAKE_URL))
                payload = next(body for verb, _, body in calls if verb == method)
                self.assertEqual(payload["trigger"]["scheduledTime"], "2026-10-06T06:45:00")
                self.assertEqual(payload["alertInfo"]["spokenInfo"]["content"][0]["text"],
                                 "School schedule wake-up. Your alarm is at 06:45.")

    def test_unsafe_input_prevents_any_alexa_api_requests(self):
        invalid = [
            wake(generated_at=None), wake(generated_at="bad"),
            wake(generated_at=NOW.replace(tzinfo=None).isoformat()),
            wake(generated_at=(NOW-timedelta(hours=3, seconds=1)).isoformat()),
            wake(generated_at=(NOW+timedelta(minutes=5, seconds=1)).isoformat()),
            wake(stale=True), wake(stale=None), wake(profile_id="other"),
            wake(next_school_day="2026-10-07"), wake(next_school_day=None),
            wake(wake_time="06:30"), wake(wake_at="2026-10-06T06:45:00"),
            wake(shortcut_action="leave"), wake(enabled=False),
            wake(fallback_status="unsafe-override-blocked"),
            {"schedule": [], "stale": False, "schedule_available": True},
        ]
        for consumer in ("updater", "skill"):
            for data in invalid:
                with self.subTest(consumer=consumer, data=data):
                    result, calls = self.consume(consumer, data)
                    self.assertEqual(len(calls), 1)
                    if consumer == "updater":
                        self.assertEqual(result, 1)
                    else:
                        self.assertNotIn("Done.", result["response"]["outputSpeech"]["ssml"])

    def test_freshness_boundaries_and_preview_validation_match_standalone(self):
        for consumer in (alexa.select_effective_wake, skill.select_effective_wake):
            for age in (timedelta(hours=3), -timedelta(minutes=5)):
                self.assertIsNotNone(consumer(wake(generated_at=(NOW-age).isoformat()), NOW)[0])
            preview = wake(next_school_day="2026-10-07", wake_at="2026-10-07T06:45:00+03:00")
            data = wake(next_alarm=preview)
            self.assertEqual(consumer(data, NOW)[0].date(), NOW.date())
            data = wake(shortcut_action="clear", enabled=False, wake_at=None, wake_time=None,
                        fallback_status="future-alarm-deferred", next_alarm=preview)
            self.assertEqual(consumer(data, NOW)[0].date().isoformat(), "2026-10-07")
            for changes in ({"profile_id": "other"}, {"generated_at": "2026-10-06T04:59:00+03:00"},
                            {"next_school_day": "2026-10-06"}, {"shortcut_action": "leave"}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    consumer({**data, "next_alarm": {**preview, **changes}}, NOW)
            with self.assertRaises(ValueError):
                consumer(wake(shortcut_action="leave", next_alarm=preview), NOW)
            with self.assertRaises(ValueError):
                consumer(wake(next_school_day="2026-10-07", next_alarm=preview), NOW)
            with self.assertRaises(ValueError):
                consumer(wake(shortcut_action="unknown", next_alarm=preview), NOW)

    def test_both_apis_can_schedule_future_preview(self):
        preview = wake(next_school_day="2026-10-07", wake_at="2026-10-07T06:45:00+03:00")
        data = wake(shortcut_action="clear", enabled=False, wake_at=None, wake_time=None,
                    fallback_status="future-alarm-deferred", next_alarm=preview)
        for consumer, method in (("updater", "PUT"), ("skill", "POST")):
            _, calls = self.consume(consumer, data)
            sent = next(body for verb, _, body in calls if verb == method)
            self.assertEqual(sent["trigger"]["scheduledTime"], "2026-10-07T06:45:00")

    def test_generation_mismatch_preserves_before_list_put_or_delete(self):
        result, calls = self.consume("updater", wake(), expected="2026-10-06T04:59:00+03:00")
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        result, calls = self.consume("updater", wake(), expected=GENERATED)
        self.assertEqual(result, 0)
        self.assertIn("PUT", [verb for verb, _, _ in calls])

    def test_put_success_precedes_deduplication_and_put_failure_never_deletes(self):
        result, calls = self.consume("updater", wake())
        self.assertEqual(result, 0)
        self.assertEqual([verb for verb, _, _ in calls], ["GET", "GET", "PUT", "DELETE"])
        self.assertTrue(calls[-1][1].endswith("/old"))
        result, calls = self.consume("updater", wake(), failure="PUT")
        self.assertEqual(result, 1)
        self.assertNotIn("DELETE", [verb for verb, _, _ in calls])

    def test_post_success_precedes_cleanup_and_post_failures_preserve_all(self):
        records = [reminder("old"), reminder("old-two"), reminder("unrelated", False),
                   reminder("replacement")]
        result, calls = self.consume("skill", wake(), reminders=records)
        self.assertIn("Done.", result["response"]["outputSpeech"]["ssml"])
        self.assertEqual([verb for verb, _, _ in calls], ["GET", "POST", "GET", "DELETE", "DELETE"])
        self.assertEqual([url.rsplit("/", 1)[-1] for verb, url, _ in calls if verb == "DELETE"],
                         ["old", "old-two"])
        for failure in ("POST", "unconfirmed-post"):
            result, calls = self.consume("skill", wake(), failure=failure)
            self.assertNotIn("DELETE", [verb for verb, _, _ in calls])

    def test_clear_removes_all_managed_duplicates_and_preserves_unrelated(self):
        data = wake(shortcut_action="clear", enabled=False, wake_at=None, wake_time=None,
                    fallback_status="manual-clear")
        for consumer in ("updater", "skill"):
            _, calls = self.consume(consumer, data)
            deleted = [url.rsplit("/", 1)[-1] for verb, url, _ in calls if verb == "DELETE"]
            self.assertEqual(set(deleted), {"old", "newest"})
            self.assertEqual(len(deleted), 2)
            self.assertNotIn("PUT", [verb for verb, _, _ in calls])
            self.assertNotIn("POST", [verb for verb, _, _ in calls])

    def test_delete_failure_is_explicit_after_replacement(self):
        for consumer in ("updater", "skill"):
            result, calls = self.consume(consumer, wake(), failure="DELETE")
            self.assertIn("DELETE", [verb for verb, _, _ in calls])
            if consumer == "updater":
                self.assertEqual(result, 1)
            else:
                self.assertIn("created the new reminder", result["response"]["outputSpeech"]["ssml"])

    def test_weekend_and_elapsed_root_use_valid_future_preview(self):
        preview = wake(next_school_day="2026-10-07", wake_at="2026-10-07T06:45:00+03:00")
        for status in ("current-weekend", "elapsed-wake"):
            data = wake(shortcut_action="leave", enabled=False, wake_at=None, wake_time=None,
                        fallback_status=status, next_alarm=preview)
            for consumer in ("updater", "skill"):
                _, calls = self.consume(consumer, data)
                payloads = [body for verb, _, body in calls if verb in ("PUT", "POST")]
                self.assertEqual(len(payloads), 1)
                self.assertEqual(payloads[0]["trigger"]["scheduledTime"], "2026-10-07T06:45:00")

    def test_future_preview_clear_and_leave_commands_are_honored(self):
        for action in ("clear", "leave"):
            preview = wake(next_school_day="2026-10-07", shortcut_action=action,
                           enabled=False, wake_at=None, wake_time=None,
                           fallback_status="manual-" + action)
            data = wake(shortcut_action="clear", enabled=False, wake_at=None, wake_time=None,
                        fallback_status="future-alarm-deferred", next_alarm=preview)
            for consumer in ("updater", "skill"):
                _, calls = self.consume(consumer, data)
                self.assertNotIn("PUT", [verb for verb, _, _ in calls])
                self.assertNotIn("POST", [verb for verb, _, _ in calls])
                self.assertEqual(sum(verb == "DELETE" for verb, _, _ in calls), 2 if action == "clear" else 0)

    def test_pages_url_cannot_bypass_worker_commands(self):
        with patch.dict(os.environ, {"ALEXA_LWA_ACCESS_TOKEN": "fixture",
                                     "SCHEDULE_DATA_URL": "https://pages.test/wake.json"}, clear=True), \
                patch.object(updater, "urlopen") as transport, patch("builtins.print"):
            self.assertEqual(updater.main(), 1)
            transport.assert_not_called()
        with patch.object(skill, "SCHEDULE_URL", "https://pages.test/wake.json"), \
                patch.object(skill, "urlopen") as transport, self.assertRaises(ValueError):
            skill.fetch_schedule()
        transport.assert_not_called()

    def test_workflow_deployment_gate_worker_url_and_artifact_generation(self):
        workflow = Path(".github/workflows/sync.yml").read_text(encoding="utf-8")
        step = workflow.split("      - name: Update Alexa wake-up reminder\n", 1)[1].split("      - name:", 1)[0]
        self.assertGreater(workflow.index("- name: Update Alexa"), workflow.index("- name: Final Pages"))
        for outcome in ("deployment", "deployment_retry", "deployment_final"):
            self.assertIn(f"steps.{outcome}.outcome == 'success'", step)
        self.assertIn(alexa.EFFECTIVE_WAKE_URL, step)
        self.assertIn("SCHEDULE_GENERATED_AT", step)
        self.assertIn(f"site/students/{alexa.PROFILE_ID}/wake.json", step)
        self.assertIn('artifact["generated_at"]', step)
        self.assertEqual(workflow.count("- name: Update Alexa wake-up reminder"), 1)


if __name__ == "__main__":
    unittest.main()
