from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .ics import Calendar, IcsEvent
from .events import event_is_past
from .alarm_controls import apply_alarm_controls, public_alarm_settings
from .model import PERIOD_TIMES
from .model import Exam
from .reconcile import ChangeRecord


PWA_ASSETS_DIR = Path(__file__).with_name("assets")
ISRAEL_WEEKEND_WEEKDAYS = frozenset({4, 5})  # Friday and Saturday
# Public Worker origin used by the managed-profile self-service alarm control.
# This is a public endpoint origin, not a credential.
PUBLIC_ALARM_API_ORIGIN = "https://shahaf-profile-admin.trading-api-9de14d.workers.dev"
ARCHIVED_PROFILE_FILES = (
    "data.json",
    "wake.json",
    "manifest.webmanifest",
    "sw.js",
    "header-logo.png",
    "icon.svg",
    "icon-180.png",
    "icon-192.png",
    "icon-512.png",
)


def _write_pwa_assets(output_dir: Path, title: str, profile_id: str, *, pink: bool) -> None:
    """Give every rendered schedule page the same installable app identity."""
    theme = "pink" if pink else "green"
    (output_dir / "header-logo.png").write_bytes((PWA_ASSETS_DIR / "header-logo.png").read_bytes())
    icon_source = (PWA_ASSETS_DIR / f"icon-{theme}.svg").read_text(encoding="utf-8")
    (output_dir / "icon.svg").write_text(icon_source, encoding="utf-8")
    for size in (180, 192, 512):
        source = PWA_ASSETS_DIR / f"icon-{theme}-{size}.png"
        (output_dir / f"icon-{size}.png").write_bytes(source.read_bytes())
    fonts_dir = output_dir / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for weight in (400, 500, 600, 700, 800):
        source = PWA_ASSETS_DIR / "fonts" / f"Heebo-{weight}.ttf"
        (fonts_dir / source.name).write_bytes(source.read_bytes())

    safe_profile_id = "".join(char if char.isalnum() else "-" for char in profile_id).strip("-")[:40] or "profile"
    background = "#fff8fb" if pink else "#f4f6f3"
    foreground = "#382633" if pink else "#142b35"
    manifest = {
        "name": title,
        "short_name": "Shahaf",
        "description": "A fast, installable Shahaf school schedule.",
        "lang": "en",
        "dir": "ltr",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": background,
        "theme_color": foreground,
        "icons": [
            {"src": "./icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "./icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    (output_dir / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    cache_name = f"shahaf-schedule-{safe_profile_id}-v3"
    service_worker = f'''const CACHE_NAME = {json.dumps(cache_name)};
const APP_SHELL = ["./", "./index.html", "./data.json", "./manifest.webmanifest", "./header-logo.png", "./icon.svg", "./icon-180.png", "./icon-192.png", "./icon-512.png", "./fonts/Heebo-400.ttf", "./fonts/Heebo-500.ttf", "./fonts/Heebo-600.ttf", "./fonts/Heebo-700.ttf", "./fonts/Heebo-800.ttf"];

self.addEventListener("install", (event) => {{
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
}});

self.addEventListener("fetch", (event) => {{
  if (event.request.method !== "GET") return;
  const request = event.request;
  if (request.mode === "navigate") {{
    event.respondWith(
      Promise.race([
        fetch(request).then((response) => {{
          if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put("./index.html", response.clone()));
          return response;
        }}),
        new Promise((_, reject) => setTimeout(() => reject(new Error("network timeout")), 3500))
      ]).catch(() => caches.match("./index.html"))
    );
    return;
  }}
  event.respondWith(caches.match(request).then((cached) => {{
    if (cached) return cached;
    return fetch(request).then((response) => {{
      if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(request, response.clone()));
      return response;
    }});
  }}));
}});
'''
    (output_dir / "sw.js").write_text(service_worker, encoding="utf-8")


def archive_profile_site(output_dir: Path, destination: str) -> None:
    """Replace an obsolete generated profile with a safe migration page."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ARCHIVED_PROFILE_FILES:
        (output_dir / filename).unlink(missing_ok=True)
    fonts_dir = output_dir / "fonts"
    if fonts_dir.is_dir():
        for child in fonts_dir.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
        try:
            fonts_dir.rmdir()
        except OSError:
            pass
    target = escape(destination, quote=True)
    target_js = json.dumps(destination)
    (output_dir / "index.html").write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta http-equiv="refresh" content="0;url={target}">
  <title>Schedule moved</title>
</head>
<body>
  <p>This schedule moved to a private profile.</p>
  <p><a href="{target}">Open the current schedule</a></p>
  <script>location.replace({target_js});</script>
</body>
</html>
""".format(target=target, target_js=target_js),
        encoding="utf-8",
    )


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
            "title": str(exam.get("title", "")),
            "teacher": str(exam.get("teacher", "")),
            "room": str(exam.get("room", "")),
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
        "title": exam.title,
        "teacher": exam.teacher,
        "room": exam.room,
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
        base = next(
            (
                candidate
                for candidate in calendar.events
                if candidate.uid == event.uid and candidate.recurrence_id is None
            ),
            None,
        )
        if base is not None and event.recurrence_id in base.exdates():
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
    buffer_minutes: int = 75,
    min_wake_time: str | None = None,
    max_wake_time: str | None = None,
    round_to_minutes: int = 1,
    no_lessons_policy: str = "clear",
    stale_policy: str = "leave",
    fallback_wake_time: str = "07:15",
    wake_time_by_first_lesson_start: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the safe, master-profile-only input for the iPhone Shortcut."""

    base: dict[str, Any] = {
        "next_school_day": None,
        "next_scheduled_school_day": None,
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
    zone = ZoneInfo("Asia/Jerusalem")
    current = now or datetime.now(zone)
    current = current.astimezone(zone) if current.tzinfo else current.replace(tzinfo=zone)
    if stale:
        if stale_policy != "set_fixed" or not schedule:
            base["fallback_status"] = "stale"
            return base
        current_day = current.date()
        candidate_dates: set[date] = set()
        for item in schedule:
            if not isinstance(item, dict) or not item.get("date"):
                continue
            try:
                candidate = date.fromisoformat(str(item["date"]))
            except ValueError:
                continue
            if candidate.weekday() in ISRAEL_WEEKEND_WEEKDAYS:
                continue
            if candidate >= current_day:
                candidate_dates.add(candidate)
        candidate_dates = sorted(candidate_dates)
        future_dates = [candidate for candidate in candidate_dates if candidate > current_day]
        base["next_scheduled_school_day"] = future_dates[0].isoformat() if future_dates else None
        for school_day in candidate_dates:
            fallback_at = datetime.combine(school_day, time.fromisoformat(fallback_wake_time)).replace(tzinfo=zone)
            if school_day == current_day and fallback_at <= current:
                continue
            base.update(
                {
                    "next_school_day": school_day.isoformat(),
                    "wake_time": fallback_at.strftime("%H:%M"),
                    "wake_at": fallback_at.isoformat(),
                    "subject": None,
                    "enabled": True,
                    "shortcut_action": "set",
                    "fallback_status": "stale-fixed",
                }
            )
            return base
        base["fallback_status"] = "stale"
        return base
    if not schedule_available or schedule is None:
        base["stale"] = True
        base["fallback_status"] = "unavailable"
        return base

    today = current.date()
    by_date: dict[date, list[dict[str, Any]]] = {}
    for item in schedule:
        try:
            item_date = date.fromisoformat(str(item["date"]))
            time.fromisoformat(str(item["start"]))
        except (KeyError, TypeError, ValueError):
            continue
        if item_date.weekday() in ISRAEL_WEEKEND_WEEKDAYS:
            continue
        if item_date >= today:
            by_date.setdefault(item_date, []).append(item)
    future_dates = [school_day for school_day in sorted(by_date) if school_day > today]
    base["next_scheduled_school_day"] = future_dates[0].isoformat() if future_dates else None

    for school_day in sorted(by_date):
        first = min(by_date[school_day], key=lambda item: (item["start"], item.get("period", 0)))
        first_start = time.fromisoformat(str(first["start"]))
        special_wake_time = None
        if wake_time_by_first_lesson_start:
            configured = wake_time_by_first_lesson_start.get(first_start.strftime("%H:%M"))
            if configured:
                try:
                    parsed_special = time.fromisoformat(str(configured))
                except ValueError:
                    parsed_special = None
                if parsed_special is not None and parsed_special < first_start:
                    special_wake_time = parsed_special
        wake_naive = (
            datetime.combine(school_day, special_wake_time)
            if special_wake_time is not None
            else datetime.combine(school_day, first_start) - timedelta(minutes=buffer_minutes)
        )
        if round_to_minutes > 1:
            rounded_minutes = (wake_naive.hour * 60 + wake_naive.minute) // round_to_minutes * round_to_minutes
            wake_naive = wake_naive.replace(hour=rounded_minutes // 60, minute=rounded_minutes % 60, second=0, microsecond=0)
        wake_local = wake_naive.replace(tzinfo=zone)
        if min_wake_time and wake_local.time() < time.fromisoformat(min_wake_time):
            base.update({"next_school_day": school_day.isoformat(), "fallback_status": "wake-time-bound", "shortcut_action": "leave"})
            return base
        if max_wake_time and wake_local.time() > time.fromisoformat(max_wake_time):
            base.update({"next_school_day": school_day.isoformat(), "fallback_status": "wake-time-bound", "shortcut_action": "leave"})
            return base
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
    base["shortcut_action"] = "clear" if no_lessons_policy == "clear" else "leave"
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
    events: list[dict[str, Any]] | None = None,
    events_available: bool = True,
    events_error: str = "",
    events_source_updated: str = "",
    now: datetime | None = None,
    alarm_safety: str | None = None,
    alarm_safety_reason: str = "",
    profile_id: str = "master",
    profile_label: str = "Master profile — יא-2",
    profile_mark: str = "XI·2",
    profile_class_id: str = "11",
    publish_wake: bool = True,
    public_profile: bool = False,
    transit_wake: dict[str, Any] | None = None,
    alarm_settings: dict[str, Any] | None = None,
    alarm_override: dict[str, Any] | None = None,
    wake_time_by_first_lesson_start: dict[str, str] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    is_pink = profile_id == "ya1" or public_profile
    _write_pwa_assets(output_dir, title, profile_id, pink=is_pink)
    schedule_data = schedule or []
    visible_changes = [item for item in changes if not _change_is_past(item, now)]
    periods = _period_metadata()
    exams_data = [_exam_to_dict(item) for item in (exams or [])]
    events_data = list(events or [])
    visible_events = [item for item in events_data if not event_is_past(item, now)]
    safe_transit_wake = dict(transit_wake) if transit_wake is not None else None
    if public_profile and safe_transit_wake is not None:
        for key in ("origin_address", "origin", "origin_coordinates"):
            safe_transit_wake.pop(key, None)
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
        "events": visible_events,
        "events_available": events_available,
        "events_error": events_error,
        "events_source_updated": events_source_updated,
        "source_url": source_url,
        "source_updated": source_updated,
        "last_successful_sync": last_successful_sync,
        "stale": stale,
        "error": error,
        "generated_at": generated_at,
        "transit_wake": safe_transit_wake if (profile_id == "ya1" or public_profile) else None,
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
        "events": visible_events,
        "events_available": events_available,
        "events_error": events_error,
        "events_source_updated": events_source_updated,
    }
    if publish_wake:
        wake_data = build_wake_data(
            schedule_data,
            schedule_available=schedule is not None,
            stale=stale,
            now=now,
            alarm_safety=alarm_safety,
            alarm_safety_reason=alarm_safety_reason,
            buffer_minutes=int((alarm_settings or {}).get("wake_buffer_minutes", 75)),
            min_wake_time=(alarm_settings or {}).get("min_wake_time"),
            max_wake_time=(alarm_settings or {}).get("max_wake_time"),
            round_to_minutes=int((alarm_settings or {}).get("round_to_minutes", 1)),
            no_lessons_policy=str((alarm_settings or {}).get("no_lessons_policy", "clear")),
            stale_policy=str((alarm_settings or {}).get("stale_policy", "leave")),
            fallback_wake_time=str((alarm_settings or {}).get("fallback_wake_time", "07:15")),
            wake_time_by_first_lesson_start=wake_time_by_first_lesson_start,
        )
        if public_profile:
            if safe_transit_wake is not None:
                # Managed transit profiles use the route-aware payload as the
                # Shortcut input. Legacy Ya-1 keeps its existing separate
                # endpoint because public_profile is false there.
                wake_data = dict(safe_transit_wake)
            wake_data["profile_id"] = profile_id
            if alarm_settings:
                wake_data = apply_alarm_controls(
                    wake_data,
                    alarm_settings,
                    override=alarm_override,
                    now=now,
                )
                wake_data["alarm_control"] = {
                    **wake_data.get("alarm_control", {}),
                    "settings": public_alarm_settings(alarm_settings),
                }
            else:
                wake_data["alarm_label"] = "Shahaf"
        data["wake"] = wake_data
    if safe_transit_wake is not None:
        data["transit_wake"] = safe_transit_wake
    (output_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if publish_wake:
        (output_dir / "wake.json").write_text(
            json.dumps(wake_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    elif safe_transit_wake is not None:
        (output_dir / "wake.json").write_text(
            json.dumps(safe_transit_wake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    status = (
        '<div id="sync-status" class="status stale"><span class="status-dot"></span><span data-i18n="syncNeedsAttention">Sync needs attention</span></div>'
        if stale
        else '<div id="sync-status" class="status"><span class="status-dot"></span><span data-i18n="synced">Synced</span></div>'
    )
    if error:
        status += f'<details class="error"><summary data-i18n="errorDetails">Error details</summary><pre>{escape(error)}</pre></details>'

    changes_html = '''<section class="changes" id="changes-view" aria-labelledby="changes-title"><div class="section-title"><h2 id="changes-title" data-i18n="changes">Changes</h2><span id="changes-count">0</span></div><div class="change-list" id="change-list"></div></section>'''

    transit_html = '''<section class="transit-wake-card" id="transit-wake-card" aria-labelledby="transit-title"><div class="section-title"><h2 id="transit-title" data-i18n="busPlan">Bus plan</h2><span id="transit-status">Checking</span></div><div id="transit-summary" class="transit-summary" data-i18n="checkingRoute">Checking the safest scheduled route…</div><div id="transit-legs" class="transit-legs"></div><p class="transit-note" data-i18n="earlierBuses">Earlier buses were considered; this is the latest scheduled departure that still arrives safely.</p><a id="transit-map" class="transit-map" href="#" target="_blank" rel="noreferrer" data-i18n="verifyRoute">Verify route in Google Maps ↗</a></section>''' if profile_id == "ya1" else ""
    alarm_html = '''<section class="alarm-self-service" id="alarm-self-service" aria-labelledby="alarm-self-service-title"><div class="section-title"><h2 id="alarm-self-service-title" data-i18n="alarmTitle">My alarm</h2></div><button id="alarm-self-service-toggle" class="small-button" type="button" aria-expanded="false" aria-controls="alarm-self-service-panel" data-i18n="alarmButton">Cancel / move my next alarm</button><div id="alarm-self-service-panel" class="alarm-panel" hidden><p class="alarm-help" data-i18n="alarmInstruction">This changes only this schedule’s next alarm. It will be applied after the next sync.</p><div class="alarm-actions"><button id="alarm-cancel-today" class="alarm-action alarm-action-danger" type="button" data-i18n="cancelTodayAlarm">Cancel my next alarm</button><div class="alarm-time-row"><label for="alarm-move-time" data-i18n="moveAlarmTo">Move my next alarm to</label><input id="alarm-move-time" type="time" inputmode="numeric" step="60"><button id="alarm-move-today" class="alarm-action" type="button" data-i18n="moveAlarm">Move alarm</button></div><button id="alarm-restore" class="alarm-action" type="button" data-i18n="restoreAlarm">Restore my alarm</button></div><button id="alarm-keep-current" class="small-button" type="button" data-i18n="keepAlarm">Keep current alarm</button></div><p id="alarm-self-service-status" class="alarm-status" role="status" aria-live="polite"></p></section>''' if public_profile else ""

    gate_html = '''<section id="site-access-gate" class="site-access-gate" aria-labelledby="gate-title"><div class="gate-card"><p class="eyebrow" data-i18n="privatePage">Private page</p><h1 id="gate-title" data-i18n="enterYa1Schedule">Enter Ya1 schedule</h1><p data-i18n="typePhrase">Type the access phrase to continue.</p><form id="gate-form"><label for="gate-phrase" data-i18n="accessPhrase">Access phrase</label><input id="gate-phrase" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" dir="auto" required><button type="submit" data-i18n="enter">Enter</button><p id="gate-error" role="alert" aria-live="polite"></p></form></div></section>''' if profile_id == "ya1" else ""
    gate_css = '''.site-locked .app{display:none}.site-access-gate{display:grid;place-items:center;min-height:100vh;padding:24px}.site-access-gate[hidden]{display:none}.gate-card{width:min(100%,420px);padding:25px 22px;border:1px solid var(--line);border-radius:22px;background:var(--card);box-shadow:var(--shadow)}.gate-card h1{font-size:34px;margin:8px 0}.gate-card>p:not(.eyebrow){color:var(--muted);font-size:14px}.gate-card label{display:block;margin:20px 0 7px;font-size:12px;font-weight:750}.gate-card input{width:100%;height:47px;padding:0 13px;border:1px solid var(--line);border-radius:12px;background:var(--paper);color:var(--ink);font:inherit}.gate-card button{width:100%;height:47px;margin-top:11px;border:0;border-radius:12px;background:var(--ink);color:#fff;font:inherit;font-weight:800;cursor:pointer}.gate-card #gate-error{min-height:18px;margin:9px 0 0;color:var(--red);font-size:12px}''' if profile_id == "ya1" else ""
    gate_script = '''<script>(()=>{const expected="אורי המלך";const body=document.body;const gate=document.getElementById("site-access-gate");const form=document.getElementById("gate-form");const input=document.getElementById("gate-phrase");const error=document.getElementById("gate-error");const unlock=()=>{body.classList.remove("site-locked");gate.hidden=true};form.addEventListener("submit",(event)=>{event.preventDefault();if(input.value.trim()===expected)unlock();else{error.textContent=document.documentElement.lang==="he"?"המשפט אינו נכון.":"That phrase is not correct.";input.select()}});input.focus()})();</script>''' if profile_id == "ya1" else ""

    exams_html = '''<section class="exams" id="exams-view" aria-labelledby="exams-title" hidden><div class="section-title"><h2 id="exams-title" data-i18n="exams">Exams</h2><span id="exams-count">0</span></div><div class="exam-list" id="exam-list"></div></section>'''
    schedule_json = json.dumps(schedule_data, ensure_ascii=False).replace("</", "<\\/")
    periods_json = json.dumps(periods, ensure_ascii=False)
    primary_profile_json = json.dumps(primary_profile, ensure_ascii=False).replace("</", "<\\/")
    alarm_command_url = f"{PUBLIC_ALARM_API_ORIGIN}/public/profiles/{profile_id}/alarm-command" if public_profile else ""
    alarm_command_url_json = json.dumps(alarm_command_url, ensure_ascii=False).replace("</", "<\\/")
    schedule_available = "true" if schedule is not None else "false"
    theme_class = "theme-pink" if (profile_id == "ya1" or public_profile) else "theme-green"
    robots = '<meta name="robots" content="noindex,nofollow,noarchive">' if public_profile else ""
    ui_translations = {
        "en": {
            "mySchedule": "My schedule", "openShahaf": "Open Shahaf app", "scheduleViews": "Schedule views",
            "now": "Now", "fullSchedule": "Schedule", "exams": "Exams", "loadingToday": "Loading today’s schedule…",
            "todaysSchedule": "Today’s schedule", "checking": "Checking…", "nextUp": "Next up", "syncNeedsAttention": "Sync needs attention",
            "synced": "Synced", "errorDetails": "Error details", "busPlan": "Bus plan", "checkingRoute": "Checking the safest scheduled route…",
            "ready": "Ready", "leaveHome": "Leave home", "arriveBy": "arrive by", "earlierBuses": "Earlier buses were considered; this is the latest scheduled departure that still arrives safely.",
            "verifyRoute": "Verify route in Google Maps ↗", "noRouteNeeded": "No route needed", "alarmUnchanged": "Alarm unchanged",
            "noLessonsScheduled": "No confirmed lessons are scheduled.", "transitUnavailable": "Transit data is unavailable, so the existing alarm stays unchanged.",
            "alarmTitle": "My alarm", "alarmButton": "Cancel / move my next alarm", "alarmInstruction": "This changes only this schedule’s next alarm. Restore returns it to the state before the last change. Run the Shahaf Shortcut to apply it immediately; the full schedule sync continues in the background.",
            "cancelTodayAlarm": "Cancel my next alarm", "moveAlarmTo": "Move my next alarm to", "moveAlarm": "Move alarm", "restoreAlarm": "Restore my alarm", "keepAlarm": "Keep current alarm",
            "alarmConfirmCancel": "Cancel this schedule’s next alarm?", "alarmConfirmMove": "Move this schedule’s next alarm to {time}?", "alarmConfirmRestore": "Restore this schedule’s alarm to how it was before the last change?", "alarmSaving": "Saving next alarm change…",
            "alarmCancelQueued": "Next alarm cancellation is queued. Run the Shahaf Shortcut to apply it immediately.", "alarmMoveQueued": "Next alarm move is queued. Run the Shahaf Shortcut to apply it immediately.", "alarmRestoreQueued": "Restore is queued. Run the Shahaf Shortcut to apply the previous alarm state immediately.",
            "alarmError": "The alarm change could not be submitted. Please try again.", "alarmFutureTime": "Choose a future time for the next alarm.",
            "privatePage": "Private page", "enterYa1Schedule": "Enter Ya1 schedule", "typePhrase": "Type the access phrase to continue.",
            "accessPhrase": "Access phrase", "enter": "Enter", "incorrectPhrase": "That phrase is not correct.", "everyPeriod": "Every period",
            "backToNow": "Back to now", "chooseSchoolDay": "Choose a school day", "today": "Today", "loading": "Loading…", "noSchoolDays": "No school days are available yet.",
            "changes": "Changes", "noUpcomingChanges": "No upcoming cancellations or updates.", "cancelled": "Cancelled", "changed": "Changed", "added": "Added",
            "scheduleUpdate": "Schedule update", "period": "Period", "examsCount": "Exams", "noUpcomingExams": "No upcoming exams found for this profile.",
            "periods": "Periods", "freePeriod": "Free period",
            "nothingScheduled": "Nothing scheduled", "lesson": "Lesson", "room": "Room", "gapsIncluded": "gaps included", "lessons": "lessons", "noLesson": "No lesson", "gap": "Gap",
            "asyncDay": "Async learning day", "asyncDayDetail": "No in-person lessons are scheduled for this day.",
            "lessonSingular": "lesson", "scheduleUnavailable": "Schedule unavailable", "tryAgain": "Try again later", "timetableAfterSync": "The synced timetable will appear after the next successful sync",
            "noClassRightNow": "No class right now", "betweenLessons": "You’re between lessons", "noMoreLessons": "No more lessons", "allDone": "You’re all done for the synced schedule",
            "inPeriod": "You’re in Period", "nextLesson": "Next lesson", "noLessonsToday": "No lessons scheduled today", "nothingElse": "Nothing else is scheduled in the synced timetable",
        },
        "he": {
            "mySchedule": "המערכת שלי", "openShahaf": "פתיחת אפליקציית שחף", "scheduleViews": "תצוגות מערכת", "now": "עכשיו", "fullSchedule": "מערכת", "exams": "מבחנים",
            "loadingToday": "טוען את המערכת של היום…", "todaysSchedule": "המערכת של היום", "checking": "בודק…", "nextUp": "השיעור הבא", "syncNeedsAttention": "נדרשת תשומת לב לסנכרון",
            "synced": "מסונכרן", "errorDetails": "פרטי שגיאה", "busPlan": "תוכנית נסיעה", "checkingRoute": "בודק את המסלול המתוזמן הבטוח ביותר…", "ready": "מוכן",
            "leaveHome": "יציאה מהבית", "arriveBy": "הגעה עד", "earlierBuses": "נבדקו גם אוטובוסים מוקדמים יותר; זהו האוטובוס המאוחר ביותר שמגיע בזמן.", "verifyRoute": "בדיקת המסלול ב-Google Maps ↗",
            "noRouteNeeded": "אין צורך במסלול", "alarmUnchanged": "ההתראה נשארת ללא שינוי", "noLessonsScheduled": "אין שיעורים מאושרים במערכת.", "transitUnavailable": "נתוני התחבורה אינם זמינים, לכן ההתראה הקיימת נשארת ללא שינוי.",
            "alarmTitle": "ההתראה שלי", "alarmButton": "ביטול / שינוי ההתראה הבאה שלי", "alarmInstruction": "פעולה זו משנה רק את ההתראה הבאה של המערכת הזו. השחזור מחזיר אותה למצב שלפני השינוי האחרון. יש להפעיל את קיצור הדרך של שחף כדי להחיל מיד; סנכרון המערכת המלא ימשיך ברקע.",
            "cancelTodayAlarm": "ביטול ההתראה הבאה שלי", "moveAlarmTo": "שינוי ההתראה הבאה שלי לשעה", "moveAlarm": "שינוי ההתראה", "restoreAlarm": "שחזור ההתראה שלי", "keepAlarm": "השארת ההתראה הנוכחית",
            "alarmConfirmCancel": "לבטל את ההתראה הבאה של המערכת הזו?", "alarmConfirmMove": "לשנות את ההתראה הבאה של המערכת הזו לשעה {time}?", "alarmConfirmRestore": "להחזיר את ההתראה של המערכת הזו למצב שלפני השינוי האחרון?", "alarmSaving": "שומר את שינוי ההתראה הבאה…",
            "alarmCancelQueued": "ביטול ההתראה הבאה הוכנס לתור. יש להפעיל את קיצור הדרך של שחף כדי להחיל מיד.", "alarmMoveQueued": "שינוי ההתראה הבאה הוכנס לתור. יש להפעיל את קיצור הדרך של שחף כדי להחיל מיד.", "alarmRestoreQueued": "השחזור הוכנס לתור. יש להפעיל את קיצור הדרך של שחף כדי להחיל את מצב ההתראה הקודם מיד.",
            "alarmError": "לא ניתן לשלוח את שינוי ההתראה. נסה שוב.", "alarmFutureTime": "יש לבחור שעה עתידית להתראה הבאה.",
            "privatePage": "עמוד פרטי", "enterYa1Schedule": "כניסה למערכת י״א 1", "typePhrase": "הקלד את משפט הגישה כדי להמשיך.", "accessPhrase": "משפט גישה", "enter": "כניסה", "incorrectPhrase": "המשפט אינו נכון.",
            "everyPeriod": "כל השעות", "backToNow": "חזרה לעכשיו", "chooseSchoolDay": "בחירת יום לימודים", "today": "היום", "loading": "טוען…", "noSchoolDays": "אין ימי לימודים זמינים עדיין.", "changes": "שינויים",
            "noUpcomingChanges": "אין ביטולים או עדכונים קרובים.", "cancelled": "בוטל", "changed": "שונה", "added": "נוסף", "scheduleUpdate": "עדכון מערכת", "period": "שעה",
            "examsCount": "מבחנים", "noUpcomingExams": "לא נמצאו מבחנים קרובים לפרופיל הזה.", "periods": "שעות",
            "freePeriod": "שעה פנויה", "nothingScheduled": "אין שיעור מתוכנן", "lesson": "שיעור", "room": "חדר", "gapsIncluded": "כולל הפסקות", "lessons": "שיעורים", "noLesson": "אין שיעור", "gap": "חלון", "lessonSingular": "שיעור",
            "asyncDay": "יום למידה אסינכרוני", "asyncDayDetail": "אין שיעורים פרונטליים ביום הזה.",
            "scheduleUnavailable": "המערכת אינה זמינה", "tryAgain": "נסה שוב מאוחר יותר", "timetableAfterSync": "המערכת תופיע לאחר סנכרון מוצלח הבא", "noClassRightNow": "אין שיעור עכשיו", "betweenLessons": "אתה בין שיעורים",
            "noMoreLessons": "אין עוד שיעורים", "allDone": "סיימת את המערכת להיום", "inPeriod": "אתה בשעה", "nextLesson": "השיעור הבא", "noLessonsToday": "אין שיעורים היום", "nothingElse": "אין שיעורים נוספים במערכת",
        },
    }
    ui_translations_json = json.dumps(ui_translations, ensure_ascii=False).replace("</", "<\\/")
    html = f'''<!doctype html>
<html lang="en" dir="ltr"><head><meta charset="utf-8">{robots}
<script>const shahafParams=new URLSearchParams(location.search);const shahafForcedLanguage=shahafParams.get("lang");const shahafDeviceLanguage=(navigator.languages&&navigator.languages[0])||navigator.language||"en";const shahafIsHebrew=shahafForcedLanguage==="he"||(!["he","en"].includes(shahafForcedLanguage)&&/^(he|iw)(-|$)/i.test(shahafDeviceLanguage));document.documentElement.lang=shahafIsHebrew?"he":"en";document.documentElement.dir=shahafIsHebrew?"rtl":"ltr";</script>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f4f6f3">
<meta name="description" content="{escape(title)}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="My Schedule">
<meta name="last-successful-sync" content="{escape(last_successful_sync or generated_at)}">
<link rel="icon" href="./icon.svg" type="image/svg+xml">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" sizes="180x180" href="./icon-180.png">
<title>{escape(title)}</title>
<style>
@font-face{{font-family:"HeeboLocal";src:url("./fonts/Heebo-400.ttf") format("truetype");font-weight:400;font-style:normal;font-display:swap}}
@font-face{{font-family:"HeeboLocal";src:url("./fonts/Heebo-500.ttf") format("truetype");font-weight:500;font-style:normal;font-display:swap}}
@font-face{{font-family:"HeeboLocal";src:url("./fonts/Heebo-600.ttf") format("truetype");font-weight:600;font-style:normal;font-display:swap}}
@font-face{{font-family:"HeeboLocal";src:url("./fonts/Heebo-700.ttf") format("truetype");font-weight:700;font-style:normal;font-display:swap}}
@font-face{{font-family:"HeeboLocal";src:url("./fonts/Heebo-800.ttf") format("truetype");font-weight:800;font-style:normal;font-display:swap}}
:root{{color-scheme:light;--paper:#f4f6f3;--card:#ffffff;--ink:#142b35;--muted:#71818a;--line:#dfe7e4;--green:#0c806d;--green-soft:#d9f0e9;--red:#c85652;--red-soft:#fae6e4;--blue:#3869bd;--shadow:0 14px 35px #142b3512}}
*{{box-sizing:border-box}}html{{background:var(--paper);overscroll-behavior-x:none}}body{{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:"HeeboLocal","Avenir Next","SF Pro Display","Noto Sans Hebrew","Heebo",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.4;-webkit-font-smoothing:antialiased;padding-bottom:env(safe-area-inset-bottom)}}
.app{{width:calc(100% - 28px);max-width:620px;margin:0 auto;padding:max(18px,env(safe-area-inset-top)) 0 34px;touch-action:pan-y}}
.app{{contain:layout style}}body:not(.app-ready) #current-subject,body:not(.app-ready) #next-subject{{color:transparent;position:relative}}body:not(.app-ready) #current-subject::after,body:not(.app-ready) #next-subject::after{{content:"";display:block;width:68%;height:1em;border-radius:8px;background:linear-gradient(100deg,#ffffff14 20%,#ffffff32 38%,#ffffff14 56%);background-size:220% 100%;animation:skeleton-shimmer 1.25s linear infinite}}body:not(.app-ready) #next-subject::after{{width:78%;background:linear-gradient(100deg,#e4ecea 20%,#f7faf8 38%,#e4ecea 56%);background-size:220% 100%}}@keyframes skeleton-shimmer{{to{{background-position:-220% 0}}}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}}.identity{{display:flex;align-items:center;gap:11px;color:var(--ink);text-decoration:none}}.mark{{display:block;width:43px;height:43px;border-radius:14px;object-fit:cover;flex:0 0 43px}}.identity strong{{display:block;font-size:15px;letter-spacing:-.02em}}.identity small{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.source{{color:var(--ink);text-decoration:none;border:1px solid var(--line);border-radius:50%;width:40px;height:40px;display:grid;place-items:center;font-size:19px;background:var(--card)}}
 .view-switch{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:4px;margin-bottom:27px;border:1px solid var(--line);border-radius:14px;background:#eaf0ed;touch-action:pan-y;user-select:none}}.view-switch button,.small-button,.day-chip{{font:inherit;border:0;cursor:pointer}}.view-switch button{{position:relative;min-height:38px;border-radius:10px;background:transparent;color:var(--muted);font-size:13px;font-weight:750;transition:background-color .36s cubic-bezier(.2,.8,.2,1),color .36s cubic-bezier(.2,.8,.2,1),box-shadow .36s cubic-bezier(.2,.8,.2,1),transform .36s cubic-bezier(.2,.8,.2,1)}}.view-switch button::after{{content:"";position:absolute;left:13px;right:13px;bottom:5px;height:2px;border-radius:99px;background:currentColor;opacity:0;transform:scaleX(.2);transition:opacity .36s ease,transform .36s cubic-bezier(.2,.8,.2,1)}}.view-switch button.is-active{{background:var(--card);color:var(--ink);box-shadow:0 2px 7px #142b3512;transform:translateY(-1px)}}.view-switch button.is-active::after{{opacity:.48;transform:scaleX(1)}}button:focus-visible,.identity:focus-visible{{outline:3px solid #8ecdc0;outline-offset:2px}}
.status{{display:flex;align-items:center;gap:7px;color:var(--green);font-size:12px;font-weight:750;margin-bottom:11px}}.status-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}}.stale{{color:#9b5b22}}.stale .status-dot{{background:#d18b3e;box-shadow:0 0 0 4px #f7e6ca}}.error{{margin:-2px 0 18px;color:#9b413a;font-size:12px}}.error summary{{cursor:pointer;font-weight:700}}.error pre{{white-space:pre-wrap;background:var(--red-soft);border-radius:10px;padding:10px;margin-top:8px}}
.date-line{{color:var(--muted);font-size:14px;margin:0 0 5px}}h1,h2,h3,p{{margin-top:0}}h1{{font-size:clamp(35px,10vw,52px);line-height:1.02;letter-spacing:-.065em;margin:0 0 22px;font-weight:800}}.live-area{{margin-bottom:31px}}
.lesson-card{{position:relative;overflow:hidden;border-radius:22px;background:var(--ink);color:#fff;padding:21px 21px 19px;min-height:185px;box-shadow:var(--shadow)}}.lesson-card::after{{content:"";position:absolute;width:175px;height:175px;border:1px solid #ffffff16;border-radius:50%;right:-65px;bottom:-115px;box-shadow:0 0 0 20px #ffffff08}}.lesson-kicker{{position:relative;z-index:1;color:#8fe1d4;font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}}.lesson-card h2{{position:relative;z-index:1;font-size:29px;line-height:1.05;letter-spacing:-.05em;margin:25px 0 7px;max-width:88%}}.lesson-detail{{position:relative;z-index:1;margin:0;color:#b9c9cf;font-size:14px;min-height:20px}}.lesson-time{{position:relative;z-index:1;display:block;margin-top:22px;font-size:18px;font-weight:750;letter-spacing:-.03em}}.lesson-time small{{color:#adc0c8;font-size:13px;font-weight:500}}.lesson-card.is-empty{{background:#e4eceb;color:var(--ink);box-shadow:none}}.lesson-card.is-empty::after{{border-color:#ffffff55;box-shadow:0 0 0 20px #ffffff33}}.lesson-card.is-empty .lesson-kicker{{color:var(--muted)}}.lesson-card.is-empty .lesson-detail,.lesson-card.is-empty .lesson-time small{{color:var(--muted)}}
.next-card{{margin-top:10px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:14px;padding:16px 18px;border:1px solid var(--line);background:var(--card);border-radius:17px}}.next-card .lesson-kicker{{color:var(--muted)}}.next-card h3{{font-size:20px;line-height:1.1;letter-spacing:-.04em;margin:7px 0 4px;max-width:235px}}.next-card .lesson-detail{{font-size:12px;color:var(--muted)}}.next-card .lesson-time{{margin:0;text-align:right;font-size:15px;color:var(--ink);white-space:nowrap}}.next-card .lesson-time small{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.transit-wake-card{{margin:18px 0 29px;padding:17px 18px;border:1px solid var(--line);border-radius:18px;background:var(--card);box-shadow:0 5px 16px #38263308}}.transit-wake-card .section-title{{margin-bottom:8px}}.transit-wake-card .section-title h2{{font-size:21px}}.transit-wake-card .section-title span{{min-width:auto;background:var(--green-soft);color:var(--green);font-size:10px;text-transform:uppercase;letter-spacing:.05em}}.transit-summary{{font-size:14px;font-weight:750;line-height:1.35}}.transit-legs{{display:grid;gap:7px;margin-top:12px}}.transit-leg{{display:grid;grid-template-columns:62px 1fr;gap:9px;padding:9px 10px;border-radius:11px;background:var(--paper);font-size:12px}}.transit-leg strong{{font-size:12px}}.transit-leg span{{display:block;color:var(--muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.transit-note{{margin:11px 0 0;color:var(--muted);font-size:11px;line-height:1.35}}.transit-map{{display:inline-block;margin-top:10px;color:var(--ink);font-size:11px;font-weight:750;text-decoration:none}}.transit-wake-card.is-warning{{background:#fffaf2;border-color:#f0dfc3}}.transit-wake-card.is-warning .section-title span{{background:#f8e8c9;color:#a96b24}}
.section-title{{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}}.section-title h2{{font-size:22px;letter-spacing:-.04em;margin:0}}.section-title>span{{display:grid;place-items:center;min-width:25px;height:25px;padding:0 7px;border-radius:99px;background:#e2e9e6;color:var(--muted);font-size:12px;font-weight:800}}.change-list{{display:grid;gap:8px}}.change-row{{display:grid;grid-template-columns:78px 1fr;gap:13px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--green);border-radius:14px;padding:13px 14px}}.change-row.cancelled{{border-left-color:var(--red)}}.change-row.added{{border-left-color:var(--blue)}}.change-date strong{{display:block;font-size:14px;letter-spacing:-.03em}}.change-date span{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}.change-body{{min-width:0}}.change-body>div{{display:flex;align-items:center;gap:7px;min-width:0}}.change-label{{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}}.cancelled .change-label{{color:var(--red)}}.added .change-label{{color:var(--blue)}}.change-body h3{{font-size:15px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}}.change-body p{{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0 0}}.quiet{{border:1px dashed #cfdad6;border-radius:14px;padding:15px;color:var(--muted);font-size:12px}}
.section-title{{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}}.section-title h2{{font-size:22px;letter-spacing:-.04em;margin:0}}.section-title>span{{display:grid;place-items:center;min-width:25px;height:25px;padding:0 7px;border-radius:99px;background:#e2e9e6;color:var(--muted);font-size:12px;font-weight:800}}.change-list,.exam-list{{display:grid;gap:8px}}.change-row,.exam-row{{display:grid;grid-template-columns:78px 1fr;gap:13px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--green);border-radius:14px;padding:13px 14px}}.change-row.cancelled{{border-left-color:var(--red)}}.change-row.added{{border-left-color:var(--blue)}}.exam-row{{border-left-color:#d08c3f}}.change-date strong,.exam-date strong{{display:block;font-size:14px;letter-spacing:-.03em}}.change-date span,.exam-date span{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}.change-body,.exam-body{{min-width:0}}.change-body>div{{display:flex;align-items:center;gap:7px;min-width:0}}.change-label{{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}}.cancelled .change-label{{color:var(--red)}}.added .change-label{{color:var(--blue)}}.change-body h3,.exam-body h3{{font-size:15px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}}.change-body p,.exam-body p{{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:4px 0 0}}.quiet{{border:1px dashed #cfdad6;border-radius:14px;padding:15px;color:var(--muted);font-size:12px}}
.full-schedule{{margin-bottom:25px}}.schedule-heading{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:16px}}.eyebrow{{margin:0 0 4px;color:var(--green);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}.schedule-heading h2{{margin:0;font-size:31px;line-height:1.05;letter-spacing:-.06em}}.small-button{{padding:9px 12px;border:1px solid var(--line);border-radius:11px;background:var(--card);color:var(--ink);font-size:12px;font-weight:750;white-space:nowrap}}.day-surface,.day-content{{touch-action:pan-y;will-change:transform,opacity}}.day-picker{{display:flex;gap:7px;overflow-x:auto;padding:2px 2px 9px;margin:0 -2px 13px;scrollbar-width:none}}.day-picker::-webkit-scrollbar{{display:none}}.day-chip{{flex:0 0 auto;padding:9px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap}}.day-chip.is-selected{{background:var(--ink);border-color:var(--ink);color:#fff}}.day-notice{{display:grid;gap:2px;margin:0 0 12px;padding:11px 13px;border:1px solid var(--green-soft);border-radius:13px;background:var(--green-soft);color:var(--ink);font-size:12px}}.day-notice[hidden]{{display:none}}.day-notice strong{{font-size:13px}}.day-notice span{{color:var(--muted)}}.selected-day{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}}.selected-day h3{{margin:0;font-size:21px;letter-spacing:-.04em}}.selected-day p{{margin:3px 0 0;color:var(--muted);font-size:12px}}.period-list{{display:grid;gap:6px}}.period-row{{display:grid;grid-template-columns:1fr 86px;min-height:68px;overflow:hidden;border:1px solid var(--line);border-radius:13px;background:var(--card);box-shadow:0 3px 8px #142b3507}}.period-main{{position:relative;display:flex;flex-direction:column;justify-content:center;min-width:0;padding:11px 14px 11px 18px;border-left:5px solid var(--slot-accent,#cbd6d2)}}.period-row.is-gap .period-main{{border-left-color:#d6dfdc}}.period-main strong{{font-size:16px;line-height:1.12;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.period-main span{{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.gap-label{{font-size:13px!important;font-weight:700;color:#8a979c!important}}.gap-sub{{margin-top:2px}}.period-info{{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;padding:9px 13px 9px 5px;border-left:1px solid var(--line);text-align:right;direction:ltr;unicode-bidi:embed;font-variant-numeric:tabular-nums}}.period-info strong{{font-size:24px;line-height:1;font-weight:800;letter-spacing:-.05em}}.period-info span{{margin-top:5px;color:var(--muted);font-size:11px;line-height:1.2;white-space:nowrap}}.period-range{{display:block;direction:ltr;unicode-bidi:embed;letter-spacing:-.02em}}.empty-day{{border:1px dashed #cfdad6;border-radius:14px;padding:18px;color:var(--muted);font-size:13px}}
.view-panel-enter-next{{animation:view-in-next .22s cubic-bezier(.22,.8,.24,1) both}}.view-panel-enter-previous{{animation:view-in-previous .22s cubic-bezier(.22,.8,.24,1) both}}.day-surface-enter-next{{animation:day-in-next .2s cubic-bezier(.22,.8,.24,1) both}}.day-surface-enter-previous{{animation:day-in-previous .2s cubic-bezier(.22,.8,.24,1) both}}@keyframes view-in-next{{from{{opacity:.35;transform:translate3d(18px,0,0)}}to{{opacity:1;transform:translate3d(0,0,0)}}}}@keyframes view-in-previous{{from{{opacity:.35;transform:translate3d(-18px,0,0)}}to{{opacity:1;transform:translate3d(0,0,0)}}}}@keyframes day-in-next{{from{{opacity:.45;transform:translate3d(13px,0,0)}}to{{opacity:1;transform:translate3d(0,0,0)}}}}@keyframes day-in-previous{{from{{opacity:.45;transform:translate3d(-13px,0,0)}}to{{opacity:1;transform:translate3d(0,0,0)}}}}
 .footer{{display:flex;justify-content:flex-end;gap:16px;margin-top:31px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}}.footer a{{color:var(--ink);font-weight:700}}
.theme-pink{{--paper:#fff8fb;--card:#ffffff;--ink:#382633;--muted:#8d7480;--line:#efdde7;--green:#c14d80;--green-soft:#f9dce8;--red:#bd536f;--red-soft:#fbe6ed;--blue:#aa5b9d;--shadow:0 14px 35px #38263312}}.theme-pink .mark,.theme-pink .lesson-card{{background:#382633}}.theme-pink .lesson-kicker{{color:#f3a7c6}}.theme-pink .view-switch{{background:#f9eaf1}}
@media (min-width:700px){{.app{{padding-top:48px}}.topbar{{margin-bottom:30px}}.lesson-card{{min-height:220px;padding:28px}}.lesson-card h2{{font-size:38px}}.next-card{{padding:19px 22px}}}}
@media (max-width:420px){{.app{{width:calc(100% - 24px)}}h1{{font-size:39px;margin-bottom:19px}}.lesson-card{{min-height:173px;padding:19px}}.lesson-card h2{{font-size:27px;margin-top:22px}}.next-card{{padding:15px 16px}}.next-card h3{{font-size:19px;max-width:205px}}.change-row{{grid-template-columns:70px 1fr;padding:12px}}.period-row{{grid-template-columns:1fr 86px}}.period-main{{padding-left:14px}}.period-info{{padding-right:11px}}}}
@media (prefers-reduced-motion:reduce){{*,*::before,*::after{{transition:none!important;animation:none!important}}}}
html[dir="rtl"] .identity,html[dir="rtl"] .source,html[dir="rtl"] .view-switch,html[dir="rtl"] .lesson-card,html[dir="rtl"] .next-card,html[dir="rtl"] .transit-wake-card,html[dir="rtl"] .changes,html[dir="rtl"] .exams,html[dir="rtl"] .full-schedule,html[dir="rtl"] .footer{{direction:rtl}}html[dir="rtl"] .lesson-time,html[dir="rtl"] .next-card .lesson-time{{text-align:left}}html[dir="rtl"] .period-main{{border-left:0;border-right:5px solid var(--slot-accent,#cbd6d2);padding-left:14px;padding-right:18px}}html[dir="rtl"] .period-row.is-gap .period-main{{border-right-color:#d6dfdc}}html[dir="rtl"] .period-info{{border-left:0;border-right:1px solid var(--line);align-items:flex-start;padding-left:13px;padding-right:5px;text-align:left}}html[dir="rtl"] .change-row,html[dir="rtl"] .exam-row{{border-left:1px solid var(--line);border-right:3px solid var(--green)}}html[dir="rtl"] .change-row.cancelled{{border-right-color:var(--red)}}html[dir="rtl"] .change-row.added{{border-right-color:var(--blue)}}html[dir="rtl"] .exam-row{{border-right-color:#d08c3f}}
 .period-info{{direction:ltr;unicode-bidi:isolate;font-variant-numeric:tabular-nums}}
 .period-info>strong,.period-info>.period-range,.lesson-time bdi{{direction:ltr;unicode-bidi:isolate;writing-mode:horizontal-tb;white-space:nowrap;display:inline-block;font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue","Arial",sans-serif;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}}
 .period-info>.period-range{{display:block;letter-spacing:-.02em}}
 .next-card .lesson-time bdi small{{display:inline;margin-top:0}}
 .view-panel-enter-next{{animation:view-in-next .46s cubic-bezier(.2,.8,.2,1) both}}.view-panel-enter-previous{{animation:view-in-previous .46s cubic-bezier(.2,.8,.2,1) both}}.day-surface-enter-next{{animation:day-in-next .42s cubic-bezier(.2,.8,.2,1) both}}.day-surface-enter-previous{{animation:day-in-previous .42s cubic-bezier(.2,.8,.2,1) both}}
 .alarm-self-service{{margin:18px 0 29px;padding:17px 18px;border:1px solid var(--line);border-radius:18px;background:var(--card);box-shadow:0 5px 16px #142b3508}}.alarm-self-service .section-title{{margin-bottom:9px}}.alarm-self-service .section-title h2{{font-size:21px}}.alarm-panel[hidden]{{display:none}}.alarm-help{{margin:0 0 13px;color:var(--muted);font-size:12px;line-height:1.4}}.alarm-actions{{display:grid;gap:9px}}.alarm-action{{min-height:42px;padding:10px 13px;border:1px solid var(--line);border-radius:11px;background:var(--paper);color:var(--ink);font:inherit;font-size:13px;font-weight:750;cursor:pointer;text-align:start}}.alarm-action-danger{{border-color:#f1d0d0;color:var(--red)}}.alarm-action:disabled,.alarm-self-service .small-button:disabled{{cursor:not-allowed;opacity:.55}}.alarm-time-row{{display:grid;grid-template-columns:1fr auto;align-items:center;gap:9px}}.alarm-time-row label{{grid-column:1 / -1;color:var(--muted);font-size:12px;font-weight:700}}.alarm-time-row input{{width:100%;min-height:42px;padding:8px 10px;border:1px solid var(--line);border-radius:11px;background:var(--paper);color:var(--ink);font:inherit;font-variant-numeric:tabular-nums}}.alarm-time-row input:focus{{outline:3px solid #8ecdc055;border-color:#8ecdc0}}.alarm-status{{min-height:18px;margin:10px 0 0;color:var(--green);font-size:12px;line-height:1.4}}.alarm-status:empty{{display:none}}
 {gate_css}
</style></head><body class="{theme_class}{' site-locked' if profile_id == 'ya1' else ''}">{gate_html}{gate_script}<main class="app">
<header class="topbar"><a class="identity" href="."><img class="mark" src="./header-logo.png" alt="" aria-hidden="true"><span><strong>My schedule</strong></span></a></header>
  <nav class="view-switch" aria-label="Schedule views"><button id="now-tab" class="is-active" type="button" aria-selected="true">Now</button><button id="full-tab" type="button" aria-selected="false">Schedule</button><button id="exams-tab" type="button" aria-selected="false">Exams</button></nav>
<section id="now-view" class="live-area" aria-labelledby="today-title"><p id="today-label" class="date-line">Loading today’s schedule…</p>{status}<h1 id="today-title">Today’s schedule</h1><article class="lesson-card" id="current-lesson"><span class="lesson-kicker">Now</span><h2 id="current-subject">Checking…</h2><p id="current-detail" class="lesson-detail"></p><div id="current-time" class="lesson-time"></div></article><article class="next-card" id="next-lesson"><div><span class="lesson-kicker">Next up</span><h3 id="next-subject">Checking…</h3><p id="next-detail" class="lesson-detail"></p></div><div id="next-time" class="lesson-time"></div></article><p id="schedule-note" class="date-line" style="margin:10px 2px 0;font-size:12px"></p>{transit_html}{alarm_html}</section>
<section id="full-view" class="full-schedule" hidden aria-labelledby="full-title"><div class="schedule-heading"><div><p class="eyebrow">Every period</p><h2 id="full-title">Schedule</h2></div><button id="back-to-now" class="small-button" type="button">Back to now</button></div><div id="full-day-surface" class="day-surface"><div id="day-picker" class="day-picker" role="listbox" aria-label="Choose a school day"></div><div id="full-day-content" class="day-content"><div id="day-notice" class="day-notice" role="status" hidden></div><div class="selected-day"><div><h3 id="selected-day-title">Loading…</h3><p id="selected-day-summary"></p></div><button id="jump-today" class="small-button" type="button">Today</button></div><div id="schedule-periods" class="period-list"></div></div></div></section>
 {exams_html}
 {changes_html}
<footer class="footer"><a id="footer-source-link" href="shfmobile://" rel="noreferrer">Open Shahaf app ↗</a></footer>
</main><script>
const uiTranslations = {ui_translations_json};
const uiLocale = shahafIsHebrew ? "he-IL" : "en-US";
const uiCopy = uiTranslations[shahafIsHebrew ? "he" : "en"];
const tr = (key) => uiCopy[key] || uiTranslations.en[key] || key;
const setUiText = (selector, key) => {{ const element = document.querySelector(selector); if (element) element.textContent = tr(key); }};
document.querySelectorAll("[data-i18n]").forEach((element) => {{ element.textContent = tr(element.dataset.i18n); }});
setUiText(".identity strong", "mySchedule");
const viewSwitch = document.querySelector(".view-switch"); if (viewSwitch) viewSwitch.setAttribute("aria-label", tr("scheduleViews"));
 setUiText("#now-tab", "now"); setUiText("#full-tab", "fullSchedule"); setUiText("#exams-tab", "exams");
setUiText("#today-label", "loadingToday"); setUiText("#today-title", "todaysSchedule");
setUiText("#current-subject", "checking"); setUiText("#next-subject", "checking");
const lessonKickers = document.querySelectorAll(".lesson-kicker"); if (lessonKickers[0]) lessonKickers[0].textContent = tr("now"); if (lessonKickers[1]) lessonKickers[1].textContent = tr("nextUp");
setUiText("#full-title", "fullSchedule"); setUiText(".schedule-heading .eyebrow", "everyPeriod"); setUiText("#back-to-now", "backToNow"); setUiText("#jump-today", "today");
const dayPicker = document.getElementById("day-picker"); if (dayPicker) dayPicker.setAttribute("aria-label", tr("chooseSchoolDay"));
const footerSource = document.getElementById("footer-source-link");
const shahafAppUrl = "shfmobile://";
const shahafStoreUrl = "itms-apps://itunes.apple.com/app/id1368425766";
const openShahafApp = (event) => {{
  event.preventDefault();
  const isAppleMobile = /iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (!isAppleMobile) {{ window.location.href = shahafStoreUrl; return; }}
  let handedOff = false;
  const fallback = window.setTimeout(() => {{ if (!handedOff && !document.hidden) window.location.href = shahafStoreUrl; }}, 1800);
  const onVisibilityChange = () => {{ if (!document.hidden) return; handedOff = true; window.clearTimeout(fallback); document.removeEventListener("visibilitychange", onVisibilityChange); }};
  document.addEventListener("visibilitychange", onVisibilityChange);
  window.setTimeout(() => document.removeEventListener("visibilitychange", onVisibilityChange), 2200);
  window.location.href = shahafAppUrl;
}};
if (footerSource) {{ footerSource.textContent = tr("openShahaf") + " ↗"; footerSource.setAttribute("aria-label", tr("openShahaf")); footerSource.addEventListener("click", openShahafApp); }}
if (shahafIsHebrew) document.title = tr("mySchedule");
 const publicAlarmEndpoint = {alarm_command_url_json};
 const activeProfile = {primary_profile_json};
 const periods = {periods_json};
const scheduleZone = "Asia/Jerusalem";
const dateFormatter = new Intl.DateTimeFormat(uiLocale, {{ weekday: "long", month: "long", day: "numeric", timeZone: scheduleZone }});
const shortDateFormatter = new Intl.DateTimeFormat(uiLocale, {{ weekday: "short", month: "short", day: "numeric", timeZone: scheduleZone }});
const palette = ["#d16d8e", "#78c8cb", "#f0bd47", "#76c983", "#8796df", "#d88a54"];
let schedule = activeProfile.schedule || [];
let scheduleAvailable = Boolean(activeProfile.schedule_available);
let changes = activeProfile.changes || [];
let events = activeProfile.events || [];
 let exams = activeProfile.exams || [];
 const transitWake = activeProfile.transit_wake || null;
function nowInSchoolZone() {{ const parts = new Intl.DateTimeFormat("en-CA", {{ timeZone: scheduleZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }}).formatToParts(new Date()); const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value])); return {{ date: `${{values.year}}-${{values.month}}-${{values.day}}`, minutes: Number(values.hour) * 60 + Number(values.minute) }}; }}
function installAlarmSelfService() {{
  const card = document.getElementById("alarm-self-service");
  if (!card || !publicAlarmEndpoint) return;
  const toggle = document.getElementById("alarm-self-service-toggle");
  const panel = document.getElementById("alarm-self-service-panel");
  const cancel = document.getElementById("alarm-cancel-today");
  const move = document.getElementById("alarm-move-today");
  const restore = document.getElementById("alarm-restore");
  const keep = document.getElementById("alarm-keep-current");
  const time = document.getElementById("alarm-move-time");
  const status = document.getElementById("alarm-self-service-status");
  const controls = [toggle, cancel, move, restore, keep, time].filter(Boolean);
  const setBusy = (busy) => controls.forEach((control) => {{ control.disabled = busy; }});
  const close = () => {{ panel.hidden = true; toggle.setAttribute("aria-expanded", "false"); }};
  const submit = async (action) => {{
    const payload = {{ action }};
    const messageKey = action === "clear" ? "alarmCancelQueued" : action === "restore" ? "alarmRestoreQueued" : "alarmMoveQueued";
    if (action === "set") payload.wake_time = time.value;
    setBusy(true);
    status.textContent = tr("alarmSaving");
    try {{
      const response = await fetch(publicAlarmEndpoint, {{ method: "POST", mode: "cors", headers: {{ "content-type": "application/json" }}, body: JSON.stringify(payload) }});
      const body = await response.json().catch(() => ({{}}));
      if (!response.ok) throw new Error(body.error || tr("alarmError"));
      status.textContent = tr(messageKey);
      close();
    }} catch (error) {{
      status.textContent = error.message || tr("alarmError");
    }} finally {{
      setBusy(false);
    }}
  }};
  toggle.addEventListener("click", () => {{
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) time.focus();
  }});
  keep.addEventListener("click", close);
  cancel.addEventListener("click", () => {{ if (window.confirm(tr("alarmConfirmCancel"))) submit("clear"); }});
  restore.addEventListener("click", () => {{ if (window.confirm(tr("alarmConfirmRestore"))) submit("restore"); }});
  move.addEventListener("click", () => {{
    if (!time.value) {{ status.textContent = tr("alarmFutureTime"); return; }}
    if (window.confirm(tr("alarmConfirmMove").replace("{{time}}", time.value))) submit("set");
  }});
}}
function minutes(value) {{ const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }}
function formatTime(value) {{ const [hour, minute] = value.split(":").map(Number); if (shahafIsHebrew) return `${{String(hour).padStart(2, "0")}}:${{String(minute).padStart(2, "0")}}`; return `${{hour % 12 || 12}}:${{String(minute).padStart(2, "0")}} ${{hour >= 12 ? "PM" : "AM"}}`; }}
function escapeHtml(value) {{ return String(value ?? "").replace(/[&<>]/g, (char) => ({{"&":"&amp;","<":"&lt;",">":"&gt;"}}[char])).replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }}
function detail(item) {{ return [item.teacher, item.room ? `${{tr("room")}} ${{item.room}}` : "", `${{tr("period")}} ${{item.period}}`].filter(Boolean).join(" · "); }}
function renderTransitWake() {{ if (!transitWake) return; const card = document.getElementById("transit-wake-card"); const summary = document.getElementById("transit-summary"); const legs = document.getElementById("transit-legs"); const status = document.getElementById("transit-status"); const map = document.getElementById("transit-map"); if (!card || !summary || !legs || !status || !map) return; map.href = transitWake.google_maps_url || "#"; const action = transitWake.shortcut_action; card.classList.toggle("is-warning", action !== "set"); if (action === "set" && transitWake.route_departure && transitWake.route_arrival) {{ status.textContent = "Ready"; summary.textContent = `Leave home at ${{formatTime(transitWake.route_departure)}} · arrive by ${{formatTime(transitWake.route_arrival)}}`; legs.innerHTML = (transitWake.route || []).map((leg) => {{ if (leg.type === "transit") return `<div class="transit-leg"><strong>Bus ${{escapeHtml(leg.route)}}</strong><div>${{escapeHtml(leg.departure)}} ← ${{escapeHtml(leg.arrival)}}<span>${{escapeHtml(leg.from_stop)}} ← ${{escapeHtml(leg.to_stop)}}</span></div></div>`; return `<div class="transit-leg"><strong>Walk</strong><div>${{escapeHtml(leg.minutes)}} min<span>${{escapeHtml(leg.from)}} ← ${{escapeHtml(leg.to)}}</span></div></div>`; }}).join(""); return; }} status.textContent = action === "clear" ? "No route needed" : "Alarm unchanged"; summary.textContent = action === "clear" ? "No confirmed lessons are scheduled." : "Transit data is unavailable, so the existing alarm stays unchanged."; legs.innerHTML = ""; }}
 function setLesson(id, item, emptyText, emptyDetail) {{ const card = document.getElementById(id); const subject = card.querySelector("h2, h3"); const detailTarget = card.querySelector(".lesson-detail"); const time = card.querySelector(".lesson-time"); card.classList.toggle("is-empty", !item); subject.textContent = item ? item.subject : emptyText; detailTarget.textContent = item ? detail(item) : emptyDetail; time.innerHTML = item ? `<bdi dir="ltr">${{formatTime(item.start)}}<small>–${{formatTime(item.end)}}</small></bdi>` : ""; }}
function refreshLiveLessons() {{ const now = nowInSchoolZone(); document.getElementById("today-label").textContent = dateFormatter.format(new Date()); if (!scheduleAvailable) {{ setLesson("current-lesson", null, "Schedule unavailable", "The synced timetable is not available yet"); setLesson("next-lesson", null, "Try again later", "The live timetable will appear after the next successful sync"); return; }} const ordered = [...schedule].sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.period - b.period); const today = ordered.filter((item) => item.date === now.date); const current = today.find((item) => minutes(item.start) <= now.minutes && now.minutes < minutes(item.end)); const next = ordered.find((item) => item.date > now.date || (item.date === now.date && minutes(item.start) > now.minutes)); setLesson("current-lesson", current, "No class right now", today.length ? "You’re between lessons" : "No lessons scheduled today"); setLesson("next-lesson", next, "No more lessons", "Nothing else is scheduled in the synced timetable"); document.getElementById("schedule-note").textContent = current ? `You’re in Period ${{current.period}} now` : next ? `Next lesson: Period ${{next.period}}` : "You’re all done for the synced schedule"; }}
function schoolDate(value) {{ return new Date(`${{value}}T12:00:00Z`); }}
function isAsyncDayEvent(event) {{ const text = `${{event.title || ""}} ${{event.detail || ""}}`.toLowerCase(); return event.classification === "no_school" || text.includes("יום למידה א-סינכרוני") || text.includes("יום למידה אסינכרוני") || text.includes("יום למידה א סינכרוני") || text.includes("async learning day"); }}
function asyncEventFor(targetDate) {{ return events.find((event) => event.date === targetDate && isAsyncDayEvent(event)) || null; }}
function scheduleDates() {{ return [...new Set([...schedule.map((item) => item.date), ...events.filter(isAsyncDayEvent).map((event) => event.date)])].sort(); }}
let selectedDayDate = null;
function animateElement(element, className) {{ if (!element || !className) return; element.classList.remove("day-surface-enter-next", "day-surface-enter-previous", "view-panel-enter-next", "view-panel-enter-previous"); void element.offsetWidth; element.classList.add(className); window.setTimeout(() => element.classList.remove(className), 500); }}
 function isolatePeriodNumerics() {{ document.querySelectorAll(".period-info > strong, .period-range").forEach((element) => {{ if (element.dataset.numericIsolated === "1") return; const value = element.textContent || ""; const bdi = document.createElement("bdi"); bdi.dir = "ltr"; bdi.textContent = value; element.textContent = ""; element.appendChild(bdi); element.dataset.numericIsolated = "1"; }}); }}
 const renderFullDayWithNumericIsolation = renderFullDay;
 renderFullDay = (targetDate, direction = "") => {{ renderFullDayWithNumericIsolation(targetDate, direction); isolatePeriodNumerics(); }};
 function selectDay(targetDate) {{ const dates = scheduleDates(); const targetIndex = dates.indexOf(targetDate); const currentIndex = dates.indexOf(selectedDayDate); if (targetIndex < 0) return; if (targetIndex === currentIndex || currentIndex < 0) {{ renderFullDay(targetDate); return; }} renderFullDay(targetDate, targetIndex > currentIndex ? "next" : "previous"); }}
function renderDayPicker(selected) {{ const picker = document.getElementById("day-picker"); const dates = scheduleDates(); if (!dates.length) {{ picker.innerHTML = `<div class="empty-day">No school days are available yet.</div>`; return; }} picker.innerHTML = dates.map((date) => `<button class="day-chip ${{date === selected ? "is-selected" : ""}}" type="button" role="option" aria-selected="${{date === selected}}" data-date="${{escapeHtml(date)}}">${{escapeHtml(shortDateFormatter.format(schoolDate(date)))}}</button>`).join(""); picker.querySelectorAll(".day-chip").forEach((button) => button.addEventListener("click", () => selectDay(button.dataset.date))); }}
function renderFullDay(targetDate, direction = "") {{ const dates = scheduleDates(); if (!dates.length) {{ document.getElementById("schedule-periods").innerHTML = `<div class="empty-day">The full schedule will appear after a successful sync.</div>`; return; }} const selected = dates.includes(targetDate) ? targetDate : dates[0]; selectedDayDate = selected; renderDayPicker(selected); const asyncEvent = asyncEventFor(selected); const notice = document.getElementById("day-notice"); if (notice) {{ notice.hidden = !asyncEvent; notice.innerHTML = asyncEvent ? `<strong>${{escapeHtml(tr("asyncDay"))}}</strong><span>${{escapeHtml(tr("asyncDayDetail"))}}</span>` : ""; }} const items = schedule.filter((item) => item.date === selected); const byPeriod = Object.fromEntries(items.map((item) => [item.period, item])); const lessonPeriods = items.map((item) => Number(item.period)).filter((period) => Number.isInteger(period)); const firstLessonPeriod = lessonPeriods.length ? Math.min(...lessonPeriods) : null; const lastLessonPeriod = lessonPeriods.length ? Math.max(...lessonPeriods) : null; const day = schoolDate(selected); document.getElementById("selected-day-title").textContent = dateFormatter.format(day); document.getElementById("selected-day-summary").textContent = `${{items.length}} lesson${{items.length === 1 ? "" : "s"}} · gaps included`; document.getElementById("schedule-periods").innerHTML = periods.map((slot) => {{ const item = byPeriod[slot.period]; const outsideSchoolDay = firstLessonPeriod === null || slot.period < firstLessonPeriod || slot.period > lastLessonPeriod; const emptyKind = outsideSchoolDay ? "no-lesson" : "gap"; const accent = palette[slot.period % palette.length]; return `<article class="period-row ${{item ? "has-lesson" : "is-gap"}}" style="--slot-accent:${{accent}}"><div class="period-main">${{item ? `<strong>${{escapeHtml(item.subject)}}</strong><span>${{escapeHtml([item.teacher, item.room ? `${{tr("room")}} ${{item.room}}` : ""].filter(Boolean).join(" · ") || tr("lesson"))}}</span>` : `<span class="gap-label" data-empty-kind="${{emptyKind}}">${{tr(emptyKind === "no-lesson" ? "noLesson" : "gap")}}</span>`}}</div><div class="period-info" dir="ltr"><strong><bdi>${{slot.period}}</bdi></strong><span class="period-range" dir="ltr"><bdi>${{formatTime(slot.start)}}</bdi>–<bdi>${{formatTime(slot.end)}}</bdi></span></div></article>`; }}).join(""); const surface = document.getElementById("full-day-content"); if (direction) animateElement(surface, direction === "next" ? "day-surface-enter-next" : "day-surface-enter-previous"); }}
function changeIsPast(change) {{ const now = nowInSchoolZone(); if (change.date < now.date) return true; if (change.date > now.date) return false; const slot = periods.find((item) => item.period === Number(change.period)); return slot ? now.minutes >= minutes(slot.end) : false; }}
function renderChanges() {{ const list = document.getElementById("change-list"); const count = document.getElementById("changes-count"); const visible = changes.filter((item) => !changeIsPast(item)); count.textContent = String(visible.length); if (!visible.length) {{ list.innerHTML = `<div class="quiet">No upcoming cancellations or updates.</div>`; return; }} list.innerHTML = visible.map((item) => {{ const label = item.kind === "cancelled" ? "Cancelled" : item.kind === "added" ? "Added" : "Changed"; const subject = item.subject || "Schedule update"; return `<article class="change-row ${{escapeHtml(item.kind)}}"><div class="change-date"><strong>${{escapeHtml(item.date.split("-").reverse().join("."))}}</strong><span>Period ${{escapeHtml(item.period)}}</span></div><div class="change-body"><div><span class="change-label">${{label}}</span><h3>${{escapeHtml(subject)}}</h3></div><p>${{escapeHtml(item.detail || "Schedule update")}}</p></div></article>`; }}).join(""); }}
 function renderExams() {{ const list = document.getElementById("exam-list"); const count = document.getElementById("exams-count"); count.textContent = String(exams.length); if (!exams.length) {{ list.innerHTML = `<div class="quiet">No upcoming exams found for this profile.</div>`; return; }} list.innerHTML = exams.map((item) => {{ let periodText = String(item.start_period); if (item.end_period !== item.start_period) periodText += `–${{item.end_period}}`; const roomText = item.room ? `${{tr("room")}} ${{item.room}}` : ""; return `<article class="exam-row"><div class="exam-date"><strong>${{escapeHtml(item.date.split("-").reverse().join("."))}}</strong><span>Periods ${{escapeHtml(periodText)}}</span></div><div class="exam-body"><h3>${{escapeHtml(item.subject)}}</h3>${{roomText ? `<p class="exam-room">${{escapeHtml(roomText)}}</p>` : ""}}</div></article>`; }}).join(""); }}
 function currentView() {{ return document.getElementById("exams-view").hidden ? (document.getElementById("full-view").hidden ? "now" : "full") : "exams"; }}
 function setView(view) {{ const previous = currentView(); const views = ["now", "full", "exams"]; const previousIndex = views.indexOf(previous); const nextIndex = views.indexOf(view); const full = view === "full"; const examsView = view === "exams"; document.getElementById("now-view").hidden = full || examsView; document.getElementById("full-view").hidden = !full; document.getElementById("exams-view").hidden = !examsView; document.getElementById("changes-view").hidden = full || examsView; document.getElementById("now-tab").classList.toggle("is-active", view === "now"); document.getElementById("full-tab").classList.toggle("is-active", full); document.getElementById("exams-tab").classList.toggle("is-active", examsView); document.getElementById("now-tab").setAttribute("aria-selected", String(view === "now")); document.getElementById("full-tab").setAttribute("aria-selected", String(full)); document.getElementById("exams-tab").setAttribute("aria-selected", String(examsView)); if (full) {{ const today = nowInSchoolZone().date; renderFullDay(scheduleDates().includes(today) ? today : scheduleDates()[0]); }} if (previous !== view && previousIndex >= 0 && nextIndex >= 0) animateElement(document.getElementById(view === "now" ? "now-view" : view === "full" ? "full-view" : "exams-view"), nextIndex > previousIndex ? "view-panel-enter-next" : "view-panel-enter-previous"); window.scrollTo({{top: 0, behavior: "smooth"}}); }}
function localizeRenderedUi() {{
  document.querySelectorAll("#change-list .change-label").forEach((element) => {{ element.textContent = element.textContent === "Cancelled" ? tr("cancelled") : element.textContent === "Added" ? tr("added") : tr("changed"); }});
  document.querySelectorAll("#change-list h3").forEach((element) => {{ if (element.textContent === "Schedule update") element.textContent = tr("scheduleUpdate"); }});
  document.querySelectorAll("#change-list .change-date span").forEach((element) => {{ element.textContent = element.textContent.replace(/^Period /, tr("period") + " "); }});
  document.querySelectorAll("#exam-list .exam-date span").forEach((element) => {{ element.textContent = element.textContent.replace(/^Periods? /, tr("periods") + " "); }});
  document.querySelectorAll("#change-list .quiet").forEach((element) => {{ element.textContent = tr("noUpcomingChanges"); }});
   document.querySelectorAll("#exam-list .quiet").forEach((element) => {{ element.textContent = tr("noUpcomingExams"); }});
  document.querySelectorAll("#schedule-periods .gap-label").forEach((element) => {{ element.textContent = tr(element.dataset.emptyKind === "no-lesson" ? "noLesson" : "gap"); }});
  document.querySelectorAll("#schedule-periods .period-main span").forEach((element) => {{ element.textContent = element.textContent.replace("Room ", tr("room") + " ").replace(/^Lesson$/, tr("lesson")); }});
  document.querySelectorAll("#schedule-periods .empty-day").forEach((element) => {{ element.textContent = tr("timetableAfterSync"); }});
  document.querySelectorAll("#day-picker .empty-day").forEach((element) => {{ element.textContent = tr("noSchoolDays"); }});
  const transitCard = document.getElementById("transit-wake-card");
  if (transitCard) {{
    const status = document.getElementById("transit-status"); const summary = document.getElementById("transit-summary");
    if (status) status.textContent = status.textContent === "Ready" ? tr("ready") : status.textContent === "No route needed" ? tr("noRouteNeeded") : status.textContent === "Alarm unchanged" ? tr("alarmUnchanged") : status.textContent === "Checking" ? tr("checking") : status.textContent;
    if (summary && summary.textContent.indexOf("Leave home at ") === 0) {{ const parts = summary.textContent.slice(14).split(" · arrive by "); summary.textContent = tr("leaveHome") + " " + parts[0] + " · " + tr("arriveBy") + " " + (parts[1] || ""); }}
    if (summary && summary.textContent === "No confirmed lessons are scheduled.") summary.textContent = tr("noLessonsScheduled");
    if (summary && summary.textContent === "Transit data is unavailable, so the existing alarm stays unchanged.") summary.textContent = tr("transitUnavailable");
    transitCard.querySelectorAll(".transit-leg strong").forEach((element) => {{ if (element.textContent.indexOf("Bus ") === 0) element.textContent = (shahafIsHebrew ? "אוטובוס " : "Bus ") + element.textContent.slice(4); if (element.textContent === "Walk") element.textContent = shahafIsHebrew ? "הליכה" : "Walk"; }});
    transitCard.querySelectorAll(".transit-leg div").forEach((element) => {{ element.childNodes.forEach((node) => {{ if (node.nodeType === Node.TEXT_NODE) node.textContent = node.textContent.replace(/ min$/, shahafIsHebrew ? " דקות" : " min"); }}); }});
  }}
}}
const localizeLiveState = () => {{ const current = document.getElementById("current-subject"); const currentDetail = document.getElementById("current-detail"); const next = document.getElementById("next-subject"); const nextDetail = document.getElementById("next-detail"); const note = document.getElementById("schedule-note"); if (current) {{ if (current.textContent === "Schedule unavailable") current.textContent = tr("scheduleUnavailable"); else if (current.textContent === "No class right now") current.textContent = tr("noClassRightNow"); }} if (currentDetail) {{ if (currentDetail.textContent === "The synced timetable is not available yet") currentDetail.textContent = tr("timetableAfterSync"); else if (currentDetail.textContent === "You’re between lessons") currentDetail.textContent = tr("betweenLessons"); else if (currentDetail.textContent === "No lessons scheduled today") currentDetail.textContent = tr("noLessonsToday"); }} if (next) {{ if (next.textContent === "Try again later") next.textContent = tr("tryAgain"); else if (next.textContent === "No more lessons") next.textContent = tr("noMoreLessons"); }} if (nextDetail && nextDetail.textContent === "Nothing else is scheduled in the synced timetable") nextDetail.textContent = tr("nothingElse"); if (note) {{ if (note.textContent.indexOf("You’re in Period ") === 0) note.textContent = tr("inPeriod") + " " + note.textContent.slice(17) + (shahafIsHebrew ? " עכשיו" : " now"); else if (note.textContent.indexOf("Next lesson: Period ") === 0) note.textContent = tr("nextLesson") + ": " + tr("period") + " " + note.textContent.slice(20); else if (note.textContent === "You’re all done for the synced schedule") note.textContent = tr("allDone"); }} }};
const baseRenderChanges = renderChanges; renderChanges = () => {{ baseRenderChanges(); localizeRenderedUi(); }};
const baseRenderExams = renderExams; renderExams = () => {{ baseRenderExams(); localizeRenderedUi(); }};
const baseRenderFullDay = renderFullDay; renderFullDay = (targetDate, direction) => {{ baseRenderFullDay(targetDate, direction); const summary = document.getElementById("selected-day-summary"); if (summary) {{ const count = document.querySelectorAll("#schedule-periods .has-lesson").length; summary.textContent = count + " " + (count === 1 ? tr("lessonSingular") : tr("lessons")) + " · " + tr("gapsIncluded"); }} localizeRenderedUi(); }};
const baseRefreshLiveLessons = refreshLiveLessons; refreshLiveLessons = () => {{ baseRefreshLiveLessons(); localizeLiveState(); }};
const baseRenderTransitWake = renderTransitWake; renderTransitWake = () => {{ baseRenderTransitWake(); localizeRenderedUi(); }};
 document.getElementById("now-tab").addEventListener("click", () => setView("now")); document.getElementById("full-tab").addEventListener("click", () => setView("full")); document.getElementById("exams-tab").addEventListener("click", () => setView("exams")); document.getElementById("back-to-now").addEventListener("click", () => setView("now")); document.getElementById("jump-today").addEventListener("click", () => {{ const today = nowInSchoolZone().date; scheduleDates().includes(today) ? selectDay(today) : renderFullDay(today); }});
function moveViewBy(delta) {{ const views = ["now", "full", "exams"]; const index = views.indexOf(currentView()); const target = index + delta; if (target >= 0 && target < views.length) setView(views[target]); }}
function moveDayBy(delta) {{ const dates = scheduleDates(); const index = dates.indexOf(selectedDayDate); const target = index + delta; if (target >= 0 && target < dates.length) renderFullDay(dates[target], delta > 0 ? "next" : "previous"); }}
function attachSwipe(surface, kind) {{ if (!surface) return; let swipeStart = null; surface.addEventListener("touchstart", (event) => {{ if (event.touches.length !== 1 || event.target.closest("button, a")) {{ swipeStart = null; return; }} const touch = event.touches[0]; swipeStart = {{ x: touch.clientX, y: touch.clientY }}; }}, {{ passive: true }}); surface.addEventListener("touchend", (event) => {{ if (!swipeStart || event.changedTouches.length !== 1) return; const touch = event.changedTouches[0]; const dx = touch.clientX - swipeStart.x; const dy = touch.clientY - swipeStart.y; swipeStart = null; if (Math.abs(dx) < 45 || Math.abs(dx) < Math.abs(dy) * 1.15) return; const next = shahafIsHebrew ? dx > 0 : dx < 0; const delta = next ? 1 : -1; if (kind === "days") moveDayBy(delta); else moveViewBy(delta); }}, {{ passive: true }}); surface.addEventListener("touchcancel", () => {{ swipeStart = null; }}, {{ passive: true }}); }}
attachSwipe(document.querySelector(".topbar"), "views");
attachSwipe(document.querySelector(".view-switch"), "views");
attachSwipe(document.querySelector(".schedule-heading"), "views");
attachSwipe(document.getElementById("day-picker"), "views");
attachSwipe(document.getElementById("full-day-content"), "days");
attachSwipe(document.getElementById("now-view"), "views");
attachSwipe(document.getElementById("changes-view"), "views");
attachSwipe(document.getElementById("exams-view"), "views");
 installAlarmSelfService(); renderChanges(); renderExams(); refreshLiveLessons(); renderTransitWake(); document.body.classList.add("app-ready"); setInterval(() => {{ refreshLiveLessons(); renderChanges(); }}, 30000); if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
</script></body></html>
'''
    (output_dir / "index.html").write_text(html, encoding="utf-8")
