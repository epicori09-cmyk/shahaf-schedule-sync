from __future__ import annotations

from datetime import date, timedelta
from html import unescape
import re

from .model import Lesson, SourceSnapshot


class ShahafSourceError(ValueError):
    """Raised when a Shahaf timetable page cannot be trusted."""


def _plain(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t\r\n\u00a0]+", " ", unescape(text)).strip()


def _date_from_header(fragment: str, reference_date: date) -> date:
    text = _plain(fragment)
    match = re.search(r"(\d{1,2})\.(\d{1,2})", text)
    if not match:
        raise ShahafSourceError(f"Cannot parse date header: {text!r}")
    day, month = int(match.group(1)), int(match.group(2))
    candidates = [date(year, month, day) for year in range(reference_date.year - 1, reference_date.year + 2)]
    return min(candidates, key=lambda item: abs((item - reference_date).days))


def _lesson_from_fragment(fragment: str) -> tuple[str, str, str] | None:
    subject_match = re.search(r"<b[^>]*>(.*?)</b>", fragment, flags=re.IGNORECASE | re.DOTALL)
    if not subject_match:
        return None
    subject = _plain(subject_match.group(1))
    rest = fragment[subject_match.end() :]
    rest_with_lines = re.sub(r"<br\s*/?>", "\n", rest, flags=re.IGNORECASE)
    rest_with_lines = re.sub(r"<[^>]+>", "", rest_with_lines)
    rest_lines = [
        re.sub(r"[ \t\r\u00a0]+", " ", unescape(item)).strip()
        for item in rest_with_lines.split("\n")
    ]
    rest_lines = [item for item in rest_lines if item]
    rest_text = " ".join(rest_lines)
    room_match = re.search(r"\(([^()]*)\)", rest_text)
    room = room_match.group(1).strip() if room_match else ""
    teacher = rest_lines[-1] if len(rest_lines) > 1 else ""
    return subject, teacher, room


def parse_timetable_html(
    html: str,
    reference_date: date,
    source_url: str = "",
) -> SourceSnapshot:
    table_match = re.search(
        r"<table[^>]*class=[\"'][^\"']*TTTable[^\"']*[\"'][^>]*>(.*?)</table>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not table_match:
        raise ShahafSourceError("Shahaf page has no timetable grid")
    table = table_match.group(1)
    header_matches = re.findall(
        r"<td[^>]*class=[\"']CTitle[\"'][^>]*data-day=[\"'](\d+)[\"'][^>]*>(.*?)</td>",
        table,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(header_matches) < 2:
        raise ShahafSourceError("Shahaf timetable has too few day headers")
    header_dates = {int(day): _date_from_header(fragment, reference_date) for day, fragment in header_matches}

    update_match = re.search(
        r"<div[^>]*class=[\"']UpdateDate[\"'][^>]*>(.*?)</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    update_text = _plain(update_match.group(1)) if update_match else ""
    lessons: list[Lesson] = []
    row_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL)
    for row in row_matches:
        name_match = re.search(
            r"<td[^>]*class=[\"']CName[\"'][^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL
        )
        if not name_match:
            continue
        name_text = _plain(name_match.group(1))
        period_match = re.search(r"\b(\d+)\b", name_text)
        times = re.findall(r"\b(\d{1,2}:\d{2})\b", name_text)
        if not period_match or len(times) < 2:
            continue
        period = int(period_match.group(1))
        cell_matches = re.findall(
            r"<td[^>]*class=[\"']TTCell[\"'][^>]*data-day=[\"'](\d+)[\"'][^>]*>(.*?)</td>",
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for day_value, cell in cell_matches:
            day_number = int(day_value)
            if day_number not in header_dates:
                continue
            for lesson_fragment in re.findall(
                r"<div[^>]*class=[\"']TTLesson[\"'][^>]*>(.*?)</div>",
                cell,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                parsed = _lesson_from_fragment(lesson_fragment)
                if not parsed:
                    continue
                subject, teacher, room = parsed
                hour_start, hour_end = times[0], times[1]
                from datetime import time

                lessons.append(
                    Lesson(
                        header_dates[day_number],
                        period,
                        time.fromisoformat(hour_start),
                        time.fromisoformat(hour_end),
                        subject,
                        teacher,
                        room,
                    )
                )
    if not update_text:
        raise ShahafSourceError("Shahaf page has no update timestamp")
    if not lessons:
        raise ShahafSourceError("Shahaf timetable contains no published lessons")
    return SourceSnapshot(
        lessons=lessons,
        covered_dates=set(header_dates.values()),
        update_text=update_text,
        source_url=source_url,
    )


def merge_snapshots(snapshots: list[SourceSnapshot]) -> SourceSnapshot:
    if not snapshots:
        raise ShahafSourceError("No usable Shahaf timetable pages were fetched")
    unique: dict[tuple[date, int, str, str, str], Lesson] = {}
    for snapshot in snapshots:
        for item in snapshot.lessons:
            unique[(item.date, item.period, item.subject, item.teacher, item.room)] = item
    return SourceSnapshot(
        lessons=list(unique.values()),
        covered_dates=set().union(*(item.covered_dates for item in snapshots)),
        update_text=max(item.update_text for item in snapshots),
        source_url=snapshots[-1].source_url,
    )
