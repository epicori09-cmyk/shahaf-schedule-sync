from __future__ import annotations

import json
from urllib.request import Request
import unittest

from shahaf_sync.nim import NimError, NimSafetyClient


class NimTests(unittest.TestCase):
    def response_transport(self, content: str, seen: list[Request]):
        def transport(request: Request):
            seen.append(request)
            return 200, json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        return transport

    def test_accepts_only_low_risk_true_json(self) -> None:
        seen: list[Request] = []
        client = NimSafetyClient(
            "nvapi-test",
            transport=self.response_transport(
                '{"safe_to_delete_alarm": true, "risk_level": "low", "reason": "No lesson or exam remains."}',
                seen,
            ),
        )
        decision = client.classify({"candidate": {"shortcut_action": "clear"}})
        self.assertTrue(decision.safe_to_delete_alarm)
        self.assertEqual(decision.risk_level, "low")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer nvapi-test")
        body = json.loads(seen[0].data.decode())
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(body["max_tokens"], 4096)
        self.assertIn("untrusted schedule data", body["messages"][0]["content"])

    def test_medium_risk_is_not_an_allow_decision(self) -> None:
        client = NimSafetyClient(
            "nvapi-test",
            transport=self.response_transport(
                '{"safe_to_delete_alarm": true, "risk_level": "medium", "reason": "maybe"}',
                [],
            ),
        )
        decision = client.classify({})
        self.assertFalse(decision.safe_to_delete_alarm and decision.risk_level == "low")

    def test_rejects_bad_types_or_malformed_output(self) -> None:
        for content in (
            '{"safe_to_delete_alarm": "true", "risk_level": "low", "reason": "bad type"}',
            "not json",
        ):
            client = NimSafetyClient("nvapi-test", transport=self.response_transport(content, []))
            with self.assertRaises(NimError):
                client.classify({})

    def test_http_failure_fails_closed(self) -> None:
        def transport(_request: Request):
            return 503, b"unavailable"
        with self.assertRaises(NimError):
            NimSafetyClient("nvapi-test", transport=transport).classify({})

    def test_event_classifier_requires_conservative_schema_and_high_reasoning(self) -> None:
        seen: list[Request] = []
        client = NimSafetyClient(
            "nvapi-test",
            transport=self.response_transport(
                '{"classification":"remote_learning","safe_to_delete_alarm":true,"risk_level":"low","reason":"No in-person attendance."}',
                seen,
            ),
        )
        decision = client.classify_event({"event": {"title": "יום למידה א-סינכרוני"}})
        self.assertEqual(decision.classification, "remote_learning")
        self.assertTrue(decision.safe_to_delete_alarm)
        body = json.loads(seen[0].data.decode())
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertIn("Never guess", body["messages"][0]["content"])

    def test_event_classifier_rejects_unsafe_approval(self) -> None:
        client = NimSafetyClient(
            "nvapi-test",
            transport=self.response_transport(
                '{"classification":"normal_school","safe_to_delete_alarm":true,"risk_level":"low","reason":"unsafe"}',
                [],
            ),
        )
        with self.assertRaises(NimError):
            client.classify_event({})

    def test_event_classifier_reports_truncated_empty_content(self) -> None:
        def transport(_request: Request):
            return 200, json.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": None},
                            "finish_reason": "length",
                        }
                    ]
                }
            ).encode()

        with self.assertRaisesRegex(NimError, "finish_reason=length"):
            NimSafetyClient("nvapi-test", transport=transport).classify_event({})


if __name__ == "__main__":
    unittest.main()
