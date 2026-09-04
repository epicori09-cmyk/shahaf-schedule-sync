CREATE TABLE IF NOT EXISTS alarm_global_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  settings_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS alarm_profile_settings (
  profile_id TEXT PRIMARY KEY,
  settings_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS alarm_settings_history (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('global', 'profile')),
  profile_id TEXT,
  settings_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS alarm_overrides (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  target_date TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('set', 'clear', 'leave')),
  wake_at TEXT,
  subject TEXT,
  force INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  published_at TEXT,
  consumed_at TEXT,
  UNIQUE (profile_id, target_date)
);

CREATE TABLE IF NOT EXISTS alarm_audit (
  id TEXT PRIMARY KEY,
  profile_id TEXT,
  action TEXT NOT NULL,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'admin'
);
