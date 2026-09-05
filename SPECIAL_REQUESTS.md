# Shahaf special requests

This file records behavior requested specifically for this project. It is
additive to the general architecture and safety rules in
`HANDOFF_NEXT_AGENT.md`.

## Ori / random managed יא-2 profile wake alarm

- Scope: Ori's canonical random managed profile only. Do not apply this rule to
  Ya1 or to other managed student profiles.
- Current verified profile ID: `d1yQtOSfobdzGs0XfzJlNw`.
- When Ori's first confirmed lesson starts at **07:45**, the wake alarm must
  be **06:45** Israel time.
- For every other first-lesson start, keep the normal configured wake rule
  (currently 75 minutes before the first lesson unless another explicit rule
  is added).
- The configured rule lives in `config.json` under
  `special_requests.wake_time_by_first_lesson_start`.
- The former root profile is archived after the canonical managed profile is
  found. Its old `data.json` and `wake.json` are not published; the root page
  only redirects to the random profile.

## Israeli weekend alarms

- The app must never create a new alarm for Friday or Saturday.
- Sunday is a valid school day and may receive an alarm.
- The schedule and transit planners skip Friday/Saturday rows before choosing
  a wake plan.
- On a valid no-school weekend response, the default `clear` action removes
  only the app's exact labeled alarm. Stale, malformed, unavailable, or
  uncertain data returns `leave` so an existing alarm is preserved.

## iPhone Shortcut contract

The main Ori Shortcut uses the exact label `Shahaf School Wake` and follows
the endpoint's `shortcut_action`:

- `leave`: stop before finding or deleting any alarm.
- `clear`: delete only the exact labeled alarm, then stop.
- `set`: delete only the exact labeled alarm and create one normal Clock alarm
  using `wake_at`.

Do not stop on `alarm_for_today = false`. On Friday or Saturday that value is
normally false because `wake_at` points to Sunday; the returned date still
needs to be created. The existing iPhone Shortcut must be edited manually to
remove the `AlarmToday is No` stop block; the web app cannot edit a Shortcut on
the phone.

## Header branding

The selected calendar/check badge is the header logo on the root, Ya1, managed
profile, and permanent test pages. It is text-free so it remains legible at
the small iPhone header size and is included in the PWA offline app shell.

## Exam/profile safety

- Exams remain profile-specific.
- Confirmed English/Math levels and major/group selectors must be respected.
- Parallel Computer Science groups and accelerated Math tracks must not be
  shown as a student's exam unless that student's confirmed selectors match.

When adding another exception, document its scope, exact trigger, expected
endpoint result, and whether it is implemented, tested, deployed, or still
requires physical-device verification.
