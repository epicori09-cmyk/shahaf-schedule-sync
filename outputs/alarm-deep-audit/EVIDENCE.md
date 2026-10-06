# Deep alarm audit — working evidence, 2026-10-06

Status: NOT PASSED; this is a continuation checkpoint, not production approval.

## Deployment checkpoint

- Production source commit `0129581d3c5af2fbade144315ff9c79ac216c374` pushed to main.
- `npx wrangler deploy`: exit 0; Worker version `d99ad754-f832-4373-a760-63298cb4c3e0`.
- GitHub schedule/Pages run `37484713245`: SUCCESS, 1m48s. Sync, retired-path check, upload, first Pages deployment and acknowledgement succeeded. Alexa updater step explicitly skipped because its access token is not configured; this is not an Alexa production verification.
- `verify_live.ps1`: exit 0, six of six live Worker/Pages profiles passed identity, generation age, supported root action, Clock occurrence (when set), command-version, cache-v7/bypass and Ori/Nitay buffer checks. Initial script failure was a verifier bug: cache slug normalization converts underscores to hyphens; corrected to match the renderer, without changing production.
- Live October 7 previews: Ori 06:45, Nitay 07:20, Jonathan 07:15, Alma/Shahar/Neta 06:30. Neta root and preview action are `leave`, with alarm_safety=blocked: async-learning event NIM review timed out. Her displayed time is planning information, NOT authorization to create an alarm. No production alarm commands were issued for testing.
- Nitay read-only browser checks: Now/Schedule/Exams in Hebrew and English at 375/768/1440 widths. No page-wide horizontal overflow; scheduled time visible; mobile input and Move button disjoint; Restore disabled with no active override; captured error/warning logs empty. Screenshot proof: `deployed-alarm-he-viewport.jpg`. Full-page capture showed renderer/capture clipping unlike the viewport; the viewport image is the visual evidence. No strict image baseline comparison, Core Web Vitals measurement, axe/screen-reader check, physical iPhone test or production cancel/move/restore click claimed.

Baseline a89e683: Python 193 passed, Node 13 passed (prior continuation).
Latest frozen candidate: `$env:PYTHONPATH='src'; uv run python -m unittest discover -s tests`: exit 0, 242 passed, 0 failed, 0 skipped. `node tests/worker_alarm_runtime.cjs`: exit 0, 24 passed, 0 failed, 0 skipped. `compileall -q src scripts alexa`, `node --check admin/worker/src/index.js`, and `git diff --check`: exit 0.
`$env:PYTHONPATH='src'; uv run python outputs/alarm-deep-audit/run_mutations.py`: exit 0; 6/6 deliberate defects detected in temporary isolated copies. Clock occurrence, obsolete Restore, cross-origin cache interception, stale command version, period-zero fallback, cancellation teacher identity. No mutations in working files. `git diff --check`: exit 0.

## Reproduced repairs

- Root time-only Clock occurrence is fenced separately from the future UI preview; 05:00/06:40, long gaps, weekend, DST, elapsed/equality, malformed inputs and uncertain source tested.
- Live wake responses bypass the service worker; static profile caches remain scoped and fast. Cache v7 invalidates the previous profile cache.
- POST requires the displayed target date and covering-command version. SQLite writes fence the complete active covering id set atomically, including concurrent windows. Unsupported student commands overlapping a range fail without changing it; the final global-pause override policy awaits user choice.
- A command uses one fetched source snapshot for planning, restore and response rather than three independent requests. DB state is reread for the response; isolated handler fixtures demonstrate the fetch count.
- Explicit Restore uses the current unmodified schedule baseline. Manual moves equal to an old saved baseline are not mistaken for Restore.
- Event-owned exclusions are released when events disappear from a successful complete retrieval. Current uncertain events, cancellation-owned exclusions and explicit/legacy manual exclusions remain protected.
- Alexa rejects stale/malformed schedules, confirms new reminders before deleting old ones, and clears every exact managed-marker duplicate while preserving unrelated reminders. No live Alexa changes tested.
- Disabled profiles' unpublished commands are not acknowledged.
- Public transit payloads remove private home origins, first walking-leg origin and origin-bearing map URLs, including nested alternatives.
- Local site installation precedes remote Gist publication; failed Gist writes roll back the local install. Fault-injection tests cover both rename and remote-write failure. Gist and GitHub Pages remain separate services, not an atomic transaction.
- Weekly live imports require all known periods and six day columns, with complete unique cells. Empty header corner cells are explicitly skipped. Normal-TLS live cls11 read parsed 279 lessons across six days. Requests use no-cache revalidation headers; source UpdateDate is last-modified, not elapsed sync age.
- Weekly imports require the requested selected class; events and exams also reject missing class identity. Live retrieval requires the complete HTML envelope before interpreting list absence. Read-only live YA2 check: 14 changes, 57 events, 156 exam candidates. This does not prove upstream list completeness.
- Root cancellations require supplied teacher identity and unique matches. Generated added lessons can be canceled without touching unrelated one-offs. Photo rebuilds preserve reordered teacher identity, keep manual exclusions slot-scoped, and reject duplicate recurring slots.
- Moves to period zero use explicit `None` checks in student and root calendar paths. Both regressions reproduced before repair; period-zero mutation detected.
- Follow-up cancellation after a teacher/period replacement matches the effective occurrence, while EXDATE retains the original recurrence identity. Original rejecting reviewer Planck explicitly rechecked old-teacher preservation and new-teacher cancellation: PASS; focused reconciliation/identity 31 passed, full Python 238 passed. Earlier 236-count evidence preceded these two regression tests.
- Alexa consumes the effective Worker feed without recomputing buffers, validates generation age/profile/date, runs after Pages with expected-generation equality, and cleans duplicates only after successful replacement. Mocked checks only; Lambda deployment remains separate from Worker/Pages.
- Remote read-only `npx wrangler d1 execute shahaf-profiles --remote --command "PRAGMA table_info(alarm_overrides);"`: exit 0, zero rows written; restore_json and target_date_end already present. Deployment README now distinguishes fresh schema from additive older-database migrations.
- NIM call timeout reduced from 90s to 20s; workflow capped at 20 minutes. No reduced reasoning quality is assumed; cost/GTFS optimizations are not claimed complete.

## Known gaps and decisions

- Installed phone guard still reported as `false`, not endpoint action `leave`; repair is not confirmed. See SHORTCUT_CONTRACT.md. This can delete a preserved alarm. 06:40 cannot cancel a 06:30 alarm discovered after the 05:00 run.
- No physical iPhone Clock state or production command mutation was tested.
- Historical raw manual EXDATE ownership already overlapping an old event marker cannot be reconstructed from the old format.
- A fetched complete HTTP response is not proof that Shahaf's upstream data itself is current. Missing source changes cannot be invented.
- All currently known profiles have transit disabled; conditional caching of the large GTFS archive remains unimplemented. NIM repeated-context caching and a whole-process deadline remain unimplemented beyond per-call/workflow caps.
- Reviewer rechecks, bounded fresh integrated review, Worker/Pages deployment and read-only live/browser checks completed below. Full-system acceptance remains unproven; no acceptance criteria have been downgraded.
- Repaired expired/consumed command resurrection, admin date/range CAS bypass, partial bulk commits and global/profile settings concurrency. Real SQLite predicate tests cover expiry/consumption and settings CAS; authenticated handler fixtures cover null/missing versions/ranges. A two-profile bulk fixture confirms an audit failure after the first commit still publishes and reports the stale second profile separately, without mutating it.
- Additional post-commit alarm audit failure reproduced as a throwing public response, then repaired through shared finalization for public clear/set/restore and admin commands. Runtime fixture confirms 202 accepted_with_warnings, effective override present, and no duplicate mutation. The alarm admin UI enhancement remains intentionally not injected; API coverage is not proof of visible dashboard controls.
- Original rejecting operations reviewer Dewey explicitly withdrew all four Alexa objections after mocked rechecks; original adversarial reviewer Parfit explicitly accepted the repaired source/photo/cancellation reproducers, including replacements and period zero. Both are read-only rechecks, not production or full-gauntlet approval.
- Independent new reviewers confirmed all earlier source/photo and Alexa reproducers repaired offline. Carver explicitly rechecked its own wrong-teacher regression and deployment documentation. Alexa Lambda code has not been deployed to Amazon by this workflow; only its checked-in source/updater can be published here.
- Curie, the original Worker rejecting reviewer, explicitly rechecked the frozen candidate: PASS for expiry/consumption, public/admin date-version-range rejection, global/profile settings CAS, bulk partial truthfulness/isolation and post-commit audit handling. Independently reran all 24 Node tests successfully. No production mutations.
- Aquinas fresh integrated review found no additional concretely reproduced server BLOCKER/HIGH; disposition is a bounded-deploy candidate for controlled validation, not full-system approval. Installed Shortcut guard, 05:00/06:40 timing and physical Clock verification remain unresolved. Its checkpoint referred to 22 Node tests; parent requested explicit recheck of the two newer authenticated handler fixtures before deployment.
- Aquinas explicitly rechecked both newer admin/bulk handler fixtures: 2/2 PASS, removed the stale fixture-coverage objection, no additional server BLOCKER/HIGH. Overall gauntlet still NOT PASSED for phone/manual and live-verification gaps.

## Criteria at checkpoint

| Criterion | Status | Evidence / gap |
|---|---|---|
| AC01 | PASS | Frozen candidate 242 Python / 24 Node; compile/syntax/diff clean |
| AC02 | UNPROVEN | Guard regressions pass; installed false guard unresolved |
| AC03 | UNPROVEN | Date/version/range SQL tests pass; range product policy pending |
| AC04 | UNPROVEN | Time/DST regressions pass; phone repair/Clock proof absent |
| AC05 | UNPROVEN | Structural source, events and identity tests; upstream freshness cannot be independently guaranteed |
| AC06 | PASS (bounded) | Cache/publication rollback tests plus successful deployment and live v7 checks; production failure recovery not injected |
| AC07 | UNPROVEN | One-fetch command test and bounded timeouts; broader efficiency work remains |
| AC08 | PASS (bounded) | Six mutations detected; original rejecters and fresh integrated recheck complete; overall phone blockers remain |
| AC09 | PASS (server/browser scope) | Worker deployed; Pages run successful; six read-only live feeds; bilingual three-tab responsive checks. Alexa skipped; phone proof absent |

Changed source: `.github/workflows/sync.yml`, `SHORTCUT.md`, `admin/worker/src/index.js`, `alexa/lambda_function.py`, `scripts/ack_alarm_commands.py`, `scripts/update_alexa_reminder.py`, `src/shahaf_sync/{alarm_controls,alexa,cli,ics,nim,reconcile,shahaf,site,public_transit}.py`; regression tests under `tests/`; this evidence directory. Unrelated prior screenshot artifacts are preserved and excluded from commits.
