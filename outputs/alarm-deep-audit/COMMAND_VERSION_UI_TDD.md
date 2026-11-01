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

Deployment and read-only visual/live checks pending. Long-term reliable
sync cadence remains unresolved; a one-time dispatch is not a scheduler fix.
