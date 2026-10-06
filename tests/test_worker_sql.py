import re
import sqlite3
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "admin/worker/src/index.js").read_text(encoding="utf-8")


def sql_after(anchor, prefix):
    section = SOURCE[SOURCE.index(anchor):]
    for sql in re.findall(r'\.prepare\("([^"]+)"\)', section):
        if sql.startswith(prefix):
            return sql
    raise AssertionError(f"SQL beginning {prefix!r} not found after {anchor!r}")


PERSIST_SQL = sql_after("async function persistAlarmOverride", "INSERT INTO alarm_overrides")
RESTORE_SQL = sql_after('if (action === "restore")', "UPDATE alarm_overrides SET")
LEGACY_RESTORE_SQL = sql_after('if (action === "restore")', "DELETE FROM alarm_overrides")
RATE_SQL = sql_after("async function rateLimit", "INSERT INTO rate_limits")
PENDING_SQL = sql_after("async function getPendingAlarmOverrides", "SELECT id, profile_id")
GLOBAL_UPDATE_SQL = sql_after("async function updateGlobalSettingsCAS", "UPDATE alarm_global_settings")
PROFILE_INSERT_SQL = sql_after("async function updateProfileSettingsCAS", "INSERT INTO alarm_profile_settings")
PROFILE_UPDATE_SQL = sql_after("async function updateProfileSettingsCAS", "UPDATE alarm_profile_settings")
PROFILE_DELETE_SQL = sql_after("async function resetProfileSettingsCAS", "DELETE FROM alarm_profile_settings")


class WorkerSqlTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
          CREATE TABLE alarm_overrides(
            id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, target_date TEXT NOT NULL,
            target_date_end TEXT, action TEXT NOT NULL, wake_at TEXT, subject TEXT,
            force INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, published_at TEXT, consumed_at TEXT, restore_json TEXT,
            UNIQUE(profile_id, target_date)
          );
          CREATE TABLE rate_limits(bucket_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, attempts INTEGER NOT NULL);
          CREATE TABLE alarm_global_settings(id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
          CREATE TABLE alarm_profile_settings(profile_id TEXT PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
        """)

    def persist(self, row_id, expected_id, wake="2026-10-07T04:00:00Z", restore='{"wake_time":"06:45"}', expected_ids=None):
        fence_enabled = expected_ids is not None
        expected_ids = expected_ids if fence_enabled else []
        self.db.execute(PERSIST_SQL, (row_id, "p1", "2026-10-07", "set", wake, None, 0,
                                      "test", "2026-10-06T00:00:00Z", "2026-10-08T00:00:00Z",
                                      restore, expected_id, int(fence_enabled), len(expected_ids),
                                      __import__("json").dumps(expected_ids), "2026-10-06T00:00:00Z"))
        return self.db.execute("SELECT changes()").fetchone()[0]

    def test_cas_insert_competing_writes_and_first_baseline(self):
        self.assertEqual(self.persist("original", ""), 1)
        self.assertEqual(self.persist("winner", "original", restore='{"wake_time":"09:00"}'), 1)
        self.assertEqual(self.persist("loser", "original"), 0)
        row = self.db.execute("SELECT id, restore_json FROM alarm_overrides").fetchone()
        self.assertEqual(row, ("winner", '{"wake_time":"06:45"}'))

    def test_restore_rotates_version_and_blocks_pre_restore_writer(self):
        self.assertEqual(self.persist("before-restore", ""), 1)
        self.assertRegex(RESTORE_SQL, r"SET id=\?1, action=\?2")
        self.db.execute(RESTORE_SQL, ("restored", "set", "2026-10-07T03:45:00Z", None,
                                     "restore", "2026-10-06T00:01:00Z", "2026-10-08T00:00:00Z",
                                     '{"wake_time":"06:45"}', "before-restore", "p1", '["before-restore"]',
                                     "2026-10-06T00:00:00Z", "2026-10-07"))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)
        self.assertEqual(self.persist("stale-writer", "before-restore"), 0)
        self.assertEqual(self.db.execute("SELECT id FROM alarm_overrides").fetchone()[0], "restored")

    def test_deleted_override_cannot_be_recreated_by_stale_writer(self):
        self.assertEqual(self.persist("original", ""), 1)
        self.db.execute("DELETE FROM alarm_overrides WHERE id='original'")
        self.assertEqual(self.persist("stale-writer", "original"), 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM alarm_overrides").fetchone()[0], 0)
        self.assertEqual(self.persist("fresh-writer", ""), 1)

    def test_expired_exact_conflict_allows_fresh_write_and_baseline(self):
        self.db.execute(
            "INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at,restore_json) VALUES('expired','p1','2026-10-07','set','','2026-10-05T00:00:00Z','2026-10-05T23:59:59Z','{\"wake_time\":\"06:00\"}')"
        )
        self.assertEqual(self.persist("fresh", "", restore='{"wake_time":"07:15"}'), 1)
        self.assertEqual(self.db.execute("SELECT id, restore_json FROM alarm_overrides").fetchone(), ("fresh", '{"wake_time":"07:15"}'))

    def test_consumed_exact_conflict_allows_fresh_write_and_baseline(self):
        self.db.execute(
            "INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at,consumed_at,restore_json) VALUES('consumed','p1','2026-10-07','set','','2026-10-05T00:00:00Z','2026-10-08T23:59:59Z','2026-10-05T12:00:00Z','{\"wake_time\":\"06:00\"}')"
        )
        self.assertEqual(self.persist("fresh", "", restore='{"wake_time":"07:15"}'), 1)
        self.assertEqual(self.db.execute("SELECT id, consumed_at, restore_json FROM alarm_overrides").fetchone(), ("fresh", None, '{"wake_time":"07:15"}'))

    def test_stale_expected_id_cannot_revive_inactive_row(self):
        self.db.execute(
            "INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at,restore_json) VALUES('old','p1','2026-10-07','set','','2026-10-05T00:00:00Z','2026-10-05T23:59:59Z','{\"wake_time\":\"06:00\"}')"
        )
        self.assertEqual(self.persist("stale", "old", restore='{"wake_time":"08:00"}'), 0)
        self.assertEqual(self.db.execute("SELECT id, restore_json FROM alarm_overrides").fetchone(), ("old", '{"wake_time":"06:00"}'))
        self.assertEqual(self.persist("fresh", "", restore='{"wake_time":"07:15"}'), 1)
        self.assertEqual(self.db.execute("SELECT id, restore_json FROM alarm_overrides").fetchone(), ("fresh", '{"wake_time":"07:15"}'))

    def test_snapshot_fence_rejects_concurrent_exact_and_range_set_changes(self):
        cases = (
            ("new exact", [], "INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at) VALUES('new','p1','2026-10-07','clear','','2026-10-06T00:01:00Z','2026-10-08T00:00:00Z')", ""),
            ("new range", [], "INSERT INTO alarm_overrides(id,profile_id,target_date,target_date_end,action,reason,created_at,expires_at) VALUES('range','p1','2026-10-06','2026-10-08','clear','','2026-10-06T00:01:00Z','2026-10-08T00:00:00Z')", ""),
            ("changed exact", ["old"], "UPDATE alarm_overrides SET id='changed' WHERE id='old'", "old"),
            ("changed range", ["old"], "UPDATE alarm_overrides SET id='changed' WHERE id='old'", ""),
            ("deleted exact", ["old"], "DELETE FROM alarm_overrides WHERE id='old'", "old"),
            ("deleted range", ["old"], "DELETE FROM alarm_overrides WHERE id='old'", ""),
        )
        for label, expected_ids, mutation, expected_exact_id in cases:
            with self.subTest(label=label):
                self.db.execute("DELETE FROM alarm_overrides")
                if expected_ids:
                    is_range = "range" in label
                    self.db.execute(
                        "INSERT INTO alarm_overrides(id,profile_id,target_date,target_date_end,action,reason,created_at,expires_at) VALUES('old','p1',?,?, 'clear','','2026-10-06T00:00:00Z','2026-10-08T00:00:00Z')",
                        ("2026-10-06" if is_range else "2026-10-07", "2026-10-08" if is_range else None),
                    )
                self.db.execute(mutation)
                self.assertEqual(self.persist("writer", expected_exact_id, expected_ids=expected_ids), 0)

    def test_restore_update_and_delete_share_the_active_covering_set_fence(self):
        self.assertRegex(RESTORE_SQL, r"json_each")
        self.assertRegex(LEGACY_RESTORE_SQL, r"json_each")
        self.db.execute("INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at) VALUES('old','p1','2026-10-07','clear','','2026-10-06T00:00:00Z','2026-10-08T00:00:00Z')")
        self.db.execute("INSERT INTO alarm_overrides(id,profile_id,target_date,target_date_end,action,reason,created_at,expires_at) VALUES('range','p1','2026-10-06','2026-10-08','clear','','2026-10-06T00:01:00Z','2026-10-08T00:00:00Z')")
        update_values = ("restored", "set", "2026-10-07T03:45:00Z", None, "restore",
                         "2026-10-06T00:02:00Z", "2026-10-08T00:00:00Z", '{"wake_time":"06:45"}', "old", "p1",
                         '["old"]', "2026-10-06T00:00:00Z", "2026-10-07")
        self.db.execute(RESTORE_SQL, update_values)
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.db.execute(LEGACY_RESTORE_SQL, ("old", "p1", '["old"]', "2026-10-06T00:00:00Z", "2026-10-07"))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM alarm_overrides").fetchone()[0], 2)

    def test_atomic_rate_limit_stops_at_limit_and_resets_window(self):
        attempts = [self.db.execute(RATE_SQL, ("client", 1000, 3)).fetchone()[0] for _ in range(3)]
        self.assertEqual(attempts, [1, 2, 3])
        self.assertIsNone(self.db.execute(RATE_SQL, ("client", 1000, 3)).fetchone())
        self.assertEqual(self.db.execute(RATE_SQL, ("client", 2000, 3)).fetchone()[0], 1)

    def test_settings_cas_predicates_are_real_sqlite_compare_and_swap(self):
        self.db.execute("INSERT INTO alarm_global_settings VALUES(1, '{\"enabled\":true}', 't0', 'admin')")
        self.db.execute(GLOBAL_UPDATE_SQL, ('{"enabled":false}', 't1', '{"enabled":true}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)
        self.db.execute(GLOBAL_UPDATE_SQL, ('{"enabled":true}', 't2', '{"enabled":true}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT settings_json FROM alarm_global_settings").fetchone()[0], '{"enabled":false}')

        self.db.execute(PROFILE_INSERT_SQL, ("p1", '{"enabled":true}', 't0'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)
        self.db.execute(PROFILE_INSERT_SQL, ("p1", '{"enabled":false}', 't1'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.db.execute(PROFILE_UPDATE_SQL, ('{"enabled":false}', 't1', 'p1', '{"enabled":true}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)
        self.db.execute(PROFILE_UPDATE_SQL, ('{"enabled":true}', 't2', 'p1', '{"enabled":true}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.db.execute(PROFILE_DELETE_SQL, ('p1', '{"enabled":true}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 0)
        self.db.execute(PROFILE_DELETE_SQL, ('p1', '{"enabled":false}'))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)

    def test_pending_query_keeps_all_active_target_dates(self):
        rows = [
            ("a", "p1", "2026-10-07", "set", "2026-10-06T02:00:00Z", "2026-10-09T00:00:00Z", None),
            ("b", "p1", "2026-10-08", "clear", "2026-10-06T03:00:00Z", "2026-10-09T00:00:00Z", None),
            ("used", "p1", "2026-10-09", "clear", "2026-10-06T04:00:00Z", "2026-10-10T00:00:00Z", "2026-10-06T05:00:00Z"),
        ]
        self.db.executemany("INSERT INTO alarm_overrides(id,profile_id,target_date,action,reason,created_at,expires_at,consumed_at) VALUES(?,?,?,?, '',?,?,?)", rows)
        found = self.db.execute(PENDING_SQL, ("p1", "2026-10-06T00:00:00Z")).fetchall()
        self.assertEqual([row[2] for row in found], ["2026-10-08", "2026-10-07"])


if __name__ == "__main__":
    unittest.main()
