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

Deployment/live verification: pending.
