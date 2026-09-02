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
4. Run **Shahaf schedule sync → Run workflow** once. The workflow then runs at 06:30 and 07:30 Israel time.

The workflow never prints the token. If the Gist is not a valid ICS file, Shahaf is unavailable, or the source page is incomplete, it publishes a stale/error banner and does not write the Gist.

The site has three swipeable views: **Now** shows the current and next lesson, **Full schedule** lets you choose a school day and see every Shahaf period (0–13), including free gaps, and **Exams** shows the selected subjects with a calendar alert four days before at 19:00. Changes are removed from the website only after the affected date and period have fully ended; the ICS keeps its `EXDATE` so subscribed calendars stay correct.

The hidden Settings view also contains the synced profile selector. The Master
profile is your יא-2 Gist-backed calendar. The additional יא-1 profile is
generated from the public class timetable using the confirmed track selectors:
Physics with גיא שגיא in room 308, Computer Science 2, and its Sunday
alternative-assessment lessons with רועי ויסברט. The public timetable exposes
parallel groups, so the selector deliberately does not import other Physics,
Computer Science, Math, or English groups. The selected profile is remembered
locally on the device; no passcode is stored in this public repository.

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
