# Text-false Shortcut compatibility — 2026-10-06

User journey: existing Shortcuts compare AlarmAction text to false before
Find/Delete. Change the shared feeds, not each phone, so preservation stops
there. Set/clear and the existing safety decisions must remain unchanged.

## RED / GREEN

- RED: Python `test_shortcut_wire.py` ran 2 tests with 3 failing subcases:
  published preservation was leave, and both Alexa consumers rejected false
  as malformed instead of preservation. Actual Worker GET returned leave
  instead of false. Checkpoint `a6597e9` contains the reproducers.
- GREEN: Python full suite 244 passed; Node Worker full suite 25 passed.
  Published-root tests cover false/set/clear and unchanged internal actions.
  Actual Worker GET tests cover old leave and new false input, false output,
  set/clear unchanged, nested preview unchanged. Both Alexa consumers treat
  false as preservation with no input mutation.
- Coverage: `uv run --with coverage coverage run --branch --source=shahaf_sync
  -m unittest discover -s tests`, followed by report for changed Python
  modules: alarm_controls 85%, alexa 85%, site 86%, combined 85%. This is
  scoped Python coverage, not a claim about total Worker or iPhone coverage.
- Six existing isolated safety mutations still detected; syntax/diff checks
  pass. No production alarm commands used as fixtures.

## Protocol

Root `shortcut_action` is string `false`, `clear`, or `set`. False is not
a JSON Boolean: after Get Text it remains the literal word false. Only the
root serialization changes; internal leave, nested baseline/preview and
stored overrides are unchanged. Worker normalizes old/new roots before
validation so deployment can accept either Pages format. UI accepts both;
Alexa source recognizes false. Its Amazon Lambda deployment is separate.

Remaining boundaries: leave-only Shortcuts are not compatible with the new
root; the user requested the false-guard contract. Physical Clock behavior
is not tested here, and 06:40 is still too late to cancel a 06:30 alarm.

## Deployment/live verification

- GREEN commit `56d38e8`, pushed after RED checkpoint `a6597e9`.
- Worker deploy exit 0, version `7c547670-263a-4006-b96a-781d0f0bbb22`.
- Pages/sync run `37496168292`: SUCCESS, 2m5s, first deploy attempt succeeded.
- Updated `verify_live.ps1`: exit 0; six Worker plus six published roots use
  only false/set/clear. Profile identity, freshness, command versions,
  next-Clock-occurrence checks for set and Ori/Nitay settings passed.
- Live Alma preservation checked on BOTH URLs: root false, System.String,
  nested preview leave. No alarm mutation, label, preference or URL changed.
- Neta's earlier blocked event review resolved in this normal sync; her
  current root is set. Alma's review is currently blocked and preserves.
  This external-review variability is not a protocol or manual override change.
- Alexa updater remains skipped without its access token. No Amazon Lambda
  deployment or physical iPhone execution claimed.

## Self-evaluation

Summary: 4.0/5; server compatibility delivered and verified, not physical
phone certification.

| Axis | Score | Evidence / improvement |
|---|---|---|
| Accuracy | 4 | RED/GREEN, 244 Python / 25 Node, six mutations and twelve live roots; confirm one actual phone run to establish device behavior. |
| Completeness | 4 | Worker and Pages boundary, website acceptance and Alexa source covered; Amazon Lambda deployment remains separate and not claimed. |
| Clarity | 4 | String false versus Boolean false explicitly documented; historical leave guidance labeled superseded. Keep the final handoff concise. |
| Actionability | 4 | Same URLs, no per-student changes for reported false guards; older leave-only consumers require migration. |
| Conciseness | 4 | Narrow root serializer avoids internal action rename; durable evidence is longer than the user-facing handoff. |

Critical issues <=2: none for this requested compatibility change.
Top improvement: user confirmation of one installed false-guard Shortcut;
no device execution can be performed here. Self-check: user can keep their
reported guard without visiting every phone, which directly meets the ask.
Verdict: deliver deployed compatibility change with physical-proof boundary.
