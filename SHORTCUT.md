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
3. **Get Dictionary Value** for `stale`.
4. **If** `stale` is `true`, add **Stop This Shortcut**.
5. Get the dictionary value for `fallback_status`.
6. Add two safety checks: if `fallback_status` is `stale` or `unavailable`, use
   **Stop This Shortcut**. Do not find or delete any alarm before these checks.
7. Get the dictionary value for `enabled`.
8. Get the dictionary value for `alarm_for_today`.
9. **Find All Alarms**. Add a filter so **Label is exactly**
   `Shahaf School Wake`.
10. **Delete Alarms**, using the result of the filtered Find action.
11. **If** `enabled` is not `true`, use **Stop This Shortcut**. This is the
    no-lessons path: only the labeled school alarm has been removed.
12. **If** `alarm_for_today` is not `true`, use **Stop This Shortcut**. This
    prevents a 05:00 run on a non-school day from creating an alarm for the
    wrong calendar day.
13. Get the dictionary value for `wake_at`.
14. Use **Get Dates from Input** (called **Get Date from Input** on some iOS
    versions) to turn `wake_at` into a Date.
15. **Create Alarm** using that Date/time and set its label to exactly
    `Shahaf School Wake`. Leave Repeat off.

The important order is: stale checks first, then delete only the exact label,
then create the replacement only when the endpoint says the alarm is for
today. A stale or unavailable endpoint therefore leaves the current alarm
untouched.

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
