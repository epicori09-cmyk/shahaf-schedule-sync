const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const workerPath = path.resolve(__dirname, "../admin/worker/src/index.js");
const workerSource = fs.readFileSync(workerPath, "utf8");

async function loadWorker() {
  const source = `${workerSource}\nexport { israelOffset, validateAlarmCommand, applyPublicAlarmOverride, createAlarmRestoreSnapshot, alarmRestoreSnapshot, fetchPublicWake, getPendingAlarmOverrides, persistAlarmOverride, publicAlarmCommandVersion, nextPublicAlarmDate, effectivePublicWake, finalizeSettingsMutation, settingsVersion };`;
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}#${Date.now()}-${Math.random()}`);
}

test("time-only Clock root cannot ring a future plan on this morning or across a long gap", async () => {
  const { applyPublicAlarmOverride } = await loadWorker();
  const future = { profile_id: "student_123", next_school_day: "2026-10-07", wake_at: "2026-10-07T06:45:00+03:00", wake_time: "06:45", shortcut_action: "set", stale: false };
  for (const hour of ["05:00", "06:40"]) {
    const result = applyPublicAlarmOverride(future, [], new Date(`2026-10-06T${hour}:00+03:00`));
    assert.equal(result.shortcut_action, "clear");
    assert.equal(result.fallback_status, "future-alarm-deferred");
  }
  assert.equal(applyPublicAlarmOverride(future, [], new Date("2026-10-06T14:00:00+03:00")).shortcut_action, "set");
  assert.equal(applyPublicAlarmOverride({ ...future, next_school_day: "2026-10-11", wake_at: "2026-10-11T06:45:00+03:00" }, [], new Date("2026-10-08T20:00:00+03:00")).shortcut_action, "clear");
  assert.equal(applyPublicAlarmOverride({ ...future, alarm_control: { settings: { no_lessons_policy: "leave" } } }, [], new Date("2026-10-06T05:00:00+03:00")).shortcut_action, "leave");
  assert.equal(applyPublicAlarmOverride({ ...future, stale: true }, [], new Date("2026-10-06T05:00:00+03:00")).shortcut_action, "leave");
  const friday = { ...future, next_school_day: "2026-10-09", wake_at: "2026-10-09T06:45:00+03:00" };
  assert.equal(applyPublicAlarmOverride(friday, [], new Date("2026-10-08T20:00:00+03:00")).shortcut_action, "clear");
  assert.equal(applyPublicAlarmOverride({ ...friday, stale: true }, [], new Date("2026-10-08T20:00:00+03:00")).shortcut_action, "leave");
  for (const fallback_status of ["stale", "unavailable", "no-safe-route", "wake-time-bound", "unsafe-override-blocked"]) {
    assert.equal(applyPublicAlarmOverride({ ...future, fallback_status }, [], new Date("2026-10-06T05:00:00+03:00")).shortcut_action, "leave", fallback_status);
    assert.equal(applyPublicAlarmOverride({ ...future, fallback_status }, [], new Date("2026-10-09T05:00:00+03:00")).shortcut_action, "leave", `weekend ${fallback_status}`);
  }
});

test("public command versions bind profile, date, and the sorted covering override id set", async () => {
  const { publicAlarmCommandVersion } = await loadWorker();
  const rows = [
    { id: "z", target_date: "2026-10-06", target_date_end: "2026-10-08" },
    { id: "a", target_date: "2026-10-07" },
    { id: "unrelated", target_date: "2026-10-09" },
  ];
  const version = await publicAlarmCommandVersion("p1", "2026-10-07", rows);
  assert.equal(version, await publicAlarmCommandVersion("p1", "2026-10-07", rows.slice().reverse()));
  assert.notEqual(version, await publicAlarmCommandVersion("p2", "2026-10-07", rows));
  assert.notEqual(version, await publicAlarmCommandVersion("p1", "2026-10-08", rows));
  assert.notEqual(version, await publicAlarmCommandVersion("p1", "2026-10-07", rows.slice(1)));
});

test("provided public wake snapshot is reused for target, restore, and effective response", async (t) => {
  const { nextPublicAlarmDate, alarmRestoreSnapshot, effectivePublicWake } = await loadWorker();
  const originalFetch = global.fetch;
  let fetches = 0;
  global.fetch = async () => { fetches += 1; throw new Error("unexpected fetch"); };
  t.after(() => { global.fetch = originalFetch; });
  const targetDate = nextWeekdayDate(1);
  const baseline = { next_school_day: targetDate, wake_time: "07:15", wake_at: isoAtIsrael(targetDate, "07:15"), shortcut_action: "set", fallback_status: "scheduled" };
  const wake = {
    profile_id: "student_123", generated_at: new Date().toISOString(), next_school_day: null, wake_at: null, shortcut_action: "clear",
    next_alarm: { profile_id: "student_123", generated_at: new Date().toISOString(), ...baseline, alarm_baseline: baseline, alarm_control: {} },
  };
  assert.equal(await nextPublicAlarmDate({}, "student_123", wake), targetDate);
  const restored = JSON.parse(await alarmRestoreSnapshot({}, "student_123", targetDate, { restore_json: JSON.stringify({ ...baseline, wake_time: "06:00" }) }, { wake, requireFreshBaseline: true }));
  assert.equal(restored.wake_time, "07:15");
  const env = { DB: { prepare() { return { bind() { return this; }, async all() { return { results: [] }; } }; } } };
  const effective = await effectivePublicWake(env, { id: "p1", public_id: "student_123" }, { wake });
  assert.match(effective.next_alarm.alarm_control.command_version, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(fetches, 0);
});

test("fresh no-lessons restore baseline never resurrects an old set snapshot", async () => {
  const { alarmRestoreSnapshot, applyPublicAlarmOverride } = await loadWorker();
  const targetDate = nextWeekdayDate(1);
  const baseline = { next_school_day: targetDate, wake_time: null, wake_at: null, shortcut_action: "clear", fallback_status: "no-lessons", enabled: false };
  const wake = { next_alarm: { next_school_day: targetDate, alarm_baseline: baseline } };
  const old = { next_school_day: targetDate, wake_time: "06:30", wake_at: isoAtIsrael(targetDate, "06:30"), shortcut_action: "set" };
  const snapshot = JSON.parse(await alarmRestoreSnapshot({}, "student_123", targetDate, { restore_json: JSON.stringify(old) }, { wake, requireFreshBaseline: true }));
  assert.equal(snapshot.shortcut_action, "clear");
  assert.equal(snapshot.wake_at, null);
  const legacyRestoredRow = { id: "legacy-restore", target_date: targetDate, action: "set", wake_at: old.wake_at, restore_json: JSON.stringify(old), reason: "Student restored the correct original alarm time" };
  const effective = applyPublicAlarmOverride({ next_school_day: targetDate, ...old, alarm_baseline: baseline, alarm_control: { override_active: true } }, legacyRestoredRow);
  assert.equal(effective.shortcut_action, "clear");
  assert.equal(effective.wake_at, null);
  assert.equal(effective.alarm_control.override_active, false);
});

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
  assert.match(sql, /alarm_overrides\.id=\?12/i);
  assert.match(sql, /COALESCE\(alarm_overrides\.restore_json,\s*excluded\.restore_json\)/i);
  assert.equal(values[11], "old-id");
});

function publicCommandEnv(overrides = []) {
  let pendingReads = 0;
  let persisted = null;
  const state = { mutations: 0 };
  const env = {
    PUBLIC_SITE_ORIGIN: "https://school.example",
    __state: state,
    DB: {
      prepare(query) {
        let values = [];
        return {
          bind(...args) { values = args; return this; },
          async first() {
            if (/INSERT INTO rate_limits/.test(query)) return { attempts: 1 };
            if (/SELECT id, public_id FROM profiles/.test(query)) return { id: "p1", public_id: "student_123" };
            if (/target_date=\?2/.test(query)) return overrides.find((item) => item.target_date === values[1]) || null;
            throw new Error(`unexpected first SQL: ${query}`);
          },
          async all() {
            if (/FROM alarm_overrides/.test(query)) {
              pendingReads += 1;
              return { results: pendingReads > 1 && persisted ? [...overrides, persisted] : overrides };
            }
            throw new Error(`unexpected all SQL: ${query}`);
          },
          async run() {
            if (/INSERT INTO alarm_overrides/.test(query)) {
              state.mutations += 1;
              persisted = { id: values[0], profile_id: values[1], target_date: values[2], action: values[3], wake_at: values[4], expires_at: values[9] };
            }
            if (/INSERT INTO alarm_audit/.test(query)) {
              if (state.auditFails) throw new Error("injected audit failure after commit");
              state.mutations += 1;
            }
            if (/INSERT INTO alarm_overrides|INSERT INTO alarm_audit/.test(query)) return { meta: { changes: 1 } };
            throw new Error(`unexpected run SQL: ${query}`);
          },
        };
      },
    },
  };
  return env;
}

test("actual public command handler rejects missing/stale preview state and accepts current version with one wake fetch", async (t) => {
  const { default: worker, publicAlarmCommandVersion } = await loadWorker();
  const originalFetch = global.fetch;
  const targetDate = nextWeekdayDate(1);
  const baseline = { next_school_day: targetDate, wake_time: "07:15", wake_at: isoAtIsrael(targetDate, "07:15"), shortcut_action: "set", fallback_status: "scheduled", enabled: true };
  const wake = {
    profile_id: "student_123", generated_at: new Date().toISOString(), next_school_day: null, wake_at: null, wake_time: null, shortcut_action: "clear", fallback_status: "no-lessons", stale: false,
    next_alarm: { profile_id: "student_123", generated_at: new Date().toISOString(), ...baseline, alarm_baseline: baseline, alarm_control: {} },
  };
  let fetches = 0;
  global.fetch = async () => { fetches += 1; return new Response(JSON.stringify(wake)); };
  t.after(() => { global.fetch = originalFetch; });
  const send = (env, body) => worker.fetch(new Request("https://worker.example/public/profiles/student_123/alarm-command", {
    method: "POST", headers: { Origin: "https://school.example", "content-type": "application/json", "CF-Connecting-IP": "127.0.0.1" }, body: JSON.stringify(body),
  }), env);

  let response = await send(publicCommandEnv(), { action: "clear" });
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /target_date is required/);
  assert.equal(fetches, 0);

  response = await send(publicCommandEnv(), { action: "clear", target_date: targetDate });
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /command_version is required/);
  assert.equal(fetches, 0);

  response = await send(publicCommandEnv(), { action: "clear", target_date: "2099-01-01", command_version: "stale" });
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /target_date changed/);
  assert.equal(fetches, 1);

  const staleVersionEnv = publicCommandEnv();
  response = await send(staleVersionEnv, { action: "clear", target_date: targetDate, command_version: "stale-version" });
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /alarm command changed/);
  assert.equal(staleVersionEnv.__state.mutations, 0);
  assert.equal(fetches, 2);

  const range = { id: "range-1", profile_id: "p1", target_date: targetDate, target_date_end: nextWeekdayDate(2), action: "clear", expires_at: new Date(Date.now() + 86400000).toISOString() };
  const rangeEnv = publicCommandEnv([range]);
  response = await send(rangeEnv, { action: "restore", target_date: targetDate, command_version: await publicAlarmCommandVersion("p1", targetDate, [range]) });
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /range alarm changes are not supported/i);
  assert.equal(rangeEnv.__state.mutations, 0);
  assert.equal(fetches, 3);

  const version = await publicAlarmCommandVersion("p1", targetDate, []);
  const acceptedEnv = publicCommandEnv();
  fetches = 0;
  response = await send(acceptedEnv, { action: "clear", target_date: targetDate, command_version: version });
  assert.equal(response.status, 202);
  const accepted = await response.json();
  assert.equal(accepted.target_date, targetDate);
  assert.equal(accepted.wake.next_alarm.alarm_control.override_active, true);
  assert.match(accepted.wake.next_alarm.alarm_control.command_version, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(fetches, 1);
  assert.equal(acceptedEnv.__state.mutations, 2);

  const auditFailureEnv = publicCommandEnv();
  auditFailureEnv.__state.auditFails = true;
  response = await send(auditFailureEnv, { action: "clear", target_date: targetDate, command_version: version });
  assert.equal(response.status, 202);
  const savedWithWarning = await response.json();
  assert.equal(savedWithWarning.status, "accepted_with_warnings");
  assert.match(savedWithWarning.warnings.join(" "), /audit/i);
  assert.equal(savedWithWarning.wake.next_alarm.alarm_control.override_active, true);
  assert.equal(auditFailureEnv.__state.mutations, 1);
});

test("public command responses carry the effective wake and accept persisted publish failures", () => {
  assert.match(workerSource, /publish_status/);
  assert.match(workerSource, /wake:\s*await effectivePublicWake/);
  assert.doesNotMatch(workerSource, /alarm change was saved, but publishing is temporarily unavailable[\s\S]{0,80}503/);
});

test("public POST requires preview date/version and rejects overlapping ranges before mutation", () => {
  assert.match(workerSource, /target_date is required[\s\S]{0,200}409/);
  assert.match(workerSource, /command_version is required[\s\S]{0,200}409/);
  assert.match(workerSource, /target_date changed; refresh and try again/);
  assert.match(workerSource, /range alarm changes are not supported[\s\S]{0,200}409/i);
  assert.match(workerSource, /next_alarm[\s\S]{0,300}command_version/);
});

test("settings audit failure after CAS reports committed mutation and still attempts publish", async (t) => {
  const { finalizeSettingsMutation } = await loadWorker();
  const originalFetch = global.fetch;
  let dispatches = 0;
  let historyWrites = 0;
  global.fetch = async () => { dispatches += 1; return new Response(null, { status: 204 }); };
  t.after(() => { global.fetch = originalFetch; });
  const env = {
    GITHUB_DISPATCH_TOKEN: "token",
    GITHUB_REPO: "owner/repo",
    GITHUB_REF: "main",
    DB: {
      prepare(query) {
        return {
          bind() { return this; },
          async run() {
            if (/alarm_settings_history/.test(query)) { historyWrites += 1; return { meta: { changes: 1 } }; }
            if (/alarm_audit/.test(query)) throw new Error("injected audit failure");
            throw new Error(`unexpected SQL: ${query}`);
          },
        };
      },
    },
  };
  const result = await finalizeSettingsMutation(env, {
    scope: "global", previousSettings: { enabled: true }, action: "global-settings-updated",
    details: { settings: { enabled: false } }, publishId: "global-alarm-settings-updated",
  });
  assert.equal(historyWrites, 1);
  assert.equal(dispatches, 1);
  assert.equal(result.status, "accepted_with_warnings");
  assert.match(result.warnings.join(" "), /audit/i);
  assert.equal(result.publish_status, "queued");
});

test("admin settings and bulk clients carry versions and render partial outcomes", () => {
  assert.match(workerSource, /settings_version:globalVersion\(\)/);
  assert.match(workerSource, /settings_version:button\.dataset\.version/);
  assert.match(workerSource, /command_version:button\.dataset\.commandVersion/);
  assert.match(workerSource, /settings_versions:versions\.settings/);
  assert.match(workerSource, /command_versions:versions\.commands/);
  assert.match(workerSource, /"Applied: "\+Number\(result\.applied/);
  assert.match(workerSource, /status==="accepted_with_warnings"/);
  assert.match(workerSource, /return json\(payload, failed\.length \? 207 : 200\)/);
});

test("admin null or missing version requests are rejected before mutation", () => {
  assert.match(workerSource, /requestJsonObject\(request\)/);
  assert.match(workerSource, /settings_versions for every selected profile are required/);
  assert.match(workerSource, /command_versions for every selected profile are required/);
  assert.match(workerSource, /profile alarm settings changed; refresh and try again/);
  assert.match(workerSource, /Commands overlapping range alarm changes are not supported until range policy is chosen/);
});

async function adminFixture(overrides = []) {
  const digest = async (value) => Buffer.from(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))).toString("base64url");
  const csrfHash = await digest("fixture-csrf");
  const state = { settings: { p1: "{}", p2: "{}" }, mutations: 0, auditFails: false };
  const env = { ADMIN_ORIGIN: "https://worker.example", GITHUB_DISPATCH_TOKEN: "fixture", GITHUB_REPO: "fixture/repo", __state: state,
    DB: { prepare(query) { let args = []; return {
      bind(...values) { args = values; return this; },
      async first() {
        if (/FROM sessions/.test(query)) return { csrf_hash: csrfHash, expires_at: new Date(Date.now() + 3600000).toISOString() };
        if (/INSERT INTO rate_limits/.test(query)) return { attempts: 1 };
        if (/FROM profiles WHERE id/.test(query)) return { id: args[0], public_id: `public_${args[0]}`, name: "Fixture", active: 1 };
        if (/FROM alarm_profile_settings/.test(query)) return { settings_json: state.settings[args[0]] };
        throw new Error(`unexpected first SQL: ${query}`);
      },
      async all() {
        if (/FROM alarm_overrides/.test(query)) return { results: overrides };
        throw new Error(`unexpected all SQL: ${query}`);
      },
      async run() {
        if (/UPDATE alarm_profile_settings/.test(query)) {
          if (state.settings[args[2]] !== args[3]) return { meta: { changes: 0 } };
          state.settings[args[2]] = args[0]; state.mutations += 1;
          return { meta: { changes: 1 } };
        }
        if (/INSERT INTO alarm_settings_history/.test(query)) return { meta: { changes: 1 } };
        if (/INSERT INTO alarm_audit/.test(query)) {
          if (state.auditFails) throw new Error("injected audit failure");
          return { meta: { changes: 1 } };
        }
        throw new Error(`unexpected run SQL: ${query}`);
      },
    }; } },
  };
  const send = (path, body) => new Request(`https://worker.example${path}`, { method: "POST", headers: { Origin: env.ADMIN_ORIGIN, Cookie: "__Host-shahaf_session=fixture-session", "X-CSRF-Token": "fixture-csrf", "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { env, send };
}

test("Shortcut GET translates preserve to text false and accepts published false while keeping set/clear", async (t) => {
  const { default: worker } = await loadWorker();
  const originalFetch = global.fetch;
  t.after(() => { global.fetch = originalFetch; });
  const target = nextWeekdayDate(1);
  for (const action of ["leave", "false", "set", "clear"]) {
    const envelope = { profile_id: "student_123", generated_at: new Date().toISOString(), stale: false,
      next_school_day: target, shortcut_action: action, fallback_status: "none", enabled: action === "set",
      wake_at: action === "set" ? isoAtIsrael(target, "06:30") : null,
      wake_time: action === "set" ? "06:30" : null };
    global.fetch = async () => new Response(JSON.stringify({ ...envelope, next_alarm: { ...envelope, shortcut_action: action === "false" ? "leave" : action, alarm_control: {}, alarm_baseline: envelope } }));
    const response = await worker.fetch(new Request("https://worker.example/public/profiles/student_123/wake.json"), publicCommandEnv());
    assert.equal(response.status, 200, action);
    const result = await response.json();
    assert.equal(result.shortcut_action, ["leave", "false"].includes(action) ? "false" : action);
    assert.equal(typeof result.shortcut_action, "string");
    assert.equal(result.next_alarm.shortcut_action, action === "false" ? "leave" : action);
  }
});

test("authenticated admin handler rejects null, missing command versions and covering ranges without mutation", async () => {
  const { default: worker, publicAlarmCommandVersion } = await loadWorker();
  const targetDate = nextWeekdayDate(1);
  const fixture = await adminFixture();
  for (const body of [null, { action: "clear" }, { action: "clear", target_date: targetDate }]) {
    const response = await worker.fetch(fixture.send("/api/profiles/p1/alarm-command", body), fixture.env);
    assert.equal(response.status, 409);
    assert.equal(fixture.env.__state.mutations, 0);
  }
  const range = { id: "range", profile_id: "p1", target_date: targetDate, target_date_end: nextWeekdayDate(2), action: "clear", expires_at: new Date(Date.now() + 86400000).toISOString() };
  const ranged = await adminFixture([range]);
  const response = await worker.fetch(ranged.send("/api/profiles/p1/alarm-command", { action: "clear", target_date: targetDate, command_version: await publicAlarmCommandVersion("p1", targetDate, [range]) }), ranged.env);
  assert.equal(response.status, 409);
  assert.match((await response.json()).error, /range/i);
  assert.equal(ranged.env.__state.mutations, 0);
});

test("actual bulk handler reports committed audit failure and stale second profile separately, then publishes", async (t) => {
  const { default: worker, settingsVersion } = await loadWorker();
  const fixture = await adminFixture();
  fixture.env.__state.auditFails = true;
  let dispatches = 0;
  const originalFetch = global.fetch;
  global.fetch = async () => { dispatches += 1; return new Response(null, { status: 204 }); };
  t.after(() => { global.fetch = originalFetch; });
  const response = await worker.fetch(fixture.send("/api/alarm-bulk", { action: "pause", profile_ids: ["p1", "p2"], settings_versions: { p1: await settingsVersion("{}"), p2: "stale" } }), fixture.env);
  assert.equal(response.status, 207);
  const result = await response.json();
  assert.equal(result.status, "partial");
  assert.equal(result.applied, 1);
  assert.equal(result.results[0].status, "applied_with_warning");
  assert.equal(result.results[1].status, "conflict");
  assert.equal(JSON.parse(fixture.env.__state.settings.p1).enabled, false);
  assert.equal(fixture.env.__state.settings.p2, "{}");
  assert.equal(fixture.env.__state.mutations, 1);
  assert.equal(dispatches, 1);
});
