# Private multi-student admin

This Worker is the private write boundary for managed student profiles. It
stores names and complete imports in D1, then dispatches the existing Pages
workflow. The Pages workflow receives only active profiles through the
authenticated `/internal/profiles` endpoint.

## One-time Cloudflare setup

1. Install Wrangler and log in with the Cloudflare account that owns the
   Worker: `npm install -g wrangler` then `wrangler login`.
2. Create a D1 database: `wrangler d1 create shahaf-profiles`.
3. Copy `wrangler.toml.example` to `wrangler.toml`, fill in the returned
   database ID, and set `ADMIN_ORIGIN` to the Worker URL.
4. Apply the schema:
   `wrangler d1 execute shahaf-profiles --remote --file schema.sql`.
5. Generate an admin hash from the repository root:
   `python scripts/hash_admin_password.py`.
6. Add Worker secrets:

   - `ADMIN_PASSWORD_HASH`: the generated `pbkdf2$...` value.
   - `GITHUB_DISPATCH_TOKEN`: fine-grained token limited to this repository’s
     Actions workflow dispatch permission.
   - `PROFILE_SYNC_TOKEN`: a long random token used only by GitHub Actions.

7. Set Worker variables for `ADMIN_ORIGIN`, `PUBLIC_SITE_ORIGIN`,
   `GITHUB_REPO`, and `GITHUB_REF`, then deploy:
   `wrangler deploy`.
8. In the GitHub repository, add Actions secrets:

   - `PROFILE_SYNC_URL`: `https://<worker-host>/internal/profiles`
   - `PROFILE_SYNC_TOKEN`: exactly the Worker secret value

The existing `GIST_TOKEN`, `NVIDIA_API_KEY`, and Alexa secrets are unchanged.

## Alarm control center

The dashboard includes a managed-profile-only alarm control center. It stores
global defaults and per-profile overrides in D1, then includes the effective
settings in the existing private profile bundle consumed by the Pages
workflow. The next run of that profile's iPhone Shortcut applies the result;
the Worker never receives or stores an iPhone, GitHub, or Gist credential.

The defaults are a 75-minute wake buffer, stale data leaves the current alarm
unchanged, and confirmed no-school data clears only that profile's primary
alarm. Existing Ya-1 and Ya-2 paths are not connected to these controls.

Each managed public profile also has a **Cancel / move my next alarm** control
at the bottom of its Now tab. The Worker reads that profile's published
`wake.json` and derives the target from its explicit
`next_scheduled_school_day`, so a click before today's alarm still targets the
next scheduled school alarm rather than today's alarm. A Saturday click skips
Saturday and targets Sunday (or the next available school day). It accepts only
a confirmed `clear` or `set` time for
that target date; a `set` is checked against the current time only when the
target is today. The Worker looks up the profile from the URL before writing
its single `alarm_overrides` row. It cannot change another profile, choose a
future date, or change global settings. The response saves the override and
triggers the normal Pages sync in the background. The fast Worker Shortcut
feed can read the matching override immediately, so the student's Shortcut can
apply the iPhone change without waiting for Pages; the Pages `wake.json` is
reconciled afterward. Each change stores a small private snapshot of the
pre-change alarm state. **Restore my alarm** uses that snapshot to put the
same profile's next alarm back exactly as it was before the cancellation or
move, then asks Pages to reconcile it. Older overrides created before restore
snapshots existed use the normal queued reconciliation path. Friday and
Saturday target dates remain protected by the normal no-weekend alarm logic.

The dashboard supports preview, bulk pause/resume/reset/set/clear/leave
commands, per-profile settings, expiring date overrides, audit history, and
settings rollback. A force command requires an explicit reason and
confirmation. Backup alarms are never managed. Transit-enabled managed
profiles can set a safe route preference; the planner still requires arrival
at least five minutes before the first lesson and falls back to automatic
routing if the preference disappears.

Apply the additive schema before deploying the Worker:

`wrangler d1 execute shahaf-profiles --remote --file migrations/0002_alarm_controls.sql`

`wrangler d1 execute shahaf-profiles --remote --file migrations/0003_alarm_restore.sql`

The Pages workflow marks one-time commands as published only after a
successful Pages deployment. It does not consume them: they remain in the
published endpoint until their target date expires, because this version has
no phone check-in yet. If publishing fails, the command remains pending and
the previous public profile remains intact.

## Import flow

Open the Worker URL, log in, paste the strict GPT JSON or load a `.json`
file, enter the admin-only student name, enter the visible יא class number, and
choose **Validate and publish**. The Worker assumes יא and maps the number to
Shahaf's internal `cls` ID automatically, so you do not need to know or type
that ID. The class-number field is required for every import and overrides the
value inside the GPT package, so the student's changes and exams are fetched for
the class number you entered.
The Worker rejects unknown rows, duplicate periods, invalid times, missing
class identity, and incomplete represented weekdays. A valid import is
idempotent for the same admin name, reactivates a disabled profile, and
queues one workflow dispatch.

The console displays:

`https://<pages>/students/<random-id>/`

`https://<worker>/public/profiles/<random-id>/wake.json`

and the alarm label `Shahaf`. The import result still provides the Pages wake
URL for the public schedule; for the fast alarm Shortcut, paste the Worker URL
above into the student's `Get Contents of URL` action. That endpoint reads the
published Pages payload and applies an active alarm override immediately.
Each profile therefore gets its own Shortcut endpoint and alarm label.
Configure the reviewed Shortcut template with those values; the `.shortcut`
file is not generated server-side.

The GitHub workflow remains the only publisher. A failed Worker dispatch or
failed sync does not replace the last published student page. The workflow
also continues to use its existing concurrency guard, and one run processes
the whole active profile bundle rather than creating one job per student.

## Profile management

The dashboard also supports:

- **Edit**: use the block editor to change weekdays and Period 0–13 cards,
  including status, times, subject, teacher, and room. It also changes the
  admin name, Shahaf class number, and optional private transit settings
  (enabled, origin address, latitude, and longitude).
- **Enable / Disable**: keep a profile recoverable in D1 while controlling
  whether it is included in the next public deployment.
- **Publish now**: queue a manual Pages refresh without changing the profile.
- **Delete**: permanently remove a profile from D1 after an explicit browser
  confirmation; its public page disappears on the next successful deployment.

All mutating controls require the authenticated session and CSRF token. Manual
schedule edits go through the same strict validation as imports, so malformed
periods, unknown rows, duplicate periods, invalid times, and missing class
identity cannot be published.

## Security boundary

The public profile ID has 128 bits of randomness and is private by obscurity,
not authentication. Public output contains no admin name, home address,
coordinates, or tokens. The Worker uses an HTTP-only Secure SameSite cookie,
PBKDF2 password verification, strict Origin checks, a hashed CSRF token, and
D1-backed login/publish rate limits.
