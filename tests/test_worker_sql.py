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
RATE_SQL = sql_after("async function rateLimit", "INSERT INTO rate_limits")
PENDING_SQL = sql_after("async function getPendingAlarmOverrides", "SELECT id, profile_id")


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
        """)

    def persist(self, row_id, expected_id, wake="2026-10-07T04:00:00Z", restore='{"wake_time":"06:45"}'):
        self.db.execute(PERSIST_SQL, (row_id, "p1", "2026-10-07", "set", wake, None, 0,
                                      "test", "2026-10-06T00:00:00Z", "2026-10-08T00:00:00Z",
                                      restore, expected_id))
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
                                     '{"wake_time":"06:45"}', "before-restore", "p1"))
        self.assertEqual(self.db.execute("SELECT changes()").fetchone()[0], 1)
        self.assertEqual(self.persist("stale-writer", "before-restore"), 0)
        self.assertEqual(self.db.execute("SELECT id FROM alarm_overrides").fetchone()[0], "restored")

    def test_deleted_override_cannot_be_recreated_by_stale_writer(self):
        self.assertEqual(self.persist("original", ""), 1)
        self.db.execute("DELETE FROM alarm_overrides WHERE id='original'")
        self.assertEqual(self.persist("stale-writer", "original"), 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM alarm_overrides").fetchone()[0], 0)
        self.assertEqual(self.persist("fresh-writer", ""), 1)

    def test_atomic_rate_limit_stops_at_limit_and_resets_window(self):
        attempts = [self.db.execute(RATE_SQL, ("client", 1000, 3)).fetchone()[0] for _ in range(3)]
        self.assertEqual(attempts, [1, 2, 3])
        self.assertIsNone(self.db.execute(RATE_SQL, ("client", 1000, 3)).fetchone())
        self.assertEqual(self.db.execute(RATE_SQL, ("client", 2000, 3)).fetchone()[0], 1)

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
