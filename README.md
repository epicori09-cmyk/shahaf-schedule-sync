# Shahaf Schedule Sync

Daily, fail-closed synchronization from Ostrovsky’s public Shahaf timetable into a personal ICS Gist and a readable GitHub Pages site.

## Source and target

- Shahaf source: `https://ostrovsky.shahaf.site/?cls=11&tab=changes`
- Class: `י״א 2` (`cls=11`)
- Target Gist: `a5891b76daf585d0953bc96958819fdf`, file `school.ics`
- iPhone subscription URL: `https://gist.githubusercontent.com/epicori09-cmyk/a5891b76daf585d0953bc96958819fdf/raw/school.ics`

The unpinned URL is important: a revision-pinned raw URL will not follow future Gist updates.

The sync reads only Shahaf's explicit, date-specific changes feed. It does not
compare the whole-school timetable, which contains parallel major groups and
would create false cancellations for a personal calendar. An empty changes
feed is a successful no-op; an unknown non-empty schema is a safe failure.

## GitHub setup

1. Create a GitHub repository and copy this directory into it.
2. Add a fine-grained personal access token as repository secret `GIST_TOKEN`. Give it only **Gists: write** permission.
3. Enable GitHub Pages with **GitHub Actions** as the source.
4. Add your NVIDIA API key as repository secret `NVIDIA_API_KEY`. From the repository folder, you can do this interactively with `gh secret set NVIDIA_API_KEY --repo epicori09-cmyk/shahaf-schedule-sync` and paste the key when prompted. Never put the key in a file or commit it. Optionally add a repository variable `NVIDIA_NIM_MODEL`; it defaults to `openai/gpt-oss-20b`.
5. Run **Shahaf schedule sync → Run workflow** once. The workflow then runs at 04:30, 06:30, and 07:30 Israel time.

The workflow never prints the token. If the Gist is not a valid ICS file, Shahaf is unavailable, or the source page is incomplete, it publishes a stale/error banner and does not write the Gist.

The separate יא-1 page is [https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/](https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/). Its configured Shahaf source is `https://ostrovsky.shahaf.site/?cls=61&tab=changes`. It is a direct URL with no passcode, profile selector, or Settings screen.

For alarm safety, the workflow sends only structured Master יא-2 schedule facts to
NVIDIA's OpenAI-compatible NIM endpoint using `openai/gpt-oss-20b` with high
reasoning effort. NIM never receives the Gist token and
cannot edit the Gist or the iPhone. It may approve a destructive alarm
replacement/clear only with a valid low-risk JSON answer. Missing credentials,
an API outage, malformed output, an exam/other possible obligation, or any
uncertainty produces `shortcut_action: leave`, preserving the existing alarm.

If `NVIDIA_API_KEY` has not been added yet, ordinary future alarms still work;
only a destructive clear or a same-day change is held safely at `leave` until
the safety check can run.

The site has three swipeable views: **Now** shows the current and next lesson, **Full schedule** lets you choose a school day and see every Shahaf period (0–13), including free gaps, and **Exams** shows the selected subjects with a calendar alert four days before at 19:00. Changes are removed from the website only after the affected date and period have fully ended; the ICS keeps its `EXDATE` so subscribed calendars stay correct.

The master page is your יא-2 Gist-backed calendar. The separate יא-1 page is
generated from the public class timetable using the supplied track selectors:
accelerated 5-point English, Physics with גיא שגיא, Computer Science with מן
שמרת, Physical Education with דולב מיכל, alternative Computer Science with
זכאי יצחק, and Cyber with לופו רועי משה, plus the shared subjects. The public
timetable exposes parallel groups, so it does not import other Physics,
Computer Science, Math, or English groups. The יא-1 page publishes only its
own scheduled-transit payload at
`https://epicori09-cmyk.github.io/shahaf-schedule-sync/ya1/wake.json`. It uses
the free Israeli Ministry of Transport GTFS feed, selects the latest route
that reaches Ostrovsky at least five minutes before the first confirmed יא-1
lesson, and calculates wake-up 75 minutes before leaving home. The page shows
the selected bus line, stops, walking legs, and scheduled times; it budgets at
least five minutes to walk from home to the first stop and considers earlier
departures when a later bus would not arrive safely. Its Shortcut
uses the separate `Shahaf Ya1 Wake` label. Scheduled transit data does not
predict live delays; the endpoint returns `leave` when route data is stale,
malformed, or no safe route is available. It cannot change the יא-2 Gist or
wake alarm.

## Screenshot timetable migration

The recurring timetable in the Gist was rebuilt from the supplied Shahaf
screenshots, including the moved teachers, periods, rooms, and gaps. The
migration keeps the existing special one-off records and date exclusions. To
inspect it without writing, run:

```powershell
$env:PYTHONPATH = 'src'
python scripts/migrate_photo_schedule.py --config config.json
```

The live migration is intentionally explicit; add `--write` only when you want
to patch the configured Gist. GitHub Gist history provides the rollback point.

## Alexa wake-up reminder

The optional Alexa integration is documented in [`alexa/README.md`](alexa/README.md).
It uses the public `site/data.json` schedule and a 75-minute preparation buffer.
The GitHub workflow updates Alexa only when `ALEXA_LWA_ACCESS_TOKEN` is present;
otherwise that step safely skips. Create the first managed reminder from the
Alexa skill before enabling the repository secret. Keep the existing iPhone
alarm until the Echo reminder has been tested.

## Local verification

```powershell
$env:PYTHONPATH = 'src'
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m shahaf_sync --dry-run
```

The dry run reads the live public source and Gist but does not call the Gist update endpoint.

## Free iPhone wake alarm

The Master יא-2 profile also publishes a safe wake payload at
`site/wake.json`. It contains the next valid school day, the first confirmed
lesson, and the wake time 75 minutes earlier. Stale or unavailable data sets a
fallback status and disables the payload so an iPhone Shortcut can leave the
existing alarm unchanged. The complete setup is in [`SHORTCUT.md`](SHORTCUT.md).
