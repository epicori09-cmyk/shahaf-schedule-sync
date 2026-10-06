from __future__ import annotations

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

class FakeResponse {
  constructor(body, { ok = true, contentType = "application/json" } = {}) {
    this.body = String(body);
    this.ok = ok;
    this.contentType = contentType;
    this.headers = {
      get: (name) => name.toLowerCase() === "content-type" ? this.contentType : null,
    };
  }

  clone() {
    return new FakeResponse(this.body, { ok: this.ok, contentType: this.contentType });
  }

  async json() {
    return JSON.parse(this.body);
  }
}

class FakeRequest {
  constructor(url, options = {}) {
    this.url = String(url);
    this.method = options.method || "GET";
    this.mode = options.mode || "cors";
  }
}

class FakeCache {
  constructor(initialData) {
    this.entries = new Map();
    this.addAllCalls = [];
    this.putCalls = [];
    if (initialData !== null) {
      this.entries.set("./data.json", new FakeResponse(JSON.stringify(initialData)));
    }
  }

  key(value) {
    return typeof value === "string" ? value : String(value.url);
  }

  async addAll(urls) {
    this.addAllCalls.push([...urls]);
    for (const url of urls) this.entries.set(url, new FakeResponse(`shell:${url}`, { contentType: "text/plain" }));
  }

  async match(value) {
    return this.entries.get(this.key(value)) || undefined;
  }

  async put(value, response) {
    const key = this.key(value);
    this.putCalls.push(key);
    this.entries.set(key, response.clone());
  }
}

function makeRuntime(initialData, response) {
  const listeners = new Map();
  const cache = new FakeCache(initialData);
  const fetchCalls = [];
  const self = {
    location: { href: "https://example.test/students/known-profile/" },
    clients: { claim() {} },
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(listener);
    },
    skipWaiting() {},
  };
  const caches = {
    async open() { return cache; },
    async keys() { return ["unused-cache"]; },
    async delete() { return true; },
    async match(value) { return cache.match(value); },
  };
  const context = vm.createContext({
    console,
    self,
    caches,
    URL,
    Request: FakeRequest,
    Promise,
    Date,
    Number,
    String,
    Array,
    JSON,
    Map,
    Error,
    fetch: async (request) => {
      fetchCalls.push(String(request.url || request));
      return response.clone();
    },
  });
  vm.runInContext(input.source, context, { filename: "sw.js" });
  return { listeners, cache, fetchCalls };
}

async function installCase(initialData, candidate) {
  const runtime = makeRuntime(
    initialData,
    new FakeResponse(candidate.body, { ok: candidate.ok, contentType: candidate.contentType }),
  );
  let installPromise;
  const event = { waitUntil(promise) { installPromise = promise; } };
  for (const listener of runtime.listeners.get("install") || []) listener(event);
  if (!installPromise) fail("install handler did not register waitUntil");
  await installPromise;
  const cached = await runtime.cache.match("./data.json");
  return {
    addAllCalls: runtime.cache.addAllCalls,
    putCalls: runtime.cache.putCalls,
    fetchCalls: runtime.fetchCalls,
    cachedData: cached ? await cached.json().catch(() => null) : null,
  };
}

function schedulePayload(id, generatedAt) {
  return {
    id,
    generated_at: generatedAt,
    schedule: [],
    changes: [],
    exams: [],
  };
}

async function installContract() {
  const result = await installCase(null, {
    body: JSON.stringify(schedulePayload("student-profile", "2026-10-06T07:00:00+03:00")),
    ok: true,
    contentType: "application/json",
  });
  const addAll = result.addAllCalls[0] || [];
  expectTrue(result.addAllCalls.length === 1, "install calls addAll once");
  expectTrue(!addAll.includes("./data.json"), "install does not precache data.json via addAll");
  expectTrue(result.fetchCalls.some((url) => url.endsWith("/data.json")), "install refreshes data.json separately");
  expectEqual(result.cachedData.id, "student-profile", "valid install response is cached");
}

async function refreshDataSafety() {
  const previous = schedulePayload("student-profile", "2026-10-05T07:00:00+03:00");
  const cases = [
    {
      name: "bad-200-html",
      candidate: { body: "<html>temporary error</html>", ok: true, contentType: "text/html" },
      expectedTimestamp: previous.generated_at,
    },
    {
      name: "wrong-profile",
      candidate: {
        body: JSON.stringify(schedulePayload("another-profile", "2026-10-06T07:00:00+03:00")),
        ok: true,
        contentType: "application/json",
      },
      expectedTimestamp: previous.generated_at,
    },
    {
      name: "older-timestamp",
      candidate: {
        body: JSON.stringify(schedulePayload("student-profile", "2026-10-04T07:00:00+03:00")),
        ok: true,
        contentType: "application/json",
      },
      expectedTimestamp: previous.generated_at,
    },
    {
      name: "valid-update",
      candidate: {
        body: JSON.stringify(schedulePayload("student-profile", "2026-10-06T07:00:00+03:00")),
        ok: true,
        contentType: "application/json",
      },
      expectedTimestamp: "2026-10-06T07:00:00+03:00",
    },
  ];
  for (const item of cases) {
    const result = await installCase(previous, item.candidate);
    expectTrue(result.cachedData !== null, `${item.name} retains cached data`);
    expectEqual(result.cachedData.generated_at, item.expectedTimestamp, `${item.name} cache timestamp`);
    const dataPuts = result.putCalls.filter((key) => key === "./data.json").length;
    expectEqual(dataPuts, item.name === "valid-update" ? 1 : 0, `${item.name} data cache writes`);
  }
}

async function alarmFeedsBypassCache() {
  const runtime = makeRuntime(null, new FakeResponse('{}'));
  const urls = [
    'https://alarm.example/public/profiles/student-profile/wake.json',
    'https://example.test/students/known-profile/wake.json',
    'https://example.test/students/another-profile/data.json',
    'https://example.test/api/alarm-command',
  ];
  for (const url of urls) {
    // Seed a stale response: bypass must hold even when CacheStorage already
    // contains the URL from a previous faulty service worker.
    runtime.cache.entries.set(url, new FakeResponse('{"shortcut_action":"set"}'));
    for (const action of ['set', 'clear']) {
      let intercepted = false;
      const event = { request: new FakeRequest(url), respondWith() { intercepted = true; }, waitUntil() {} };
      for (const listener of runtime.listeners.get('fetch') || []) listener(event);
      expectEqual(intercepted, false, `${url}: ${action} read must reach network, not the stored set`);
    }
  }
  expectEqual(runtime.cache.putCalls.length, 0, 'no alarm feed is written into the cache');
}

const scenarios = {
  install_contract: installContract,
  refresh_data_safety: refreshDataSafety,
  alarm_feeds_bypass_cache: alarmFeedsBypassCache,
};

(async () => {
  const scenario = scenarios[input.scenario];
  if (!scenario) fail(`unknown scenario ${input.scenario}`);
  await scenario();
  process.stdout.write(JSON.stringify({ ok: true, scenario: input.scenario }));
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
'''


class ServiceWorkerRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node.js is required for generated service-worker runtime tests")

    def rendered_worker(self) -> str:
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
                schedule=[],
                profile_id="student-profile",
                public_profile=True,
            )
            return (output / "sw.js").read_text(encoding="utf-8")

    def run_runtime(self, scenario: str) -> None:
        payload = json.dumps(
            {"scenario": scenario, "source": self.rendered_worker()},
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
                f"Node service-worker scenario {scenario!r} failed (exit {result.returncode}).\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        self.assertEqual(json.loads(result.stdout), {"ok": True, "scenario": scenario})

    def test_install_precaches_shell_then_refreshes_data_runtime(self) -> None:
        self.run_runtime("install_contract")

    def test_data_refresh_rejects_html_wrong_profile_and_older_runtime(self) -> None:
        self.run_runtime("refresh_data_safety")

    def test_alarm_feeds_never_use_even_preexisting_cache(self) -> None:
        self.run_runtime("alarm_feeds_bypass_cache")


if __name__ == "__main__":
    unittest.main()
