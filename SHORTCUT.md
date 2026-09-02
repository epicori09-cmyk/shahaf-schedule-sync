# Free iPhone wake-alarm setup

This uses the normal iPhone Clock alarm. It does not require Spotify,
jailbreak access, Apple Developer membership, or a paid service.

The public endpoint is:

`https://epicori09-cmyk.github.io/shahaf-schedule-sync/wake.json`

It is intentionally based on the Master profile only (your יא-2 schedule),
not the יא-1 profile.

## Before testing

Keep your existing 07:15 alarm enabled as the backup. Do not give that alarm
the label `Shahaf School Wake`; the Shortcut deletes only alarms with that
exact label.

## Create the Shortcut

In the Shortcuts app, create a shortcut named **Refresh School Wake Alarm**.
Add these actions in order:

1. **Get Contents of URL**
   - URL: `https://epicori09-cmyk.github.io/shahaf-schedule-sync/wake.json`
   - Method: `GET`
2. **Get Dictionary from Input**.
3. **Get Dictionary Value** for `shortcut_action` (using the Dictionary output
   from step 2).
4. Add **If**. Its left value is the result of step 3; set the condition to
   `is` and type `leave`. Inside the block, add **Stop Shortcut** (shown as
   **Stop This Shortcut** on some iOS versions).
5. **Find Alarm** (shown as **Find Alarms** on some iOS versions). Add a
   filter so **Label is exactly** `Shahaf School Wake`.
6. Add **If** with the Find result and condition `has any value`. Inside it,
   add **Delete Alarms** using the Find result.
7. Get the dictionary value for `shortcut_action` again, using the Dictionary
   output from step 2.
8. Add **If**. Set it to `shortcut_action is clear`; inside it add
   **Stop Shortcut**.
9. Get the dictionary value for `wake_at`, using the Dictionary output from
   step 2.
10. Use **Get Dates from Input** to turn `wake_at` into a Date.
11. **Add Alarm** (shown as **Create Alarm** on some iOS versions) using that
    Date/time. Set its label to exactly `Shahaf School Wake`; leave Repeat off.

`shortcut_action` is deliberately plain text so the Shortcut avoids fragile
Boolean pickers:

- `leave`: Shahaf data is stale or unavailable. Stop before touching alarms.
- `clear`: no school today, or the wake time has already passed. Delete only
  the labeled school alarm, then stop.
- `set`: a valid future school-day wake alarm (today or the next school day)
  should be created.

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

## Test safely

Run the Shortcut manually once while the backup alarm remains enabled. On a
school day it should leave the backup alone and create one separately labeled
`Shahaf School Wake` alarm at the returned `wake_time`. Run it again; there
should still be only one alarm with that label. Do not remove the 07:15 backup
until several school mornings have succeeded.
