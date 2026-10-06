# User-reported installed Shortcut — 2026-10-06

## Current compatibility update, requested by the user

The root Shortcut-facing action now maps internal `leave` to text `"false"`
on both Worker and Pages feeds, globally. The reported initial false stop
therefore matches the endpoint; no per-student phone edits are needed for
that guard. `set` and `clear` are unchanged. Internal and nested planning
actions remain canonical. Any older leave-only consumer needs the new text
guard. Physical Clock confirmation, set-timestamp validation and the reported
05:00/06:40 timing gap remain separate concerns.

## Pre-migration audit snapshot (superseded action recommendation)

The user reports root `shortcut_action` → text `AlarmAction`; first guard is `If AlarmAction is false → Stop`, then Find/Delete alarms with exact label `SHAHAF`, then `If AlarmAction is clear → Stop`, then parse `wake_at` and Create Alarm named `SHAHAF`. No `alarm_for_today` guard remains. User confirmed daily runs at 05:00 and 06:40 (Asia/Jerusalem).

Critical incompatibility: endpoint instructions are `leave`, `clear`, `set`, not Boolean `false`. On a safe-preserve `leave`, the reported Shortcut still deletes its alarm before failing/continuing with missing time. This is a phone-side safety gap, not server cancellation evidence.

Required manual repair: before Find/Delete, stop if AlarmAction is `leave`. More defensive: only enter Find/Delete if AlarmAction is exactly `set` or `clear`; unknown/missing actions must stop. Keep deletion restricted to exact `SHAHAF`; never delete unrelated alarms. Check network/parsing failures stop without deleting. Phone change and physical Clock confirmation cannot be performed here.

Do not change the shared endpoint to return `false`: other students' correct `leave` comparisons would stop working. Preserve supported action strings. User notified immediately; manual confirmation pending.

Timing limitation: the 06:40 automation cannot apply cancellations discovered after 05:00 before a 06:30 alarm rings. A further phone automation before that alarm is required to shorten this window; server sync alone cannot execute an iPhone Shortcut. No phone automation changes or Clock-state verification have been performed.
