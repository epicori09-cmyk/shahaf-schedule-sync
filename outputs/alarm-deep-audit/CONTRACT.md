# Deep alarm safety and efficiency audit — 2026-10-06

FULL LOOPER. User requests continued whole-project coding/efficiency investigation, especially unintended cancellation and missed cancellation. Baseline commit a89e683. Prior audit evidence is context, not proof for new cases.

Goal: find and repair reproducible safety, data-integrity, operational and efficiency defects across retrieval, filtering, alarm calculation, publication, Worker persistence, UI/cache and integrations. Deploy verified repairs under existing user authorization.

Non-goals: change student course selections, preferences or actual alarm overrides as test fixtures; edit installed Shortcuts; claim physical Clock confirmation; promise zero future external-service failures; unrelated cosmetic rewrites.

Mandatory criteria:

- AC01: baseline and final Python/Node suites pass with exact counts; no tests weakened.
- AC02: every root clear/set has fresh valid profile/date-scoped evidence or an explicit active supported command; malformed/stale/uncertain data preserves existing alarms.
- AC03: cancel/move/restore semantics, command ordering, expiry, date ranges, concurrency and acknowledgements are deterministic and profile-isolated.
- AC04: Israel weekday/DST/date boundaries and time-only iPhone Clock constraints are explicitly tested; unsupported assumptions recorded, not guessed.
- AC05: source identity, completeness and cancellation matching cannot silently mis-scope or omit lessons; events/exams/AI/transit dependencies do not fabricate safe evidence.
- AC06: publication, failed syncs, restarts, cache updates, UI refresh and freshness signals retain last-good state without falsely fresh destructive commands.
- AC07: concrete inefficiencies are measured or reproducible; fixes preserve safety, bounded retries/timeouts and observable failures.
- AC08: independent correctness, adversarial, specification/regression, domain, operations/security reviews, explicit rejecting-reviewer rechecks, fresh final integrated review and isolated dangerous-mutation checks.
- AC09: applicable deployment succeeds; live six-profile endpoints are checked read-only with scoped identities and intended settings, plus browser inspection if UI behavior changes.

Invariants: preserve working student packages, randomized IDs and special requests; no private data/secrets published; exact-label alarm deletion only; do not test production alarm mutations. Stop for an unresolved policy conflict or unavailable essential phone information instead of silently broadening authority.

Evidence ledger and findings will record inspected subsystems, exact reproduction/check commands, repaired or deferred findings and remaining limitations.
