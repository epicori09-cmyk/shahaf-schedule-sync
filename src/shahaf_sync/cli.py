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
from .model import SourceSnapshot
from .reconcile import ChangeRecord, reconcile_calendar
from .shahaf import ShahafSourceError, parse_changes_html, parse_exams_html
from .site import build_schedule, render_site


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


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["timezone", "source_base_url", "class_id", "gist_id", "gist_filename", "lookahead_days", "site_title", "site_dir"]
    missing = [key for key in required if key not in data]
    if missing:
        raise SyncFailure(f"Missing config keys: {', '.join(missing)}")
    return Config(*(data[key] for key in required), int(data.get("class_number", 2)))


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "ostrovsky-shahaf-sync/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise SyncFailure(f"Source returned HTTP {response.status}")
            return response.read().decode("utf-8")
    except (HTTPError, URLError, UnicodeDecodeError) as exc:
        raise SyncFailure(f"Could not read source: {exc}") from exc


def fetch_source(config: Config, today: date) -> tuple[SourceSnapshot, list[str]]:
    url = f"{config.source_base_url}?cls={config.class_id}&tab=changes"
    try:
        html = fetch_text(url)
        return parse_changes_html(html, today, url, expected_class_id=config.class_id), [url]
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf changes feed is not trustworthy: {exc}") from exc


def fetch_exams(config: Config, today: date):
    url = f"{config.source_base_url}?cls={config.class_id}&tab=exams"
    try:
        html = fetch_text(url)
        return parse_exams_html(
            html,
            today,
            url,
            expected_class_number=config.class_number,
            expected_class_id=config.class_id,
        )
    except (ShahafSourceError, SyncFailure) as exc:
        raise SyncFailure(f"Shahaf exams feed is not trustworthy: {exc}") from exc


def _now(config: Config) -> datetime:
    return datetime.now(ZoneInfo(config.timezone))


def _site_path(config: Config, root: Path) -> Path:
    return root / config.site_dir


def _previous_site_state(site_path: Path) -> dict[str, str]:
    try:
        data = json.loads((site_path / "data.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def execute(root: Path, config: Config, dry_run: bool = False, now: datetime | None = None) -> list[ChangeRecord]:
    current = now or _now(config)
    client = GistClient(token=os.environ.get("GIST_TOKEN"))
    site_path = _site_path(config, root)
    previous = _previous_site_state(site_path)
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
