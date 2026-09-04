# Shahaf Schedule Sync — complete chat summary

This is the chronological summary of the work and decisions made in the
previous chat. It is intentionally detailed so a new agent can continue
without reconstructing the picture from the many screenshots.

## 1. Starting point: timetable screenshots and the initial correction

The chat began with several Hebrew Shahaf timetable screenshots. The first
interpretation was not reliable enough: the user explicitly corrected that the
teachers, hours, and class placements had changed and that the user had moved
classes. The screenshots, rather than an assumed generic grade timetable, became
the source of truth for the personal baseline.

The user wanted a schedule experience that could be swiped side-to-side to
switch between tabs. The user also wanted a plan-mode style question flow for
future school features. A key product boundary was established early: keep the
existing “Now” behavior and vertical scrolling, while adding separate smooth
horizontal tab navigation.

Exams and a room map were discussed. Rooms were later explicitly deferred. Exam
notifications were acceptable only if the PWA could deliver them consistently;
the intended reminder lead time was four days. The user later asked to remove
the visible Events tab, but event data remained necessary internally.

The user clarified that the main profile is יא-2 and later identified it as Ori
Fisher. The separate יא-1 profile was later identified as Shahar Mosseri.

## 2. Main and Ya1 schedule interpretation

The screenshots showed many parallel tracks and moved lessons. The system was
made careful about the user's exact English, Math, Computer Science, Diplomacy,
Physics, and other major groups. The user repeatedly emphasized filtering out
classes that might belong to another parallel group.

For the main יא-2 schedule, the configuration uses Shahaf `cls=11`. The
personal recurring schedule was rebuilt from screenshots and preserved in the
Gist-backed main pipeline. The main profile's changes and exams are selected by
exact selectors/subjects instead of treating every class in the grade as the
user's class.

For Ya1, screenshots supplied a separate baseline. The configured source uses
`cls=61`. The hardcoded Ya1 baseline in `src/shahaf_sync/ya1_schedule.py`
contains only the explicitly supplied rows, including the subject groups,
teachers, periods, rooms, Monday alternative-assessment rows with צחי, and the
Ya1-specific track selectors. The user later clarified that Ya1 is Shahar
Mosseri.

The user supplied a detailed Ya1 schedule including:

- Sunday literature, Bible, physical education and literature rows;
- Monday history, Hebrew, accelerated five-point English, and alternative
  assessment rows;
- Tuesday Computer Science, Physics, and education;
- Wednesday education, accelerated English, history, Hebrew, PE, and Cyber;
- Thursday Physics, Computer Science, Bible, literature, and Hebrew.

The Ya1 transit version uses this baseline to find the first confirmed lesson
for each school day.

## 3. Main iPhone wake alarm design

The user requested a free iPhone Shortcuts wake-alarm system using a normal
Clock alarm, not Spotify playback, jailbreak functionality, or Apple Developer
membership.

The root public endpoint was designed as `wake.json`. It contains the next
valid school day, first confirmed lesson, calculated wake time (first lesson
minus 75 minutes), subject, `enabled`, `stale`, fallback information, and a
plain-text `shortcut_action`.

The safety contract is:

- `set`: delete/recreate only the labeled school alarm at the calculated time;
- `clear`: delete only the labeled school alarm, then stop;
- `leave`: stop before touching any alarm;
- stale, malformed, unavailable, or uncertain data must produce leave behavior;
- the existing 07:15 backup alarm remains untouched while testing.

The main Shortcut is called `Refresh School Wake Alarm` and manages exactly:

`Shahaf School Wake`

The user went through a long iPhone Shortcuts setup/debugging process. The
correct chain uses `Get Contents of URL`, `Get Dictionary from Input`, and
dictionary-value reads from the original dictionary output. It reads
`shortcut_action`, handles leave, finds alarms by the exact label, deletes only
those alarms, handles clear, reads `wake_at`, converts it with `Get Dates from
Input`, and creates a normal Clock alarm.

Two daily personal automations were intended at approximately 05:00 and 06:45
Israel time. The user asked whether the system was self-healing if the alarm
did not already exist; the answer was yes for a valid `set` response because
the Shortcut can create it after finding zero existing matching alarms.

The user manually tested creation and saw the alarm appear. The main יא-2
alarm later worked correctly in a real morning test.

## 4. Shortcuts errors and fixes

Several iPhone Shortcuts issues were resolved in the chat:

### Text-to-dictionary conversion error

The user saw:

`Conversion Error: Get Dictionary Value failed because Shortcuts couldn't convert from text to dictionary.`

The problem was using text or the wrong magic-variable output instead of the
Dictionary produced by `Get Dictionary from Contents of URL` / `Get Dictionary
from Input`. The fix was to keep using the original Dictionary variable for
every `Get Value` action, including `shortcut_action` and `wake_at`.

### Date conversion

The user asked when dates were made. The correct flow is to read `wake_at` from
the original Dictionary, pass that value to `Get Dates from Input`, and use the
resulting Dates variable in `Create Alarm For`. The date is not manually
constructed in the Shortcut.

### Alarm label mismatch

The user had an alarm labeled `Shahaf` while the main Shortcut was configured
for `Shahaf School Wake`. The Find Alarms filter is exact, so a mismatch means
the old alarm is not found. The user later made the alarm on the phone and
confirmed the label issue was understood. The current docs keep the legacy
main label as `Shahaf School Wake`, the Ya1 label as `Shahaf Ya1 Wake`, and the
managed profile import default as `Shahaf`.

### Sharing/importing Shortcuts

The user had iCloud sharing trouble and later shared a Shortcut file/link with
a friend. The guidance was that first-time users must grant Clock/Shortcuts
permissions, configure their own personal automations, select Run Immediately
or turn off Ask Before Running where iOS offers it, and preserve the backup
alarm. A server-side signed `.shortcut` file was not generated; the reviewed
template is configured per endpoint/label.

## 5. Ya1 transit wake system

The user requested a separate Ya1 transit-based wake system:

- origin: `מרדכי זעירא 5, רעננה`;
- destination: Ostrovsky High School, `אוסטרובסקי 26, רעננה`;
- first confirmed Ya1 lesson determines the arrival deadline;
- arrival must be at least five minutes before that lesson;
- choose the latest safe departure;
- include at least five minutes of walking to the first stop;
- wake 75 minutes before leaving home;
- use `Shahaf Ya1 Wake` only;
- leave a valid existing alarm unchanged when Shahaf/GTFS/route data is stale,
  malformed, unavailable, or unsafe.

Moovit’s official API was found unsuitable for a free unauthenticated server
integration. Google Maps links were retained for manual route verification. The
automated planner uses the Israeli Ministry of Transport scheduled GTFS feed.
The route payload contains walking and transit legs, stops, transfers, line,
departure, arrival, duration, early-arrival margin, and earlier safe
alternatives. It does not claim live bus delay or cancellation awareness.

The user asked which bus route the site chooses and requested that route arrows
be flipped because they rendered swapped. The Ya1 display was adjusted to show
the intended departure-to-arrival order.

The user also requested a simple Ya1 access gate requiring `אורי המלך` on every
entry. The gate was implemented for Ya1 and later visually adjusted so the
locked access screen did not leave the user scrolling below it. The main/root
and managed profiles do not use this gate.

The Ya1 alarm was at one point observed as 07:15. That is consistent with a
safe fallback/leave situation, but the exact cause must be checked from that
day's endpoint payload and route/source status rather than blamed on one label
or one browser cache. The user later confirmed the main Ya2 alarm worked
perfectly; Ya1 still needs a real morning validation when the route is valid.

## 6. Cancellations, events, async days, and NIM

The user was concerned that Shahaf may publish only cancellations, not newly
moved/added lessons. The system therefore remains conservative: it applies
date/period-scoped explicit changes and does not invent a replacement lesson.

The user specifically asked whether a cancellation exposes its reason. The
Shahaf events feed was added to investigate events such as tests, concerts,
school activities, remote learning, and asynchronous days. Events are parsed
separately from ordinary cancellation rows.

NVIDIA NIM was added as a conservative classification gate for destructive
alarm operations. The key was loaded from a local secret file during setup and
was never meant to be committed. The selected default model is
`openai/gpt-oss-20b`, with `reasoning_effort: high`, temperature 0, and strict
JSON output validation. A repository variable can override the model.

NIM’s behavior is deliberately fail-closed. It receives sanitized facts, not
credentials or instructions. It must classify an event or alarm operation,
return a risk level and short reason, and can approve deletion only for a
clearly safe low-risk no-school/remote-learning case. Any missing data, outage,
malformed output, possible exam/obligation, or uncertainty preserves the
existing alarm.

The user asked for the NIM response/reasoning and whether it was smart. The
system does not expose hidden chain-of-thought. What can be shown/audited is
the prompt, request parameters, sanitized context, returned JSON, risk level,
reason, and final action. The root cause of literal uncertainty was addressed
by adding deterministic recognition for the exact Shahaf phrase rather than
making the model guess.

The explicit event:

`יום למידה א-סינכרוני`

was identified as an asynchronous learning day with no in-person school. The
event classifier recognizes this phrase directly. It suppresses normal lessons
for that date for alarm purposes, but the PWA now still shows the date in the
Schedule tab with an explicit async notice instead of hiding the day.

The event decision precedence is raw Shahaf event text first, same-day exams or
obligations second, baseline lessons third. Ordinary events remain overlays and
do not automatically delete an alarm.

## 7. Exams and student-specific subject filtering

The user considered whether to show every exam or only exams relevant to each
student. The chosen direction was profile-specific filtering. English and Math
levels, major selections, exact subjects, teachers, rooms, and selectors are
used to prevent a Math 5-point or Computer Science exam from a parallel group
appearing for the wrong student.

Nitay was added as a managed student profile from screenshots and JSON. The
user specified Nitay Bezalel, class יא-7, and later clarified that Nitay also
takes מזרחנות. Parallel-group filtering was important for this profile too.

The first Nitay JSON had typographic curly quotes, causing strict JSON parse
errors. The GPT prompt was rewritten to require ASCII JSON serialization and
proper escaping of Hebrew internal quotes, for example `תנ\"ך` and `י\"א`.

Another validation issue was that lesson rows lacked rooms. The validator was
adjusted so a lesson may have a null room when the room is not visible, while
still requiring subject, teacher, start, and end. Unknown rows remain hard
errors until corrected; a missing visible room is retained as a warning rather
than guessed.

## 8. Multi-student admin concept and implementation

The user proposed sending timetable screenshots to a custom GPT, receiving
strict JSON, then pasting/importing that JSON through an admin page. The design
became a private Cloudflare Worker + D1 admin service with GitHub Actions as
the publisher.

The custom GPT prompt is stored in `CUSTOM_GPT_PROMPT.txt`. It requires:

- English JSON keys;
- exact Hebrew subjects, teachers, rooms, class labels, and notes;
- no guessing;
- periods 0–13 for represented weekdays;
- `lesson`, `gap`, and `unknown` distinction;
- warnings for clipped/missing/unreadable data;
- optional English/Math level and majors;
- subject/teacher/room selectors only when confirmed;
- exact exam terms only for the student's own tracks;
- disabled transit unless explicitly supplied;
- strict JSON serialization and parse validation.

The operator enters the visible יא class number, not the Shahaf internal
`cls` ID. The Worker maps the number to the known Shahaf class list. This was a
direct response to the user seeing `shahaf.class_id is required` and saying
they did not know internal IDs. The browser should never require the operator
to type the ID.

The Worker stores the student name and complete package privately in D1,
generates an unguessable public ID, and publishes only sanitized public output.
The public URL is private by obscurity, not real authentication. Student names,
home address/coordinates, tokens, and admin notes must not appear on Pages.

The import flow supports JSON paste or `.json` upload, warning display, strict
validation, duplicate-by-admin-name update/reactivation, automatic publish
dispatch, and result links. The worker returns:

- public schedule URL;
- public wake/Shortcut endpoint;
- alarm label;
- validation warnings;
- queued publish status.

The profile editor was changed from confusing raw JSON into day-by-day block
cards for weekdays and Periods 0–13. It still keeps a hidden synchronized JSON
payload for the API, but the visible editing experience is cards with fields
for status, time, subject, teacher, and room. Profiles can be enabled,
disabled, published, edited, or explicitly deleted.

The major picker was expanded after checking Shahaf’s live class list. Current
choices include Physics, Chemistry, Biology, Computer Science, Cyber,
Diplomacy, Geography, Arabic, Mizrahnut, Social Sciences, Business Management,
Communications/Society/New Media, French, Spanish, Russian, Art, and Extended
History. English and Math have dropdowns for 3, 4, 5, and accelerated 5 points.

The first managed public ID seen in the chat was
`X_3uvcs0BuZlzO6HP5Q3MQ`. It is an example of the generated random ID, not a
secret. The admin result showed schedule/wake URLs and a generic `Shahaf`
alarm label. Do not assume that historical profile is still active without
checking D1/admin status.

## 9. Worker setup and errors

The admin Worker uses:

- Worker name `shahaf-profile-admin`;
- D1 database `shahaf-profiles`;
- secure HTTP-only session cookie;
- separate CSRF token/cookie;
- PBKDF2 password hash;
- strict Origin validation;
- rate limits for login/import/publish;
- Worker-to-GitHub dispatch token;
- profile-sync token for GitHub Actions;
- no browser exposure of GitHub/Gist/NIM secrets.

The user ran `wrangler secret put ...` from a directory where Wrangler could
not find the Worker configuration and got:

`Required Worker name missing. Please specify the Worker name in your Wrangler configuration file, or pass it as an argument with --name`

The fix was to run Wrangler from `admin/worker`, where `wrangler.toml`
contains the Worker name.

The user also saw `csrf rejected`. The cause is a missing/mismatched CSRF token
or expired session. A fresh login obtains the session and token; subsequent
mutating requests must send `X-CSRF-Token` from the current CSRF cookie/value.

The admin Enter Dashboard button was previously reported as not working. The
dashboard script was repaired, and the live Worker page was used during later
checks. The admin page is private/no-store; it should not be cached like the
Pages PWA.

## 10. Alarm control center detour and later removal from the UI

At one point the user requested a large Alarm Control Center with global and
per-profile settings, wake buffers, bounds, rounding, stale policies, bulk
actions, audit history, rollback, one-time date commands, transit route
preferences, and preview/confirmation flows.

That plan was implemented in the managed pipeline and Worker backend, including
the additive D1 migration and effective settings passed through the internal
profile bundle. It intentionally excluded legacy Ya1/Ya2 behavior.

The user then said the controls were too complicated and explicitly requested
that all those new controls be removed. The desired admin surface became only:

- create students;
- choose English/Math levels;
- choose majors;
- view/edit schedules in blocks;
- open English/Hebrew schedule links;
- open/copy the Shortcut endpoint;
- enable/disable/delete/publish profiles;
- keep address/transit information only where relevant.

The source currently reflects an important split: the simple dashboard HTML and
active `dashboardEnhancements` are mounted, while the older
`alarmDashboardEnhancements` string and its API routes remain in the Worker
source for managed compatibility but are not mounted in the returned HTML.
The next agent should preserve this behavior unless the user explicitly asks
for alarm controls again.

## 11. UI/PWA work before the latest request

The user requested a permanent test page with a test schedule and the ability
to switch Hebrew/English. PWA identity and clean logos were added to generated
pages. Skeleton loaders and weak-network caching were also added.

The public site was translated based on device/system language with a manual
`?lang=` override for QA. A bundled Heebo font was added because remote/default
font loading was unreliable. The service worker pre-caches the font files and
uses a bumped version so stale tabs can be refreshed.

Screenshot-driven UI changes included:

- remove the top-left source arrow;
- remove “Student schedule” subtitle;
- rename Full schedule to Schedule / מערכת;
- remove visible last successful sync text;
- use room numbers in exam cards when present;
- fix the gap around tabs;
- create fast clean tab/day animations;
- fix Hebrew period/time formatting;
- label outer empty rows as No lesson / אין שיעור;
- label inner empty rows as Gap / חלון;
- preserve the async date and notice.

The latest live Hebrew and English browser checks showed the corrected header,
three tabs, local font, correctly ordered periods/times, and the Wednesday,
9 September 2026 async day with all periods shown as no lesson.

## 12. Git history at the handoff point

The important recent commits, newest first before the documentation commit,
were:

1. `70d45c1` — Refine swipe zones and show async days
2. `cb0d6d5` — Improve schedule navigation and typography
3. `172fae7` — Add complete Shahaf major picker
4. `b968b10` — Simplify profile admin controls
5. `6b73387` — Simplify alarm control dashboard
6. `4f8df54` — Fix dashboard script rendering
7. `9911a5e` — Fix managed alarm command scoping
8. `5c11f5c` — Add managed-profile alarm control center
9. `97eedba` — Fix NIM event classification and Ori Sundays
10. `9b4682c` — Deploy schedule sync updates and PWA branding
11. `d85c52c` — Filter managed exams by exact course track
12. `18564c4` — Add permanent bilingual schedule test page
13. `9718357` — Add device-language localization to schedule PWA
14. `ef6e150` — Derive Shahaf class IDs from Ya class numbers
15. `6fd2acd` — Hide internal class IDs in admin picker
16. `7fa06b9` — Add Shahaf class picker to profile admin
17. `2aed178` — Replace profile JSON editing with timetable blocks
18. `0cabec6` — Add managed profile administration controls
19. `839970e` — Use template-compatible managed alarm label
20. `783e6cf` — Allow lessons with undisclosed rooms

The documentation added by this handoff is separate from the Pages runtime
code. Do not dispatch a schedule sync merely because the documentation commit
was pushed.

## 13. Current verification status

Verified in the chat:

- repository tests had been developed for site, profile, events, exams,
  transit, alarms, NIM, admin contract, and legacy behavior;
- latest Pages deployment for `70d45c1` succeeded;
- fresh Hebrew live page showed the corrected three-tab interface;
- fresh English live page showed the corresponding interface;
- local Heebo TTF assets returned HTTP 200;
- service worker used the new cache version;
- event data included the async Wednesday and `no_school` classification;
- main Ya2 alarm worked in a real morning test;
- manual Shortcut alarm creation worked;
- root/Ya1/managed alarm scopes were designed separately;
- admin dashboard code supports student add/edit/enable/disable/delete/publish
  and class-number mapping.

Not fully verified in the chat:

- a physical iPhone swipe gesture after the final zone change;
- live bus delays/cancellations, since scheduled GTFS is not real-time;
- the exact Ya1 route/alarm result on a particular future morning;
- a verified Shahaf private app deep link beyond the App Store scheme;
- every live managed profile's current D1/public status;
- true multi-user concurrency capacity under production rate limits;
- whether a new GitHub sync failure after the last successful run has occurred.

Always state these boundaries honestly. A source-string check or unit test is
not the same as physical-device, browser-integration, deployment, or live
morning proof.

## 14. Recommended continuation procedure

When the user opens the next chat, the next agent should:

1. Read `HANDOFF_NEXT_AGENT.md` and this file.
2. Check `git status --short` and the latest log.
3. Check the latest GitHub Actions run and failed-step log if the user reports
   a job failure.
4. Open fresh, cache-busted root, Ya1, test, and admin URLs as relevant.
5. Preserve root יא-2, `/ya1/`, the Gist, and their labeled alarm behavior.
6. Make only the requested change, preferably in a separate commit.
7. Run the full local test suite.
8. Deploy only when requested or when the requested code change requires it.
9. Re-check live output in both Hebrew and English.
10. Report implemented, tested, deployed, and live-verified status separately.

The safest short reminder is: this is an additive system around two legacy
profiles. The user values practical UI, exact Hebrew schedule data, smooth
swipe behavior, profile-specific subject filtering, and alarms that fail closed.

