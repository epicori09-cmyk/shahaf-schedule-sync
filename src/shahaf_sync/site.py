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
    if not value:
        return "Unknown"
    value = re.sub(r"^מעודכן ל:\s*", "Updated: ", value)
    return re.sub(r",\s*שעה:\s*", " · ", value)


def _kind_label(kind: str) -> tuple[str, str]:
    return {
        "cancelled": ("Cancelled", "cancelled"),
        "changed": ("Changed", "changed"),
        "added": ("Added", "added"),
    }.get(kind, (kind, "changed"))


def _teacher(event: IcsEvent) -> str:
    for line in event.description.splitlines():
        if line.strip().startswith("מורה:"):
            return line.split(":", 1)[1].strip()
    return ""


def build_schedule(calendar: Calendar, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Expand the reconciled ICS into browser-friendly local schedule data."""
    from datetime import datetime

    start = datetime.fromisoformat(f"{start_date}T00:00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59")
    items: list[dict[str, Any]] = []
    for event in calendar.events:
        for occurrence in event.occurrences(start, end):
            period = event.period
            if period is None:
                continue
            actual_end = occurrence + (event.end - event.start)
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

    status = (
        '<div class="status stale"><span class="status-dot"></span><span>Sync needs attention</span></div>'
        if stale
        else '<div class="status"><span class="status-dot"></span><span>Synced</span></div>'
    )
    if error:
        status += f'<details class="error"><summary>Error details</summary><pre>{escape(error)}</pre></details>'

    if changes:
        rows = []
        for item in changes:
            label, css_kind = _kind_label(item.kind)
            detail = item.detail or "Schedule update"
            rows.append(
                f'''<article class="change-row {css_kind}">
  <div class="change-date"><strong>{escape(_pretty_date(item.date.isoformat()))}</strong><span>Period {item.period}</span></div>
  <div class="change-body"><div><span class="change-label">{escape(label)}</span><h3>{escape(item.subject)}</h3></div><p>{escape(detail)}</p></div>
</article>'''
            )
        changes_html = f'''<section class="changes" aria-labelledby="changes-title"><div class="section-title"><h2 id="changes-title">Changes</h2><span>{len(changes)}</span></div><div class="change-list">{"".join(rows)}</div></section>'''
    else:
        changes_html = '''<section class="changes" aria-labelledby="changes-title"><div class="section-title"><h2 id="changes-title">Changes</h2><span>0</span></div><div class="quiet">No cancellations or updates in the next 21 days.</div></section>'''

    schedule_json = json.dumps(schedule_data, ensure_ascii=False).replace("</", "<\\/")
    schedule_available = "true" if schedule is not None else "false"
    sync_display = _pretty_timestamp(last_successful_sync or generated_at)
    html = f'''<!doctype html>
<html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f5f2ec">
<meta name="description" content="Your live Ostrovsky Grade 11-8 school schedule">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="My Schedule">
<meta name="last-successful-sync" content="{escape(last_successful_sync or generated_at)}">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" href="./icon.svg">
<title>{escape(title)}</title>
<style>
:root{{color-scheme:light;--paper:#f5f2ec;--card:#fffdfa;--ink:#172b36;--muted:#71808a;--line:#e5e1d9;--green:#148979;--green-soft:#dff1eb;--red:#c95e55;--red-soft:#fae8e4;--blue:#456dc5;--blue-soft:#e8edfb}}
*{{box-sizing:border-box}}html{{background:var(--paper)}}body{{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",sans-serif;line-height:1.4;-webkit-font-smoothing:antialiased;padding-bottom:env(safe-area-inset-bottom)}}
.app{{width:min(100% - 32px,600px);margin:0 auto;padding:max(22px,env(safe-area-inset-top)) 0 32px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:36px}}.identity{{display:flex;align-items:center;gap:11px;color:var(--ink);text-decoration:none}}.mark{{display:grid;place-items:center;width:42px;height:42px;border-radius:14px;background:var(--ink);color:#fff;font-weight:800;font-size:14px;letter-spacing:-.05em}}.identity strong{{display:block;font-size:15px;letter-spacing:-.02em}}.identity small{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.source{{color:var(--ink);text-decoration:none;border:1px solid var(--line);border-radius:50%;width:40px;height:40px;display:grid;place-items:center;font-size:19px;background:var(--card)}}
.status{{display:flex;align-items:center;gap:7px;color:var(--green);font-size:12px;font-weight:700;margin-bottom:13px}}.status-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}}.stale{{color:#9b5b22}}.stale .status-dot{{background:#d18b3e;box-shadow:0 0 0 4px #f7e6ca}}.error{{margin:-2px 0 20px;color:#9b413a;font-size:12px}}.error summary{{cursor:pointer;font-weight:700}}.error pre{{white-space:pre-wrap;background:var(--red-soft);border-radius:10px;padding:10px;margin-top:8px}}
.date-line{{color:var(--muted);font-size:14px;margin:0 0 5px}}h1,h2,h3,p{{margin-top:0}}h1{{font-size:clamp(35px,10vw,52px);line-height:1.02;letter-spacing:-.065em;margin:0 0 25px;font-weight:800}}.live-area{{margin-bottom:36px}}
.lesson-card{{position:relative;overflow:hidden;border-radius:22px;background:var(--ink);color:#fff;padding:22px 22px 20px;min-height:190px;box-shadow:0 14px 25px #172b3620}}.lesson-card::after{{content:"";position:absolute;width:175px;height:175px;border:1px solid #ffffff16;border-radius:50%;right:-65px;bottom:-115px;box-shadow:0 0 0 20px #ffffff08}}.lesson-kicker{{position:relative;z-index:1;color:#8fe1d4;font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}}.lesson-card h2{{position:relative;z-index:1;font-size:30px;line-height:1.05;letter-spacing:-.05em;margin:27px 0 7px;max-width:88%}}.lesson-detail{{position:relative;z-index:1;margin:0;color:#b9c9cf;font-size:14px;min-height:20px}}.lesson-time{{position:relative;z-index:1;display:block;margin-top:23px;font-size:18px;font-weight:700;letter-spacing:-.03em}}.lesson-time small{{color:#adc0c8;font-size:13px;font-weight:500}}.lesson-card.is-empty{{background:#e9eef0;color:var(--ink);box-shadow:none}}.lesson-card.is-empty::after{{border-color:#ffffff55;box-shadow:0 0 0 20px #ffffff33}}.lesson-card.is-empty .lesson-kicker{{color:var(--muted)}}.lesson-card.is-empty .lesson-detail,.lesson-card.is-empty .lesson-time small{{color:var(--muted)}}
.next-card{{margin-top:10px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:14px;padding:17px 20px;border:1px solid var(--line);background:var(--card);border-radius:18px}}.next-card .lesson-kicker{{color:var(--muted)}}.next-card h3{{font-size:21px;line-height:1.1;letter-spacing:-.04em;margin:7px 0 4px;max-width:230px}}.next-card .lesson-detail{{font-size:12px;color:var(--muted)}}.next-card .lesson-time{{margin:0;text-align:right;font-size:15px;color:var(--ink);white-space:nowrap}}.next-card .lesson-time small{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.section-title{{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}}.section-title h2{{font-size:22px;letter-spacing:-.04em;margin:0}}.section-title>span{{display:grid;place-items:center;min-width:25px;height:25px;padding:0 7px;border-radius:99px;background:#e5e1d9;color:var(--muted);font-size:12px;font-weight:800}}.change-list{{display:grid;gap:8px}}.change-row{{display:grid;grid-template-columns:78px 1fr;gap:13px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--green);border-radius:14px;padding:13px 14px}}.change-row.cancelled{{border-left-color:var(--red)}}.change-row.added{{border-left-color:var(--blue)}}.change-date strong{{display:block;font-size:14px;letter-spacing:-.03em}}.change-date span{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}.change-body{{min-width:0}}.change-body>div{{display:flex;align-items:center;gap:7px;min-width:0}}.change-label{{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}}.cancelled .change-label{{color:var(--red)}}.added .change-label{{color:var(--blue)}}.change-body h3{{font-size:15px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}}.change-body p{{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0 0}}.quiet{{border:1px dashed #d8d3c9;border-radius:14px;padding:15px;color:var(--muted);font-size:12px}}
.footer{{display:flex;justify-content:space-between;gap:16px;margin-top:36px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}}.footer a{{color:var(--ink);font-weight:700}}
@media (min-width:700px){{.app{{padding-top:55px}}.topbar{{margin-bottom:48px}}.live-area{{margin-bottom:50px}}.lesson-card{{min-height:225px;padding:28px}}.lesson-card h2{{font-size:38px}}.next-card{{padding:19px 22px}}}}
@media (max-width:420px){{.app{{width:calc(100% - 24px)}}.topbar{{margin-bottom:28px}}h1{{font-size:39px;margin-bottom:20px}}.lesson-card{{min-height:175px;padding:19px}}.lesson-card h2{{font-size:27px;margin-top:23px}}.next-card{{padding:15px 16px;grid-template-columns:1fr auto}}.next-card h3{{font-size:19px;max-width:205px}}.change-row{{grid-template-columns:70px 1fr;padding:12px}}}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style></head><body><main class="app">
<header class="topbar"><a class="identity" href="."><span class="mark">XI·8</span><span><strong>My schedule</strong><small>Ostrovsky High School</small></span></a><a class="source" href="{escape(source_url)}" target="_blank" rel="noreferrer" aria-label="Open Shahaf">↗</a></header>
<section class="live-area" aria-labelledby="today-title"><p id="today-label" class="date-line">Loading today’s schedule…</p>{status}<h1 id="today-title">Today’s schedule</h1><article class="lesson-card" id="current-lesson"><span class="lesson-kicker">Now</span><h2 id="current-subject">Checking…</h2><p id="current-detail" class="lesson-detail"></p><div id="current-time" class="lesson-time"></div></article><article class="next-card" id="next-lesson"><div><span class="lesson-kicker">Next up</span><h3 id="next-subject">Checking…</h3><p id="next-detail" class="lesson-detail"></p></div><div id="next-time" class="lesson-time"></div></article><p id="schedule-note" class="date-line" style="margin:10px 2px 0;font-size:12px"></p></section>
{changes_html}
<footer class="footer"><span>Last successful sync: {escape(sync_display)}</span><a href="{escape(source_url)}" target="_blank" rel="noreferrer">Open Shahaf ↗</a></footer>
</main><script>
const schedule = {schedule_json};
const scheduleAvailable = {schedule_available};
const scheduleZone = "Asia/Jerusalem";
const dateFormatter = new Intl.DateTimeFormat("en-US", {{ weekday: "long", month: "long", day: "numeric", timeZone: scheduleZone }});
function nowInSchoolZone() {{ const parts = new Intl.DateTimeFormat("en-CA", {{ timeZone: scheduleZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }}).formatToParts(new Date()); const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value])); return {{ date: `${{values.year}}-${{values.month}}-${{values.day}}`, minutes: Number(values.hour) * 60 + Number(values.minute) }}; }}
function minutes(value) {{ const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }}
function formatTime(value) {{ const [hour, minute] = value.split(":").map(Number); return `${{hour % 12 || 12}}:${{String(minute).padStart(2, "0")}} ${{hour >= 12 ? "PM" : "AM"}}`; }}
function detail(item) {{ return [item.teacher, item.room ? `Room ${{item.room}}` : "", `Period ${{item.period}}`].filter(Boolean).join(" · "); }}
function setLesson(id, item, emptyText, emptyDetail) {{ const card = document.getElementById(id); const subject = card.querySelector("h2, h3"); const detailTarget = card.querySelector(".lesson-detail"); const time = card.querySelector(".lesson-time"); card.classList.toggle("is-empty", !item); subject.textContent = item ? item.subject : emptyText; detailTarget.textContent = item ? detail(item) : emptyDetail; time.innerHTML = item ? `${{formatTime(item.start)}} <small>– ${{formatTime(item.end)}}</small>` : ""; }}
function refreshLiveLessons() {{ const now = nowInSchoolZone(); document.getElementById("today-label").textContent = dateFormatter.format(new Date()); if (!scheduleAvailable || !schedule.length) {{ setLesson("current-lesson", null, "Schedule unavailable", "The synced timetable is not available yet"); setLesson("next-lesson", null, "Try again later", "The live timetable will appear after the next successful sync"); return; }} const ordered = [...schedule].sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.period - b.period); const today = ordered.filter((item) => item.date === now.date); const current = today.find((item) => minutes(item.start) <= now.minutes && now.minutes < minutes(item.end)); const next = ordered.find((item) => item.date > now.date || (item.date === now.date && minutes(item.start) > now.minutes)); setLesson("current-lesson", current, "No class right now", today.length ? "You’re between lessons" : "No lessons scheduled today"); setLesson("next-lesson", next, "No more lessons", "Nothing else is scheduled in the synced timetable"); document.getElementById("schedule-note").textContent = current ? `You’re in Period ${{current.period}} now` : next ? `Next lesson: Period ${{next.period}}` : "You’re all done for the synced schedule"; }}
refreshLiveLessons(); setInterval(refreshLiveLessons, 30000); if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
</script></body></html>
'''
    (output_dir / "index.html").write_text(html, encoding="utf-8")
