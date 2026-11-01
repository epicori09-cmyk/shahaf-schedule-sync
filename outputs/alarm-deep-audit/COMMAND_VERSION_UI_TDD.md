# Missing alarm command version — 2026-11-01

User asks to fix alarm edits failing with command_version required, and to
check why data is stale. No production alarm commands are test fixtures.

Observed: static embedded alarm data contains no DB command revision. The
page allowed POST before its background Worker GET succeeded. Worker also
correctly strips date/revision when generated data is over three hours old.
At 20:12 UTC the latest publication was 15:50 UTC (4h22 old): Pages stale=false,
Worker stale=true. Last two scheduled runs were six hours apart, not hourly.
Exact cause of GitHub trigger gaps unproven. GitHub documents cron delay/drop
possibility, especially at minute zero. No freshness threshold is relaxed.

RED checkpoint 013ad65: two executed rendered-JS scenarios reproduced direct
unversioned POST from embedded state, including when the live feed would be
stale. Fix preflights missing revisions, validates profile/date/staleness,
preserves the typed time, and obtains a version before write. If target date
changes, require review rather than automatically writing to another date.
Unknown/unavailable state displays localized human text, not internal field
names. Busy guard prevents duplicate submits; no retries of uncertain writes.
Cache v8 retires cached v7 app shell. Worker CAS contract is unchanged.

GREEN: 250 Python / 26 Node PASS, including 10 generated-JS runtime scenarios.
Existing stale-GET race and POST failure/timeout scenarios now explicitly seed
an already-confirmed version so they still exercise their intended paths.
Three new scenarios cover preflight, stale abort and changed-date abort.
Coverage command with coverage and full suite: site.py 86%; this measures
Python renderer execution, not JavaScript branch coverage. Six safety
mutations detected; diff checks exit 0.

Deployment: fix 16cbc23 pushed to main. Pages run 41345746485 succeeded in
46s. Six live Worker/Pages profiles checked read-only: fresh, identity and
version valid, cache v8 and bypass present; generated 22:13:44 Israel time.
New preflight code confirmed in published HTML. No Worker deployment needed.
Browser panel opens, correct upcoming time shown, no captured console errors.
Screenshot command-version-panel.jpg; no production alarm POST performed.
Mutation behavior verified with rendered-JS/mock networking, not on students.
Long-term reliable sync cadence remains unresolved; a one-time dispatch is
not a scheduler fix. GitHub scheduling documentation consulted:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Self-evaluation

Summary: 4.0/5 for the UI bug fix and stale-state diagnosis, not scheduler
reliability certification.

| Axis | Score | Evidence / improvement |
|---|---|---|
| Accuracy | 4 | Executed RED/GREEN, 250 Python/26 Node, six live identities and fresh versions. Exact cause of scheduler gaps remains an inference, not confirmed platform incident. |
| Completeness | 4 | Missing token, stale abort, date rollover, timeout and cached-client deployment covered. Real alarm writes intentionally not tested on students. |
| Clarity | 4 | Replaces internal schema errors with actionable English/Hebrew text; final handoff must distinguish current freshness from future scheduling. |
| Actionability | 4 | Deployed and cache bumped; reopening page loads fix. A reliable external schedule remains separate work. |
| Conciseness | 4 | Localized preflight instead of weakening CAS or renaming schema; tests/evidence are longer than production edit. |

Critical axes <=2: none. Top improvement: independently reliable timed
publishing so feeds do not repeatedly age beyond the 3h safety window.
Self-check: user can retry after refreshing, but should not be told recurring
staleness is permanently solved. Verdict: deliver bounded deployed fix.
