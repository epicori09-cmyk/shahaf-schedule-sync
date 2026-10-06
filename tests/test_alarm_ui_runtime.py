from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from shahaf_sync.site import render_site


ROOT = Path(__file__).resolve().parents[1]
NODE_HARNESS = r'''
const fs = require("fs");
const vm = require("vm");

const input = JSON.parse(fs.readFileSync(0, "utf8"));

function fail(message) {
  throw new Error(message);
}

function expectEqual(actual, expected, label) {
  if (actual !== expected) {
    fail(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function expectTrue(value, label) {
  if (!value) fail(`${label}: expected a truthy value`);
}

function expectFalse(value, label) {
  if (value) fail(`${label}: expected a falsy value`);
}

class ClassList {
  constructor(element, initial = []) {
    this.element = element;
    this.values = new Set(initial.filter(Boolean));
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name);
    else this.values.delete(name);
    return next;
  }

  toString() {
    return [...this.values].join(" ");
  }
}

class Element {
  constructor(id = "", tagName = "div", classNames = []) {
    this.id = id;
    this.tagName = tagName.toUpperCase();
    this.classList = new ClassList(this, classNames);
    this.attributes = {};
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.textContent = "";
    this.innerHTML = "";
    this.title = "";
    this.focused = false;
    this.selected = false;
  }

  setAttribute(name, value) {
    const stringValue = String(value);
    this.attributes[name] = stringValue;
    if (name === "class") this.classList = new ClassList(this, stringValue.split(/\s+/));
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      this.dataset[key] = stringValue;
    }
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  dispatch(type, extra = {}) {
    const event = {
      type,
      target: this,
      preventDefault() {},
      ...extra,
    };
    for (const listener of this.listeners.get(type) || []) listener(event);
  }

  click() {
    this.dispatch("click");
  }

  focus() {
    this.focused = true;
  }

  select() {
    this.selected = true;
  }

  querySelector(selector) {
    if ((selector === "h2, h3" || selector === "h2" || selector === "h3") && this.id === "current-lesson") {
      return this.ownerDocument.byId("current-subject");
    }
    if ((selector === "h2, h3" || selector === "h2" || selector === "h3") && this.id === "next-lesson") {
      return this.ownerDocument.byId("next-subject");
    }
    if (selector === ".lesson-detail") {
      return this.ownerDocument.byId(this.id === "current-lesson" ? "current-detail" : "next-detail");
    }
    if (selector === ".lesson-time") {
      return this.ownerDocument.byId(this.id === "current-lesson" ? "current-time" : "next-time");
    }
    if (selector === "[data-i18n]" && this.id === "sync-status") {
      return this.ownerDocument.byId("sync-status-label");
    }
    return null;
  }

  querySelectorAll() {
    return [];
  }
}

function makeDocument(html) {
  const elements = new Map();
  const idPattern = /\sid="([^"]+)"/g;
  let match;
  while ((match = idPattern.exec(html))) {
    if (!elements.has(match[1])) elements.set(match[1], new Element(match[1]));
  }

  const tagFor = (id) => {
    const pattern = new RegExp(`<([a-z0-9]+)([^>]*\\sid="${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*)>`, "i");
    const found = html.match(pattern);
    return found ? found[1] : "div";
  };
  const classesFor = (id) => {
    const pattern = new RegExp(`<[^>]*\\sid="${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*\\sclass="([^"]*)"`, "i");
    const found = html.match(pattern);
    return found ? found[1].split(/\s+/) : [];
  };
  for (const [id, element] of elements) {
    element.tagName = tagFor(id).toUpperCase();
    element.classList = new ClassList(element, classesFor(id));
    element.ownerDocument = null;
  }

  const document = {
    hidden: false,
    title: "",
    listeners: new Map(),
    documentElement: { lang: "en", dir: "ltr" },
    body: new Element("body", "body"),
    byId(id) {
      return elements.get(id) || null;
    },
    getElementById(id) {
      return elements.get(id) || null;
    },
    createElement(tagName) {
      const element = new Element("", tagName);
      element.ownerDocument = document;
      return element;
    },
    querySelector(selector) {
      if (selector === ".identity strong" || selector === ".view-switch" || selector === ".schedule-heading .eyebrow") {
        return new Element("synthetic", "span");
      }
      if (selector === ".topbar" || selector === ".schedule-heading") return new Element("synthetic", "div");
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(listener);
    },
    dispatch(type) {
      for (const listener of this.listeners.get(type) || []) listener({ type });
    },
  };
  document.body.ownerDocument = document;
  document.body.classList = new ClassList(document.body, []);
  for (const element of elements.values()) element.ownerDocument = document;

  for (const id of ["full-view", "exams-view", "alarm-self-service-panel", "alarm-feedback"]) {
    const element = elements.get(id);
    if (element) element.hidden = true;
  }
  const syncLabel = new Element("sync-status-label", "span");
  syncLabel.ownerDocument = document;
  syncLabel.dataset.i18n = "synced";
  const syncStatus = elements.get("sync-status");
  if (syncStatus) syncStatus.querySelector = (selector) => selector === "[data-i18n]" ? syncLabel : null;

  return document;
}

function makeNetwork() {
  const requests = [];
  const pending = new Map();
  const fetch = (url, options = {}) => {
    const request = { url: String(url), options, settled: false };
    const index = requests.push(request) - 1;
    request.index = index;
    const promise = new Promise((resolve, reject) => {
      request.resolve = (body, ok = true) => {
        if (request.settled) return;
        request.settled = true;
        pending.delete(index);
        resolve({ ok, json: async () => body });
      };
      request.reject = (error) => {
        if (request.settled) return;
        request.settled = true;
        pending.delete(index);
        reject(error);
      };
      pending.set(index, request);
      if (options.signal) {
        if (options.signal.aborted) {
          const error = new Error("The operation was aborted.");
          error.name = "AbortError";
          request.reject(error);
        } else {
          options.signal.addEventListener("abort", () => {
            const error = new Error("The operation was aborted.");
            error.name = "AbortError";
            request.reject(error);
          }, { once: true });
        }
      }
    });
    request.promise = promise;
    return promise;
  };
  return {
    fetch,
    requests,
    respond(index, body, ok = true) {
      const request = pending.get(index);
      if (!request) fail(`request ${index} is not pending`);
      request.resolve(body, ok);
    },
    reject(index, message, name = "Error") {
      const request = pending.get(index);
      if (!request) fail(`request ${index} is not pending`);
      const error = new Error(message);
      error.name = name;
      request.reject(error);
    },
  };
}

function makeTimers() {
  let nextId = 1;
  const timers = new Map();
  const setTimeout = (callback, delay = 0) => {
    const id = nextId++;
    timers.set(id, { callback, delay, cancelled: false });
    return id;
  };
  const clearTimeout = (id) => {
    const timer = timers.get(id);
    if (timer) timer.cancelled = true;
  };
  return {
    setTimeout,
    clearTimeout,
    setInterval() { return nextId++; },
    clearInterval() {},
    run(delay) {
      for (const [id, timer] of [...timers.entries()]) {
        if (timer.cancelled || timer.delay !== delay) continue;
        timers.delete(id);
        timer.callback();
      }
    },
  };
}

function flush() {
  return new Promise((resolve) => {
    let rounds = 0;
    const step = () => {
      if (++rounds >= 12) return resolve();
      Promise.resolve().then(step);
    };
    step();
  });
}

function extractRenderedScripts(html) {
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  if (!scripts.length) fail("rendered page has no executable script");
  return scripts.map((script) => script[1]).join("\n");
}

function boot(html) {
  const document = makeDocument(html);
  const network = makeNetwork();
  const timers = makeTimers();
  const window = {
    confirm: () => true,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    addEventListener() {},
    scrollTo() {},
    location: { href: "" },
  };
  const context = vm.createContext({
    console,
    document,
    window,
    navigator: { languages: ["en"], language: "en", userAgent: "node", platform: "node", maxTouchPoints: 0 },
    location: { search: "" },
    fetch: network.fetch,
    AbortController,
    URLSearchParams,
    Date,
    Intl,
    Promise,
    Object,
    Array,
    Number,
    String,
    Boolean,
    Math,
    JSON,
    RegExp,
    Error,
    Node: { TEXT_NODE: 3 },
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
  });
  const bridge = `
    globalThis.__alarmRuntime = {
      refreshAlarmState,
      refreshDataInBackground,
      renderScheduledAlarm,
      localizeLiveState,
      get alarmState() { return alarmState; },
      get embeddedRootWake() { return activeProfile.wake; },
      get alarmRevision() { return alarmRevision; },
      get alarmIsAuthoritative() { return alarmIsAuthoritative; },
    };
  `;
  vm.runInContext(`${extractRenderedScripts(html)}\n${bridge}`, context, { filename: "rendered-index.html" });
  return { document, network, timers, runtime: context.__alarmRuntime };
}

function alarmValue(app) {
  return app.document.byId("alarm-scheduled-time").textContent;
}

function alarmFeedback(app) {
  const feedback = app.document.byId("alarm-feedback");
  return { text: feedback.textContent, hidden: feedback.hidden, error: feedback.classList.contains("is-error") };
}

function dataBody(id, generatedAt, wake) {
  return {
    id,
    generated_at: generatedAt,
    stale: false,
    schedule: [],
    schedule_available: true,
    changes: [],
    exams: [],
    events: [],
    wake,
  };
}

function wake(profileId, time, action = "set", extra = {}) {
  return {
    profile_id: profileId,
    next_school_day: "2026-10-07",
    wake_time: time,
    wake_at: time ? `2026-10-07T${time}:00+03:00` : null,
    shortcut_action: action,
    enabled: action === "set",
    ...extra,
  };
}

function previewEnvelope(profileId) {
  const root = wake(profileId, "06:45", "set", {
    generated_at: "2026-10-06T07:00:00+03:00",
    next_school_day: "2026-10-06",
    next_scheduled_school_day: "2026-10-06",
    wake_at: "2026-10-06T06:45:00+03:00",
    alarm_for_today: true,
    enabled: true,
    alarm_control: {
      enabled: true,
      wake_buffer_minutes: 75,
      round_to_minutes: 1,
      override_active: false,
      override_pending: true,
      transit_min_arrival_margin: 5,
    },
  });
  root.next_alarm = {
    profile_id: profileId,
    generated_at: "2026-10-06T07:00:00+03:00",
    next_school_day: "2026-10-07",
    next_scheduled_school_day: "2026-10-07",
    wake_time: null,
    wake_at: null,
    subject: null,
    enabled: false,
    alarm_for_today: false,
    stale: false,
    fallback_status: "manual-clear",
    shortcut_action: "clear",
    alarm_safety: "approved",
    alarm_safety_reason: "",
    timezone: "Asia/Jerusalem",
    alarm_label: "Shahaf",
    alarm_control: {
      command_version: "fixture-command-version",
      enabled: true,
      wake_buffer_minutes: 75,
      round_to_minutes: 1,
      override_active: true,
      override_pending: false,
      transit_min_arrival_margin: 5,
    },
    alarm_baseline: {
      next_school_day: "2026-10-07",
      wake_time: "07:15",
      wake_at: "2026-10-07T07:15:00+03:00",
      subject: "ספרות",
      enabled: true,
      shortcut_action: "set",
      fallback_status: "none",
      alarm_for_today: false,
      stale: false,
    },
  };
  return root;
}

function assertPreviewState(app, label) {
  const root = app.runtime.embeddedRootWake;
  const selected = app.runtime.alarmState;
  expectEqual(root.profile_id, "student-profile", `${label} root profile tag`);
  expectEqual(root.next_school_day, "2026-10-06", `${label} root school day`);
  expectEqual(root.wake_time, "06:45", `${label} root wake time`);
  expectEqual(root.shortcut_action, "set", `${label} root Shortcut action`);
  expectTrue(root.enabled, `${label} root remains enabled`);
  expectTrue(root.alarm_for_today, `${label} root remains today's alarm`);
  expectEqual(root.next_alarm.profile_id, "student-profile", `${label} nested profile tag`);
  expectEqual(root.next_alarm.next_school_day, "2026-10-07", `${label} nested future school day`);
  expectTrue(root.next_alarm.next_school_day > root.next_school_day, `${label} nested alarm is strictly future`);
  expectEqual(root.next_alarm.shortcut_action, "clear", `${label} nested Shortcut action`);
  expectEqual(selected.profile_id, "student-profile", `${label} selected profile tag`);
  expectEqual(selected.next_school_day, "2026-10-07", `${label} selected school day`);
  expectEqual(selected.shortcut_action, "clear", `${label} selected Shortcut action`);
  expectEqual(alarmValue(app), "Cancelled", `${label} displayed alarm state`);
  expectTrue(app.document.byId("alarm-scheduled-date").textContent.includes("October 7"), `${label} displayed future date`);
}

async function nestedPreviewSelection(html) {
  let app = boot(html);
  assertPreviewState(app, "initial embedded payload");

  app = boot(html);
  const getRefresh = app.runtime.refreshAlarmState();
  expectEqual(app.network.requests.length, 1, "nested GET starts one request");
  app.network.respond(0, previewEnvelope("student-profile"));
  await getRefresh;
  assertPreviewState(app, "authoritative GET payload");

  app.document.byId("alarm-self-service-toggle").click();
  app.document.byId("alarm-move-time").value = "08:00";
  app.document.byId("alarm-move-today").click();
  await flush();
  expectEqual(app.network.requests[1].options.method, "POST", "nested POST uses POST");
  const sent = JSON.parse(app.network.requests[1].options.body);
  expectEqual(sent.target_date, "2026-10-07", "command fences the displayed date");
  expectEqual(sent.command_version, "fixture-command-version", "command fences the displayed override version");
  app.network.respond(1, { status: "queued", action: "set", wake: previewEnvelope("student-profile") });
  await flush();
  assertPreviewState(app, "command POST payload");

  app = boot(html);
  const dataRefresh = app.runtime.refreshDataInBackground();
  expectEqual(app.network.requests.length, 1, "nested data refresh starts one request");
  app.network.respond(0, dataBody("student-profile", "2026-10-06T08:00:00+03:00", previewEnvelope("student-profile")));
  await dataRefresh;
  assertPreviewState(app, "data refresh payload");
}

async function cachedDataThenWorker(html) {
  const app = boot(html);
  expectEqual(alarmValue(app), "7:15 AM", "embedded alarm is rendered before refresh");
  const dataRefresh = app.runtime.refreshDataInBackground();
  expectEqual(app.network.requests.length, 1, "data refresh makes one request");
  expectTrue(app.network.requests[0].url.startsWith("./data.json?refresh="), "data refresh targets data.json");
  app.network.respond(0, dataBody("student-profile", "2026-10-06T07:00:00+03:00", wake("student-profile", "07:30")));
  await dataRefresh;
  expectEqual(alarmValue(app), "7:30 AM", "newer data refresh replaces cached alarm");

  const workerRefresh = app.runtime.refreshAlarmState();
  expectEqual(app.network.requests.length, 2, "authoritative refresh makes one request");
  expectTrue(app.network.requests[1].url.endsWith("/wake.json"), "authoritative refresh targets wake.json");
  app.network.respond(1, wake("student-profile", "07:45"));
  await workerRefresh;
  expectEqual(alarmValue(app), "7:45 AM", "authoritative Worker state replaces data refresh state");
  expectTrue(app.runtime.alarmIsAuthoritative, "Worker response is marked authoritative");
}

async function slowPreCommandGet(html) {
  const app = boot(html);
  const oldRefresh = app.runtime.refreshAlarmState();
  expectEqual(app.network.requests.length, 1, "pre-command alarm GET starts");

  app.document.byId("alarm-self-service-toggle").click();
  app.document.byId("alarm-move-time").value = "08:00";
  app.document.byId("alarm-move-today").click();
  await flush();
  expectEqual(app.network.requests.length, 2, "command POST starts while old GET is pending");
  expectEqual(app.network.requests[1].options.method, "POST", "command uses POST");
  app.network.respond(1, { target_date: "2026-10-07", wake_time: "08:00", wake_at: null });
  await flush();
  expectEqual(alarmValue(app), "8:00 AM", "command state is rendered before stale GET completes");

  app.network.respond(0, wake("student-profile", "06:30"));
  await oldRefresh;
  await flush();
  expectEqual(alarmValue(app), "8:00 AM", "slow pre-command GET cannot overwrite command state");
  expectTrue(alarmFeedback(app).text.includes("queued"), "successful command feedback remains visible");
}

async function mismatchedAndOlderRefreshes(html) {
  const app = boot(html);
  const initial = alarmValue(app);

  const mismatchedData = app.runtime.refreshDataInBackground();
  app.network.respond(0, dataBody("another-profile", "2026-10-07T08:00:00+03:00", wake("another-profile", "06:00")));
  await mismatchedData;
  expectEqual(alarmValue(app), initial, "profile-mismatched data leaves rendered alarm unchanged");

  const olderData = app.runtime.refreshDataInBackground();
  app.network.respond(1, dataBody("student-profile", "2026-10-05T08:00:00+03:00", wake("student-profile", "06:00")));
  await olderData;
  expectEqual(alarmValue(app), initial, "older data leaves rendered alarm unchanged");

  const mismatchedWorker = app.runtime.refreshAlarmState();
  app.network.respond(2, wake("another-profile", "06:00"));
  await mismatchedWorker;
  expectEqual(alarmValue(app), initial, "profile-mismatched Worker state leaves rendered alarm unchanged");
}

async function leaveIsPreserved(html) {
  const app = boot(html);
  expectEqual(alarmValue(app), "Current alarm preserved", "leave state renders as preserved");
  expectFalse(alarmValue(app).includes("Not scheduled"), "leave state is not rendered as not scheduled");
}

async function actionErrorAndTimeout(html) {
  const app = boot(html);
  app.document.byId("alarm-self-service-toggle").click();
  app.document.byId("alarm-move-time").value = "08:00";
  app.document.byId("alarm-move-today").click();
  await flush();
  app.network.respond(0, { error: "Worker rejected this alarm change" }, false);
  await flush();
  let feedback = alarmFeedback(app);
  expectEqual(feedback.text, "Worker rejected this alarm change", "server error is shown to the user");
  expectFalse(feedback.hidden, "server error feedback is visible");
  expectTrue(feedback.error, "server error feedback is styled as an error");
  expectEqual(alarmValue(app), "7:15 AM", "server error preserves the last rendered alarm");

  app.document.byId("alarm-move-time").value = "08:30";
  app.document.byId("alarm-move-today").click();
  await flush();
  expectEqual(app.network.requests.length, 3, "retry starts after the failed command's status refresh");
  expectEqual(app.network.requests[2].options.method, "POST", "retry uses POST after the status refresh");
  app.timers.run(15000);
  await flush();
  feedback = alarmFeedback(app);
  expectEqual(feedback.text, "Could not confirm the change. Refresh the alarm status before trying again.", "timeout explains that the command is unconfirmed");
  expectFalse(feedback.hidden, "timeout feedback is visible");
  expectTrue(feedback.error, "timeout feedback is styled as an error");
  expectEqual(alarmValue(app), "7:15 AM", "timeout preserves the last rendered alarm");
}

async function localizedLiveState(html) {
  const app = boot(html);
  const note = app.document.byId("schedule-note");

  note.textContent = "You’re in Period 5 now";
  app.runtime.localizeLiveState();
  expectEqual(note.textContent, "You’re in Period 5 now", "current-period note does not duplicate now");

  note.textContent = "Next lesson: Period 10";
  app.runtime.localizeLiveState();
  expectEqual(note.textContent, "Next lesson: Period 10", "next-lesson note preserves multi-digit period");
}

const scenarios = {
  cached_data_then_worker: cachedDataThenWorker,
  slow_pre_command_get: slowPreCommandGet,
  mismatched_and_older_refreshes: mismatchedAndOlderRefreshes,
  leave_is_preserved: leaveIsPreserved,
  action_error_and_timeout: actionErrorAndTimeout,
  localized_live_state: localizedLiveState,
  nested_preview_selection: nestedPreviewSelection,
};

(async () => {
  const scenario = scenarios[input.scenario];
  if (!scenario) fail(`unknown scenario ${input.scenario}`);
  await scenario(input.html);
  process.stdout.write(JSON.stringify({ ok: true, scenario: input.scenario }));
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
'''


class AlarmUiRuntimeTests(unittest.TestCase):
    PROFILE_ID = "student-profile"
    NOW = datetime(2026, 10, 6, 6, 0, tzinfo=timezone(timedelta(hours=3)))

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node.js is required for generated alarm UI runtime tests")

    def rendered_page(
        self,
        *,
        alarm_safety: str | None = None,
        schedule_date: str = "2026-10-07",
        special_wake_time: str | None = None,
    ) -> str:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            render_site(
                output,
                title="Student schedule",
                generated_at="2026-10-06T06:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                now=self.NOW,
                schedule=[
                    {
                        "date": schedule_date,
                        "period": 1,
                        "subject": "ספרות",
                        "teacher": "בר סבן",
                        "room": "208",
                        "start": "08:30",
                        "end": "09:10",
                    }
                ],
                profile_id=self.PROFILE_ID,
                public_profile=True,
                alarm_safety=alarm_safety,
                wake_time_by_first_lesson_start=(
                    {"08:30": special_wake_time} if special_wake_time else None
                ),
            )
            return (output / "index.html").read_text(encoding="utf-8")

    def rendered_preview_page(self) -> str:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            render_site(
                output,
                title="Student schedule",
                generated_at="2026-10-06T06:00:00+03:00",
                source_url="https://example.invalid",
                source_updated="fresh",
                changes=[],
                stale=False,
                now=self.NOW,
                schedule=[
                    {
                        "date": day,
                        "period": 1,
                        "subject": "ספרות",
                        "teacher": "בר סבן",
                        "room": "208",
                        "start": "08:30",
                        "end": "09:10",
                    }
                    for day in ("2026-10-06", "2026-10-07")
                ],
                profile_id=self.PROFILE_ID,
                public_profile=True,
                alarm_settings={"wake_buffer_minutes": 75},
                alarm_overrides=[
                    {
                        "id": "cancel-tomorrow",
                        "target_date": "2026-10-07",
                        "action": "clear",
                        "expires_at": "2026-10-07T20:59:59Z",
                    }
                ],
                wake_time_by_first_lesson_start={"08:30": "06:45"},
            )
            return (output / "index.html").read_text(encoding="utf-8")

    def run_runtime(self, scenario: str, *, alarm_safety: str | None = None) -> None:
        html = self.rendered_preview_page() if scenario == "nested_preview_selection" else self.rendered_page(alarm_safety=alarm_safety)
        payload = json.dumps(
            {"scenario": scenario, "html": html},
            ensure_ascii=False,
        )
        result = subprocess.run(
            [self.node, "-e", NODE_HARNESS],
            cwd=ROOT,
            input=payload,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                f"Node runtime scenario {scenario!r} failed (exit {result.returncode}).\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        self.assertEqual(json.loads(result.stdout), {"ok": True, "scenario": scenario})

    def test_cached_embedded_alarm_refreshes_from_data_then_authoritative_worker(self) -> None:
        self.run_runtime("cached_data_then_worker")

    def test_slow_pre_command_get_cannot_overwrite_newer_command_state(self) -> None:
        self.run_runtime("slow_pre_command_get")

    def test_profile_mismatched_and_older_refreshes_are_ignored(self) -> None:
        self.run_runtime("mismatched_and_older_refreshes")

    def test_leave_alarm_is_rendered_as_preserved(self) -> None:
        self.run_runtime("leave_is_preserved", alarm_safety="review-needed")

    def test_alarm_action_reports_server_errors_and_timeouts(self) -> None:
        self.run_runtime("action_error_and_timeout")

    def test_live_state_localization_preserves_period_notes(self) -> None:
        self.run_runtime("localized_live_state")

    def test_future_next_alarm_preview_is_selected_without_mutating_today_root(self) -> None:
        self.run_runtime("nested_preview_selection")


if __name__ == "__main__":
    unittest.main()
