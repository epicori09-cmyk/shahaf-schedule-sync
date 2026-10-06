"""Run deliberate safety defects only inside automatically removed temp copies."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = [
    ("Clock occurrence guard removed", "src/shahaf_sync/alarm_controls.py", "if current.weekday() in {4, 5} or timestamp != next_ring:", "if False:", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_clock_occurrence.py"]),
    ("Restore replays saved baseline", "src/shahaf_sync/alarm_controls.py", "restore_snapshot = fresh_baseline", "restore_snapshot = json.loads(override['restore_json'])", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_restore_freshness.py"]),
    ("Service worker intercepts live cross-origin feed", "src/shahaf_sync/site.py", "if (requestUrl.origin !== scopeUrl.origin || !requestUrl.pathname.startsWith(scopeUrl.pathname)) return;", "if (requestUrl.origin !== scopeUrl.origin) {{ event.respondWith(caches.match(request)); return; }}", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_service_worker_runtime.py"]),
    ("Worker permits stale command version", "admin/worker/src/index.js", 'if (!same(String(body.command_version || ""), commandVersion))', "if (false)", ["node", "tests/worker_alarm_runtime.cjs"]),
    ("Period zero treated as missing", "src/shahaf_sync/profiles.py", "target_period = change.new_period if change.new_period is not None else old.period", "target_period = change.new_period or old.period", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_profiles.py"]),
    ("Cancellation ignores supplied teacher", "src/shahaf_sync/reconcile.py", 'if change.teacher and _detail_key(_teacher(effective)) != _detail_key(change.teacher):', "if False:", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_reconcile.py"]),
]

failures = 0
for label, filename, before, after, command in MUTATIONS:
    with TemporaryDirectory(prefix="shahaf-isolated-mutation-") as directory:
        clone = Path(directory)
        for folder in ("src", "tests", "admin/worker/src"):
            shutil.copytree(ROOT / folder, clone / folder)
        # Tests inspect the generated site or other scripts in the checkout.
        shutil.copytree(ROOT / "scripts", clone / "scripts")
        shutil.copytree(ROOT / "alexa", clone / "alexa")
        target = clone / filename
        source = target.read_text(encoding="utf-8")
        if before not in source:
            raise SystemExit(f"Mutation anchor missing: {label}")
        target.write_text(source.replace(before, after, 1), encoding="utf-8")
        result = subprocess.run(command, cwd=clone, env={**os.environ, "PYTHONPATH": str(clone / "src")}, capture_output=True, text=True, timeout=60)
        killed = result.returncode != 0 and ("FAIL" in result.stderr or "fail " in result.stdout)
        print(f"{'KILLED' if killed else 'SURVIVED/INVALID'}: {label}; exit={result.returncode}")
        if not killed:
            print((result.stdout + result.stderr)[-2000:])
            failures += 1
raise SystemExit(1 if failures else 0)
