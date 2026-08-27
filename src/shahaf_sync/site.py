from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re
from typing import Any

from .ics import Calendar, IcsEvent
from .reconcile import ChangeRecord


def _record_to_dict(record: ChangeRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "date": record.date.isoformat(),
        "period": record.period,
        "subject": record.subject,
        "detail": record.detail,
    }


def _pretty_date(value: str) -> str:
    """Return a compact Israeli date while keeping malformed input harmless."""
    try:
        year, month, day = value.split("-", 2)
        return f"{day}.{month}.{year}"
    except ValueError:
        return value


def _pretty_timestamp(value: str) -> str:
    if not value:
        return "Unknown"
    try:
        date_part, time_part = value.split("T", 1)
        return f"{_pretty_date(date_part)} · {time_part[:5]}"
    except ValueError:
        return value


def _pretty_source_updated(value: str) -> str:
    """Translate Shahaf's known Hebrew timestamp label for the English UI."""
    if not value:
        return "Unknown"
    value = re.sub(r"^מעודכן ל:\s*", "Updated: ", value)
    return re.sub(r",\s*שעה:\s*", " · ", value)


def _kind_label(kind: str) -> tuple[str, str, str]:
    return {
        "cancelled": ("Cancelled", "Cancellation", "cancelled"),
        "changed": ("Changed", "Schedule update", "changed"),
        "added": ("Added", "New lesson", "added"),
    }.get(kind, (kind, "Schedule update", "changed"))


def _teacher(event: IcsEvent) -> str:
    for line in event.description.splitlines():
        if line.strip().startswith("מורה:"):
            return line.split(":", 1)[1].strip()
    return ""


def build_schedule(calendar: Calendar, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Expand the already-reconciled ICS into browser-friendly local schedule data."""
    from datetime import datetime

    start = datetime.fromisoformat(f"{start_date}T00:00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59")
    items: list[dict[str, Any]] = []
    for event in calendar.events:
        for occurrence in event.occurrences(start, end):
            period = event.period
            if period is None:
                continue
            duration = event.end - event.start
            actual_end = occurrence + duration
            items.append({
                "date": occurrence.date().isoformat(),
                "period": period,
                "subject": event.subject,
                "teacher": _teacher(event),
                "room": event.location,
                "start": occurrence.strftime("%H:%M"),
                "end": actual_end.strftime("%H:%M"),
            })
    return sorted(items, key=lambda item: (item["date"], item["start"], item["period"], item["subject"]))


def render_site(
    output_dir: Path,
    *,
    title: str,
    generated_at: str,
    source_url: str,
    source_updated: str,
    changes: list[ChangeRecord],
    stale: bool,
    last_successful_sync: str = "",
    error: str = "",
    schedule: list[dict[str, Any]] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_data = schedule or []
    data = {
        "title": title,
        "generated_at": generated_at,
        "source_url": source_url,
        "source_updated": source_updated,
        "last_successful_sync": last_successful_sync,
        "stale": stale,
        "error": error,
        "changes": [_record_to_dict(item) for item in changes],
        "schedule": schedule_data,
        "schedule_available": schedule is not None,
    }
    (output_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if stale:
        banner = '<div class="status-banner stale"><span class="status-icon">!</span><div><strong>Data may be stale · sync needs attention</strong><span>Your calendar was not changed. The last saved information is shown.</span></div></div>'
    else:
        banner = '<div class="status-banner fresh"><span class="status-icon">✓</span><div><strong>Everything is synced</strong><span>The latest changes were checked successfully against Shahaf.</span></div></div>'
    if error:
        banner += f'<details class="error"><summary>Error details</summary><pre>{escape(error)}</pre></details>'
    if changes:
        cards = []
        for item in changes:
            label, sublabel, css_kind = _kind_label(item.kind)
            detail = item.detail or "A schedule update was published for this lesson"
            cards.append(
                f'''<article class="change-card {css_kind}">
  <div class="change-date"><span>{escape(_pretty_date(item.date.isoformat()))}</span><small>Period {item.period}</small></div>
  <div class="change-main"><div class="change-topline"><span class="change-kind">{escape(label)}</span><span class="change-subkind">{escape(sublabel)}</span></div>
  <h3>{escape(item.subject)}</h3><p>{escape(detail)}</p></div>
  <span class="change-arrow" aria-hidden="true">←</span>
</article>'''
            )
        changes_html = '<section class="changes-section" aria-labelledby="changes-title"><div class="section-heading"><div><p class="eyebrow">Next 21 days</p><h2 id="changes-title">What changed?</h2></div><span class="count-pill">{} updates</span></div><div class="change-list">{}</div></section>'.format(len(changes), "".join(cards))
    else:
        changes_html = '''<section class="empty-state" aria-label="No changes">
  <div class="empty-icon" aria-hidden="true">✓</div><div><p class="eyebrow">All clear</p><h2>No changes for now</h2><p>No cancellations or updates were found in the next 21 days.</p></div>
</section>'''
    count_label = "1 update" if len(changes) == 1 else f"{len(changes)} updates"
    sync_display = _pretty_timestamp(last_successful_sync or generated_at)
    source_display = _pretty_source_updated(source_updated)
    schedule_json = json.dumps(schedule_data, ensure_ascii=False).replace("</", "<\\/")
    schedule_available = "true" if schedule is not None else "false"
    lesson_section = '''<section class="lesson-section" aria-labelledby="lesson-title">
  <div class="section-heading lesson-heading"><div><p class="eyebrow">Live timetable</p><h2 id="lesson-title">Right now</h2><p id="today-label" class="today-label">Loading today’s schedule…</p></div><span class="live-pill"><span></span>Live</span></div>
  <div class="lesson-grid"><article class="lesson-card current" id="current-lesson"><span class="lesson-kicker">Now</span><div class="lesson-content"><h3 id="current-subject">Checking your schedule…</h3><p id="current-detail" class="lesson-detail"></p></div><div class="lesson-time" id="current-time"></div></article><article class="lesson-card next" id="next-lesson"><span class="lesson-kicker">Next up</span><div class="lesson-content"><h3 id="next-subject">Checking your schedule…</h3><p id="next-detail" class="lesson-detail"></p></div><div class="lesson-time" id="next-time"></div></article></div>
  <p id="schedule-note" class="schedule-note"></p>
</section>'''
    html = f"""<!doctype html>
<html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#10233f">
<meta name="description" content="Synced schedule changes for Ostrovsky Grade 11-8">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="My Schedule">
<meta name="last-successful-sync" content="{escape(last_successful_sync or generated_at)}">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" href="./icon.svg">
<title>{escape(title)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700;800&family=Rubik:wght@500;600;700&display=swap');
:root{{color-scheme:light;--ink:#10233f;--muted:#64748b;--line:#e6ebf2;--cream:#f7f8f5;--card:#ffffff;--teal:#0b8f82;--teal-soft:#e5f6f2;--coral:#e86d5c;--coral-soft:#fff0ec;--blue-soft:#eaf1ff;}}
*{{box-sizing:border-box}}html{{background:var(--cream)}}body{{margin:0;min-height:100vh;background:var(--cream);color:var(--ink);font-family:'Heebo',system-ui,sans-serif;line-height:1.5;padding-bottom:env(safe-area-inset-bottom)}}
body::before{{content:"";display:block;height:9px;background:linear-gradient(90deg,#0b8f82 0 28%,#f4b860 28% 51%,#e86d5c 51% 73%,#6c7df7 73%)}}
.shell{{width:min(1100px,calc(100% - 32px));margin:0 auto;padding:28px 0 54px}}
.topbar{{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:42px}}
.brand{{display:flex;align-items:center;gap:12px;color:inherit;text-decoration:none;font-weight:800;letter-spacing:-.02em}}
.brand-mark{{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:var(--ink);color:#fff;font-family:Rubik,sans-serif;font-size:18px;box-shadow:0 8px 18px #10233f22}}
.brand-copy{{display:flex;flex-direction:column;line-height:1.15}}.brand-copy small{{color:var(--muted);font-size:12px;font-weight:500;margin-top:4px}}
.source-link{{display:inline-flex;align-items:center;gap:8px;color:var(--ink);font-size:14px;font-weight:600;text-decoration:none;border:1px solid var(--line);background:#fff;padding:9px 14px;border-radius:999px;transition:.2s ease}}
.source-link:hover{{border-color:#b8c7d8;transform:translateY(-1px)}}.source-link span{{font-size:16px;color:var(--teal)}}
.hero{{display:grid;grid-template-columns:1.2fr .8fr;gap:28px;align-items:stretch;margin-bottom:26px}}
.hero-copy{{padding:14px 0 10px}}.eyebrow{{margin:0 0 8px;color:var(--teal);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}
h1,h2,h3,p{{margin-top:0}}h1{{font-family:Rubik,'Heebo',sans-serif;font-size:clamp(36px,5vw,62px);letter-spacing:-.06em;line-height:1.04;margin-bottom:17px;max-width:650px}}
.hero-copy>p:not(.eyebrow){{color:var(--muted);font-size:18px;max-width:540px;margin-bottom:24px}}
.hero-note{{display:flex;align-items:center;gap:9px;color:var(--muted);font-size:13px}}.pulse{{width:8px;height:8px;border-radius:50%;background:var(--teal);box-shadow:0 0 0 5px var(--teal-soft)}}
.hero-panel{{position:relative;overflow:hidden;background:var(--ink);color:#fff;border-radius:24px;padding:26px;min-height:215px;display:flex;flex-direction:column;justify-content:space-between;box-shadow:0 18px 40px #10233f24}}
.hero-panel::after{{content:"";position:absolute;width:190px;height:190px;border-radius:50%;border:1px solid #ffffff20;left:-55px;bottom:-100px;box-shadow:0 0 0 22px #ffffff09,0 0 0 44px #ffffff06}}
.panel-label{{color:#a9c8d0;font-size:13px;font-weight:600}}.panel-status{{display:flex;align-items:center;gap:12px;font-size:28px;font-family:Rubik,'Heebo',sans-serif;letter-spacing:-.04em;margin-top:9px}}.panel-status-icon{{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--teal);color:white;font-size:20px}}
.panel-meta{{position:relative;z-index:1;color:#b7c3d1;font-size:13px;margin:0}}.panel-meta strong{{color:#fff;font-size:16px;font-weight:600;display:block}}
.status-banner{{display:flex;align-items:center;gap:13px;border-radius:16px;padding:14px 17px;margin-bottom:26px;border:1px solid transparent}}.status-banner strong,.status-banner span{{display:block}}.status-banner strong{{font-size:15px}}.status-banner span:not(.status-icon){{font-size:13px;margin-top:2px;opacity:.8}}.status-icon{{display:grid;place-items:center;flex:0 0 31px;height:31px;border-radius:50%;font-weight:800}}
.fresh{{background:var(--teal-soft);color:#11665e;border-color:#ccece5}}.fresh .status-icon{{background:var(--teal);color:white}}.stale{{background:#fff4df;color:#85530c;border-color:#f3dcad}}.stale .status-icon{{background:#e9a93f;color:white}}
.error{{margin:-12px 0 26px;padding:12px 15px;border:1px solid #f2c5c0;border-radius:12px;background:#fff7f6;color:#9b4237;font-size:13px}}.error summary{{cursor:pointer;font-weight:700}}.error pre{{white-space:pre-wrap;margin:10px 0 0;font:12px/1.5 ui-monospace,monospace}}
.meta-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:45px}}.meta-card{{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:16px 17px;min-height:88px}}.meta-card .meta-label{{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}}.meta-card strong{{font-size:17px;font-weight:700;display:block}}.meta-card .meta-icon{{float:left;font-size:20px;color:var(--teal);margin-top:4px}}
.lesson-section{{margin-bottom:48px}}.lesson-heading{{margin-bottom:16px}}.today-label{{margin:3px 0 0;color:var(--muted);font-size:14px}}.live-pill{{display:inline-flex;align-items:center;gap:7px;border:1px solid #ccece5;color:#167268;background:var(--teal-soft);padding:7px 11px;border-radius:999px;font-size:12px;font-weight:800}}.live-pill span{{width:7px;height:7px;border-radius:50%;background:var(--teal);box-shadow:0 0 0 4px #ccece5}}
.lesson-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.lesson-card{{position:relative;display:flex;flex-direction:column;justify-content:space-between;min-height:154px;border-radius:19px;padding:20px;background:var(--card);border:1px solid var(--line);overflow:hidden}}.lesson-card::after{{content:"";position:absolute;width:120px;height:120px;border-radius:50%;right:-45px;bottom:-72px;background:var(--blue-soft)}}.lesson-card.current{{background:var(--ink);border-color:var(--ink);color:#fff;box-shadow:0 14px 28px #10233f1e}}.lesson-card.current::after{{background:#1c4160}}.lesson-kicker{{position:relative;z-index:1;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;color:var(--teal)}}.current .lesson-kicker{{color:#82ded3}}.lesson-content{{position:relative;z-index:1;margin-top:17px}}.lesson-card h3{{font-family:Rubik,'Heebo',sans-serif;font-size:24px;letter-spacing:-.04em;line-height:1.1;margin:0 0 5px;max-width:90%}}.lesson-detail{{color:var(--muted);font-size:13px;margin:0;min-height:20px}}.current .lesson-detail{{color:#b7c8d4}}.lesson-time{{position:relative;z-index:1;align-self:flex-end;margin-top:13px;font-size:16px;font-weight:800;letter-spacing:-.02em}}.lesson-time small{{font-size:12px;font-weight:500;color:var(--muted)}}.current .lesson-time small{{color:#b7c8d4}}.schedule-note{{margin:12px 2px 0;color:var(--muted);font-size:12px}}
.lesson-card.is-empty{{background:#f1f4f6;color:var(--ink);border-color:var(--line);box-shadow:none}}.lesson-card.is-empty::after{{background:#e4eaee}}.lesson-card.is-empty .lesson-kicker{{color:var(--muted)}}.lesson-card.is-empty .lesson-detail,.lesson-card.is-empty .lesson-time small{{color:var(--muted)}}
.section-heading{{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:15px}}h2{{font-family:Rubik,'Heebo',sans-serif;font-size:30px;letter-spacing:-.04em;margin-bottom:0}}.count-pill{{background:var(--ink);color:#fff;padding:7px 12px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}}
.change-list{{display:grid;gap:11px}}.change-card{{display:grid;grid-template-columns:120px 1fr 28px;align-items:center;gap:20px;background:var(--card);border:1px solid var(--line);border-right:4px solid var(--teal);border-radius:16px;padding:17px 19px;min-height:100px;transition:transform .2s ease,box-shadow .2s ease}}
.change-card:hover{{transform:translateY(-2px);box-shadow:0 10px 24px #10233f0e}}.change-card.cancelled{{border-right-color:var(--coral)}}.change-card.added{{border-right-color:#6c7df7}}
.change-date{{display:flex;flex-direction:column;gap:2px;color:var(--ink);font-weight:800;font-size:18px;letter-spacing:-.02em}}.change-date small{{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:0}}.change-main{{min-width:0}}.change-topline{{display:flex;align-items:center;gap:8px;margin-bottom:3px}}.change-kind{{font-size:11px;font-weight:800;padding:3px 8px;border-radius:999px;background:var(--teal-soft);color:#167268}}.cancelled .change-kind{{background:var(--coral-soft);color:#b84c3c}}.added .change-kind{{background:var(--blue-soft);color:#4d5ac5}}.change-subkind{{font-size:12px;color:var(--muted)}}.change-card h3{{font-size:20px;margin-bottom:0;letter-spacing:-.02em}}.change-card p{{font-size:13px;color:var(--muted);margin:1px 0 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.change-arrow{{font-size:22px;color:#a8b4c4;transition:transform .2s ease}}.change-card:hover .change-arrow{{transform:translateX(-4px);color:var(--teal)}}
.empty-state{{display:flex;align-items:center;gap:20px;padding:30px 28px;background:var(--card);border:1px solid var(--line);border-radius:20px}}.empty-icon{{display:grid;place-items:center;width:58px;height:58px;border-radius:18px;background:var(--teal-soft);color:var(--teal);font-size:29px;font-weight:800;flex:0 0 auto}}.empty-state h2{{font-size:26px;margin-bottom:3px}}.empty-state p:last-child{{color:var(--muted);margin-bottom:0;font-size:14px}}
.footer{{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:44px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}.footer a{{color:var(--ink);font-weight:700}}.ltr{{direction:ltr;unicode-bidi:embed}}
@media (max-width:700px){{.shell{{width:min(100% - 24px,520px);padding-top:max(20px,env(safe-area-inset-top));padding-bottom:calc(34px + env(safe-area-inset-bottom))}}.topbar{{margin-bottom:30px}}.brand-mark{{width:38px;height:38px;border-radius:11px}}.brand-copy{{font-size:14px}}.source-link{{font-size:0;width:42px;height:42px;justify-content:center;padding:0;flex:0 0 42px}}.source-link span{{font-size:18px}}.hero{{display:block}}.hero-copy{{padding:0;margin-bottom:22px}}h1{{font-size:42px}}.hero-copy>p:not(.eyebrow){{font-size:16px}}.hero-panel{{min-height:185px;border-radius:20px;padding:21px}}.panel-status{{font-size:24px}}.meta-grid{{grid-template-columns:1fr 1fr;margin-bottom:34px}}.meta-card:last-child{{grid-column:span 2}}.meta-card{{min-height:76px;padding:13px 14px}}.lesson-section{{margin-bottom:37px}}.lesson-grid{{grid-template-columns:1fr;gap:10px}}.lesson-card{{min-height:130px;padding:17px;border-radius:17px}}.lesson-card h3{{font-size:22px}}.section-heading{{align-items:center}}h2{{font-size:26px}}.change-card{{grid-template-columns:82px 1fr;gap:12px;padding:14px 14px;min-height:94px}}.change-arrow{{display:none}}.change-date{{font-size:15px}}.change-card h3{{font-size:18px}}.change-card p{{font-size:12px}}.footer{{display:block;line-height:1.8}}.footer span{{display:block}}.empty-state{{align-items:flex-start;padding:23px 18px;gap:14px}}.empty-icon{{width:48px;height:48px;border-radius:14px;font-size:23px}}}}
@media (prefers-reduced-motion:reduce){{*,*::before,*::after{{transition:none!important}}}}
</style></head><body><main>
<div class="shell"><header class="topbar"><a class="brand" href="."><span class="brand-mark">XI</span><span class="brand-copy">My schedule<small>Ostrovsky · Grade 11-8</small></span></a><a class="source-link" href="{escape(source_url)}" target="_blank" rel="noreferrer"><span>↗</span>Open Shahaf</a></header>
<section class="hero"><div class="hero-copy"><p class="eyebrow">Your school day</p><h1>Today’s<br>schedule.</h1><p>Current class, next class, and important changes — at a glance.</p><div class="hero-note"><span class="pulse"></span>Updates automatically</div></div><aside class="hero-panel"><div><span class="panel-label">Sync status</span><div class="panel-status"><span class="panel-status-icon">✓</span>{"Up to date" if not stale else "Check needed"}</div></div><p class="panel-meta">Last successful sync<strong>{escape(sync_display)}</strong></p></aside></section>
{banner}
{lesson_section}
<section class="meta-grid" aria-label="Schedule details"><div class="meta-card"><span class="meta-icon">↻</span><span class="meta-label">Last updated</span><strong>{escape(sync_display)}</strong></div><div class="meta-card"><span class="meta-icon">✦</span><span class="meta-label">Found</span><strong>{escape(count_label)}</strong></div><div class="meta-card"><span class="meta-icon">◷</span><span class="meta-label">Shahaf source update</span><strong>{escape(source_display)}</strong></div></section>
{changes_html}
<footer class="footer"><span>Generated {escape(_pretty_timestamp(generated_at))} · Checking 21 days</span><a href="{escape(source_url)}" target="_blank" rel="noreferrer">Open Shahaf ↗</a></footer></div>
</main><script>
const schedule = {schedule_json};
const scheduleAvailable = {schedule_available};
const scheduleZone = "Asia/Jerusalem";
const dateFormatter = new Intl.DateTimeFormat("en-US", {{ weekday: "long", month: "long", day: "numeric", timeZone: scheduleZone }});
const byStart = (a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.period - b.period;
function nowInSchoolZone() {{
  const parts = new Intl.DateTimeFormat("en-CA", {{ timeZone: scheduleZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }}).formatToParts(new Date());
  const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return {{ date: `${{values.year}}-${{values.month}}-${{values.day}}`, minutes: Number(values.hour) * 60 + Number(values.minute) }};
}}
function minutes(value) {{ const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }}
function formatTime(value) {{ const [hour, minute] = value.split(":").map(Number); const shownHour = hour % 12 || 12; return `${{shownHour}}:${{String(minute).padStart(2, "0")}} ${{hour >= 12 ? "PM" : "AM"}}`; }}
function detail(item) {{ return [item.teacher, item.room ? `Room ${{item.room}}` : "", `Period ${{item.period}}`].filter(Boolean).join(" · "); }}
function setLesson(id, item, emptyText, emptyDetail) {{
  const card = document.getElementById(id); const subject = card.querySelector("h3"); const detailTarget = card.querySelector(".lesson-detail"); const time = card.querySelector(".lesson-time");
  card.classList.toggle("is-empty", !item); subject.textContent = item ? item.subject : emptyText; detailTarget.textContent = item ? detail(item) : emptyDetail; time.innerHTML = item ? `${{formatTime(item.start)}} <small>– ${{formatTime(item.end)}}</small>` : "";
}}
function refreshLiveLessons() {{
  const now = nowInSchoolZone(); document.getElementById("today-label").textContent = dateFormatter.format(new Date());
  if (!scheduleAvailable || !schedule.length) {{ setLesson("current-lesson", null, "Schedule unavailable", "The synced timetable is not available yet"); setLesson("next-lesson", null, "Try again later", "The live timetable will appear after the next successful sync"); document.getElementById("schedule-note").textContent = ""; return; }}
  const ordered = [...schedule].sort(byStart); const today = ordered.filter((item) => item.date === now.date); const current = today.find((item) => minutes(item.start) <= now.minutes && now.minutes < minutes(item.end));
  const next = ordered.find((item) => item.date > now.date || (item.date === now.date && minutes(item.start) > now.minutes));
  setLesson("current-lesson", current, "No class right now", today.length ? "You’re between lessons" : "No lessons scheduled today");
  setLesson("next-lesson", next, "No more lessons", "Nothing else is scheduled in the synced timetable");
  document.getElementById("schedule-note").textContent = current ? `You’re in Period ${{current.period}} now` : next ? `Next lesson: Period ${{next.period}}` : "You’re all done for the synced schedule";
}}
refreshLiveLessons(); setInterval(refreshLiveLessons, 30000);
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
</script></body></html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")
