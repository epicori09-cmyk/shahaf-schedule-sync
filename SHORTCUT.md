# Free iPhone wake-alarm setup

This uses the normal iPhone Clock alarm. It does not require Spotify,
jailbreak access, Apple Developer membership, or a paid service.

## Current installed student shortcut log

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
currently installed Shortcut also checks `alarm_for_today` as text and stops
when it is `No`. This is intentional: on Saturday, a Sunday `wake_at` would
become a time-only Clock alarm whose next occurrence could be Saturday rather
than Sunday. The daily automation will run again on Sunday, when the endpoint
returns `alarm_for_today: true`, and then create the alarm. Do not remove this
guard unless the Shortcut is redesigned to create a genuinely date-specific
alarm and separately proves Friday/Saturday safety.

The schedule and transit wake planners explicitly ignore Friday and Saturday
dates (the Israeli weekend). Sunday remains a valid school day. When a valid
response has no school on the current weekend, the default `clear` action
removes only the app's exact labeled alarm; stale or uncertain responses still
return `leave` so an existing alarm is preserved.

The current Ori Shortcut endpoint is:

`https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json`

It is the randomly generated managed profile for Ori's יא-2 schedule. The
former root endpoint is archived and should no longer be used.

## Before testing

Keep your existing 07:15 alarm enabled as the backup. Do not give that alarm
the label `Shahaf`; the Shortcut deletes only alarms with that exact label.

## Create the Shortcut

In the Shortcuts app, create a shortcut named **Refresh School Wake Alarm**.
Add these actions in order:

1. **Get Contents of URL**
   - URL: `https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json`
   - Method: `GET`
2. **Get Dictionary from Input**.
3. **Get Dictionary Value** for `shortcut_action` (using the Dictionary output
   from step 2).
4. Add **If**. Its left value is the result of step 3; set the condition to
   `is` and type `leave`. Inside the block, add **Stop Shortcut** (shown as
   **Stop This Shortcut** on some iOS versions).
5. **Find Alarm** (shown as **Find Alarms** on some iOS versions). Add a
   filter so **Label is exactly** `Shahaf`.
6. Add **If** with the Find result and condition `has any value`. Inside it,
   add **Delete Alarms** using the Find result.
7. Get the dictionary value for `shortcut_action` again, using the Dictionary
   output from step 2.
8. Add **If**. Set it to `shortcut_action is clear`; inside it add
   **Stop Shortcut**.
9. Get `alarm_for_today` from the Dictionary output → **Get Text from Input**.
10. Add **If**. If that text is `No`, add **Stop Shortcut**.
11. Get the dictionary value for `wake_at`, using the Dictionary output from
   step 2.
12. Use **Get Dates from Input** to turn `wake_at` into a Date.
13. **Add Alarm** (shown as **Create Alarm** on some iOS versions) using that
    Date/time. Set its label to exactly `Shahaf`; leave Repeat off.

`shortcut_action` is deliberately plain text so the Shortcut avoids fragile
Boolean pickers:

- `leave`: Shahaf data is stale or unavailable. Stop before touching alarms.
- `clear`: no school today, or the wake time has already passed. Delete only
  the labeled school alarm, then stop.
- `set`: a valid school-day wake alarm is available. The `alarm_for_today`
  guard creates it only when the target is today, preventing a future
  Sunday time from becoming a Friday or Saturday Clock occurrence.

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
3. Create a second identical automation at `06:45`.

Make sure the iPhone's time zone is set to Israel. Apple's Shortcuts supports
daily Time of Day automations, and Clock alarms can be labeled and repeated
by weekday; this setup deliberately uses a one-time normal Clock alarm and
refreshes it each morning. See Apple's [Time of Day automation guide](https://support.apple.com/en-euro/guide/shortcuts/apd932ff833f/ios)
and [Clock alarm guide](https://support.apple.com/guide/iphone/set-an-alarm-iph2909d3a74/26/ios).

## Separate יא-1 transit alarm

The יא-1 transit endpoint is:

`https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/wake.json`

Create a second shortcut named **Refresh Ya1 Transit Wake Alarm**. It is
intentionally separate from the main shortcut and must use the exact label
`Shahaf Ya1 Wake`.

Use these actions in order:

1. **Get Contents of URL** → the יא-1 `wake.json` URL above, method `GET`.
2. **Get Dictionary from Input**.
3. **Get Dictionary Value** for `shortcut_action` using the dictionary from
   step 2.
4. **If** that value **is** `leave`, add **Stop This Shortcut** inside the If.
5. **Find Alarms** with the filter **Label is exactly** `Shahaf Ya1 Wake`.
6. **If** the Find Alarms result **has any value**, add **Delete Alarms** using
   that Find Alarms result.
7. Get the dictionary value for `shortcut_action` again, using the original
   dictionary from step 2.
8. **If** that value **is** `clear`, add **Stop This Shortcut** inside the If.
9. Get the dictionary value for `wake_at`, using the original dictionary from
   step 2.
10. **Get Dates from Input** using the `wake_at` value.
11. **Create Alarm** using that date, with label exactly `Shahaf Ya1 Wake` and
    Repeat turned off.

If `leave` is returned, the Shortcut stops before finding or deleting an
alarm. If `clear` is returned, it deletes only the יא-1-labeled alarm. The
main `Shahaf` alarm is never searched for by this Shortcut.

Create two separate daily **Time of Day** automations at `05:00` and `06:45`,
both running **Refresh Ya1 Transit Wake Alarm**. Turn off **Ask Before
Running** / choose **Run Immediately** where iOS offers that option. Keep the
existing 07:15 backup alarm enabled while testing.

## Test safely

Run the Shortcut manually once while the backup alarm remains enabled. On a
school day it should leave the backup alone and create one separately labeled
`Shahaf` alarm at the returned `wake_time`. Run it again; there
should still be only one alarm with that label. Do not remove the 07:15 backup
until several school mornings have succeeded.
