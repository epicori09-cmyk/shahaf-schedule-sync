from __future__ import annotations

from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import re
from dataclasses import dataclass, field

from .model import Lesson, PublishedChange, SourceSnapshot


class ShahafSourceError(ValueError):
    """Raised when a Shahaf timetable page cannot be trusted."""


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list["_HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(part for part in self.text_parts if part).strip()


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag.lower():
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].text_parts.append(data)


def _walk(node: _HtmlNode):
    for child in node.children:
        yield child
        yield from _walk(child)


def _node_text(node: _HtmlNode) -> str:
    return " ".join([node.text(), *(_node_text(child) for child in node.children)]).strip()


def _class_value(node: _HtmlNode) -> str:
    return node.attrs.get("class", "").casefold()


def _descendant_value(node: _HtmlNode, class_words: tuple[str, ...]) -> str:
    for child in _walk(node):
        classes = _class_value(child)
        if any(word in classes for word in class_words):
            value = _node_text(child)
            if value:
                return value
    return ""


def _first_tag_value(node: _HtmlNode, tag: str) -> str:
    for child in _walk(node):
        if child.tag == tag:
            value = _node_text(child)
            if value:
                return value
    return ""


def _date_from_value(value: str, reference_date: date) -> date | None:
    value = unescape(value)
    iso_match = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", value)
    if iso_match:
        return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
    match = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?\b", value)
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else reference_date.year
    candidates = [date(candidate_year, month, day) for candidate_year in range(reference_date.year - 1, reference_date.year + 2)]
    return min(candidates, key=lambda item: abs((item - reference_date).days)) if not match.group(3) else date(year, month, day)


def _attr(node: _HtmlNode, *names: str) -> str:
    for name in names:
        if node.attrs.get(name):
            return node.attrs[name]
        data_name = f"data-{name}"
        if node.attrs.get(data_name):
            return node.attrs[data_name]
    return ""


def _parse_published_change(node: _HtmlNode, reference_date: date) -> PublishedChange | None:
    text = _node_text(node)
    date_value = _attr(node, "date", "day") or _descendant_value(node, ("date", "day")) or text
    change_date = _date_from_value(date_value, reference_date)
    if change_date is None:
        return None

    period_value = _attr(node, "period", "hour") or _descendant_value(node, ("period", "hour"))
    period_match = re.search(r"\d+", period_value)
    if period_match is not None:
        period = int(period_match.group(0))
    else:
        period_match = re.search(r"(?:שעה|hour|period)\s*[:#-]?\s*(\d+)", text, re.IGNORECASE)
        if period_match is None:
            return None
        period = int(period_match.group(1))

    subject = (
        _attr(node, "subject", "lesson", "activity")
        or _descendant_value(node, ("subject", "lesson", "activity", "course"))
        or _first_tag_value(node, "b")
    )
    if not subject:
        labeled = re.search(r"(?:מקצוע|שיעור|פעילות|subject|lesson)\s*[:#-]\s*([^|;]+)", text, re.IGNORECASE)
        subject = labeled.group(1).strip() if labeled else ""
    subject = re.sub(r"\s+", " ", subject).strip(" -:;")
    if not subject:
        return None

    kind_value = (_attr(node, "kind", "action", "type") or text).casefold()
    if re.search(r"בוטל|בוטלה|בוטלו|ביטול|מבוטל|cancel", kind_value, re.IGNORECASE):
        kind = "cancelled"
    elif re.search(r"נוסף|נוספה|הוספ|חדש|added|new", kind_value, re.IGNORECASE):
        kind = "added"
    else:
        kind = "changed"

    new_period_value = _attr(node, "new-period", "target-period", "to-period")
    new_period_match = re.search(r"\d+", new_period_value)
    new_period = int(new_period_match.group()) if new_period_match else None
    start_end = re.search(r"(\d{1,2}:\d{2})\s*(?:-|–|—|עד|to)\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    start_value = _attr(node, "start", "start-time")
    end_value = _attr(node, "end", "end-time")
    if start_end:
        start_value, end_value = start_end.group(1), start_end.group(2)

    def parse_time(value: str):
        from datetime import time

        match = re.search(r"\b(\d{1,2}):(\d{2})\b", value)
        return time(int(match.group(1)), int(match.group(2))) if match else None

    teacher = _attr(node, "teacher") or _descendant_value(node, ("teacher", "instructor"))
    room = _attr(node, "room", "location") or _descendant_value(node, ("room", "location"))
    if not teacher:
        teacher_match = re.search(r"(?:מורה(?:\s+מחליף)?|teacher)\s*[:#-]\s*([^|;]+)", text, re.IGNORECASE)
        teacher = teacher_match.group(1).strip() if teacher_match else None
    if not room:
        room_match = re.search(r"(?:חדר|room|location)\s*[:#-]\s*([^|;]+)", text, re.IGNORECASE)
        room = room_match.group(1).strip() if room_match else None
    detail = re.sub(r"\s+", " ", text).strip()
    return PublishedChange(
        date=change_date,
        period=period,
        subject=subject,
        kind=kind,
        new_period=new_period,
        start=parse_time(start_value),
        end=parse_time(end_value),
        teacher=teacher,
        room=room,
        detail=detail,
    )


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


def parse_changes_html(
    html: str,
    reference_date: date,
    source_url: str = "",
    expected_class_id: str = "17",
) -> SourceSnapshot:
    """Parse Shahaf's explicit date-specific change feed.

    The regular ``changestable`` page is a whole-school timetable containing
    parallel major groups. It must not be used as a cancellation oracle for a
    personal calendar. This parser only accepts records from the ``changes``
    feed and fails closed when a non-empty feed has an unknown shape.
    """
    parser = _TreeParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser can reject malformed markup.
        raise ShahafSourceError(f"Shahaf changes page is malformed: {exc}") from exc

    select_match = re.search(
        r"<select\b[^>]*\bname=[\"']cls[\"'][^>]*>(.*?)</select>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if select_match and not re.search(
        rf"<option\b[^>]*\bvalue=[\"']{re.escape(expected_class_id)}[\"'][^>]*\bselected",
        select_match.group(1),
        flags=re.IGNORECASE,
    ):
        raise ShahafSourceError(f"Shahaf page is not selected for class {expected_class_id}")

    update_match = re.search(
        r"<div[^>]*class=[\"'][^\"']*UpdateDate[^\"']*[\"'][^>]*>(.*?)</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    update_text = _plain(update_match.group(1)) if update_match else ""
    if not update_text:
        raise ShahafSourceError("Shahaf changes page has no update timestamp")

    candidates: list[_HtmlNode] = []
    for node in _walk(parser.root):
        classes = _class_value(node)
        if node.tag == "tr" or re.search(r"change|שינוי", classes, re.IGNORECASE) or any(
            key in node.attrs for key in ("data-date", "data-day", "data-period", "data-hour")
        ):
            candidates.append(node)

    changes: list[PublishedChange] = []
    seen: set[tuple[object, ...]] = set()
    for node in candidates:
        change = _parse_published_change(node, reference_date)
        if change is None:
            continue
        key = (
            change.date,
            change.period,
            change.subject,
            change.kind,
            change.new_period,
            change.start,
            change.end,
            change.teacher,
            change.room,
        )
        if key not in seen:
            seen.add(key)
            changes.append(change)

    page_text = _plain(html)
    if not changes:
        if re.search(r"class=[\"'][^\"']*EmptyList[^\"']*[\"']", html, re.IGNORECASE) or "אין שינויים" in page_text:
            return SourceSnapshot([], set(), update_text, source_url, [])
        raise ShahafSourceError("Shahaf changes page has unsupported non-empty change markup")

    return SourceSnapshot(
        lessons=[],
        covered_dates={change.date for change in changes},
        update_text=update_text,
        source_url=source_url,
        changes=changes,
    )


def merge_snapshots(snapshots: list[SourceSnapshot]) -> SourceSnapshot:
    if not snapshots:
        raise ShahafSourceError("No usable Shahaf timetable pages were fetched")
    unique_lessons: dict[tuple[date, int, str, str, str], Lesson] = {}
    unique_changes: dict[tuple[object, ...], PublishedChange] = {}
    for snapshot in snapshots:
        for item in snapshot.lessons:
            unique_lessons[(item.date, item.period, item.subject, item.teacher, item.room)] = item
        for item in snapshot.changes:
            unique_changes[
                (
                    item.date,
                    item.period,
                    item.subject,
                    item.kind,
                    item.new_period,
                    item.start,
                    item.end,
                    item.teacher,
                    item.room,
                )
            ] = item
    return SourceSnapshot(
        lessons=list(unique_lessons.values()),
        covered_dates=set().union(*(item.covered_dates for item in snapshots)),
        update_text=max(item.update_text for item in snapshots),
        source_url=snapshots[-1].source_url,
        changes=list(unique_changes.values()),
    )
