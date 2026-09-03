from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class AdminContractTests(unittest.TestCase):
    def test_worker_has_private_routes_and_security_controls(self) -> None:
        source = (ROOT / "admin" / "worker" / "src" / "index.js").read_text(encoding="utf-8")
        for route in ("/api/login", "/api/logout", "/api/session", "/api/profiles", "/api/profiles/import", "/internal/profiles", "const publish ="):
            self.assertIn(route, source)
        for import_control in ("id=\"classNumber\"", "body.class_number", "shortcut_url", "Shortcut URL (paste into Get Contents of URL)"):
            self.assertIn(import_control, source)
        for control in ("PBKDF2", "HttpOnly", "SameSite=Strict", "X-CSRF-Token", "ADMIN_ORIGIN", "rateLimit"):
            self.assertIn(control, source)
        self.assertIn("GITHUB_DISPATCH_TOKEN", source)
        self.assertNotIn("GIST_TOKEN", source)

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
