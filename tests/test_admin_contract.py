from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class AdminContractTests(unittest.TestCase):
    def test_worker_has_private_routes_and_security_controls(self) -> None:
        source = (ROOT / "admin" / "worker" / "src" / "index.js").read_text(encoding="utf-8")
        for route in ("/api/login", "/api/logout", "/api/session", "/api/classes", "/api/profiles", "/api/profiles/import", "/enable$/", "/disable$/", "request.method === \"DELETE\"", "/internal/profiles", "/internal/alarm-commands/ack", "/api/alarm-settings", "/api/alarm-preview", "/api/alarm-bulk", "/alarm-history$/", "alarm-settings/rollback", "const publish ="):
            self.assertIn(route, source)
        for import_control in ("id=\"classNumber\"", "id=\"editPayload\"", "id=\"englishLevel\"", "id=\"mathLevel\"", 'name=\"major\"', 'name=\"edit-major\"', "id=\"blockEditor\"", "Weekly timetable", "Gap / free period", "body.class_number", "YA_CLASS_IDS", "Enter the visible class number", "shortcut_url", 'alarm_label: "Shahaf"', "English schedule", "Hebrew schedule", "Shortcut endpoint"):
            self.assertIn(import_control, source)
        for control in ("PBKDF2", "HttpOnly", "SameSite=Strict", "X-CSRF-Token", "ADMIN_ORIGIN", "rateLimit", "Permanently delete this profile", "Alarm control center", "Force this change (advanced)", "Restore this version", "route_alternatives", "published_at"):
            self.assertIn(control, source)
        self.assertIn("GITHUB_DISPATCH_TOKEN", source)
        self.assertNotIn("GIST_TOKEN", source)
        self.assertNotIn("dashboardEnhancements + alarmDashboardEnhancements", source)
        schema = (ROOT / "admin" / "worker" / "schema.sql").read_text(encoding="utf-8")
        migration = (ROOT / "admin" / "worker" / "migrations" / "0002_alarm_controls.sql").read_text(encoding="utf-8")
        for table in ("alarm_global_settings", "alarm_profile_settings", "alarm_settings_history", "alarm_overrides", "alarm_audit"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", migration)
        self.assertIn("published_at TEXT", schema)
        self.assertIn("published_at TEXT", migration)

    def test_workflow_fetches_profiles_without_committing_them_and_skips_failed_deploy(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")
        self.assertIn("fetch_managed_profiles.py", workflow)
        self.assertIn("PROFILE_SYNC_TOKEN", workflow)
        self.assertIn("--profiles-file", workflow)
        self.assertIn("if: always()", workflow)

    def test_public_profile_docs_warn_about_obscurity(self) -> None:
        docs = (ROOT / "admin" / "worker" / "README.md").read_text(encoding="utf-8")
        self.assertIn("private by obscurity", docs)
        self.assertIn("home address", docs)
        self.assertIn(".shortcut", docs)


if __name__ == "__main__":
    unittest.main()
