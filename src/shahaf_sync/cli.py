from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .github import GistClient, GitHubError
from .exams import reconcile_exam_events
from .ics import CalendarFormatError, parse_calendar
from .model import Lesson, SourceSnapshot
from .nim import NimError, NimSafetyClient, context_for_alarm_review
from .profiles import apply_changes, lesson_to_dict, select_changes, select_exams, select_lessons
from .reconcile import ChangeRecord, reconcile_calendar
from .shahaf import ShahafSourceError, parse_changes_html, parse_exams_html, parse_timetable_html
from .site import build_schedule, build_wake_data, render_site
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


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["timezone", "source_base_url", "class_id", "gist_id", "gist_filename", "lookahead_days", "site_title", "site_dir"]
    missing = [key for key in required if key not in data]
    if missing:
        raise SyncFailure(f"Missing config keys: {', '.join(missing)}")
    profiles = data.get("additional_profiles", [])
    if not isinstance(profiles, list) or not all(isinstance(item, dict) for item in profiles):
        raise SyncFailure("additional_profiles must be a list of objects")
    return Config(
        *(data[key] for key in required),
        int(data.get("class_number", 2)),
        tuple(profiles),
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
        )
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf exams feed is not trustworthy: {exc}") from exc


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
        "source_updated": "",
        "last_successful_sync": "",
        "stale": True,
        "error": error,
        "generated_at": current.isoformat(),
    }


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


def _alarm_safety(
    *,
    wake: dict[str, object],
    changes: list[ChangeRecord],
    schedule: list[dict[str, object]],
    exams: list[object],
    current: datetime,
) -> tuple[str, str]:
    """Return approved/not-required/blocked without ever failing the sync.

    Normal future alarms need no model call. NIM is used for destructive
    cases: clearing an alarm, or replacing today's alarm after a same-day
    Shahaf change. Missing credentials and every model/API/schema failure are
    deliberately treated as blocked, so the iPhone keeps its current alarm.
    """
    action = str(wake.get("shortcut_action", "leave"))
    today = current.date().isoformat()
    today_changes = [_dict_change(item) for item in changes if item.date.isoformat() == today]
    needs_review = action == "clear" or (action == "set" and bool(today_changes))
    if not needs_review:
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

    changes_snapshot, _ = fetch_source(config, current.date(), class_id=class_id)
    update_text = update_text or changes_snapshot.update_text
    selected_changes = [
        item
        for item in select_changes(changes_snapshot.changes, spec)
        if window_start <= item.date <= window_end
    ]
    selected_lessons = apply_changes(selected_lessons, selected_changes)

    exams_snapshot = fetch_exams(
        config,
        current.date(),
        class_id=class_id,
        class_number=class_number,
    )
    exams = select_exams(exams_snapshot.exams, spec)
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
        "source_url": source_url,
        "source_updated": update_text or changes_snapshot.update_text,
        "last_successful_sync": current.isoformat(),
        "stale": False,
        "error": "",
        "generated_at": current.isoformat(),
    }


def execute(root: Path, config: Config, dry_run: bool = False, now: datetime | None = None) -> list[ChangeRecord]:
    current = now or _now(config)
    client = GistClient(token=os.environ.get("GIST_TOKEN"))
    site_path = _site_path(config, root)
    previous = _previous_site_state(site_path)
    ya1_site_path = site_path / "ya1"
    previous_ya1 = _previous_site_state(ya1_site_path)
    source_url = f"{config.source_base_url}?cls={config.class_id}&tab=changes"
    try:
        gist_file = client.read_file(config.gist_id, config.gist_filename)
        calendar = parse_calendar(gist_file.content)
        snapshot, _urls = fetch_source(config, current.date())
        exam_snapshot = fetch_exams(config, current.date())
        changes = reconcile_calendar(
            calendar,
            snapshot,
            current.date(),
            current.date() + timedelta(days=config.lookahead_days),
        )
        reconcile_exam_events(calendar, exam_snapshot.exams)
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
        )
        alarm_safety, alarm_safety_reason = _alarm_safety(
            wake=candidate_wake,
            changes=changes,
            schedule=schedule,
            exams=exam_snapshot.exams,
            current=current,
        )
        profile_views: list[dict[str, object]] = []
        for spec in config.additional_profiles:
            try:
                profile_views.append(_build_public_profile(config, spec, current))
            except (ShahafSourceError, SyncFailure, ValueError, OSError) as profile_exc:
                profile_views.append(
                    _profile_failure(spec, previous_ya1, current, str(profile_exc))
                )
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
            exams=exam_snapshot.exams,
            now=current,
            alarm_safety=alarm_safety,
            alarm_safety_reason=alarm_safety_reason,
        )
        for profile in profile_views:
            profile_schedule = profile.get("schedule") if profile.get("schedule_available") else None
            profile_exams = profile.get("exams") if profile.get("exams_available") else None
            render_site(
                ya1_site_path,
                title=str(profile.get("label", "Ostrovsky Grade 11-1")),
                generated_at=current.isoformat(),
                source_url=str(profile.get("source_url", f"{config.source_base_url}?cls=61&tab=changes")),
                source_updated=str(profile.get("source_updated", "")),
                changes=list(profile.get("changes", [])),
                stale=bool(profile.get("stale", False)),
                last_successful_sync=str(profile.get("last_successful_sync", "")),
                error=str(profile.get("error", "")),
                schedule=profile_schedule if isinstance(profile_schedule, list) else None,
                exams=profile_exams if isinstance(profile_exams, list) else None,
                now=current,
                profile_id=str(profile.get("id", "ya1")),
                profile_label=str(profile.get("label", "Grade 11-1")),
                profile_mark=str(profile.get("mark", "XI·1")),
                profile_class_id=str(profile.get("class_id", "61")),
                publish_wake=False,
            )
        print(f"Sync complete: {len(changes)} change(s), {len(exam_snapshot.exams)} exam(s); Gist write={'skipped' if dry_run else 'performed' if updated_content != gist_file.content else 'not needed'}")
        return changes
    except (GitHubError, CalendarFormatError, SyncFailure, ShahafSourceError, ValueError) as exc:
        message = str(exc)
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
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        execute(root, load_config(root / args.config), dry_run=args.dry_run)
        return 0
    except (OSError, SyncFailure, json.JSONDecodeError) as exc:
        print(f"SAFE FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
