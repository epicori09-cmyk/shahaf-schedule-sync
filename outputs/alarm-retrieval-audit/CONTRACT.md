# Alarm and retrieval audit — 2026-10-06

User request: Use LOOPER to check alarm check/change design, cancellation retrieval, and data retrieval methods after complaints. Existing authorization includes repair and deployment.

Level: FULL, because alarms involve persisted commands, timezone/date boundaries, and unattended external data.

Goal: Repair reproducible defects in the alarm controls and school-data pipeline, improve the mobile alarm interaction, and verify the deployed behavior with reproducible evidence.

Non-goals: Editing installed iPhone Shortcuts or proving Clock alarms on a physical phone; changing students' subject selections or real alarm preferences as audit fixtures; rewriting unrelated product areas.

Mandatory acceptance criteria:

| ID | Criterion | Initial status |
|---|---|---|
| AC-01 | Existing regression suite passes; exact counts/commands recorded. | PASS: `PYTHONPATH=src uv run python -m unittest discover -s tests`, exit 0, 149 run, 0 failures, 0 skipped. |
| AC-02 | Cancel/move/restore remain scoped to one profile and its next scheduled school date, with deterministic repeated/concurrent behavior. | UNPROVEN |
| AC-03 | No Friday/Saturday alarm is created, including override/fallback/restore paths; Israel timezone and DST respected. | UNPROVEN |
| AC-04 | Unavailable, malformed, stale, or uncertain data never claims a fresh safe alarm; last known good data remains usable. | UNPROVEN |
| AC-05 | Cancellation matching respects student lesson, teacher, period, and date; newly supported formats have meaningful regressions. | UNPROVEN |
| AC-06 | Alarm UI has a clear date/time/state, visible operation feedback and error recovery, no time-input overlap, and works in Hebrew/English on mobile and desktop. | UNPROVEN |
| AC-07 | Loading/cache/refresh behavior preserves profile isolation and newest command state, with bounded fetches and accurate freshness. | UNPROVEN |
| AC-08 | Changes pass independent correctness, adversarial, specification/regression, domain, operations/security, and fresh final integrated review. | UNPROVEN |
| AC-09 | Applicable dangerous mutations are detected in an isolated environment; none remain in delivered files. | UNPROVEN |
| AC-10 | Deployed Pages/Worker and public endpoints show the verified behavior; no private data/credentials exposed. | UNPROVEN |

Invariants: preserve unrelated user edits, each student's package and settings, original per-profile alarm exceptions, supported public Shortcut fields, randomized public IDs, and exact-label alarm deletion contract. Do not mutate real alarm overrides for test purposes. Existing authority to deploy remains in force.

Risks: cached app HTML can hide updates; frozen published wake timestamps can drift across dates; Pages and Worker can disagree; stale original restore snapshots can override updated schedules; profile identity ambiguity can drop individual rules; parser filters can silently miss teacher-only cancellations; network/AI dependencies can delay unattended publishing.

Baseline head: `0554b9c`. Working tree clean before this audit. Independent reviews started for alarm correctness/domain, retrieval adversarial/operations, and Worker security/regression.
