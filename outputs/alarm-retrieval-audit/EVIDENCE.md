# Alarm and retrieval reliability audit — 2026-10-06

Implementation: commit `ea20b3c` (core repair `3129a30`); baseline `0554b9c` (149 Python tests). FULL LOOPER scope.

## Changes

- Pin Ori's 07:45 → 06:45 exception to his randomized profile; preserve Nitay's 25-minute buffer.
- Separate next-schoolday UI preview from the authoritative Shortcut root; validate Israel dates, DST, elapsed wake timestamps and weekends.
- Retain all active date-scoped overrides; optimistic command versions protect repeated/concurrent saves and restores, including deleted legacy rows.
- Match cancellations to exact date/period/subject/teacher occurrences; reject wrong-teacher and orphan rows, preserve ambiguous data as stale.
- Bounded retrieval retries, academic-year source validation, fail-closed malformed early lessons, strict profile bundles, staged site output, and deferred Gist writes after rendering.
- Validate cached JSON before replacement; refresh alarm state independently; show alarm date/time and loading/error feedback with compact mobile controls.

## Automated checks

| Command | Exit | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| `$env:PYTHONPATH='src'; uv run python -m unittest discover -s tests` | 0 | 193 | 0 | 0 |
| `node tests/worker_alarm_runtime.cjs` | 0 | 13 | 0 | 0 |
| `node --check admin/worker/src/index.js` | 0 | n/a | n/a | n/a |
| `git diff --check` | 0 | n/a | n/a | n/a |

Python coverage includes generated UI JavaScript and service-worker execution, actual SQLite command/rate-limit queries, source-parser failures and cross-profile/date regressions. Test stdout SAFE FAILURE messages are deliberate negative fixtures, not production errors.

## Independent review and repairs

- Correctness/domain and retrieval reviews identified dropped Ori identity, clear/restore confusion, weekend/DST paths, missing retries and cache freshness issues; these were repaired with regressions.
- Fresh adversarial/specification/regression reviewer Schrodinger identified obsolete source year, malformed early-row skipping, wrong-teacher selector fallback, orphan cancellation and invalid fallback-clock issues. Explicit recheck passed local AC01–AC09; AC10 pending production evidence.
- Independent security/operations reviewer Boole verified optimistic SQLite CAS, deletion race repair and restore version rotation. Found early Gist publication before failed rendering; write was deferred and zero-write-on-render-failure asserted. Explicit recheck: 192 Python and 13 Node passed, no remaining BLOCKER/HIGH in bounded scope.

## Isolated mutation checks

Only the isolated copy `C:\Users\epico\AppData\Local\Temp\shahaf-gauntlet-34c816ed78854f33b08e53425de93b7a` was mutated. No mutations remain in the committed implementation.

| Mutation | Detection | Exit |
|---|---|---:|
| Remove retrieval retries (3 → 1) | Retrieval suite: 1 failure, 1 error of 4 tests | 1 |
| Disable configured canonical profile ID | CLI suite: 1 failure of 6 tests | 1 |
| Remove current-weekend alarm guard | Alarm suite: 4 failing subcases of 17 tests | 1 |
| Disable cancellation teacher identity | Cancellation suite: 2 failures of 10 tests | 1 |

## Production and browser evidence

- `git push origin main`: exit 0. Pages run `37457293117` succeeded for `3129a30`; final visual-fix run `37457810238` succeeded for `ea20b3c` (1m26s). Sync, artifact upload, Pages deployment and command acknowledgement all succeeded.
- `npx wrangler deploy` in `admin/worker`: exit 0, version `ded586cf-d8d0-4397-8393-678ae4e31708`. No database migration or real test alarm override was written.
- `& outputs/alarm-retrieval-audit/verify_endpoints.ps1`: exit 0 after final rollout; all six data/Page wake/Worker wake identities match, fresh non-stale feeds, same root time/action and nested next-schoolday preview. Saved `live-endpoints.json`.
- October 7 next alarms: Ori 06:45, Nitay 07:20, Shahar 06:30, Jonathan 07:15, Neta 06:30, Alma 06:30.
- Allowed-origin public GET: HTTP 200, `Access-Control-Allow-Origin: https://epicori09-cmyk.github.io`, `Cache-Control: no-store`. Normal certificate validation enabled. Retired root `wake.json`, `data.json`, and `ya1/wake.json`: HTTP 404.
- Nitay Now/Schedule/Exams visited in Hebrew and English. Expanded alarm controls inspected without submitting commands. Input and move button maintain a 9px gap; narrow Hebrew 320px layout also fits. Mobile 375px, tablet 768px and desktop 1440px inspected; desktop both languages.
- Screenshots found an existing dark-on-dark pink empty-card heading; fixed with a specific empty-card background and regression. Final deployed DOM confirms `rgb(244, 231, 238)` background with `rgb(56, 38, 51)` text. Screenshots: `deployed-alarm-he.jpg`, `deployed-mobile-en.jpg`, `deployed-tablet-en.jpg`, `deployed-desktop-he.jpg`, `deployed-desktop-en.jpg`. Browser console inspection returned no warnings/errors.
- Cached app shell served the prior CSS on the first navigation; a reload after background refresh displayed the current build. Data/alarm refresh remained current independently. Full-page screenshot capture can clip a scrollbar-width edge in this browser; viewport screenshots were used for Hebrew visual proof.
- No baseline screenshot comparison, Core Web Vitals instrumentation, full network waterfall, axe audit or physical screen-reader verification was performed. These are explicitly not claimed.

## Files changed

`.github/workflows/sync.yml`, `SPECIAL_REQUESTS.md`, `admin/worker/src/index.js`, `config.json`, `scripts/ack_alarm_commands.py`, `scripts/fetch_managed_profiles.py`, `src/shahaf_sync/alarm_controls.py`, `src/shahaf_sync/cli.py`, `src/shahaf_sync/profiles.py`, `src/shahaf_sync/shahaf.py`, `src/shahaf_sync/site.py`, `tests/test_admin_contract.py`, `tests/test_alarm_controls.py`, `tests/test_alarm_ui_runtime.py`, `tests/test_cancellation_identity.py`, `tests/test_cli.py`, `tests/test_github_and_site.py`, `tests/test_retrieval_safety.py`, `tests/test_service_worker_runtime.py`, `tests/test_source_safety.py`, `tests/test_worker_sql.py`, `tests/worker_alarm_runtime.cjs`.

## Acceptance criteria

| ID | Status | Evidence |
|---|---|---|
| AC01 | PASS | 193 Python / 13 Node tests, exit 0 |
| AC02 | PASS offline | Date/profile override tests, actual SQLite CAS/deletion/restore queries |
| AC03 | PASS offline | Weekend/elapsed/DST runtime and Python regressions |
| AC04 | PASS offline | Source safety, staging failure and retrieval tests |
| AC05 | PASS offline | Cancellation identity and orphan/teacher regressions; explicit reviewer recheck |
| AC06 | PASS | Generated UI tests and deployed Hebrew/English mobile, tablet, desktop inspection; contrast repair verified |
| AC07 | PASS offline | Generated UI/SW tests for cache isolation, newest state and bounded fetches |
| AC08 | PASS | Boole explicit operations/security recheck; Schrodinger final integrated review after viewing deployed Hebrew/English mobile and desktop screenshots |
| AC09 | PASS | Four detected isolated mutations |
| AC10 | PASS | Final Pages run 37457810238, Worker version, six live endpoint checks, CORS/404 checks |

## Assumptions and limits

- Feed evidence is not physical iPhone Clock confirmation. The user-confirmed Shortcut uses exact label `Shahaf` and must obey root `shortcut_action`.
- GitHub scheduling can be delayed; an hourly trigger is not a real-time delivery guarantee. Stale envelopes preserve alarms instead of guessing.
- Unchanged valid academic-year source timestamps are not treated as download-age timestamps.
- Gist and Pages are separate external services, not a distributed atomic transaction. Rendering failures no longer publish the Gist first; downstream deploy failures remain observable in Actions.
- Production alarm mutations are not used as QA fixtures. Generated-runtime/SQLite fixtures test write paths.
- No committed visual baseline or physical screen-reader/iPhone pass: visual regression and full accessibility certification are not claimed.

## Self-evaluation

The agent-self-evaluation skill was applied to check omissions and avoid overstating production proof. Overall 4.0/5.

| Axis | Score | Evidence and remaining improvement |
|---|---:|---|
| Accuracy | 4 | 193 Python/13 Node tests and six live feeds verified; physical iPhone Clock behavior is not observable here |
| Completeness | 4 | Alarm/retrieval/design and deployment covered; prospective unattended reliability still needs operational observation |
| Clarity | 4 | Acceptance criteria and exact outputs recorded; detailed report is longer than the user-facing summary |
| Actionability | 4 | Fixes are deployed and the verifier is saved; an installed Shortcut must still run to apply the feed to Clock |
| Conciseness | 4 | Short final summary with linked evidence; report retains verbose audit details for reproduction |

Highest-impact improvements: verify one actual phone Shortcut run; observe future automatic runs without promising zero failures. Self-check: the user can verify the endpoint times and visual result, but cannot infer physical Clock success from these checks.

## Final review status

Schrodinger returned final integrated PASS for AC01–AC10 after independently viewing deployed mobile and desktop images and reviewing commit, Actions, Worker and endpoint evidence. Superseded pre-reload full-page captures were not used as current visual proof. Final `deployed-alarm-he.jpg` is the readable Hebrew viewport capture; `deployed-tablet-en.jpg` was refreshed after the corrected app shell loaded.

Remaining BLOCKER: 0. Remaining HIGH: 0. No new unresolved MEDIUM/LOW findings reported. Existing Actions Node-runtime deprecation/Ubuntu image migration warnings are non-failing operational notices, not proof that future jobs cannot fail.

GAUNTLET STATUS: PASSED — defined software/feed/browser scope only; physical iPhone Clock state remains unverified.
