# Alarm incident and date-scoped event review — 2026-10-13

User requested inspection of missed October 12/13 alarms and website Load
failed, then explicitly requested fixing the AI block/timeout. No production
alarm command was submitted for testing and no preference/URL was changed.

## Historical evidence

- October 13 morning run 38336889757 succeeded; its Pages artifact generated
  05:26:40 Israel time. Nitay, Alma, Jonathan, Neta and Shahar had text-false
  roots caused by a December 22 async-learning NIM read timeout. Ori had set.
- Previous-night run 38302261419 artifact generated October 12 23:08:40,
  with Nitay set for October 13 08:05. At the reported 05:00 automation that
  artifact was about 5h51 old, exceeding the Worker's 3-hour age guard. The
  morning blocked artifact was published before the reported 06:40 run.
  This reconstructs server instructions, not actual phone execution logs.
- Recent scheduled runs are 7–10 hours apart despite hourly source config.
  Sparse scheduling/freshness is a distinct unresolved operational problem.
- Current Worker GETs for all six profiles returned 200 and set. CORS GET
  and cancellation OPTIONS from the actual Pages origin returned 200/204.
  Browser panel opens, no captured warning/error logs. The user's website
  Load failed and manual Shortcut failure are not yet reproduced.

## TDD / fix

Journey: uncertainty on one event date must not block an unrelated alarm or
undo a separately confirmed no-school decision. Same-target uncertainty
must still preserve, and irrelevant out-of-window events must not call AI.

- RED checkpoint c90ac61: future timeout test reproduced global restoration
  of a confirmed no-school date; date-scoped API absent. Added outside-window
  call test separately failed because the model was called unnecessarily.
- GREEN: event processing retains independently approved filtering, records
  uncertainty per date, passes it through managed-profile rendering, and
  checks root and next-alarm candidates separately. Future/past no-attendance
  events defer AI review until relevant; they remain visibly uncertain.
- Unavailable entire event source still blocks globally. Same-target timeout
  returns canonical leave / wire text false. No timeout is treated as proof
  of cancellation, and no stale-policy or weekend protection was relaxed.
- Full unittest suite 247 PASS; Worker Node 25 PASS; six mutations killed;
  compileall and diff checks exit 0. Changed module coverage: site 86%, CLI
  64%, combined 73% (below skill 80% module target; not claimed passed).
  New scoped behaviors have direct runtime regressions, not just string checks.

## Deployment and live verification

- Fix commit ffecd69 pushed; Pages/sync run 38454306823 SUCCESS in 41s.
  No Worker production source changed in this patch; existing Worker reads
  new published roots and preserves its freshness/time-only guards.
- verify_live.ps1 exit 0: all six Worker/Pages profiles fresh, identity and
  command versions correct, buffers preserved and roots set for October 14.
  Ori 06:45; Nitay 07:20; Jonathan 07:15; Shahar/Neta/Alma 06:30.
- User ran Ori's Shortcut after publication and explicitly confirmed creation
  of the 06:45 alarm. This is phone creation evidence for one profile, NOT
  proof it rang or that every student's device works.
- Website Load failed remains un-reproduced: read-only panel and CORS checks
  succeeded, no production cancel command was issued. Screenshot/request
  evidence needed. Sparse scheduled runs/freshness remain unresolved; not
  fixed by moving AI uncertainty to the correct date.

## Self-evaluation

Summary: 3.8/5. Requested AI regression repaired and deployed; broader alarm
incident is not fully closed.

| Axis | Score | Evidence and improvement |
|---|---|---|
| Accuracy | 4 | Historical artifact establishes five blocked feeds; 247 Python/25 Node pass; six live feeds and one user-confirmed phone creation. Do not extrapolate ringing evidence. |
| Completeness | 3 | AI scope/timeout cause fixed; website Load failed and sparse scheduler unresolved. Obtain the failed request and repair scheduling independently. |
| Clarity | 4 | Separate server generation, current feed and phone confirmation recorded; keep the final reply focused on what is fixed versus still open. |
| Actionability | 4 | Deployed patch, same URLs, Ori manual run confirmed; next useful evidence is screenshot/request for cancellation failure. |
| Conciseness | 4 | Narrow date-scoped implementation avoids globally weakening safety; report is longer than user-facing summary. |

Overall 3.8/5; no axis <=2. Improvements: capture cancellation request failure;
establish reliable sync cadence; broaden CLI module coverage (currently 64%).
Self-check: the user can see the AI issue was real and repaired, but should
not accept a blanket all-alarms-working claim with scheduler gaps still open.
Verdict: deliver bounded fix with explicit unresolved incident items.
