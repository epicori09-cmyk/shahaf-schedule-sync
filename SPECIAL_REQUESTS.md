# Shahaf special requests

This file records behavior requested specifically for this project. It is
additive to the general architecture and safety rules in
`HANDOFF_NEXT_AGENT.md`.

## Ori / random managed יא-2 profile wake alarm

- Scope: Ori's canonical random managed profile only. Do not apply this rule to
  other managed student profiles.
- Current verified profile ID: `d1yQtOSfobdzGs0XfzJlNw`.
- When Ori's first confirmed lesson starts at **07:45**, the wake alarm must
  be **06:45** Israel time.
- For every other first-lesson start, keep the normal configured wake rule
  (currently 75 minutes before the first lesson unless another explicit rule
  is added).
- The configured rule lives in `config.json` under
  `special_requests.wake_time_by_first_lesson_start`.
- The former root YA2 profile is retired. Its old `index.html`, `data.json`,
  and `wake.json` are removed from every generated Pages artifact and the root
  is not redirected.

## Retired legacy schedules

- The YA1 schedule and transit endpoint under `/ya1/` were removed from the
  config and publication pipeline.
- The legacy root YA2 schedule was removed from the publication pipeline.
- Both retired paths must remain absent from new Pages artifacts and should
  return HTTP 404 after deployment.
- Randomized managed student profiles under `/students/<public-id>/` are the
  only active public schedule and wake endpoints.

## Israeli weekend alarms

- The app must never create a new alarm for Friday or Saturday.
- Sunday is a valid school day and may receive an alarm.
- The schedule and transit planners skip Friday/Saturday rows before choosing
  a wake plan.
- On a valid no-school weekend response, the default `clear` action removes
  only the app's exact labeled alarm. Stale, malformed, unavailable, or
  uncertain data returns `leave` so an existing alarm is preserved.

## iPhone Shortcut contract

The user-confirmed working Shortcut uses the exact label `Shahaf` and follows
the endpoint's `shortcut_action`:

- `leave`: stop before finding or deleting any alarm.
- `clear`: delete only the exact labeled alarm, then stop.
- `set`: delete only the exact labeled alarm and create one normal Clock alarm
  using `wake_at`.

The root endpoint must return `clear` on fresh Friday/Saturday data, never
`set` for a future Sunday alarm: iOS Clock alarms are time-only and could ring
on the weekend. Stale data returns `leave`. The additive `next_alarm` object
is a UI preview of the next school-day plan, not the Shortcut instruction.
The root `shortcut_action` remains the authority. The web app cannot edit or
confirm alarms in the phone's Clock app.

## Alarm/retrieval reliability audit — 2026-10-06

- Ori's special rule is pinned to `d1yQtOSfobdzGs0XfzJlNw`, not inferred
  from the class number shared with other students. Absolute special times
  are not rounded by normal buffer-rounding settings.
- Nitay retains a 25-minute wake buffer. No student course choices were changed
  by this audit.
- Cancel/move/restore target the next scheduled school date. The alarm card
  shows that date and time; `next_alarm` is its sanitized preview. The root
  payload may still describe today's alarm before its wake time.
- All active date-scoped commands are retained. Saving and restoring rotate
  command versions so competing stale writes cannot replace confirmed state.
- Worker wake responses check age, profile/date identity, current Israel
  weekday, and elapsed wake timestamps. Stale data preserves the existing alarm.
- Cancellation identity includes the selected teacher, subject, date and period.
  Ambiguous identities preserve the previous timetable instead of guessing.
- Source retrieval has bounded retries. Invalid profile bundles and failed
  staged renders do not remove known-good student outputs. Cached JSON is
  validated before replacement.
- Browser controls refresh independently of cached page HTML, show loading and
  transient success/error feedback, and retain the confirmed alarm on errors.

## Header branding

The selected calendar/check badge is the header logo on managed profile and
permanent test pages. It is text-free so it remains legible at the small iPhone
header size and is included in the PWA offline app shell.

## Exam/profile safety

- Exams remain profile-specific.
- Confirmed English/Math levels and major/group selectors must be respected.
- Parallel Computer Science groups and accelerated Math tracks must not be
  shown as a student's exam unless that student's confirmed selectors match.

When adding another exception, document its scope, exact trigger, expected
endpoint result, and whether it is implemented, tested, deployed, or still
requires physical-device verification.
