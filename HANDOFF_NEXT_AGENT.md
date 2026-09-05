# Shahaf Schedule Sync — handoff for the next agent

This file is the operational handoff. It describes the repository as it stood
after the last code changes in this chat. Read it before changing anything.

## Mission and non-negotiable safety rules

This project is a school timetable PWA and synchronization system for
Ostrovsky/Shahaf schedules. It has two legacy profiles and an additive
multi-student profile system.

The most important rule is scope isolation:

- The random managed profile `d1yQtOSfobdzGs0XfzJlNw` is the canonical יא-2
  schedule for Ori Fisher. The former root profile is archived and redirects
  to it; root `data.json` and `wake.json` are no longer published.
- `/ya1/` and `/ya1/wake.json` are the separate יא-1 schedule. The user
  identifies this profile as Shahar Mosseri.
- Managed students under `/students/<random-id>/` remain scoped. Ori's managed
  profile does not alter the root יא-2 Gist or legacy יא-1 behavior.
- A student's cancellations, exams, selectors, route, alarm command, and
  public output must remain scoped to that student.
- Do not put names, home addresses, home coordinates, API keys, tokens,
  passphrases, or admin reasons into public Pages output.
- Stale, malformed, unavailable, or ambiguous source data must fail closed.
  In particular, it must never delete or replace a valid existing alarm.
- Keep normal backup alarms untouched. Only the exact profile-specific primary
  label may be searched, deleted, or recreated by a Shortcut.
- Do not add rooms as a separate feature unless the user explicitly asks.
- Do not add jailbreak functionality or require Apple Developer membership.

Credentials were supplied/configured during the chat. They are intentionally
not repeated in this document. Never commit them or print them in logs.

## Repository and live locations

Local repository:

`C:\Users\epico\Documents\Codex\2026-08-27\the\outputs\shahaf-schedule-sync`

GitHub repository:

`https://github.com/epicori09-cmyk/shahaf-schedule-sync`

GitHub Pages site:

`https://epicori09-cmyk.github.io/shahaf-schedule-sync/`

Main endpoints:

- Archived root redirect: `https://epicori09-cmyk.github.io/shahaf-schedule-sync/`
- Ori schedule: `https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/d1yQtOSfobdzGs0XfzJlNw/`
- Ori wake JSON: `https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/d1yQtOSfobdzGs0XfzJlNw/wake.json`
- יא-1 schedule: `https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/`
- יא-1 transit wake JSON:
  `https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/wake.json`
- Permanent UI test page:
  `https://epicori09-cmyk.github.io/shahaf-schedule-sync/test/`
- Private profile admin Worker:
  `https://shahaf-profile-admin.trading-api-9de14d.workers.dev/`

Source pages:

- Main Shahaf class source: `https://ostrovsky.shahaf.site/?cls=11&tab=changes`
- יא-1 Shahaf class source: `https://ostrovsky.shahaf.site/?cls=61&tab=changes`
- Main ICS subscription Gist raw URL is documented in `README.md`; its
  unpinned raw URL must remain unpinned so future Gist revisions are followed.

The latest code commit before this documentation is `3152351`:
`Show scheduled alarm time on student page` (following `f89efa0`, which made
Restore return to the correct original alarm time, `fb90b9d`, which removed the
Keep-current alarm control, `f463fbd`, which removed the secondary alarm helper
text, and `3579688`, which added the restore action).

The last live Pages workflow verified in the chat was run `33983791072`,
successful, for `3152351`. The Worker was deployed from the scheduled-alarm
display code version `48680a50-d063-4505-b5e5-b35627893e77`, with the public
per-profile alarm endpoint targeting the next scheduled school day. A
docs-only commit does not change the generated site, but this workflow remains
the repository's deployment verification path.

The final live visual QA covered Nitai's active profile
`Z1_SNYeGELFxRHXa0FQ0mA` in both `?lang=he` and `?lang=en`. Now, Schedule, and
Exams were opened in each language; Schedule day selection and return-to-Now
were also exercised. The alarm panel showed the scheduled time (`07:15` in
Hebrew and `7:15 AM` in English), then Cancel, Move, and Restore only, with no
visible helper/status copy or Keep-current control. Schedule period numerals
and time ranges were also visually isolated correctly, and Exams showed the
expected real exams. No mutating alarm action was pressed. There is no
committed screenshot baseline, so formal baseline comparison remains an
INCONCLUSIVE boundary even though the live visual inspection was clean.

## What is live now

### PWA behavior

The generated site has three visible main tabs:

- Now / עכשיו
- Schedule / מערכת
- Exams / מבחנים

The former visible “Full schedule” label was shortened to Schedule / מערכת.
The old visible “Student schedule” subtitle, source arrow, and last-successful-
sync footer text were removed. The footer now has one localized Shahaf app
link.

The page is bilingual. By default it uses the device/browser language; the
debug/verification override is `?lang=en` or `?lang=he`. Use a fresh URL or a
cache-busting query while testing an old browser tab.

The bundled Heebo TTF files are copied into each generated page under
`fonts/`. CSS uses local `@font-face` entries named `HeeboLocal`, and the
service-worker cache was bumped to `shahaf-schedule-v2`. The intention is that
the site still looks correct on weak cellular/Wi-Fi and does not silently fall
back to an ugly or missing Hebrew font.

The PWA also has a manifest, clean app icons, skeleton loading states, and a
cache-first/data-fallback service worker. Do not remove the local fonts or
change the cache version without a deployment and fresh-page check.

### Swipe behavior

Swipe routing is intentionally zone-based:

- When the visible page is not Schedule, a horizontal swipe in the visible
  content changes the main tab.
- On Schedule, the schedule content area is reserved for day switching. The
  upper navigation area, selected-day heading, and day picker switch main tabs.
- Buttons and links are ignored as swipe starts so a tap does not accidentally
  navigate.
- Vertical scrolling remains available (`touch-action: pan-y`).
- The animation is short and uses a reduced-motion fallback.
- For Hebrew, a physical swipe right goes to the next day and a physical swipe
  left goes to the previous day.
- For English, the direction is reversed: physical swipe left goes to the next
  day and physical swipe right goes to the previous day.

The wiring was checked in a desktop/in-app browser with DOM/accessibility
probes and screenshots. A real physical iPhone gesture was not directly
automated in the final verification, so it remains a device-level verification
boundary.

### Schedule rows and async days

The Schedule tab shows all periods 0–13 when a day is represented.

- An empty period before the first lesson or after the last lesson displays
  `No lesson` / `אין שיעור`.
- An empty period between two lessons displays `Gap` / `חלון`.
- Period numbers and time ranges are forced LTR so Hebrew rendering does not
  swap or distort the numbers.
- The exact Shahaf event `יום למידה א-סינכרוני` is classified as an explicit
  no-school/asynchronous day.
- Such a date is not removed from the day picker. It remains selectable and
  displays a notice:
  `Async learning day` / `יום למידה אסינכרוני`, plus the localized explanation
  that there are no in-person lessons.
- The async date used for the final live check was Wednesday, 9 September
  2026. The live output showed the date, notice, zero lessons, and all periods
  as no lesson.

The visible Events tab was removed earlier, but event data is still retained
internally because it is needed for schedule/alarm safety and async-day
handling.

### Exams

The Exams tab remains visible. Exam records are filtered to each profile's
confirmed subject/track selectors instead of showing every parallel class's
exam. The earlier generic `Reminder: 4 days before · 19:00` card text was
removed; where an exam room is available, the room is shown instead.

The user specifically cares about distinguishing English and Math levels and
major tracks, including parallel Computer Science, Diplomacy, Physics,
Mizrahnut, and other majors. Do not loosen selectors into whole-grade matches.

### Shahaf app link

The footer label is localized as `Open Shahaf app` / `פתיחת אפליקציית שחף`.
The current launcher tries the student app's inferred iOS scheme first:

`shfmobile://`

If iOS does not hand the page off to the installed app, the launcher falls
back after a short delay to the official app listing:

`itms-apps://itunes.apple.com/app/id1368425766`

The app-first scheme is inferred from the iOS bundle identifier
`com.shahaf-soft.shfmobile`; it still needs confirmation on a physical iPhone.

## Alarm systems

### Ori managed יא-2 alarm

Ori's random managed `wake.json` is based on the canonical profile only. Its
core fields include the next valid school day, first confirmed lesson,
calculated wake time, subject, `enabled`, `stale`, `fallback_status`, and
plain-text `shortcut_action`.

For fast manual alarm changes, the Shortcut should fetch the Worker endpoint:
`https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/d1yQtOSfobdzGs0XfzJlNw/wake.json`.
It reads the published Pages payload and applies Ori's active audited override
without waiting for the full Pages rebuild. The Pages wake URL remains the
public schedule endpoint and the background sync still republishes it.

The reviewed iPhone Shortcut is documented in `SHORTCUT.md` and is named
`Refresh School Wake Alarm`. Its exact main alarm label is:

`Shahaf School Wake`

Its intended logic is:

1. Fetch Ori's random managed Worker `wake.json` endpoint above.
2. Convert the URL contents to a Dictionary.
3. Read `shortcut_action` from the original Dictionary.
4. If it is `leave`, stop before touching alarms.
5. Find Clock alarms whose Label is exactly `Shahaf School Wake`.
6. Delete only that result if present.
7. If `shortcut_action` is `clear`, stop after the labeled alarm is gone.
8. Read `wake_at` from the original Dictionary, convert it to Dates, and
   create one normal Clock alarm with the exact label.

The Shortcut is meant for Ori's random managed יא-2 profile only. It does not
manage the יא-1 alarm or any other managed-student alarm.

### יא-1 transit alarm

The יא-1 Shortcut is named `Refresh Ya1 Transit Wake Alarm` and uses only:

`Shahaf Ya1 Wake`

The route planner uses the scheduled Israel Ministry of Transport GTFS feed,
not an unauthenticated Moovit API. It starts at `מרדכי זעירא 5, רעננה`, ends
at Ostrovsky High School / `אוסטרובסקי 26, רעננה`, includes the walk to the
first stop, and requires arrival at least five minutes before the first
confirmed lesson. It chooses the latest safe departure, then minimizes
transfers and duration as tie breakers. Earlier safe alternatives are exposed
in the payload/UI.

The Ya1 transit endpoint contains route legs, bus line/stops, walking legs,
departure, arrival, arrival deadline, wake time, stale/fallback status, and a
Google Maps verification URL. It does not claim real-time delay/cancellation
prediction. If GTFS is stale/malformed, Shahaf is unavailable, or no safe
route exists, it returns `leave`, preserving the existing Ya1 alarm.

Both legacy alarm Shortcuts are intended to run at roughly 05:00 and 06:45
Israel time using daily personal automations. The existing 07:15 backup alarms
were intentionally kept during testing. Normal iPhone Clock alarms are used;
Spotify, jailbreaks, and Apple Developer membership are not required.

### Managed profile alarms

Worker-managed students receive public `students/<random-id>/wake.json`
schedule payloads and a Worker Shortcut endpoint at
`/public/profiles/<random-id>/wake.json`, plus an admin-generated public ID. The default managed label returned by
the current import flow is `Shahaf`; the legacy labels above are different and
must not be accidentally substituted.

The managed engine can carry effective alarm settings and one-time commands,
but the user later requested a simple dashboard and asked to remove the large
alarm-control UI. Therefore:

- The active dashboard UI is for adding students, editing student data and
  timetable cards, enabling/disabling, deleting, publishing, and opening
  links.
- The Worker source still contains the older alarm settings/preview/audit
  backend and an unmounted `alarmDashboardEnhancements` string. It is not
  currently appended to the dashboard HTML response. Treat it as retained
  compatibility code, not as an instruction to expose the controls again.
- Do not remove those backend tables or endpoints without checking whether
  managed wake payload generation still consumes them.
- Do not re-enable the old alarm-control panel unless the user explicitly asks.

## Source map

- `config.json`: main class `cls=11`, main Gist/site settings, and the
  config-driven `ya1` profile with `cls=61` and selectors.
- `src/shahaf_sync/cli.py`: orchestration, source/exam/event caches, root and
  additional profile processing, managed bundle loading, transit invocation,
  safe output handling, and Pages generation.
- `src/shahaf_sync/site.py`: HTML/PWA generator, localization, fonts/assets,
  tab/day swipe routing, schedule rows, async-day notices, exam display,
  manifests, service workers, and wake JSON rendering.
- `src/shahaf_sync/shahaf.py`: strict Shahaf HTML parsing for timetable,
  changes, exams, and events.
- `src/shahaf_sync/profiles.py`: profile selectors, subject/track matching,
  exact change application, and profile-specific exam/lesson selection.
- `src/shahaf_sync/profile_package.py`: strict validation and normalization of
  imported screenshot/GPT packages.
- `src/shahaf_sync/ya1_schedule.py`: supplied Ya1 weekly baseline, including
  photographed periods and the Monday alternative-assessment rows with צחי.
- `src/shahaf_sync/events.py`: event detection, explicit async/no-school
  phrase recognition, conservative suppression decisions, and display fields.
- `src/shahaf_sync/exams.py`: exam reconciliation and ICS exam handling.
- `src/shahaf_sync/nim.py`: NVIDIA OpenAI-compatible client and conservative
  alarm/event classification. It does not receive the Gist token.
- `src/shahaf_sync/transit.py`: GTFS download/validation and safe route search.
- `src/shahaf_sync/alarm_controls.py`: managed-profile effective settings and
  safe public metadata.
- `src/shahaf_sync/assets/fonts/`: bundled Heebo TTF files.
- `admin/worker/src/index.js`: Cloudflare Worker, login/session/CSRF, class
  list, profile import/edit/enable/disable/delete/publish, dashboard data,
  internal sync bundle, and retained alarm-control APIs.
- `admin/worker/schema.sql`: D1 base schema.
- `admin/worker/migrations/0002_alarm_controls.sql`: additive managed alarm
  tables.
- `.github/workflows/sync.yml`: hourly sync, manual dispatch, private profile
  fetch, sync, Pages deployment, alarm-command acknowledgement, and failure
  reporting.
- `scripts/fetch_managed_profiles.py`: fetches active private profiles from the
  Worker using the profile-sync token.
- `scripts/ack_alarm_commands.py`: acknowledges published managed commands.
- `SHORTCUT.md`: user-facing iPhone setup and test instructions.
- `CUSTOM_GPT_PROMPT.txt`: strict screenshot-to-JSON extraction prompt.
- `tests/`: unit/contract tests for source parsing, schedules, events, exams,
  alarms, profiles, transit, admin contract, and site output.

## Admin behavior

The private Worker is at the URL above. It uses a Cloudflare D1 database and
an HTTP-only secure session cookie plus a separate CSRF cookie/token. Mutating
requests need the CSRF header; a stale session or missing token caused the
earlier `csrf rejected` error.

The simple admin flow is:

1. Log in.
2. Add a student name (admin-only).
3. Enter the visible יא class number; the Worker maps it to the Shahaf `cls`
   value. The operator should not need to know the internal ID.
4. Choose English level and Math level from the dropdowns.
5. Choose every confirmed major. The currently represented picker includes:
   Physics, Chemistry, Biology, Computer Science, Cyber, Diplomacy,
   Geography, Arabic, Mizrahnut/Oriental studies, Social Sciences, Business
   Management, Communications/Society/New Media, French, Spanish, Russian,
   Art, and Extended History.
6. Paste or upload the strict JSON package.
7. Add and publish. A valid import returns a random public ID, schedule URL,
   wake URL, and alarm label.
8. Edit a profile through day-by-day Period 0–13 cards, not only raw JSON.
9. Use English/Hebrew schedule links and the Shortcut endpoint shown on the
   profile card.
10. Enable/disable or permanently delete only after checking the confirmation.

Import JSON must use straight ASCII JSON quotes, not typographic curly quotes.
The prompt now explicitly requires JSON serialization and escaping of inner
Hebrew quotes such as `תנ\"ך` and `י\"א`. Unknown rows are not allowed to be
published. A clearly empty row is a gap; a clipped or missing row is unknown.

The current Worker import endpoint overwrites the package's class identity
with the entered class number's mapped ID before validation. That is why an
operator can enter only the visible יא number. A repeat import by the same
admin name updates/reactivates the same profile instead of creating a second
one. Public IDs have at least 128 bits of randomness and are private by
obscurity, not real authentication.

### Public per-student alarm control

Every active managed `/students/<random-id>/` page now renders a
**Cancel / move my next alarm** control at the bottom of its Now tab.
The control opens an explicit cancel-or-move choice and confirmation. It calls
`POST /public/profiles/<random-id>/alarm-command` on the Worker, with only
`{"action":"clear"}` or `{"action":"set","wake_time":"HH:MM"}`. The Worker
requires the configured Pages origin, reads the profile's published `wake.json`,
and derives the target from its validated `next_scheduled_school_day`. This
means a click before today's alarm still targets the next scheduled school
alarm; a Saturday click skips Saturday and targets Sunday (or the next
available school day), not the current calendar date. It rejects past times
only when the target is today, rejects weekend target dates, rate-limits
requests, and updates only that public ID's `alarm_overrides` row. It does not
expose the admin session or allow global/profile settings changes.

The response saves the override and triggers a Pages sync in the background.
When the Shortcut uses the Worker feed documented above, it can fetch and
apply the matching override immediately; the Pages `wake.json` is reconciled
afterward. Friday and Saturday still produce no alarms through the normal schedule guard. The
control is intentionally absent from the archived root and the separate Ya-1
page, because those are not managed random student profiles.

The old `admin/worker/README.md` says the Worker is not deployed; that text is
out of date relative to this chat. The Worker was deployed and its live URL is
listed above. If deployment is needed, run Wrangler from `admin/worker`, where
`wrangler.toml` supplies the Worker name. Running `wrangler secret put` from
the wrong directory caused the earlier “Worker name missing” error.

## NIM safety behavior

The model defaults to `openai/gpt-oss-20b` unless the repository variable
`NVIDIA_NIM_MODEL` overrides it. The request uses `temperature: 0`,
`max_tokens: 4096`, `stream: false`, and `reasoning_effort: high`.

The classifier is not trusted as an autonomous scheduler. It receives only a
sanitized facts object. It must return strict JSON. It may approve a
destructive alarm operation only with `safe_to_delete_alarm: true`,
`risk_level: low`, and an allowed low-risk classification. Missing data,
malformed output, stale sources, possible exams/obligations, outages, or
uncertainty result in `leave`/preserve behavior.

The exact event policy includes this important precedence:

1. Raw Shahaf title/detail.
2. Same-day exams or obligations.
3. Baseline lesson list.

The explicit Hebrew phrase `יום למידה א-סינכרוני` is recognized directly as an
async day with no in-person attendance, so the system does not need to ask NIM
to understand that obvious case. Other events remain overlays or require a
conservative NIM decision.

There is no user-visible access to hidden model chain-of-thought. What can be
audited is the request configuration, sanitized facts, validated JSON result,
classification, risk level, reason, and the fail-closed action.

## Workflow and failure boundaries

`.github/workflows/sync.yml` currently:

- runs manually or hourly at `0 * * * *` with `Asia/Jerusalem` timezone;
- fetches the private active managed-profile bundle from the Worker;
- runs one Python sync for the root plus all managed profiles;
- caches Shahaf changes/exams/events once per distinct class where possible;
- uploads/deploys the Pages artifact;
- acknowledges managed alarm commands only after successful deployment;
- uses workflow concurrency protection;
- fails the run if private profile fetch or sync fails.

An earlier failed sync notification was investigated in the chat. Do not call a
failure “fixed” only because source tests pass: inspect the specific GitHub run
with `gh run view <run-id> --log-failed`, then check the deployed Pages output.
The latest referenced deployment was successful, but any new failure should be
diagnosed at the exact failing step.

A failed source fetch keeps the previous valid output and marks the new
calculation stale/leave where applicable. A failed managed publish must not
replace a previously published student page. The main Gist and legacy outputs
are especially sensitive: no broad cleanup or rebuild should run before
checking the diff and output paths.

## Verification checklist for the next agent

Start every follow-up with:

```powershell
Set-Location C:\Users\epico\Documents\Codex\2026-08-27\the\outputs\shahaf-schedule-sync
git status --short
git log --oneline --decorate -10
```

Then run the local test suite:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

For a non-writing live source check:

```powershell
$env:PYTHONPATH = 'src'
python -m shahaf_sync --config config.json --dry-run
```

For the latest UI deployment, check both languages with fresh URLs such as:

- `...?lang=he&v=<commit>`
- `...?lang=en&v=<commit>`

Verify in each language:

- three tab labels;
- no old header subtitle/source arrow/last-sync display;
- local Heebo font requests return HTTP 200;
- `sw.js` contains the current cache version;
- Schedule contains the async date and notice;
- periods/numbers/time ranges are visually ordered correctly;
- swipe listeners are in the intended zones;
- the app link and manifest are present;
- root and Ya1 endpoints remain separate.

For Pages/workflow verification:

```powershell
gh run list --repo epicori09-cmyk/shahaf-schedule-sync --limit 10
gh run view <run-id> --repo epicori09-cmyk/shahaf-schedule-sync --log-failed
```

For any Gist-affecting change, use dry-run first and inspect the exact output.
Do not use destructive Git commands to “clean up” a dirty worktree unless the
user explicitly authorizes it.

## Known limitations and unresolved boundaries

- Real iPhone swipe behavior has not been directly automated in the final
  browser QA; it needs a physical-device check.
- Scheduled GTFS does not know real-time bus delays, cancellations, or traffic.
- The Shahaf app-first scheme still needs confirmation on a physical iPhone;
  unsupported devices fall back to the App Store listing.
- Public random profile URLs are private by obscurity, not authenticated. Anyone
  who obtains one can view that profile's public schedule.
- The Worker dashboard is intentionally English and simple; public student
  pages are bilingual. Do not infer that every Worker backend feature should
  be visible in the UI.
- The README and some older comments describe earlier 04:30/06:30/07:30
  schedules or the old alarm-control UI. The current workflow is hourly and the
  current dashboard was simplified later. Verify source before repeating old
  prose.
- Exam/room-map ingestion was originally deferred until trustworthy source
  data existed. Exams are now fetched/filtered; a separate room-map product is
  not part of the current scope.

## Suggested first response in a new chat

“I found the Shahaf handoff files in the repository. The code baseline before
the documentation commit was `70d45c1`; root יא-2, legacy `/ya1/`, and managed
student profiles are separate. I will first check `git status`, the latest
workflow run, and the live endpoints before making any changes.”
