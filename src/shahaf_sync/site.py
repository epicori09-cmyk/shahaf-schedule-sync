from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .ics import Calendar, IcsEvent
from .model import PERIOD_TIMES
from .model import Exam
from .reconcile import ChangeRecord


def _record_to_dict(record: ChangeRecord) -> dict[str, Any]:
    if isinstance(record, dict):
        return {
            "kind": str(record.get("kind", "changed")),
            "date": str(record.get("date", "")),
            "period": int(record.get("period", 0)),
            "subject": str(record.get("subject", "Schedule update")),
            "detail": str(record.get("detail", "")),
        }
    return {
        "kind": record.kind,
        "date": record.date.isoformat(),
        "period": record.period,
        "subject": record.subject,
        "detail": record.detail,
    }


def _exam_to_dict(exam: Exam) -> dict[str, Any]:
    if isinstance(exam, dict):
        exam_date = str(exam.get("date", ""))
        try:
            reminder_date = (date.fromisoformat(exam_date) - timedelta(days=4)).isoformat()
        except ValueError:
            reminder_date = ""
        return {
            "date": exam_date,
            "subject": str(exam.get("subject", "")),
            "start_period": int(exam.get("start_period", 0)),
            "end_period": int(exam.get("end_period", 0)),
            "detail": str(exam.get("detail", "")),
            "group": str(exam.get("group", "")),
            "reminder_date": str(exam.get("reminder_date", "")) or reminder_date,
            "reminder_time": str(exam.get("reminder_time", "19:00")),
        }
    return {
        "date": exam.date.isoformat(),
        "subject": exam.subject,
        "start_period": exam.start_period,
        "end_period": exam.end_period,
        "detail": exam.detail,
        "group": exam.group,
        "reminder_date": (exam.date - timedelta(days=4)).isoformat(),
        "reminder_time": "19:00",
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


def _change_is_past(change: ChangeRecord, now: datetime | None) -> bool:
    """Hide a change only after that date's actual period has ended."""
    if now is None:
        return False
    if change.date < now.date():
        return True
    if change.date > now.date():
        return False
    period_times = PERIOD_TIMES.get(change.period)
    if period_times is None:
        return False
    return now.time().replace(tzinfo=None) >= period_times[1]


def _schedule_item(event: IcsEvent, occurrence: datetime) -> dict[str, Any]:
    actual_end = occurrence + (event.end - event.start)
    period = event.period
    if period is None:
        raise ValueError(f"Event {event.uid!r} has no Shahaf period")
    return {
        "date": occurrence.date().isoformat(),
        "period": period,
        "subject": event.subject,
        "teacher": _teacher(event),
        "room": event.location,
        "start": occurrence.strftime("%H:%M"),
        "end": actual_end.strftime("%H:%M"),
    }


def build_schedule(calendar: Calendar, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Expand the reconciled ICS into browser-friendly local schedule data.

    RFC 5545 recurrence overrides replace their matching base occurrence. The
    parser keeps both records, so this expansion resolves that relationship
    before sending data to the website.
    """
    start = datetime.fromisoformat(f"{start_date}T00:00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59")
    override_keys = {
        (event.uid, event.recurrence_id)
        for event in calendar.events
        if event.recurrence_id is not None
    }
    items: list[dict[str, Any]] = []

    for event in calendar.events:
        if event.recurrence_id is not None:
            continue
        for occurrence in event.occurrences(start, end):
            if (event.uid, occurrence) in override_keys:
                continue
            if event.period is None:
                continue
            items.append(_schedule_item(event, occurrence))

    for event in calendar.events:
        if event.recurrence_id is None or not (start <= event.start <= end):
            continue
        if event.period is None:
            continue
        items.append(_schedule_item(event, event.start))

    return sorted(items, key=lambda item: (item["date"], item["start"], item["period"], item["subject"]))


def build_day_slots(schedule: list[dict[str, Any]], target_date: date) -> list[dict[str, Any]]:
    """Return every Shahaf period for one date, including empty periods."""
    by_period = {
        item["period"]: item
        for item in schedule
        if item.get("date") == target_date.isoformat()
    }
    return [
        {
            "period": period,
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "lesson": by_period.get(period),
        }
        for period, (start, end) in PERIOD_TIMES.items()
    ]


def _period_metadata() -> list[dict[str, Any]]:
    return [
        {"period": period, "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
        for period, (start, end) in PERIOD_TIMES.items()
    ]


def build_wake_data(
    schedule: list[dict[str, Any]] | None,
    *,
    schedule_available: bool,
    stale: bool,
    now: datetime | None = None,
    alarm_safety: str | None = None,
    alarm_safety_reason: str = "",
) -> dict[str, Any]:
    """Build the safe, master-profile-only input for the iPhone Shortcut."""

    base: dict[str, Any] = {
        "next_school_day": None,
        "wake_time": None,
        "wake_at": None,
        "subject": None,
        "enabled": False,
        "alarm_for_today": False,
        "stale": stale,
        "fallback_status": "none",
        # A text-only instruction for the iPhone Shortcut.  Text comparisons
        # are substantially less error-prone in the Shortcuts editor than
        # Boolean magic variables.
        "shortcut_action": "leave",
        "alarm_safety": alarm_safety or "not-reviewed",
        "alarm_safety_reason": alarm_safety_reason,
        "timezone": "Asia/Jerusalem",
    }
    if stale:
        base["fallback_status"] = "stale"
        return base
    if not schedule_available or schedule is None:
        base["stale"] = True
        base["fallback_status"] = "unavailable"
        return base

    zone = ZoneInfo("Asia/Jerusalem")
    current = now or datetime.now(zone)
    current = current.astimezone(zone) if current.tzinfo else current.replace(tzinfo=zone)
    today = current.date()
    by_date: dict[date, list[dict[str, Any]]] = {}
    for item in schedule:
        try:
            item_date = date.fromisoformat(str(item["date"]))
            time.fromisoformat(str(item["start"]))
        except (KeyError, TypeError, ValueError):
            continue
        if item_date >= today:
            by_date.setdefault(item_date, []).append(item)

    for school_day in sorted(by_date):
        first = min(by_date[school_day], key=lambda item: (item["start"], item.get("period", 0)))
        first_start = time.fromisoformat(str(first["start"]))
        wake_naive = datetime.combine(school_day, first_start) - timedelta(minutes=75)
        wake_local = wake_naive.replace(tzinfo=zone)
        if school_day == today and wake_local <= current:
            continue
        base.update(
            {
                "next_school_day": school_day.isoformat(),
                "wake_time": wake_local.strftime("%H:%M"),
                "wake_at": wake_local.isoformat(),
                "subject": str(first.get("subject", "")),
                "enabled": True,
                "alarm_for_today": school_day == today,
                # The Shortcut runs before school and may need to create an
                # alarm for tomorrow (for example on a no-school day today).
                "shortcut_action": "set",
            }
        )
        if alarm_safety not in (None, "approved", "not-required"):
            # The AI is a deletion/replacement gate. Any missing, failed, or
            # ambiguous review preserves the current labeled alarm.
            base["shortcut_action"] = "leave"
        return base

    base["fallback_status"] = "no-lessons"
    base["shortcut_action"] = "clear"
    if alarm_safety not in (None, "approved", "not-required"):
        base["shortcut_action"] = "leave"
    return base


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
    exams: list[Exam] | None = None,
    now: datetime | None = None,
    alarm_safety: str | None = None,
    alarm_safety_reason: str = "",
    profile_id: str = "master",
    profile_label: str = "Master profile — יא-2",
    profile_mark: str = "XI·2",
    profile_class_id: str = "11",
    publish_wake: bool = True,
    transit_wake: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_data = schedule or []
    visible_changes = [item for item in changes if not _change_is_past(item, now)]
    periods = _period_metadata()
    exams_data = [_exam_to_dict(item) for item in (exams or [])]
    primary_profile = {
        "id": profile_id,
        "label": profile_label,
        "mark": profile_mark,
        "class_id": profile_class_id,
        "schedule": schedule_data,
        "schedule_available": schedule is not None,
        "changes": [_record_to_dict(item) for item in changes],
        "exams": exams_data,
        "exams_available": exams is not None,
        "source_url": source_url,
        "source_updated": source_updated,
        "last_successful_sync": last_successful_sync,
        "stale": stale,
        "error": error,
        "generated_at": generated_at,
        "transit_wake": transit_wake if profile_id == "ya1" else None,
    }
    data = {
        "id": profile_id,
        "label": profile_label,
        "mark": profile_mark,
        "class_id": profile_class_id,
        "title": title,
        "generated_at": generated_at,
        "source_url": source_url,
        "source_updated": source_updated,
        "last_successful_sync": last_successful_sync,
        "stale": stale,
        "error": error,
        "changes": [_record_to_dict(item) for item in visible_changes],
        "schedule": schedule_data,
        "schedule_available": schedule is not None,
        "periods": periods,
        "exams": exams_data,
        "exams_available": exams is not None,
    }
    if publish_wake:
        wake_data = build_wake_data(
            schedule_data,
            schedule_available=schedule is not None,
            stale=stale,
            now=now,
            alarm_safety=alarm_safety,
            alarm_safety_reason=alarm_safety_reason,
        )
        data["wake"] = wake_data
    if transit_wake is not None:
        data["transit_wake"] = transit_wake
    (output_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if publish_wake:
        (output_dir / "wake.json").write_text(
            json.dumps(wake_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    elif transit_wake is not None:
        (output_dir / "wake.json").write_text(
            json.dumps(transit_wake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    status = (
        '<div id="sync-status" class="status stale"><span class="status-dot"></span><span>Sync needs attention</span></div>'
        if stale
        else '<div id="sync-status" class="status"><span class="status-dot"></span><span>Synced</span></div>'
    )
    if error:
        status += f'<details class="error"><summary>Error details</summary><pre>{escape(error)}</pre></details>'

    changes_html = '''<section class="changes" id="changes-view" aria-labelledby="changes-title"><div class="section-title"><h2 id="changes-title">Changes</h2><span id="changes-count">0</span></div><div class="change-list" id="change-list"></div></section>'''

    transit_html = '''<section class="transit-wake-card" id="transit-wake-card" aria-labelledby="transit-title"><div class="section-title"><h2 id="transit-title">Bus plan</h2><span id="transit-status">Checking</span></div><div id="transit-summary" class="transit-summary">Checking the safest scheduled route…</div><div id="transit-legs" class="transit-legs"></div><p class="transit-note">Earlier buses were considered; this is the latest scheduled departure that still arrives safely.</p><a id="transit-map" class="transit-map" href="#" target="_blank" rel="noreferrer">Verify route in Google Maps ↗</a></section>''' if profile_id == "ya1" else ""

    gate_html = '''<section id="site-access-gate" class="site-access-gate" aria-labelledby="gate-title"><div class="gate-card"><p class="eyebrow">Private page</p><h1 id="gate-title">Enter Ya1 schedule</h1><p>Type the access phrase to continue.</p><form id="gate-form"><label for="gate-phrase">Access phrase</label><input id="gate-phrase" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" dir="auto" required><button type="submit">Enter</button><p id="gate-error" role="alert" aria-live="polite"></p></form></div></section>''' if profile_id == "ya1" else ""
    gate_css = '''.site-locked .app{display:none}.site-access-gate{display:grid;place-items:center;min-height:100vh;padding:24px}.gate-card{width:min(100%,420px);padding:25px 22px;border:1px solid var(--line);border-radius:22px;background:var(--card);box-shadow:var(--shadow)}.gate-card h1{font-size:34px;margin:8px 0}.gate-card>p:not(.eyebrow){color:var(--muted);font-size:14px}.gate-card label{display:block;margin:20px 0 7px;font-size:12px;font-weight:750}.gate-card input{width:100%;height:47px;padding:0 13px;border:1px solid var(--line);border-radius:12px;background:var(--paper);color:var(--ink);font:inherit}.gate-card button{width:100%;height:47px;margin-top:11px;border:0;border-radius:12px;background:var(--ink);color:#fff;font:inherit;font-weight:800;cursor:pointer}.gate-card #gate-error{min-height:18px;margin:9px 0 0;color:var(--red);font-size:12px}''' if profile_id == "ya1" else ""
    gate_script = '''<script>(()=>{const expected="אורי המלך";const key="shahaf-ya1-access";const body=document.body;const gate=document.getElementById("site-access-gate");const form=document.getElementById("gate-form");const input=document.getElementById("gate-phrase");const error=document.getElementById("gate-error");const unlock=()=>{body.classList.remove("site-locked");gate.hidden=true;try{localStorage.setItem(key,"granted")}catch(_error){}};try{if(localStorage.getItem(key)==="granted")unlock()}catch(_error){}form.addEventListener("submit",(event)=>{event.preventDefault();if(input.value.trim()===expected)unlock();else{error.textContent="That phrase is not correct.";input.select()}});if(!gate.hidden)input.focus()})();</script>''' if profile_id == "ya1" else ""

    exams_html = '''<section class="exams" id="exams-view" aria-labelledby="exams-title" hidden><div class="section-title"><h2 id="exams-title">Exams</h2><span id="exams-count">0</span></div><div class="exam-list" id="exam-list"></div></section>'''

    schedule_json = json.dumps(schedule_data, ensure_ascii=False).replace("</", "<\\/")
    periods_json = json.dumps(periods, ensure_ascii=False)
    primary_profile_json = json.dumps(primary_profile, ensure_ascii=False).replace("</", "<\\/")
    schedule_available = "true" if schedule is not None else "false"
    sync_display = _pretty_timestamp(last_successful_sync or generated_at)
    theme_class = "theme-pink" if profile_id == "ya1" else "theme-green"
    html = f'''<!doctype html>
<html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f4f6f3">
<meta name="description" content="{escape(title)}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="My Schedule">
<meta name="last-successful-sync" content="{escape(last_successful_sync or generated_at)}">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" href="./icon.svg">
<title>{escape(title)}</title>
<style>
:root{{color-scheme:light;--paper:#f4f6f3;--card:#ffffff;--ink:#142b35;--muted:#71818a;--line:#dfe7e4;--green:#0c806d;--green-soft:#d9f0e9;--red:#c85652;--red-soft:#fae6e4;--blue:#3869bd;--shadow:0 14px 35px #142b3512}}
*{{box-sizing:border-box}}html{{background:var(--paper);overscroll-behavior-x:none}}body{{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",sans-serif;line-height:1.4;-webkit-font-smoothing:antialiased;padding-bottom:env(safe-area-inset-bottom)}}
.app{{width:calc(100% - 28px);max-width:620px;margin:0 auto;padding:max(18px,env(safe-area-inset-top)) 0 34px;touch-action:pan-y}}
.app{{contain:layout style}}body:not(.app-ready) #current-subject,body:not(.app-ready) #next-subject{{color:transparent;position:relative}}body:not(.app-ready) #current-subject::after,body:not(.app-ready) #next-subject::after{{content:"";display:block;width:68%;height:1em;border-radius:8px;background:linear-gradient(100deg,#ffffff14 20%,#ffffff32 38%,#ffffff14 56%);background-size:220% 100%;animation:skeleton-shimmer 1.25s linear infinite}}body:not(.app-ready) #next-subject::after{{width:78%;background:linear-gradient(100deg,#e4ecea 20%,#f7faf8 38%,#e4ecea 56%);background-size:220% 100%}}@keyframes skeleton-shimmer{{to{{background-position:-220% 0}}}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}}.identity{{display:flex;align-items:center;gap:11px;color:var(--ink);text-decoration:none}}.mark{{display:grid;place-items:center;width:43px;height:43px;border-radius:14px;background:var(--ink);color:#fff;font-weight:800;font-size:14px;letter-spacing:-.05em}}.identity strong{{display:block;font-size:15px;letter-spacing:-.02em}}.identity small{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.source{{color:var(--ink);text-decoration:none;border:1px solid var(--line);border-radius:50%;width:40px;height:40px;display:grid;place-items:center;font-size:19px;background:var(--card)}}
.view-switch{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;padding:4px;margin-bottom:27px;border:1px solid var(--line);border-radius:14px;background:#eaf0ed}}.view-switch button,.small-button,.day-chip{{font:inherit;border:0;cursor:pointer}}.view-switch button{{min-height:38px;border-radius:10px;background:transparent;color:var(--muted);font-size:13px;font-weight:750}}.view-switch button.is-active{{background:var(--card);color:var(--ink);box-shadow:0 2px 7px #142b3512}}button:focus-visible,.source:focus-visible,.identity:focus-visible{{outline:3px solid #8ecdc0;outline-offset:2px}}
.status{{display:flex;align-items:center;gap:7px;color:var(--green);font-size:12px;font-weight:750;margin-bottom:11px}}.status-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}}.stale{{color:#9b5b22}}.stale .status-dot{{background:#d18b3e;box-shadow:0 0 0 4px #f7e6ca}}.error{{margin:-2px 0 18px;color:#9b413a;font-size:12px}}.error summary{{cursor:pointer;font-weight:700}}.error pre{{white-space:pre-wrap;background:var(--red-soft);border-radius:10px;padding:10px;margin-top:8px}}
.date-line{{color:var(--muted);font-size:14px;margin:0 0 5px}}h1,h2,h3,p{{margin-top:0}}h1{{font-size:clamp(35px,10vw,52px);line-height:1.02;letter-spacing:-.065em;margin:0 0 22px;font-weight:800}}.live-area{{margin-bottom:31px}}
.lesson-card{{position:relative;overflow:hidden;border-radius:22px;background:var(--ink);color:#fff;padding:21px 21px 19px;min-height:185px;box-shadow:var(--shadow)}}.lesson-card::after{{content:"";position:absolute;width:175px;height:175px;border:1px solid #ffffff16;border-radius:50%;right:-65px;bottom:-115px;box-shadow:0 0 0 20px #ffffff08}}.lesson-kicker{{position:relative;z-index:1;color:#8fe1d4;font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}}.lesson-card h2{{position:relative;z-index:1;font-size:29px;line-height:1.05;letter-spacing:-.05em;margin:25px 0 7px;max-width:88%}}.lesson-detail{{position:relative;z-index:1;margin:0;color:#b9c9cf;font-size:14px;min-height:20px}}.lesson-time{{position:relative;z-index:1;display:block;margin-top:22px;font-size:18px;font-weight:750;letter-spacing:-.03em}}.lesson-time small{{color:#adc0c8;font-size:13px;font-weight:500}}.lesson-card.is-empty{{background:#e4eceb;color:var(--ink);box-shadow:none}}.lesson-card.is-empty::after{{border-color:#ffffff55;box-shadow:0 0 0 20px #ffffff33}}.lesson-card.is-empty .lesson-kicker{{color:var(--muted)}}.lesson-card.is-empty .lesson-detail,.lesson-card.is-empty .lesson-time small{{color:var(--muted)}}
.next-card{{margin-top:10px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:14px;padding:16px 18px;border:1px solid var(--line);background:var(--card);border-radius:17px}}.next-card .lesson-kicker{{color:var(--muted)}}.next-card h3{{font-size:20px;line-height:1.1;letter-spacing:-.04em;margin:7px 0 4px;max-width:235px}}.next-card .lesson-detail{{font-size:12px;color:var(--muted)}}.next-card .lesson-time{{margin:0;text-align:right;font-size:15px;color:var(--ink);white-space:nowrap}}.next-card .lesson-time small{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.transit-wake-card{{margin:18px 0 29px;padding:17px 18px;border:1px solid var(--line);border-radius:18px;background:var(--card);box-shadow:0 5px 16px #38263308}}.transit-wake-card .section-title{{margin-bottom:8px}}.transit-wake-card .section-title h2{{font-size:21px}}.transit-wake-card .section-title span{{min-width:auto;background:var(--green-soft);color:var(--green);font-size:10px;text-transform:uppercase;letter-spacing:.05em}}.transit-summary{{font-size:14px;font-weight:750;line-height:1.35}}.transit-legs{{display:grid;gap:7px;margin-top:12px}}.transit-leg{{display:grid;grid-template-columns:62px 1fr;gap:9px;padding:9px 10px;border-radius:11px;background:var(--paper);font-size:12px}}.transit-leg strong{{font-size:12px}}.transit-leg span{{display:block;color:var(--muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.transit-note{{margin:11px 0 0;color:var(--muted);font-size:11px;line-height:1.35}}.transit-map{{display:inline-block;margin-top:10px;color:var(--ink);font-size:11px;font-weight:750;text-decoration:none}}.transit-wake-card.is-warning{{background:#fffaf2;border-color:#f0dfc3}}.transit-wake-card.is-warning .section-title span{{background:#f8e8c9;color:#a96b24}}
.section-title{{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}}.section-title h2{{font-size:22px;letter-spacing:-.04em;margin:0}}.section-title>span{{display:grid;place-items:center;min-width:25px;height:25px;padding:0 7px;border-radius:99px;background:#e2e9e6;color:var(--muted);font-size:12px;font-weight:800}}.change-list{{display:grid;gap:8px}}.change-row{{display:grid;grid-template-columns:78px 1fr;gap:13px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--green);border-radius:14px;padding:13px 14px}}.change-row.cancelled{{border-left-color:var(--red)}}.change-row.added{{border-left-color:var(--blue)}}.change-date strong{{display:block;font-size:14px;letter-spacing:-.03em}}.change-date span{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}.change-body{{min-width:0}}.change-body>div{{display:flex;align-items:center;gap:7px;min-width:0}}.change-label{{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}}.cancelled .change-label{{color:var(--red)}}.added .change-label{{color:var(--blue)}}.change-body h3{{font-size:15px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}}.change-body p{{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0 0}}.quiet{{border:1px dashed #cfdad6;border-radius:14px;padding:15px;color:var(--muted);font-size:12px}}
.section-title{{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}}.section-title h2{{font-size:22px;letter-spacing:-.04em;margin:0}}.section-title>span{{display:grid;place-items:center;min-width:25px;height:25px;padding:0 7px;border-radius:99px;background:#e2e9e6;color:var(--muted);font-size:12px;font-weight:800}}.change-list,.exam-list{{display:grid;gap:8px}}.change-row,.exam-row{{display:grid;grid-template-columns:78px 1fr;gap:13px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--green);border-radius:14px;padding:13px 14px}}.change-row.cancelled{{border-left-color:var(--red)}}.change-row.added{{border-left-color:var(--blue)}}.exam-row{{border-left-color:#d08c3f}}.change-date strong,.exam-date strong{{display:block;font-size:14px;letter-spacing:-.03em}}.change-date span,.exam-date span{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}.change-body,.exam-body{{min-width:0}}.change-body>div{{display:flex;align-items:center;gap:7px;min-width:0}}.change-label{{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}}.cancelled .change-label{{color:var(--red)}}.added .change-label{{color:var(--blue)}}.change-body h3,.exam-body h3{{font-size:15px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}}.change-body p,.exam-body p{{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0 0}}.quiet{{border:1px dashed #cfdad6;border-radius:14px;padding:15px;color:var(--muted);font-size:12px}}
.full-schedule{{margin-bottom:25px}}.schedule-heading{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:16px}}.eyebrow{{margin:0 0 4px;color:var(--green);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}.schedule-heading h2{{margin:0;font-size:31px;line-height:1.05;letter-spacing:-.06em}}.small-button{{padding:9px 12px;border:1px solid var(--line);border-radius:11px;background:var(--card);color:var(--ink);font-size:12px;font-weight:750;white-space:nowrap}}.day-picker{{display:flex;gap:7px;overflow-x:auto;padding:2px 2px 9px;margin:0 -2px 13px;scrollbar-width:none}}.day-picker::-webkit-scrollbar{{display:none}}.day-chip{{flex:0 0 auto;padding:9px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap}}.day-chip.is-selected{{background:var(--ink);border-color:var(--ink);color:#fff}}.selected-day{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}}.selected-day h3{{margin:0;font-size:21px;letter-spacing:-.04em}}.selected-day p{{margin:3px 0 0;color:var(--muted);font-size:12px}}.period-list{{display:grid;gap:6px}}.period-row{{display:grid;grid-template-columns:1fr 78px;min-height:68px;overflow:hidden;border:1px solid var(--line);border-radius:13px;background:var(--card);box-shadow:0 3px 8px #142b3507}}.period-main{{position:relative;display:flex;flex-direction:column;justify-content:center;min-width:0;padding:11px 14px 11px 18px;border-left:5px solid var(--slot-accent,#cbd6d2)}}.period-row.is-gap .period-main{{border-left-color:#d6dfdc}}.period-main strong{{font-size:16px;line-height:1.12;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.period-main span{{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.gap-label{{font-size:13px!important;font-weight:700;color:#8a979c!important}}.gap-sub{{margin-top:2px}}.period-info{{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;padding:9px 13px 9px 5px;border-left:1px solid var(--line);text-align:right}}.period-info strong{{font-size:24px;line-height:1;font-weight:800;letter-spacing:-.05em}}.period-info span{{margin-top:5px;color:var(--muted);font-size:11px;line-height:1.2;white-space:nowrap}}.empty-day{{border:1px dashed #cfdad6;border-radius:14px;padding:18px;color:var(--muted);font-size:13px}}
 .footer{{display:flex;justify-content:space-between;gap:16px;margin-top:31px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}}.footer a{{color:var(--ink);font-weight:700}}
.theme-pink{{--paper:#fff8fb;--card:#ffffff;--ink:#382633;--muted:#8d7480;--line:#efdde7;--green:#c14d80;--green-soft:#f9dce8;--red:#bd536f;--red-soft:#fbe6ed;--blue:#aa5b9d;--shadow:0 14px 35px #38263312}}.theme-pink .mark,.theme-pink .lesson-card{{background:#382633}}.theme-pink .lesson-kicker{{color:#f3a7c6}}.theme-pink .view-switch{{background:#f9eaf1}}
@media (min-width:700px){{.app{{padding-top:48px}}.topbar{{margin-bottom:30px}}.lesson-card{{min-height:220px;padding:28px}}.lesson-card h2{{font-size:38px}}.next-card{{padding:19px 22px}}}}
@media (max-width:420px){{.app{{width:calc(100% - 24px)}}h1{{font-size:39px;margin-bottom:19px}}.lesson-card{{min-height:173px;padding:19px}}.lesson-card h2{{font-size:27px;margin-top:22px}}.next-card{{padding:15px 16px}}.next-card h3{{font-size:19px;max-width:205px}}.change-row{{grid-template-columns:70px 1fr;padding:12px}}.period-row{{grid-template-columns:1fr 72px}}.period-main{{padding-left:14px}}.period-info{{padding-right:11px}}}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
{gate_css}
</style></head><body class="{theme_class}{' site-locked' if profile_id == 'ya1' else ''}">{gate_html}<main class="app">
<header class="topbar"><a class="identity" href="."><span class="mark">{escape(profile_mark)}</span><span><strong>My schedule</strong><small>{escape(profile_label)}</small></span></a><a class="source" id="source-link" href="{escape(source_url)}" target="_blank" rel="noreferrer" aria-label="Open Shahaf">↗</a></header>
<nav class="view-switch" aria-label="Schedule views"><button id="now-tab" class="is-active" type="button" aria-selected="true">Now</button><button id="full-tab" type="button" aria-selected="false">Full schedule</button><button id="exams-tab" type="button" aria-selected="false">Exams</button></nav>
<section id="now-view" class="live-area" aria-labelledby="today-title"><p id="today-label" class="date-line">Loading today’s schedule…</p>{status}<h1 id="today-title">Today’s schedule</h1><article class="lesson-card" id="current-lesson"><span class="lesson-kicker">Now</span><h2 id="current-subject">Checking…</h2><p id="current-detail" class="lesson-detail"></p><div id="current-time" class="lesson-time"></div></article><article class="next-card" id="next-lesson"><div><span class="lesson-kicker">Next up</span><h3 id="next-subject">Checking…</h3><p id="next-detail" class="lesson-detail"></p></div><div id="next-time" class="lesson-time"></div></article><p id="schedule-note" class="date-line" style="margin:10px 2px 0;font-size:12px"></p>{transit_html}</section>
<section id="full-view" class="full-schedule" hidden aria-labelledby="full-title"><div class="schedule-heading"><div><p class="eyebrow">Every period</p><h2 id="full-title">Full schedule</h2></div><button id="back-to-now" class="small-button" type="button">Back to now</button></div><div id="day-picker" class="day-picker" role="listbox" aria-label="Choose a school day"></div><div class="selected-day"><div><h3 id="selected-day-title">Loading…</h3><p id="selected-day-summary"></p></div><button id="jump-today" class="small-button" type="button">Today</button></div><div id="schedule-periods" class="period-list"></div></section>
{exams_html}
{changes_html}
<footer class="footer"><span>Last successful sync: <span id="last-sync">{escape(sync_display)}</span></span><a id="footer-source-link" href="{escape(source_url)}" target="_blank" rel="noreferrer">Open Shahaf ↗</a></footer>
</main><script>
{gate_script}
const activeProfile = {primary_profile_json};
const periods = {periods_json};
const scheduleZone = "Asia/Jerusalem";
const dateFormatter = new Intl.DateTimeFormat("en-US", {{ weekday: "long", month: "long", day: "numeric", timeZone: scheduleZone }});
const shortDateFormatter = new Intl.DateTimeFormat("en-US", {{ weekday: "short", month: "short", day: "numeric", timeZone: scheduleZone }});
const palette = ["#d16d8e", "#78c8cb", "#f0bd47", "#76c983", "#8796df", "#d88a54"];
let schedule = activeProfile.schedule || [];
let scheduleAvailable = Boolean(activeProfile.schedule_available);
let changes = activeProfile.changes || [];
let exams = activeProfile.exams || [];
const transitWake = activeProfile.transit_wake || null;
function nowInSchoolZone() {{ const parts = new Intl.DateTimeFormat("en-CA", {{ timeZone: scheduleZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }}).formatToParts(new Date()); const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value])); return {{ date: `${{values.year}}-${{values.month}}-${{values.day}}`, minutes: Number(values.hour) * 60 + Number(values.minute) }}; }}
function minutes(value) {{ const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }}
function formatTime(value) {{ const [hour, minute] = value.split(":").map(Number); return `${{hour % 12 || 12}}:${{String(minute).padStart(2, "0")}} ${{hour >= 12 ? "PM" : "AM"}}`; }}
function escapeHtml(value) {{ return String(value ?? "").replace(/[&<>]/g, (char) => ({{"&":"&amp;","<":"&lt;",">":"&gt;"}}[char])).replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }}
function detail(item) {{ return [item.teacher, item.room ? `Room ${{item.room}}` : "", `Period ${{item.period}}`].filter(Boolean).join(" · "); }}
function renderTransitWake() {{ if (!transitWake) return; const card = document.getElementById("transit-wake-card"); const summary = document.getElementById("transit-summary"); const legs = document.getElementById("transit-legs"); const status = document.getElementById("transit-status"); const map = document.getElementById("transit-map"); if (!card || !summary || !legs || !status || !map) return; map.href = transitWake.google_maps_url || "#"; const action = transitWake.shortcut_action; card.classList.toggle("is-warning", action !== "set"); if (action === "set" && transitWake.route_departure && transitWake.route_arrival) {{ status.textContent = "Ready"; summary.textContent = `Leave home at ${{formatTime(transitWake.route_departure)}} · arrive by ${{formatTime(transitWake.route_arrival)}}`; legs.innerHTML = (transitWake.route || []).map((leg) => {{ if (leg.type === "transit") return `<div class="transit-leg"><strong>Bus ${{escapeHtml(leg.route)}}</strong><div>${{escapeHtml(leg.departure)}} ← ${{escapeHtml(leg.arrival)}}<span>${{escapeHtml(leg.from_stop)}} ← ${{escapeHtml(leg.to_stop)}}</span></div></div>`; return `<div class="transit-leg"><strong>Walk</strong><div>${{escapeHtml(leg.minutes)}} min<span>${{escapeHtml(leg.from)}} ← ${{escapeHtml(leg.to)}}</span></div></div>`; }}).join(""); return; }} status.textContent = action === "clear" ? "No route needed" : "Alarm unchanged"; summary.textContent = action === "clear" ? "No confirmed lessons are scheduled." : "Transit data is unavailable, so the existing alarm stays unchanged."; legs.innerHTML = ""; }}
function setLesson(id, item, emptyText, emptyDetail) {{ const card = document.getElementById(id); const subject = card.querySelector("h2, h3"); const detailTarget = card.querySelector(".lesson-detail"); const time = card.querySelector(".lesson-time"); card.classList.toggle("is-empty", !item); subject.textContent = item ? item.subject : emptyText; detailTarget.textContent = item ? detail(item) : emptyDetail; time.innerHTML = item ? `${{formatTime(item.start)}} <small>– ${{formatTime(item.end)}}</small>` : ""; }}
function refreshLiveLessons() {{ const now = nowInSchoolZone(); document.getElementById("today-label").textContent = dateFormatter.format(new Date()); if (!scheduleAvailable) {{ setLesson("current-lesson", null, "Schedule unavailable", "The synced timetable is not available yet"); setLesson("next-lesson", null, "Try again later", "The live timetable will appear after the next successful sync"); return; }} const ordered = [...schedule].sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.period - b.period); const today = ordered.filter((item) => item.date === now.date); const current = today.find((item) => minutes(item.start) <= now.minutes && now.minutes < minutes(item.end)); const next = ordered.find((item) => item.date > now.date || (item.date === now.date && minutes(item.start) > now.minutes)); setLesson("current-lesson", current, "No class right now", today.length ? "You’re between lessons" : "No lessons scheduled today"); setLesson("next-lesson", next, "No more lessons", "Nothing else is scheduled in the synced timetable"); document.getElementById("schedule-note").textContent = current ? `You’re in Period ${{current.period}} now` : next ? `Next lesson: Period ${{next.period}}` : "You’re all done for the synced schedule"; }}
function schoolDate(value) {{ return new Date(`${{value}}T12:00:00Z`); }}
function scheduleDates() {{ return [...new Set(schedule.map((item) => item.date))].sort(); }}
function renderDayPicker(selected) {{ const picker = document.getElementById("day-picker"); const dates = scheduleDates(); if (!dates.length) {{ picker.innerHTML = `<div class="empty-day">No school days are available yet.</div>`; return; }} picker.innerHTML = dates.map((date) => `<button class="day-chip ${{date === selected ? "is-selected" : ""}}" type="button" role="option" aria-selected="${{date === selected}}" data-date="${{escapeHtml(date)}}">${{escapeHtml(shortDateFormatter.format(schoolDate(date)))}}</button>`).join(""); picker.querySelectorAll(".day-chip").forEach((button) => button.addEventListener("click", () => renderFullDay(button.dataset.date))); }}
function renderFullDay(targetDate) {{ const dates = scheduleDates(); if (!dates.length) {{ document.getElementById("schedule-periods").innerHTML = `<div class="empty-day">The full schedule will appear after a successful sync.</div>`; return; }} const selected = dates.includes(targetDate) ? targetDate : dates[0]; renderDayPicker(selected); const items = schedule.filter((item) => item.date === selected); const byPeriod = Object.fromEntries(items.map((item) => [item.period, item])); const day = schoolDate(selected); document.getElementById("selected-day-title").textContent = dateFormatter.format(day); document.getElementById("selected-day-summary").textContent = `${{items.length}} lesson${{items.length === 1 ? "" : "s"}} · gaps included`; document.getElementById("schedule-periods").innerHTML = periods.map((slot) => {{ const item = byPeriod[slot.period]; const accent = palette[slot.period % palette.length]; return `<article class="period-row ${{item ? "has-lesson" : "is-gap"}}" style="--slot-accent:${{accent}}"><div class="period-main">${{item ? `<strong>${{escapeHtml(item.subject)}}</strong><span>${{escapeHtml([item.teacher, item.room ? `Room ${{item.room}}` : ""].filter(Boolean).join(" · ") || "Lesson")}}</span>` : `<span class="gap-label">Free period</span><span class="gap-sub">Nothing scheduled</span>`}}</div><div class="period-info"><strong>${{slot.period}}</strong><span>${{formatTime(slot.start)}}<br>– ${{formatTime(slot.end)}}</span></div></article>`; }}).join(""); }}
function changeIsPast(change) {{ const now = nowInSchoolZone(); if (change.date < now.date) return true; if (change.date > now.date) return false; const slot = periods.find((item) => item.period === Number(change.period)); return slot ? now.minutes >= minutes(slot.end) : false; }}
function renderChanges() {{ const list = document.getElementById("change-list"); const count = document.getElementById("changes-count"); const visible = changes.filter((item) => !changeIsPast(item)); count.textContent = String(visible.length); if (!visible.length) {{ list.innerHTML = `<div class="quiet">No upcoming cancellations or updates.</div>`; return; }} list.innerHTML = visible.map((item) => {{ const label = item.kind === "cancelled" ? "Cancelled" : item.kind === "added" ? "Added" : "Changed"; const subject = item.subject || "Schedule update"; return `<article class="change-row ${{escapeHtml(item.kind)}}"><div class="change-date"><strong>${{escapeHtml(item.date.split("-").reverse().join("."))}}</strong><span>Period ${{escapeHtml(item.period)}}</span></div><div class="change-body"><div><span class="change-label">${{label}}</span><h3>${{escapeHtml(subject)}}</h3></div><p>${{escapeHtml(item.detail || "Schedule update")}}</p></div></article>`; }}).join(""); }}
function renderExams() {{ const list = document.getElementById("exam-list"); const count = document.getElementById("exams-count"); count.textContent = String(exams.length); if (!exams.length) {{ list.innerHTML = `<div class="quiet">No upcoming exams found for this profile.</div>`; return; }} list.innerHTML = exams.map((item) => {{ let periodText = String(item.start_period); if (item.end_period !== item.start_period) periodText += `–${{item.end_period}}`; return `<article class="exam-row"><div class="exam-date"><strong>${{escapeHtml(item.date.split("-").reverse().join("."))}}</strong><span>Periods ${{escapeHtml(periodText)}}</span></div><div class="exam-body"><h3>${{escapeHtml(item.subject)}}</h3><p>Reminder: 4 days before · 7:00 PM</p></div></article>`; }}).join(""); }}
function setView(view) {{ const full = view === "full"; const examsView = view === "exams"; document.getElementById("now-view").hidden = full || examsView; document.getElementById("full-view").hidden = !full; document.getElementById("exams-view").hidden = !examsView; document.getElementById("changes-view").hidden = full || examsView; document.getElementById("now-tab").classList.toggle("is-active", view === "now"); document.getElementById("full-tab").classList.toggle("is-active", full); document.getElementById("exams-tab").classList.toggle("is-active", examsView); document.getElementById("now-tab").setAttribute("aria-selected", String(view === "now")); document.getElementById("full-tab").setAttribute("aria-selected", String(full)); document.getElementById("exams-tab").setAttribute("aria-selected", String(examsView)); if (full) {{ const today = nowInSchoolZone().date; renderFullDay(scheduleDates().includes(today) ? today : scheduleDates()[0]); }} window.scrollTo({{top: 0, behavior: "smooth"}}); }}
document.getElementById("now-tab").addEventListener("click", () => setView("now")); document.getElementById("full-tab").addEventListener("click", () => setView("full")); document.getElementById("exams-tab").addEventListener("click", () => setView("exams")); document.getElementById("back-to-now").addEventListener("click", () => setView("now")); document.getElementById("jump-today").addEventListener("click", () => renderFullDay(nowInSchoolZone().date));
let swipeStart = null;
const swipeSurface = document.querySelector(".app");
swipeSurface.addEventListener("touchstart", (event) => {{
  if (event.touches.length !== 1 || event.target.closest("button, a, .day-picker")) {{ swipeStart = null; return; }}
  const touch = event.touches[0];
  swipeStart = {{ x: touch.clientX, y: touch.clientY }};
}}, {{ passive: true }});
swipeSurface.addEventListener("touchend", (event) => {{
  if (!swipeStart || event.changedTouches.length !== 1) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - swipeStart.x;
  const dy = touch.clientY - swipeStart.y;
  swipeStart = null;
  if (Math.abs(dx) < 55 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
  const views = ["now", "full", "exams"];
  const currentView = document.getElementById("exams-view").hidden ? (document.getElementById("full-view").hidden ? "now" : "full") : "exams";
  const nextIndex = views.indexOf(currentView) + (dx < 0 ? 1 : -1);
  if (nextIndex >= 0 && nextIndex < views.length) setView(views[nextIndex]);
}}, {{ passive: true }});
renderChanges(); renderExams(); refreshLiveLessons(); renderTransitWake(); document.body.classList.add("app-ready"); setInterval(() => {{ refreshLiveLessons(); renderChanges(); }}, 30000); if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
</script></body></html>
'''
    (output_dir / "index.html").write_text(html, encoding="utf-8")
