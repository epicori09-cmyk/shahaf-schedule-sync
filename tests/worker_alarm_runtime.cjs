const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const workerPath = path.resolve(__dirname, "../admin/worker/src/index.js");
const workerSource = fs.readFileSync(workerPath, "utf8");

async function loadWorker() {
  const source = `${workerSource}\nexport { israelOffset, validateAlarmCommand, applyPublicAlarmOverride, createAlarmRestoreSnapshot, fetchPublicWake, getPendingAlarmOverrides, persistAlarmOverride };`;
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}#${Date.now()}-${Math.random()}`);
}

function isoAtIsrael(targetDate, clock) {
  const noon = new Date(`${targetDate}T12:00:00Z`);
  const zone = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Jerusalem", timeZoneName: "shortOffset" })
    .formatToParts(noon).find((part) => part.type === "timeZoneName").value;
  const match = zone.match(/^GMT([+-])(\d{1,2})(?::(\d{2}))?$/);
  const offset = `${match[1]}${match[2].padStart(2, "0")}:${match[3] || "00"}`;
  return `${targetDate}T${clock}:00${offset}`;
}

function nextWeekdayDate(daysAhead = 1) {
  const date = new Date();
  for (let count = 0; count < daysAhead || [5, 6].includes(date.getUTCDay());) {
    date.setUTCDate(date.getUTCDate() + 1);
    if (![5, 6].includes(date.getUTCDay())) count += 1;
  }
  return date.toISOString().slice(0, 10);
}

test("Israel offsets and embedded dashboard payloads follow DST", async () => {
  const { israelOffset } = await loadWorker();
  assert.equal(israelOffset("2026-01-15"), "+02:00");
  assert.equal(israelOffset("2026-07-15"), "+03:00");
  assert.doesNotMatch(workerSource, /wake_at=.*:00\+03:00/);
  assert.match(workerSource, /requestBody\.wake_at=requestBody\.target_date[\s\S]*israelOffsetForDate/);
});

test("set commands reject naive, mismatched-date, and weekend timestamps", async () => {
  const { validateAlarmCommand } = await loadWorker();
  assert.match(validateAlarmCommand({ action: "set", target_date: "2026-01-18", wake_at: "2026-01-18T07:00:00" }).errors.join(" "), /offset/i);
  assert.match(validateAlarmCommand({ action: "set", target_date: "2026-01-18", wake_at: "2026-01-19T07:00:00+02:00" }).errors.join(" "), /target_date/i);
  assert.match(validateAlarmCommand({ action: "set", target_date: "2026-01-17", wake_at: "2026-01-17T07:00:00+02:00" }).errors.join(" "), /Friday|Saturday|weekend/i);
  assert.match(validateAlarmCommand({ action: "set", target_date: "2026-02-30", wake_at: "2026-03-02T07:00:00+02:00" }).errors.join(" "), /target_date/i);
  assert.equal(validateAlarmCommand({ action: "set", target_date: "2026-01-18", wake_at: "2026-01-18T07:00:00+02:00" }).errors, undefined);
});

test("legacy restore snapshots require an explicit unaffected baseline", async () => {
  const { createAlarmRestoreSnapshot } = await loadWorker();
  const moved = {
    profile_id: "student_123",
    next_school_day: "2026-01-18",
    wake_time: "08:30",
    wake_at: "2026-01-18T06:30:00.000Z",
    shortcut_action: "set",
  };
  assert.equal(createAlarmRestoreSnapshot(moved, "2026-01-18", { requireExplicitBaseline: true }), null);
  moved.alarm_baseline = { ...moved, wake_time: "07:00", wake_at: "2026-01-18T05:00:00.000Z" };
  assert.equal(JSON.parse(createAlarmRestoreSnapshot(moved, "2026-01-18", { requireExplicitBaseline: true })).wake_time, "07:00");
});

test("public wake fetch rejects stale, mis-tagged, and invalid future envelopes", async (t) => {
  const { fetchPublicWake } = await loadWorker();
  const originalFetch = global.fetch;
  t.after(() => { global.fetch = originalFetch; });
  const future = nextWeekdayDate(2);
  const valid = {
    profile_id: "student_123",
    generated_at: new Date().toISOString(),
    next_school_day: nextWeekdayDate(1),
    wake_at: isoAtIsrael(nextWeekdayDate(1), "07:00"),
    shortcut_action: "set",
    next_alarm: {
      profile_id: "student_123",
      generated_at: new Date().toISOString(),
      next_school_day: future,
      wake_at: isoAtIsrael(future, "07:10"),
      shortcut_action: "set",
      alarm_baseline: { next_school_day: future, wake_time: "07:10", wake_at: isoAtIsrael(future, "07:10"), shortcut_action: "set" },
      alarm_control: { override_active: false },
    },
  };
  global.fetch = async () => new Response(JSON.stringify(valid));
  assert.equal((await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123")).profile_id, "student_123");

  global.fetch = async () => new Response(JSON.stringify({ ...valid, generated_at: new Date(Date.now() - 3 * 60 * 60 * 1000 - 1).toISOString() }));
  const stale = await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123");
  assert.equal(stale.shortcut_action, "leave");
  assert.equal(stale.next_alarm.shortcut_action, "leave");
  assert.equal(stale.wake_at, null);

  global.fetch = async () => new Response(JSON.stringify({ ...valid, profile_id: "other_student" }));
  assert.equal(await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123"), null);

  global.fetch = async () => new Response(JSON.stringify({ ...valid, next_alarm: { ...valid.next_alarm, next_school_day: nextWeekdayDate(1), wake_at: isoAtIsrael(future, "07:10") } }));
  assert.equal(await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123"), null);
});

test("fresh safe no-lessons roots with null target are accepted without authorizing stale clears", async (t) => {
  const { fetchPublicWake } = await loadWorker();
  const originalFetch = global.fetch;
  t.after(() => { global.fetch = originalFetch; });
  const noLessons = {
    profile_id: "student_123", generated_at: new Date().toISOString(), stale: false,
    next_school_day: null, wake_at: null, wake_time: null, shortcut_action: "clear", fallback_status: "no-lessons",
    next_alarm: {
      profile_id: "student_123", generated_at: new Date().toISOString(), stale: false,
      next_school_day: null, wake_at: null, wake_time: null, shortcut_action: "clear", fallback_status: "no-lessons",
      alarm_baseline: { next_school_day: null, wake_at: null, wake_time: null, shortcut_action: "clear", fallback_status: "no-lessons" },
      alarm_control: {},
    },
  };
  global.fetch = async () => new Response(JSON.stringify(noLessons));
  const fresh = await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123");
  assert.equal(fresh.shortcut_action, "clear");
  assert.equal(fresh.next_alarm.shortcut_action, "clear");
  assert.equal(fresh.next_alarm.next_school_day, null);
  global.fetch = async () => new Response(JSON.stringify({ ...noLessons, stale: true }));
  const stale = await fetchPublicWake({ PUBLIC_SITE_ORIGIN: "https://school.example" }, "student_123");
  assert.equal(stale.shortcut_action, "leave");
  assert.equal(stale.next_alarm.shortcut_action, "leave");
  assert.equal(stale.next_alarm.next_school_day, null);
});

test("applying a future cancellation preserves the current root and updates next_alarm", async () => {
  const { applyPublicAlarmOverride } = await loadWorker();
  const currentDate = nextWeekdayDate(1);
  const futureDate = nextWeekdayDate(2);
  const wake = {
    profile_id: "student_123",
    next_school_day: currentDate,
    wake_time: "06:45",
    wake_at: isoAtIsrael(currentDate, "06:45"),
    shortcut_action: "set",
    alarm_control: { override_active: false },
    next_alarm: {
      profile_id: "student_123",
      next_school_day: futureDate,
      wake_time: "07:10",
      wake_at: isoAtIsrael(futureDate, "07:10"),
      shortcut_action: "set",
      alarm_control: { override_active: false },
    },
  };
  const result = applyPublicAlarmOverride(wake, { id: "future-clear", target_date: futureDate, action: "clear" });
  assert.equal(result.wake_time, "06:45");
  assert.equal(result.shortcut_action, "set");
  assert.equal(result.alarm_control.override_pending, true);
  assert.equal(result.next_alarm.shortcut_action, "clear");
  assert.equal(result.next_alarm.alarm_control.override_active, true);
});

test("set overrides never create Friday or Saturday alarms at runtime", async () => {
  const { applyPublicAlarmOverride } = await loadWorker();
  const date = "2026-01-17";
  const wake = { next_school_day: date, wake_time: null, wake_at: null, shortcut_action: "clear" };
  const result = applyPublicAlarmOverride(wake, { target_date: date, action: "set", wake_at: "2026-01-17T07:00:00+02:00" });
  assert.deepEqual(result, wake);
});

test("current Israel weekend clears root set while preserving Sunday preview", async () => {
  const { applyPublicAlarmOverride } = await loadWorker();
  const sunday = "2026-10-11";
  const wake = {
    next_school_day: sunday, wake_time: "06:45", wake_at: `${sunday}T06:45:00+03:00`, shortcut_action: "set", enabled: true,
    next_alarm: { next_school_day: sunday, wake_time: "06:45", wake_at: `${sunday}T06:45:00+03:00`, shortcut_action: "set", enabled: true },
  };
  const friday = new Date("2026-10-09T00:05:00+03:00");
  for (const overrides of [[], [{ target_date: sunday, action: "set", wake_at: `${sunday}T07:10:00+03:00`, force: true }]]) {
    const result = applyPublicAlarmOverride(wake, overrides, friday);
    assert.equal(result.shortcut_action, "clear");
    assert.equal(result.wake_at, null);
    assert.equal(result.next_alarm.shortcut_action, "set");
    assert.equal(result.next_alarm.next_school_day, sunday);
  }
});

test("elapsed or missing root set leaves Clock untouched and keeps future preview", async () => {
  const { applyPublicAlarmOverride } = await loadWorker();
  const now = new Date("2026-10-06T06:50:00+03:00");
  const future = "2026-10-07";
  const preview = { next_school_day: future, wake_time: "07:00", wake_at: `${future}T07:00:00+03:00`, shortcut_action: "set" };
  for (const wakeAt of ["2026-10-06T06:45:00+03:00", null]) {
    const result = applyPublicAlarmOverride({ next_school_day: "2026-10-06", wake_time: "06:45", wake_at: wakeAt, shortcut_action: "set", next_alarm: preview }, [], now);
    assert.equal(result.shortcut_action, "leave");
    assert.equal(result.next_alarm.shortcut_action, "set");
    assert.equal(result.next_alarm.next_school_day, future);
  }
});

test("public wake GET/OPTIONS expose CORS only to the configured site origin", async () => {
  const { default: worker } = await loadWorker();
  const allowed = "https://school.example";
  const env = { PUBLIC_SITE_ORIGIN: allowed, DB: { prepare() { throw new Error("DB should not be reached for preflight"); } } };
  const okay = await worker.fetch(new Request("https://worker.example/public/profiles/student_123/wake.json", { method: "OPTIONS", headers: { Origin: allowed } }), env);
  assert.equal(okay.status, 204);
  assert.equal(okay.headers.get("access-control-allow-origin"), allowed);
  assert.match(okay.headers.get("access-control-allow-methods"), /GET/);
  const rejected = await worker.fetch(new Request("https://worker.example/public/profiles/student_123/wake.json", { method: "OPTIONS", headers: { Origin: "https://evil.example" } }), env);
  assert.equal(rejected.status, 403);
  assert.equal(rejected.headers.get("access-control-allow-origin"), null);
});

test("active override reads are additive and do not let the newest unrelated date mask another", async () => {
  const { getPendingAlarmOverrides } = await loadWorker();
  let sql = "";
  const env = { DB: { prepare(query) { sql = query; return { bind() { return this; }, async all() { return { results: [
    { id: "tomorrow", target_date: "2026-01-19", action: "clear" },
    { id: "today", target_date: "2026-01-18", action: "set" },
  ] }; } }; } } };
  const rows = await getPendingAlarmOverrides(env, "profile-1");
  assert.deepEqual(rows.map((row) => row.id), ["tomorrow", "today"]);
  assert.doesNotMatch(sql, /LIMIT 1/i);
  assert.match(workerSource, /alarm_overrides:\s*profileAlarm\.overrides/);
});

test("override persistence uses optimistic id CAS and preserves the first restore baseline", async () => {
  const { persistAlarmOverride } = await loadWorker();
  let sql = "";
  let values = [];
  const env = { DB: { prepare(query) { sql = query; return { bind(...args) { values = args; return this; }, async run() { return { meta: { changes: 0 } }; } }; } } };
  const saved = await persistAlarmOverride(env, {
    id: "new-id", profileId: "profile-1", targetDate: "2026-01-18", action: "clear", wakeAt: null,
    subject: null, force: false, reason: "test", createdAt: new Date().toISOString(), expiresAt: new Date(Date.now() + 86400000).toISOString(),
    restoreJson: JSON.stringify({ wake_time: "07:00" }), expectedOverrideId: "old-id",
  });
  assert.equal(saved, false);
  assert.match(sql, /WHERE\s+alarm_overrides\.id=\?12/i);
  assert.match(sql, /COALESCE\(alarm_overrides\.restore_json,\s*excluded\.restore_json\)/i);
  assert.equal(values.at(-1), "old-id");
});

test("public command responses carry the effective wake and accept persisted publish failures", () => {
  assert.match(workerSource, /publish_status/);
  assert.match(workerSource, /wake:\s*await effectivePublicWake/);
  assert.doesNotMatch(workerSource, /alarm change was saved, but publishing is temporarily unavailable[\s\S]{0,80}503/);
});

