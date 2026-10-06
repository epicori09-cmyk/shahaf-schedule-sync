# Free iPhone wake-alarm setup

This uses the normal iPhone Clock alarm. It does not require Spotify,
jailbreak access, Apple Developer membership, or a paid service.

## Latest installed Shortcut report — 2026-10-06

The user reports an initial `AlarmAction is false` stop, followed by deletion
of exact-label `SHAHAF` alarms, a `clear` stop, then `wake_at` → Create Alarm.
There is **no `alarm_for_today` condition**. Daily runs are 05:00 and 06:40.

This initial condition is unsafe: the endpoint returns text `leave`, not
Boolean `false`. Change it to **AlarmAction is leave → Stop This Shortcut**
before Find/Delete. A stronger guard permits deletion only when the action
is exactly `set` or `clear`; missing/unknown actions stop. Validate a `set`
timestamp before deleting the existing alarm. No phone repair is confirmed.

The 06:40 run cannot apply new cancellations before a 06:30 alarm. Add an
earlier refresh if that window is unacceptable. Server sync cannot run a
Shortcut on the phone.

## Historical installed student shortcut log — 2026-09-05

Recorded 2026-09-05 from the currently working shortcut. This is an observed
flow, not a generated or inferred shortcut:

1. **Get Contents of URL** → the configured student `wake.json` URL.
2. **Get Dictionary from Input** → set the result as `WakeData`.
3. Get `shortcut_action` from `WakeData` → **Get Text from Input** → set as
   `AlarmAction`.
4. If `AlarmAction` is `leave`, **Stop This Shortcut**.
5. **Find Alarms** where **Label is exactly** `Shahaf`.
6. If the Find Alarms result has any value, **Delete Alarms**.
7. If `AlarmAction` is `clear`, **Stop This Shortcut**.
8. Get `alarm_for_today` from `WakeData` → **Get Text from Input** → set
   `AlarmToday`.
9. If `AlarmToday` is `No`, **Stop This Shortcut**.
10. Get `wake_at` from `WakeData` → **Get Dates from Input**.
11. **Create Alarm** for that date/time with label `Shahaf`.

The configured student URL is intentionally not copied into this log because
the public ID is the access path for that student's page. The fast Shortcut
feed template is
`https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/<random-id>/wake.json`.
It reads the published schedule from Pages and applies that profile's active
audited alarm override immediately; the normal Pages wake URL remains the
public schedule endpoint.

### Endpoint compatibility note

The student endpoint returns a JSON object with `shortcut_action`,
`alarm_for_today` (a Boolean), and `wake_at` (an ISO-8601 timestamp). The
historical Shortcut checked `alarm_for_today`; the latest user report does
not. The root feed now checks the actual next time-only Clock occurrence.
Future planning remains in `next_alarm` for the website; Shortcuts must read
the root fields, never that preview. A future calendar date alone cannot make
an iPhone Clock alarm date-specific. Do not combine the historical daily-only
guard with the current root contract without reviewing the delete/create flow.

The schedule and transit wake planners explicitly ignore Friday and Saturday
dates (the Israeli weekend). Sunday remains a valid school day. When a valid
response has no school on the current weekend, the default `clear` action
removes only the app's exact labeled alarm; stale or uncertain responses still
return `leave` so an existing alarm is preserved.

The current Ori Shortcut endpoint is:

`https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json`

It is the randomly generated managed profile for Ori's יא-2 schedule. The
former root endpoint is retired and should no longer be used.

## Before testing

Keep your existing 07:15 alarm enabled as the backup. Do not give that alarm
the label `Shahaf`; the Shortcut deletes only alarms with that exact label.

## Create the Shortcut

In the Shortcuts app, create a shortcut named **Refresh School Wake Alarm**.
New setups use the endpoint's default label `Shahaf`. When updating the reported
existing Shortcut, keep its `SHAHAF` label in both Find and Create instead;
do not leave a second spelling's old alarms behind. Add these actions in order:

1. **Get Contents of URL**
   - URL: `https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json`
   - Method: `GET`
2. **Get Dictionary from Input**.
3. **Get Dictionary Value** for `shortcut_action` (using the Dictionary output
   from step 2).
4. Set that text as `AlarmAction`. If it is neither exactly `set` nor
   exactly `clear`, **Stop This Shortcut**. This includes `leave`, missing
   values and unknown actions; never treat `false` as the preservation action.
5. If `AlarmAction` is `set`, get `wake_at` from the original dictionary,
   use **Get Dates from Input**, and set the result as `WakeDate`. Require
   exactly one date, later than **Current Date**; otherwise stop. Do this
   validation **before deleting any alarm**.
6. **Find Alarm** (shown as **Find Alarms** on some iOS versions). Add a
   filter so **Label is exactly** your managed label (`Shahaf` for new setups,
   `SHAHAF` in the reported existing Shortcut).
7. Add **If** with the Find result and condition `has any value`. Inside it,
   add **Delete Alarms** using the Find result.
8. Add **If**. Set it to `AlarmAction is clear`; inside it add
   **Stop Shortcut**.
9. **Add Alarm** (shown as **Create Alarm** on some iOS versions) using the
    `WakeDate` date/time. Use the same exact label in Find and Create; the reported
    current label is `SHAHAF`. Leave Repeat off.

`shortcut_action` is deliberately plain text so the Shortcut avoids fragile
Boolean pickers:

- `leave`: Shahaf data is stale or unavailable. Stop before touching alarms.
- `clear`: confirmed no-school/manual cancellation or an unsafe future Clock occurrence. Delete only
  the labeled school alarm, then stop.
- `set`: a valid school-day wake alarm whose next Clock occurrence matches
  the planned date/time is available. An elapsed root returns `leave`.

The schedule workflow uses NVIDIA NIM as an additional conservative gate for
destructive cases. If NIM is unavailable or sees a possible exam/other
obligation, the endpoint returns `leave`, so the Shortcut leaves the current
alarm alone. NIM never has access to the Gist token.

## Add the automatic triggers

Create two Personal Automations that both run the existing shortcut:

1. Shortcuts → Automation → New Automation → **Time of Day**.
2. Set `05:00`, repeat **Daily**, choose **Run Immediately** (or turn off Ask
   Before Running), and select **Run Existing Shortcut** → **Refresh School
   Wake Alarm**.
3. The reported second automation runs at `06:40`; this is too late for
   cancellations of 06:30 alarms discovered after the 05:00 run.

Make sure the iPhone's time zone is set to Israel. Apple's Shortcuts supports
daily Time of Day automations, and Clock alarms can be labeled and repeated
by weekday; this setup deliberately uses a one-time normal Clock alarm and
refreshes it each morning. See Apple's [Time of Day automation guide](https://support.apple.com/en-euro/guide/shortcuts/apd932ff833f/ios)
and [Clock alarm guide](https://support.apple.com/guide/iphone/set-an-alarm-iph2909d3a74/26/ios).

The legacy YA1 transit Shortcut and the root YA2 Shortcut endpoint are retired.
Do not create or run a Shortcut against `/ya1/wake.json`; active students use
their own randomized managed-profile `wake.json` endpoint and exact profile
alarm label.

## Test safely

Run the Shortcut manually once while the backup alarm remains enabled. On a
school day it should leave the backup alone and create one separately labeled
   alarm with your exact managed label (`Shahaf` for new setups; reported
`SHAHAF` for the existing Shortcut) at the returned `wake_time`. Run it again; there
should still be only one alarm with that label. Do not remove the 07:15 backup
until several school mornings have succeeded.
