from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import argparse
import json
import os
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .github import GistClient, GitHubError
from .events import apply_event_decisions, decision_allows_suppression, event_key, event_requires_review, event_to_dict, is_explicit_no_school
from .exams import reconcile_exam_events
from .ics import CalendarFormatError, parse_calendar
from .model import EventSnapshot, Lesson, SourceSnapshot
from .nim import EventSafetyDecision, NimError, NimSafetyClient, context_for_alarm_review, context_for_event_review
from .profiles import apply_changes, lesson_to_dict, select_changes, select_exams, select_lessons
from .profile_package import ProfilePackageError, build_package_schedule, package_to_spec, validate_package
from .reconcile import ChangeRecord, reconcile_calendar, reconcile_event_entries
from .shahaf import ShahafSourceError, parse_changes_html, parse_events_html, parse_exams_html, parse_timetable_html
from .site import archive_profile_site, build_schedule, build_wake_data, render_site
from .transit import (
    TransitSourceError,
    build_ya1_transit_wake,
    download_gtfs,
    load_gtfs,
)
from .ya1_schedule import build_ya1_schedule


class SyncFailure(RuntimeError):
    """A safe-to-report sync failure; no Gist write should occur."""


@dataclass(frozen=True, slots=True)
class Config:
    timezone: str
    source_base_url: str
    class_id: str
    gist_id: str
    gist_filename: str
    lookahead_days: int
    site_title: str
    site_dir: str
    class_number: int = 2
    additional_profiles: tuple[dict[str, object], ...] = ()
    transit: dict[str, object] | None = None
    special_requests: dict[str, object] | None = None


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["timezone", "source_base_url", "class_id", "gist_id", "gist_filename", "lookahead_days", "site_title", "site_dir"]
    missing = [key for key in required if key not in data]
    if missing:
        raise SyncFailure(f"Missing config keys: {', '.join(missing)}")
    profiles = data.get("additional_profiles", [])
    if not isinstance(profiles, list) or not all(isinstance(item, dict) for item in profiles):
        raise SyncFailure("additional_profiles must be a list of objects")
    special_requests = data.get("special_requests", {})
    if not isinstance(special_requests, dict):
        raise SyncFailure("special_requests must be an object")
    return Config(
        *(data[key] for key in required),
        int(data.get("class_number", 2)),
        tuple(profiles),
        data.get("transit") if isinstance(data.get("transit"), dict) else None,
        special_requests,
    )


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "ostrovsky-shahaf-sync/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise SyncFailure(f"Source returned HTTP {response.status}")
            return response.read().decode("utf-8")
    except (HTTPError, URLError, UnicodeDecodeError) as exc:
        raise SyncFailure(f"Could not read source: {exc}") from exc


def fetch_source(
    config: Config,
    today: date,
    class_id: str | None = None,
) -> tuple[SourceSnapshot, list[str]]:
    selected_class_id = class_id or config.class_id
    url = f"{config.source_base_url}?cls={selected_class_id}&tab=changes"
    try:
        html = fetch_text(url)
        return parse_changes_html(html, today, url, expected_class_id=selected_class_id), [url]
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf changes feed is not trustworthy: {exc}") from exc


def fetch_exams(
    config: Config,
    today: date,
    class_id: str | None = None,
    class_number: int | None = None,
    include_all: bool = False,
):
    selected_class_id = class_id or config.class_id
    url = f"{config.source_base_url}?cls={selected_class_id}&tab=exams"
    try:
        html = fetch_text(url)
        return parse_exams_html(
            html,
            today,
            url,
            expected_class_number=class_number if class_number is not None else config.class_number,
            expected_class_id=selected_class_id,
            include_all=include_all,
        )
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf exams feed is not trustworthy: {exc}") from exc


def fetch_events(
    config: Config,
    today: date,
    class_id: str | None = None,
) -> EventSnapshot:
    selected_class_id = class_id or config.class_id
    url = f"{config.source_base_url}?cls={selected_class_id}&tab=events"
    try:
        html = fetch_text(url)
        return parse_events_html(html, today, url, expected_class_id=selected_class_id)
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf events feed is not trustworthy: {exc}") from exc


def _now(config: Config) -> datetime:
    return datetime.now(ZoneInfo(config.timezone))


def _site_path(config: Config, root: Path) -> Path:
    return root / config.site_dir


def _previous_site_state(site_path: Path) -> dict[str, object]:
    try:
        data = json.loads((site_path / "data.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _profile_failure(
    spec: dict[str, object],
    previous: dict[str, object],
    current: datetime,
    error: str,
) -> dict[str, object]:
    if previous:
        result = dict(previous)
        result.setdefault("id", str(spec.get("id", "profile")))
        result.setdefault("label", str(spec.get("label", "Additional profile")))
        result.setdefault("mark", str(spec.get("mark", "XI")))
        result.setdefault("class_id", str(spec.get("class_id", "")))
        result["stale"] = True
        result["error"] = error
        result.setdefault("events", [])
        result["events_available"] = False
        result["events_error"] = error
        return result
    return {
        "id": str(spec.get("id", "profile")),
        "label": str(spec.get("label", "Additional profile")),
        "mark": str(spec.get("mark", "XI")),
        "class_id": str(spec.get("class_id", "")),
        "schedule": [],
        "schedule_available": False,
        "changes": [],
        "exams": [],
        "exams_available": False,
        "events": [],
        "events_available": False,
        "events_error": error,
        "source_updated": "",
        "last_successful_sync": "",
        "stale": True,
        "error": error,
        "generated_at": current.isoformat(),
        "alarm_settings": spec.get("alarm_settings") if spec.get("managed_profile") else None,
        "alarm_override": spec.get("alarm_override") if spec.get("managed_profile") else None,
    }


def _stale_transit_payload(config: Config, current: datetime, error: str) -> dict[str, object]:
    transit_spec = config.transit or {}
    payload = build_ya1_transit_wake(
        None,
        [],
        now=current,
        origin=(0.0, 0.0),
        destination=(0.0, 0.0),
        stale=True,
        origin_address=str(transit_spec.get("origin_address", "מרדכי זעירא 5, רעננה")),
        destination_address=str(transit_spec.get("destination_address", "אוסטרובסקי 26, רעננה")),
    )
    payload["error"] = error
    return payload


def _dict_change(change: ChangeRecord) -> dict[str, object]:
    return {
        "kind": change.kind,
        "date": change.date.isoformat(),
        "period": change.period,
        "subject": change.subject,
        "detail": change.detail,
    }


def _dict_exam(exam: object) -> dict[str, object]:
    if isinstance(exam, dict):
        return {str(key): value for key, value in exam.items()}
    return {
        "date": exam.date.isoformat(),
        "subject": exam.subject,
        "start_period": exam.start_period,
        "end_period": exam.end_period,
        "detail": exam.detail,
        "group": exam.group,
    }


@dataclass(frozen=True, slots=True)
class EventProcessing:
    events: list[dict[str, object]]
    schedule: list[dict[str, object]]
    decisions: dict[tuple[object, ...], object]
    alarm_safety: str
    alarm_safety_reason: str


def _process_events(
    *,
    snapshot: EventSnapshot | None,
    schedule: list[dict[str, object]],
    exams: list[object],
    class_number: int,
    current: datetime,
    profile_id: str,
    nim_client: NimSafetyClient | None,
) -> EventProcessing:
    if snapshot is None:
        return EventProcessing([], schedule, {}, "blocked", "Shahaf events are unavailable; preserving the current alarm.")
    relevant = [event for event in snapshot.events if event.applies_to_class(class_number)]
    decisions: dict[tuple[object, ...], object] = {}
    blocked_reasons: list[str] = []
    approved_reasons: list[str] = []
    for event in relevant:
        if not event_requires_review(event):
            continue
        event_data = event_to_dict(event)
        event_date = event.date.isoformat()
        lessons_on_date = [item for item in schedule if str(item.get("date", "")) == event_date]
        exams_on_date = [
            _dict_exam(item)
            for item in exams
            if getattr(item, "date", None) is not None and item.date.isoformat() == event_date
        ]
        if is_explicit_no_school(event):
            decision: object = EventSafetyDecision(
                "no_school",
                True,
                "low",
                "Shahaf explicitly marks this date as an asynchronous learning day with no in-person school.",
            )
        elif nim_client is None:
            decision: object = EventSafetyDecision(
                "uncertain",
                False,
                "high",
                "NVIDIA_API_KEY is not configured; preserving the current schedule and alarm.",
            )
        else:
            try:
                decision = nim_client.classify_event(
                    context_for_event_review(
                        profile=profile_id,
                        event=event_data,
                        lessons_on_date=lessons_on_date,
                        exams_on_date=exams_on_date,
                        now=current.isoformat(),
                    )
                )
            except NimError as exc:
                decision = EventSafetyDecision("uncertain", False, "high", str(exc))
        decisions[event_key(event)] = decision
        if decision_allows_suppression(decision):
            approved_reasons.append(f"{event.title}: {decision.reason}")
        elif str(getattr(decision, "classification", "uncertain")) in {"uncertain", "no_school", "remote_learning"}:
            blocked_reasons.append(f"{event.title}: {decision.reason}")

    filtered_schedule = apply_event_decisions(schedule, relevant, decisions)
    serialized = [event_to_dict(event, decisions.get(event_key(event))) for event in relevant]
    if blocked_reasons:
        return EventProcessing(
            serialized,
            filtered_schedule if not blocked_reasons else schedule,
            decisions,
            "blocked",
            "Event review required: " + " | ".join(blocked_reasons),
        )
    if approved_reasons:
        return EventProcessing(
            serialized,
            filtered_schedule,
            decisions,
            "approved",
            "Event review approved: " + " | ".join(approved_reasons),
        )
    return EventProcessing(
        serialized,
        schedule,
        decisions,
        "not-required",
        "Ordinary Shahaf events are overlays; normal lessons and alarms remain unchanged.",
    )


def _alarm_safety(
    *,
    wake: dict[str, object],
    changes: list[ChangeRecord],
    schedule: list[dict[str, object]],
    exams: list[object],
    current: datetime,
    event_alarm_safety: str = "not-required",
    event_alarm_safety_reason: str = "",
) -> tuple[str, str]:
    """Return approved/not-required/blocked without ever failing the sync.

    Normal future alarms need no model call. NIM is used for destructive
    cases: clearing an alarm, or replacing today's alarm after a same-day
    Shahaf change. Missing credentials and every model/API/schema failure are
    deliberately treated as blocked, so the iPhone keeps its current alarm.
    """
    action = str(wake.get("shortcut_action", "leave"))
    if event_alarm_safety == "blocked":
        return "blocked", event_alarm_safety_reason or "Event review was unavailable; preserving the current alarm."
    today = current.date().isoformat()
    today_changes = [_dict_change(item) for item in changes if item.date.isoformat() == today]
    needs_review = action == "clear" or (action == "set" and bool(today_changes))
    if not needs_review:
        if event_alarm_safety == "approved":
            return "approved", event_alarm_safety_reason or "Event review approved the alarm change."
        return "not-required", "No destructive schedule change needs AI review."
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        return "blocked", "NVIDIA_API_KEY is not configured; preserving the current alarm."

    today_lessons = [item for item in schedule if str(item.get("date", "")) == today]
    today_exams = [_dict_exam(item) for item in exams if getattr(item, "date", None) and item.date.isoformat() == today]
    candidate = {
        "shortcut_action": action,
        "alarm_for_today": bool(wake.get("alarm_for_today")),
        "next_school_day": wake.get("next_school_day"),
        "wake_at": wake.get("wake_at"),
        "subject": wake.get("subject"),
        "stale": bool(wake.get("stale")),
    }
    context = context_for_alarm_review(
        candidate=candidate,
        changes= today_changes,
        today_lessons=today_lessons,
        today_exams=today_exams,
        now=current.isoformat(),
    )
    try:
        decision = NimSafetyClient(
            api_key,
            model=os.environ.get("NVIDIA_NIM_MODEL") or "openai/gpt-oss-20b",
        ).classify(context)
    except NimError as exc:
        return "blocked", str(exc)
    if not decision.safe_to_delete_alarm or decision.risk_level != "low":
        return "blocked", f"NIM preserved the alarm: {decision.reason}"
    return "approved", f"NIM approved the alarm change: {decision.reason}"


def _build_public_profile(
    config: Config,
    spec: dict[str, object],
    current: datetime,
    *,
    events_snapshot: EventSnapshot | None = None,
    nim_client: NimSafetyClient | None = None,
) -> dict[str, object]:
    profile_id = str(spec.get("id", "profile"))
    class_id = str(spec.get("class_id", ""))
    class_number = int(spec.get("class_number", 0))
    if not class_id:
        raise SyncFailure(f"Profile {profile_id} has no class_id")
    window_start = current.date()
    window_end = window_start + timedelta(days=config.lookahead_days)

    lessons: list[Lesson] = []
    update_text = ""
    if spec.get("baseline") == "transcribed":
        selected_lessons = build_ya1_schedule(window_start, window_end)
    elif spec.get("baseline") == "package":
        package = spec.get("package")
        if not isinstance(package, dict):
            raise SyncFailure(f"Profile {profile_id} has no imported package")
        selected_lessons = build_package_schedule(package, window_start, window_end)
    else:
        for week in range(4):
            suffix = f"&week={week}" if week else ""
            url = f"{config.source_base_url}?cls={class_id}&tab=changestable{suffix}"
            snapshot = parse_timetable_html(fetch_text(url), current.date(), url)
            update_text = snapshot.update_text or update_text
            lessons.extend(
                item
                for item in snapshot.lessons
                if window_start <= item.date <= window_end
            )
        unique_lessons = {
            (
                item.date,
                item.period,
                item.subject,
                item.teacher,
                item.room,
            ): item
            for item in lessons
        }
        selected_lessons = select_lessons(list(unique_lessons.values()), spec)
    if not selected_lessons:
        raise SyncFailure(f"Profile {profile_id} has no selected lessons in the published window")

    changes_snapshot = spec.get("changes_snapshot")
    if not hasattr(changes_snapshot, "changes"):
        changes_snapshot, _ = fetch_source(config, current.date(), class_id=class_id)
    update_text = update_text or changes_snapshot.update_text
    selected_changes = [
        item
        for item in select_changes(changes_snapshot.changes, spec)
        if window_start <= item.date <= window_end
    ]
    selected_lessons = apply_changes(selected_lessons, selected_changes)

    exams_snapshot = spec.get("exams_snapshot")
    if not hasattr(exams_snapshot, "exams"):
        exams_snapshot = fetch_exams(
            config,
            current.date(),
            class_id=class_id,
            class_number=class_number,
            include_all=True,
        )
    exams = select_exams(exams_snapshot.exams, spec, lessons=selected_lessons)
    if events_snapshot is None:
        events_snapshot = fetch_events(config, current.date(), class_id=class_id)
    event_processing = _process_events(
        snapshot=events_snapshot,
        schedule=[lesson_to_dict(item) for item in selected_lessons],
        exams=exams,
        class_number=class_number,
        current=current,
        profile_id=profile_id,
        nim_client=nim_client,
    )
    selected_lessons = [
        Lesson(
            date.fromisoformat(str(item["date"])),
            int(item["period"]),
            time.fromisoformat(str(item["start"])),
            time.fromisoformat(str(item["end"])),
            str(item.get("subject", "")),
            str(item.get("teacher", "")),
            str(item.get("room", "")),
        )
        for item in event_processing.schedule
    ]
    change_records = [
        ChangeRecord(
            item.kind,
            item.date,
            item.period,
            item.subject or item.teacher or "Schedule update",
            item.detail or "Published Shahaf update",
        )
        for item in selected_changes
    ]
    source_url = f"{config.source_base_url}?cls={class_id}&tab=changes"
    return {
        "id": profile_id,
        "label": str(spec.get("label", profile_id)),
        "mark": str(spec.get("mark", "XI")),
        "class_id": class_id,
        "schedule": [lesson_to_dict(item) for item in selected_lessons],
        "schedule_available": True,
        "changes": change_records,
        "exams": exams,
        "exams_available": True,
        "events": event_processing.events,
        "events_available": True,
        "events_source_updated": events_snapshot.update_text,
        "events_alarm_safety": event_processing.alarm_safety,
        "events_alarm_safety_reason": event_processing.alarm_safety_reason,
        "source_url": source_url,
        "source_updated": update_text or changes_snapshot.update_text,
        "last_successful_sync": current.isoformat(),
        "stale": False,
        "error": "",
        "generated_at": current.isoformat(),
    }


def _managed_specs(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncFailure(f"Managed profile bundle is unreadable: {exc}") from exc
    records = payload.get("profiles", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise SyncFailure("Managed profile bundle must contain a profiles list")
    result: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not record.get("active", True):
            continue
        public_id = str(record.get("public_id", ""))
        package = record.get("package")
        if len(public_id) < 22 or not isinstance(package, dict):
            raise SyncFailure(f"Managed profile {index} is missing public_id or package")
        try:
            normalized = validate_package(package)
        except ProfilePackageError as exc:
            raise SyncFailure(f"Managed profile {public_id} is invalid: {exc}") from exc
        spec = package_to_spec(normalized, public_id)
        spec["package"] = normalized
        if isinstance(record.get("alarm_settings"), dict):
            spec["alarm_settings"] = record["alarm_settings"]
        if isinstance(record.get("alarm_override"), dict):
            spec["alarm_override"] = record["alarm_override"]
        result.append(spec)
    return result


def _canonical_managed_profile_id(
    profiles: list[dict[str, object]],
    specs_by_id: dict[str, dict[str, object]],
    config: Config,
) -> str | None:
    """Find the one managed profile replacing the former root profile."""
    matches: list[str] = []
    for profile in profiles:
        profile_id = str(profile.get("id", ""))
        spec = specs_by_id.get(profile_id, {})
        if not profile_id or not spec.get("managed_profile") or not profile.get("active", True):
            continue
        if str(profile.get("class_id", "")) != str(config.class_id):
            continue
        try:
            class_number = int(spec.get("class_number", 0))
        except (TypeError, ValueError):
            continue
        if class_number == config.class_number:
            matches.append(profile_id)
    return matches[0] if len(matches) == 1 else None


def execute(
    root: Path,
    config: Config,
    dry_run: bool = False,
    now: datetime | None = None,
    managed_profiles_path: Path | None = None,
) -> list[ChangeRecord]:
    current = now or _now(config)
    client = GistClient(token=os.environ.get("GIST_TOKEN"))
    site_path = _site_path(config, root)
    previous = _previous_site_state(site_path)
    ya1_site_path = site_path / "ya1"
    managed_site_path = site_path / "students"
    previous_managed: dict[str, dict[str, object]] = {}
    if managed_site_path.exists():
        for child in managed_site_path.iterdir():
            if child.is_dir():
                previous_managed[child.name] = _previous_site_state(child)
    # This directory is generated exclusively from the private Worker bundle.
    # Clearing this exact output root ensures disabled profiles disappear from
    # the next Pages artifact without touching the legacy root or /ya1 page.
    if managed_site_path.exists():
        shutil.rmtree(managed_site_path)
    previous_ya1 = _previous_site_state(ya1_site_path)
    source_url = f"{config.source_base_url}?cls={config.class_id}&tab=changes"
    try:
        gist_file = client.read_file(config.gist_id, config.gist_filename)
        calendar = parse_calendar(gist_file.content)
        snapshot, _urls = fetch_source(config, current.date())
        exam_snapshot = fetch_exams(config, current.date(), include_all=True)
        event_snapshot = fetch_events(config, current.date())
        changes = reconcile_calendar(
            calendar,
            snapshot,
            current.date(),
            current.date() + timedelta(days=config.lookahead_days),
        )
        pre_event_schedule = build_schedule(
            calendar,
            current.date().isoformat(),
            (current.date() + timedelta(days=config.lookahead_days)).isoformat(),
        )
        root_exam_spec: dict[str, object] = {
            "exam_terms": [],
            "exam_exact_terms": [],
        }
        root_exams = select_exams(exam_snapshot.exams, root_exam_spec, lessons=pre_event_schedule)
        reconcile_exam_events(calendar, root_exams)
        nim_client = (
            NimSafetyClient(
                os.environ["NVIDIA_API_KEY"],
                model=os.environ.get("NVIDIA_NIM_MODEL") or "openai/gpt-oss-20b",
            )
            if os.environ.get("NVIDIA_API_KEY")
            else None
        )
        root_event_processing = _process_events(
            snapshot=event_snapshot,
            schedule=pre_event_schedule,
            exams=root_exams,
            class_number=config.class_number,
            current=current,
            profile_id="master-ya2",
            nim_client=nim_client,
        )
        reconcile_event_entries(
            calendar,
            event_snapshot.events,
            root_event_processing.decisions,
            config.class_number,
            current.date(),
            current.date() + timedelta(days=config.lookahead_days),
        )
        updated_content = calendar.render()
        if updated_content != gist_file.content and not dry_run:
            client.update_file(config.gist_id, config.gist_filename, updated_content)
        schedule = build_schedule(
            calendar,
            current.date().isoformat(),
            (current.date() + timedelta(days=config.lookahead_days)).isoformat(),
        )
        candidate_wake = build_wake_data(
            schedule,
            schedule_available=True,
            stale=False,
            now=current,
            wake_time_by_first_lesson_start=(
                config.special_requests.get("wake_time_by_first_lesson_start")
                if isinstance(config.special_requests, dict)
                and isinstance(config.special_requests.get("wake_time_by_first_lesson_start"), dict)
                else None
            ),
        )
        alarm_safety, alarm_safety_reason = _alarm_safety(
            wake=candidate_wake,
            changes=changes,
            schedule=schedule,
            exams=root_exams,
            current=current,
            event_alarm_safety=root_event_processing.alarm_safety,
            event_alarm_safety_reason=root_event_processing.alarm_safety_reason,
        )
        profile_specs = [dict(spec) for spec in config.additional_profiles]
        try:
            profile_specs.extend(_managed_specs(managed_profiles_path))
        except SyncFailure as managed_exc:
            # A private bundle problem is isolated to the additive feature;
            # it must not make the established master or legacy Ya1 sync fail.
            print(f"Managed profiles skipped: {managed_exc}")
        profile_views: list[dict[str, object]] = []
        profile_specs_by_id: dict[str, dict[str, object]] = {}
        changes_cache: dict[str, object] = {str(config.class_id): snapshot}
        exams_cache: dict[tuple[str, int], object] = {(str(config.class_id), config.class_number): exam_snapshot}
        events_cache: dict[str, EventSnapshot] = {str(config.class_id): event_snapshot}
        for spec in profile_specs:
            try:
                # Keep the established config-driven profiles on their old
                # path byte-for-byte in behavior. Only Worker-managed
                # profiles use the shared class/exam cache below.
                if not spec.get("managed_profile"):
                    class_id = str(spec.get("class_id", ""))
                    if class_id not in events_cache:
                        events_cache[class_id] = fetch_events(config, current.date(), class_id=class_id)
                    profile_views.append(
                        _build_public_profile(
                            config,
                            spec,
                            current,
                            events_snapshot=events_cache[class_id],
                            nim_client=nim_client,
                        )
                    )
                    profile_specs_by_id[str(spec.get("id", "profile"))] = spec
                    continue
                class_id = str(spec.get("class_id", ""))
                class_number = int(spec.get("class_number", 0))
                if class_id not in changes_cache:
                    changes_cache[class_id], _ = fetch_source(config, current.date(), class_id=class_id)
                if (class_id, class_number) not in exams_cache:
                    exams_cache[(class_id, class_number)] = fetch_exams(
                        config,
                        current.date(),
                        class_id=class_id,
                        class_number=class_number,
                        include_all=True,
                    )
                if class_id not in events_cache:
                    events_cache[class_id] = fetch_events(config, current.date(), class_id=class_id)
                profile_spec = dict(spec)
                profile_spec["changes_snapshot"] = changes_cache[class_id]
                profile_spec["exams_snapshot"] = exams_cache[(class_id, class_number)]
                profile_spec["events_snapshot"] = events_cache[class_id]
                profile = _build_public_profile(
                    config,
                    profile_spec,
                    current,
                    events_snapshot=events_cache[class_id],
                    nim_client=nim_client,
                )
                profile_specs_by_id[str(profile.get("id"))] = profile_spec
                profile_views.append(profile)
            except (ShahafSourceError, SyncFailure, ValueError, OSError) as profile_exc:
                output_id = str(spec.get("public_id", spec.get("id", "profile")))
                output_path = site_path / "students" / output_id if spec.get("managed_profile") else ya1_site_path
                previous_profile = previous_managed.get(output_id, {})
                profile_specs_by_id[output_id] = spec
                profile_views.append(
                    _profile_failure(spec, previous_profile if spec.get("managed_profile") else previous_ya1, current, str(profile_exc))
                )

        transit_spec = config.transit or {}
        transit_archive: Path | None = None
        transit_timestamp = ""
        transit_download_error: str | None = None
        transit_cache: dict[date, object] = {}
        for profile in profile_views:
            profile_spec = profile_specs_by_id.get(str(profile.get("id")), {})
            if str(profile.get("id")) != "ya1" and not profile_spec.get("managed_profile"):
                continue
            profile_transit = profile_spec.get("transit") if profile_spec.get("managed_profile") else transit_spec
            profile_transit = profile_transit if isinstance(profile_transit, dict) else {}
            if profile_spec.get("managed_profile") and not bool(profile_transit.get("enabled", False)):
                continue
            origin_address = str(profile_transit.get("origin_address", transit_spec.get("origin_address", "מרדכי זעירא 5, רעננה")))
            destination_address = str(transit_spec.get("destination_address", "אוסטרובסקי 26, רעננה"))
            try:
                origin_raw = transit_spec.get("origin_coordinates", {})
                if profile_spec.get("managed_profile"):
                    origin_raw = {"lat": profile_transit["origin_lat"], "lon": profile_transit["origin_lon"]}
                destination_raw = transit_spec["destination_coordinates"]
                origin = (float(origin_raw["lat"]), float(origin_raw["lon"]))
                destination = (float(destination_raw["lat"]), float(destination_raw["lon"]))
                if not bool(profile_transit.get("enabled", False)):
                    raise TransitSourceError("Ya1 transit wake is disabled in config")
                if transit_archive is None and transit_download_error is None:
                    transit_archive, transit_timestamp = download_gtfs(
                        str(transit_spec.get("gtfs_url", ""))
                    )

                def schedule_for(day: date):
                    if day not in transit_cache:
                        transit_cache[day] = load_gtfs(
                            transit_archive,
                            day,
                            source_timestamp=transit_timestamp,
                        )
                    return transit_cache[day]

                profile_schedule = profile.get("schedule")
                if not isinstance(profile_schedule, list) or bool(profile.get("stale")):
                    raise TransitSourceError(str(profile.get("error") or "Ya1 Shahaf schedule is stale"))
                alarm_settings = profile_spec.get("alarm_settings") if profile_spec.get("managed_profile") else {}
                alarm_settings = alarm_settings if isinstance(alarm_settings, dict) else {}
                profile["transit_wake"] = build_ya1_transit_wake(
                    schedule_for,
                    profile_schedule,
                    now=current,
                    origin=origin,
                    destination=destination,
                    max_walk_m=int(profile_transit.get("max_walk_m", transit_spec.get("max_walk_m", 1800))),
                    source_timestamp=transit_timestamp,
                    origin_address=origin_address,
                    destination_address=destination_address,
                    arrival_margin_minutes=int(alarm_settings.get("transit_min_arrival_margin", 5)),
                    wake_buffer_minutes=int(alarm_settings.get("wake_buffer_minutes", 75)),
                    walk_buffer_minutes=int(alarm_settings.get("transit_walk_buffer_minutes", 0)),
                    route_preference=alarm_settings.get("transit_route_preference") if isinstance(alarm_settings.get("transit_route_preference"), dict) else None,
                    round_to_minutes=int(alarm_settings.get("round_to_minutes", 1)),
                    min_wake_time=alarm_settings.get("min_wake_time"),
                    max_wake_time=alarm_settings.get("max_wake_time"),
                    managed_controls=bool(profile_spec.get("managed_profile")),
                )
                if profile_spec.get("managed_profile"):
                    # New student endpoints may show the selected route, but
                    # never publish a home address or precise home point.
                    for key in ("origin_address", "origin", "origin_coordinates"):
                        profile["transit_wake"].pop(key, None)
            except (KeyError, TypeError, ValueError, TransitSourceError, OSError) as transit_exc:
                transit_download_error = str(transit_exc) if transit_archive is None else transit_download_error
                profile["transit_wake"] = _stale_transit_payload(config, current, str(transit_exc))
                profile["transit_wake"]["source_timestamp"] = transit_timestamp
                if profile_spec.get("managed_profile"):
                    for key in ("origin_address", "origin", "origin_coordinates"):
                        profile["transit_wake"].pop(key, None)
        canonical_profile_id = _canonical_managed_profile_id(
            profile_views,
            profile_specs_by_id,
            config,
        )
        root_wake_rules = (
            config.special_requests.get("wake_time_by_first_lesson_start")
            if isinstance(config.special_requests, dict)
            and isinstance(config.special_requests.get("wake_time_by_first_lesson_start"), dict)
            else None
        )
        if canonical_profile_id:
            archive_profile_site(site_path, f"students/{canonical_profile_id}/")
        else:
            render_site(
                site_path,
                title=config.site_title,
                generated_at=current.isoformat(),
                source_url=source_url,
                source_updated=snapshot.update_text,
                changes=changes,
                stale=False,
                last_successful_sync=current.isoformat(),
                schedule=schedule,
                exams=root_exams,
                events=root_event_processing.events,
                events_available=True,
                events_source_updated=event_snapshot.update_text,
                now=current,
                alarm_safety=alarm_safety,
                alarm_safety_reason=alarm_safety_reason,
                wake_time_by_first_lesson_start=root_wake_rules,
            )
        for profile in profile_views:
            profile_spec = profile_specs_by_id.get(str(profile.get("id")), {})
            managed = bool(profile_spec.get("managed_profile"))
            if managed and not profile.get("active", True):
                continue
            profile_schedule = profile.get("schedule") if profile.get("schedule_available") else None
            profile_exams = profile.get("exams") if profile.get("exams_available") else None
            profile_events = profile.get("events") if profile.get("events_available") else None
            profile_output = site_path / "students" / str(profile.get("id")) if managed else ya1_site_path
            profile_wake_rules = (
                root_wake_rules
                if managed and str(profile.get("id")) == canonical_profile_id
                else None
            )
            render_site(
                profile_output,
                title="Student schedule" if managed else str(profile.get("label", "Ostrovsky Grade 11-1")),
                generated_at=current.isoformat(),
                source_url=str(profile.get("source_url", f"{config.source_base_url}?cls=61&tab=changes")),
                source_updated=str(profile.get("source_updated", "")),
                changes=list(profile.get("changes", [])),
                stale=bool(profile.get("stale", False)),
                last_successful_sync=str(profile.get("last_successful_sync", "")),
                error=str(profile.get("error", "")),
                schedule=profile_schedule if isinstance(profile_schedule, list) else None,
                exams=profile_exams if isinstance(profile_exams, list) else None,
                events=profile_events if isinstance(profile_events, list) else None,
                events_available=bool(profile.get("events_available", False)),
                events_error=str(profile.get("events_error", "")),
                events_source_updated=str(profile.get("events_source_updated", "")),
                now=current,
                alarm_safety=str(profile.get("events_alarm_safety", "not-required")),
                alarm_safety_reason=str(profile.get("events_alarm_safety_reason", "")),
                profile_id=str(profile.get("id", "ya1")),
                profile_label="Student schedule" if managed else str(profile.get("label", "Grade 11-1")),
                profile_mark="STUDENT" if managed else str(profile.get("mark", "XI·1")),
                profile_class_id=str(profile.get("class_id", "61")),
                publish_wake=managed,
                public_profile=managed,
                transit_wake=profile.get("transit_wake") if isinstance(profile.get("transit_wake"), dict) else None,
                alarm_settings=profile_spec.get("alarm_settings") if managed and isinstance(profile_spec.get("alarm_settings"), dict) else None,
                alarm_override=profile_spec.get("alarm_override") if managed and isinstance(profile_spec.get("alarm_override"), dict) else None,
                wake_time_by_first_lesson_start=profile_wake_rules,
            )
        print(f"Sync complete: {len(changes)} change(s), {len(exam_snapshot.exams)} exam(s); Gist write={'skipped' if dry_run else 'performed' if updated_content != gist_file.content else 'not needed'}")
        return changes
    except (GitHubError, CalendarFormatError, SyncFailure, ShahafSourceError, ValueError) as exc:
        message = str(exc)
        # Always leave a JSON response for the isolated Shortcut, even when
        # the main Gist/source fails before the ya1 profile loop starts.
        ya1_wake_path = site_path / "ya1" / "wake.json"
        ya1_wake_path.parent.mkdir(parents=True, exist_ok=True)
        ya1_wake_path.write_text(
            json.dumps(_stale_transit_payload(config, current, message), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        render_site(
            site_path,
            title=config.site_title,
            generated_at=current.isoformat(),
            source_url=source_url,
            source_updated=str(previous.get("source_updated", "")),
            changes=[],
            stale=True,
            last_successful_sync=str(previous.get("last_successful_sync", "")),
            error=message,
            now=current,
        )
        print(f"SAFE FAILURE: {message}")
        raise SyncFailure(message) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Ostrovsky Shahaf changes into a personal ICS Gist.")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--dry-run", action="store_true", help="Fetch and reconcile without writing the Gist.")
    parser.add_argument("--profiles-file", type=Path, help="Private JSON bundle fetched from the admin Worker.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        profiles_path = (root / args.profiles_file) if args.profiles_file and not args.profiles_file.is_absolute() else args.profiles_file
        execute(root, load_config(root / args.config), dry_run=args.dry_run, managed_profiles_path=profiles_path)
        return 0
    except (OSError, SyncFailure, json.JSONDecodeError) as exc:
        print(f"SAFE FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
