from __future__ import annotations

from datetime import date, time, timedelta
from html import unescape
from html.parser import HTMLParser
import re
from dataclasses import dataclass, field

from .model import EventSnapshot, Exam, ExamSnapshot, Lesson, PERIOD_TIMES, PublishedChange, ShahafEvent, SourceSnapshot


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

    teacher_only_row = "changesinfo" in _class_value(node)
    teacher_only_match = re.search(
        r"(?:שיעור|lesson)\s*(\d+)\s*,\s*([^,]+?)\s*,\s*(.+)$",
        text,
        re.IGNORECASE,
    ) if teacher_only_row else None

    period_value = _attr(node, "period", "hour") or _descendant_value(node, ("period", "hour"))
    period_match = re.search(r"\d+", period_value)
    if period_match is not None:
        period = int(period_match.group(0))
    else:
        period_match = re.search(r"(?:שעה|שיעור|hour|period)\s*[:#-]?\s*(\d+)", text, re.IGNORECASE)
        if period_match is None:
            return None
        period = int(period_match.group(1))

    if teacher_only_match:
        subject = ""
        teacher = teacher_only_match.group(2).strip()
        action_text = teacher_only_match.group(3).strip()
    else:
        teacher = None
        action_text = ""

    subject = (
        _attr(node, "subject", "lesson", "activity")
        or _descendant_value(node, ("subject", "lesson", "activity", "course"))
        or _first_tag_value(node, "b")
    ) if not teacher_only_match else subject
    if not subject and not teacher_only_match:
        labeled = re.search(r"(?:מקצוע|שיעור|פעילות|subject|lesson)\s*[:#-]\s*([^|;]+)", text, re.IGNORECASE)
        subject = labeled.group(1).strip() if labeled else ""
    subject = re.sub(r"\s+", " ", subject).strip(" -:;")
    if not subject and not teacher_only_match:
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

    teacher = teacher or _attr(node, "teacher") or _descendant_value(node, ("teacher", "instructor"))
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
    # Some Shahaf rows have only a teacher after the subject (no room in
    # parentheses).  Treat that single remaining line as the teacher too;
    # otherwise track-specific filters cannot distinguish parallel groups.
    teacher = rest_lines[-1] if rest_lines else ""
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
    if select_match:
        selected_class = any(
            re.search(rf"\bvalue=[\"']{re.escape(expected_class_id)}[\"']", attrs, re.IGNORECASE)
            and re.search(r"\bselected(?:\s*=|\b)", attrs, re.IGNORECASE)
            for attrs in re.findall(r"<option\b([^>]*)>", select_match.group(1), flags=re.IGNORECASE)
        )
        if not selected_class:
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
        if node.tag in {"tr", "li", "article"} or re.search(r"change|שינוי", classes, re.IGNORECASE) or any(
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


def _event_class_scope(value: str) -> tuple[tuple[int, ...], bool]:
    """Extract only explicit grade-11 class membership from an event row."""
    text = unescape(value).casefold().replace("\u00a0", " ")
    all_classes = bool(re.search(r"כל\s+הכיתות|all\s+classes", text, re.IGNORECASE))
    numbers = {int(item) for item in re.findall(r"יא\s*[-–]?\s*(\d+)", text)}
    for first, last in re.findall(
        r"יא\s*[-–]?\s*(\d+)\s*\.\.\.\s*יא\s*[-–]?\s*(\d+)", text
    ):
        low, high = sorted((int(first), int(last)))
        numbers.update(range(low, high + 1))
    return tuple(sorted(numbers)), all_classes


def parse_events_html(
    html: str,
    reference_date: date,
    source_url: str = "",
    expected_class_id: str = "11",
) -> EventSnapshot:
    """Parse Shahaf's explicit school-event feed.

    The feed is informational by default. Only events whose title explicitly
    indicates asynchronous/remote/no-school operation are eligible for the
    separate AI safety decision; ordinary activities remain overlays.
    """
    parser = _TreeParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise ShahafSourceError(f"Shahaf events page is malformed: {exc}") from exc

    select_match = re.search(
        r"<select\b[^>]*\bname=[\"']cls[\"'][^>]*>(.*?)</select>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if select_match:
        selected_class = any(
            re.search(rf"\bvalue=[\"']{re.escape(expected_class_id)}[\"']", attrs, re.IGNORECASE)
            and re.search(r"\bselected(?:\s*=|\b)", attrs, re.IGNORECASE)
            for attrs in re.findall(r"<option\b([^>]*)>", select_match.group(1), flags=re.IGNORECASE)
        )
        if not selected_class:
            raise ShahafSourceError(f"Shahaf events page is not selected for class {expected_class_id}")

    update_match = re.search(
        r"<div[^>]*class=[\"'][^\"']*UpdateDate[^\"']*[\"'][^>]*>(.*?)</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    update_text = _plain(update_match.group(1)) if update_match else ""
    if not update_text:
        raise ShahafSourceError("Shahaf events page has no update timestamp")

    rows = [
        node
        for node in _walk(parser.root)
        if node.tag == "li" and "changesinfo" in _class_value(node)
    ]
    page_text = _plain(html)
    if not rows:
        if "אין אירועים" in page_text or re.search(r"class=[\"'][^\"']*EmptyList", html, re.IGNORECASE):
            return EventSnapshot([], update_text, source_url)
        raise ShahafSourceError("Shahaf events page has no recognized event list")

    parsed: dict[tuple[object, ...], ShahafEvent] = {}
    for row in rows:
        metadata_text = row.text()
        detail = re.sub(r"\s+", " ", _node_text(row)).strip()
        title = _first_tag_value(row, "b")
        date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", metadata_text)
        period_match = re.search(
            r"משיעור\s*(\d+)\s*עד\s*שיעור\s*(\d+)", metadata_text, re.IGNORECASE
        )
        clock_match = re.search(
            r"משעה\s*(\d{1,2}:\d{2})\s*עד\s*שעה\s*(\d{1,2}:\d{2})",
            metadata_text,
            re.IGNORECASE,
        )
        class_match = re.search(r"לכיתות:\s*(.*)$", metadata_text)
        if not title or not date_match or not class_match or (not period_match and not clock_match):
            raise ShahafSourceError(f"Shahaf event row has unsupported format: {detail!r}")

        event_date = date(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
        start_period = end_period = None
        start_clock = end_clock = None
        if period_match:
            start_period, end_period = int(period_match.group(1)), int(period_match.group(2))
            # Shahaf uses periods beyond the regular lesson grid for events
            # such as parent meetings (for example 14–21). They are valid
            # overlays, but can never suppress lesson periods 0–13.
            if not (0 <= start_period <= end_period <= 99):
                raise ShahafSourceError(f"Shahaf event row has invalid period range: {detail!r}")
        else:
            try:
                start_clock = time.fromisoformat(clock_match.group(1))
                end_clock = time.fromisoformat(clock_match.group(2))
            except ValueError as exc:
                raise ShahafSourceError(f"Shahaf event row has invalid clock range: {detail!r}") from exc
            if start_clock >= end_clock:
                raise ShahafSourceError(f"Shahaf event row has reversed clock range: {detail!r}")

        scope = class_match.group(1).strip()
        # Some live rows serialize the nested title after the class list in
        # row.text(), even though it appears as a separate <b> element in the
        # markup. Keep the public scope limited to the actual class selector.
        if title and scope.endswith(title):
            scope = scope[: -len(title)].rstrip(" ,:-")
        class_numbers, all_classes = _event_class_scope(scope)
        if not scope or (not class_numbers and not all_classes):
            raise ShahafSourceError(f"Shahaf event row has no explicit grade-11 class scope: {detail!r}")
        event = ShahafEvent(
            date=event_date,
            title=re.sub(r"\s+", " ", unescape(title)).strip(),
            start_period=start_period,
            end_period=end_period,
            start=start_clock,
            end=end_clock,
            class_scope=scope,
            detail=detail,
            class_numbers=class_numbers,
            all_classes=all_classes,
        )
        key = (
            event.date,
            event.title,
            event.start_period,
            event.end_period,
            event.start,
            event.end,
            event.class_scope,
        )
        parsed[key] = event

    return EventSnapshot(
        sorted(parsed.values(), key=lambda item: (item.date, item.start_period if item.start_period is not None else 99, item.start or time.min, item.title)),
        update_text,
        source_url,
    )


def _class_number_includes(value: str, expected_class_number: int) -> bool:
    """Match Hebrew 11th-grade class lists, including compact ranges."""
    text = unescape(value).casefold().replace("\u00a0", " ")
    if re.search(r"כל\s+הכיתות|all\s+classes", text, re.IGNORECASE):
        return True
    numbers = {int(item) for item in re.findall(r"יא\s*[-–]?\s*(\d+)", text)}
    if expected_class_number in numbers:
        return True
    for first, last in re.findall(
        r"יא\s*[-–]?\s*(\d+)\s*\.\.\.\s*יא\s*[-–]?\s*(\d+)", text
    ):
        if int(first) <= expected_class_number <= int(last):
            return True
    return False


def _exam_subject(title: str) -> str | None:
    value = re.sub(r"^\s*מבחן(?:\s+פתיחת\s+שנה|\s+מעבר)?\s*(?:ב|ב-)?\s*", "", title).strip()
    normalized = value.casefold().replace('"', "").replace("׳", "'")
    if "מתמטיקה" in normalized:
        if re.search(r"(?:4\s*יח|4\s*יח|4\s*units)", normalized):
            return None
        return "מתמטיקה 5 יח״ל מואץ" if "מואץ" in normalized or "5" not in normalized else "מתמטיקה 5 יח״ל"
    if "אנגלית" in normalized:
        if re.search(r"(?:4\s*יח|4\s*units)", normalized):
            return None
        if "5" not in normalized and "מואץ" not in normalized:
            return None
        return "אנגלית 5 יח״ל מואץ" if "מואץ" in normalized else "אנגלית 5 יח״ל"
    if "מדמ" in normalized or "מדעי המחשב" in normalized:
        return "מדעי המחשב 1"
    for needle, subject in (
        ("ספרות", "ספרות"),
        ("היסטוריה", "היסטוריה"),
        ("עברית", "עברית"),
        ("תנך", "תנ״ך"),
        ("תנ'ך", "תנ״ך"),
        ("דיפלומטיה", "דיפלומטיה"),
        ("סייבר", "סייבר — טלפונים חכמים"),
    ):
        if needle in normalized:
            return subject
    return None


def _candidate_exam_subject(title: str) -> str | None:
    """Map a visible exam title without discarding an unknown student's major."""
    known = _exam_subject(title)
    if known is not None:
        return known
    value = re.sub(r"^\s*מבחן(?:\s+פתיחת\s+שנה|\s+מעבר)?\s*(?:ב|ב-)?\s*", "", title).strip()
    normalized = value.casefold().replace('"', "").replace("׳", "'")
    for needle, subject in (
        ("פיסיקה", "פיסיקה"),
        ("ביולוגיה", "ביולוגיה"),
        ("כימיה", "כימיה"),
        ("מזרחנות", "מזרחנות"),
        ("ערבית", "ערבית"),
        ("אזרחות", "אזרחות"),
        ("גיאוגרפיה", "גיאוגרפיה"),
        ("מדעי החברה", "מדעי החברה"),
    ):
        if needle in normalized:
            return subject
    return None


_PERSONAL_EXAM_TEACHERS: dict[str, tuple[str, ...]] = {
    "מתמטיקה 5 יח״ל מואץ": ("אפי כהן",),
    "אנגלית 5 יח״ל מואץ": ("אירין שפינל",),
    "מדעי המחשב 1": ("שמרת מן",),
    "דיפלומטיה": ("אורית גרינברג",),
    "סייבר — טלפונים חכמים": ("רועי ויסברט",),
    "הערכה חלופית — מדעי המחשב 1": ("רועי ויסברט",),
    "ספרות": ("דנה לילקובסקי",),
    "עברית": ("לימור חן",),
    "תנ״ך": ("דוד לוי",),
    "היסטוריה": ("ירון דור",),
}


def _detail_tokens(value: str) -> set[str]:
    return set(re.findall(r"[\wא-ת]+", unescape(value).casefold(), flags=re.UNICODE))


def _exam_belongs_to_personal_track(subject: str, title: str, group: str) -> bool:
    """Use Shahaf's group teacher to avoid importing another major's exam."""
    if not group:
        return True
    group_tokens = _detail_tokens(group)
    teacher_matches = [
        teacher
        for teacher in _PERSONAL_EXAM_TEACHERS.get(subject, ())
        if _detail_tokens(teacher) <= group_tokens
    ]
    if teacher_matches:
        return True
    # Shahaf sometimes labels a common grade-wide test with the subject itself
    # instead of a teacher. This is safe only for generic Math/English rows;
    # majors and elective tracks must remain teacher-specific.
    generic_term = "מתמטיקה" if subject.startswith("מתמטיקה") else "אנגלית"
    # The title often contains the Hebrew prefix ב־ (for example,
    # "מבחן במתמטיקה"), so token equality is too strict here.
    normalized_group = unescape(group).casefold()
    normalized_title = unescape(title).casefold()
    return (
        subject.startswith(("מתמטיקה", "אנגלית"))
        and generic_term in normalized_group
        and generic_term in normalized_title
    )


def parse_exams_html(
    html: str,
    reference_date: date,
    source_url: str = "",
    expected_class_number: int = 2,
    expected_class_id: str = "11",
    include_all: bool = False,
) -> ExamSnapshot:
    """Parse Shahaf's class-filtered exam list into exam candidates.

    The legacy default keeps the older personal-track filtering behavior. The
    sync pipeline uses ``include_all`` so it can select the right candidate
    separately for every student's actual subject/teacher/room combination.
    """
    parser = _TreeParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise ShahafSourceError(f"Shahaf exams page is malformed: {exc}") from exc

    select_match = re.search(
        r"<select\b[^>]*\bname=[\"']cls[\"'][^>]*>(.*?)</select>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if select_match:
        selected_class = any(
            re.search(rf"\bvalue=[\"']{re.escape(expected_class_id)}[\"']", attrs, re.IGNORECASE)
            and re.search(r"\bselected(?:\s*=|\b)", attrs, re.IGNORECASE)
            for attrs in re.findall(r"<option\b([^>]*)>", select_match.group(1), flags=re.IGNORECASE)
        )
        if not selected_class:
            raise ShahafSourceError(f"Shahaf exams page is not selected for class {expected_class_id}")

    update_match = re.search(
        r"<div[^>]*class=[\"'][^\"']*UpdateDate[^\"']*[\"'][^>]*>(.*?)</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    update_text = _plain(update_match.group(1)) if update_match else ""
    if not update_text:
        raise ShahafSourceError("Shahaf exams page has no update timestamp")

    rows = [
        node
        for node in _walk(parser.root)
        if node.tag == "li" and "changesinfo" in _class_value(node)
    ]
    page_text = _plain(html)
    if not rows:
        if "אין מבחנים" in page_text or re.search(r"class=[\"'][^\"']*EmptyList", html, re.IGNORECASE):
            return ExamSnapshot([], update_text, source_url)
        raise ShahafSourceError("Shahaf exams page has no recognized exam list")

    exams: dict[tuple[date, str, int, int], Exam] = {}
    for row in rows:
        # _node_text intentionally gathers nested text for display, but that
        # reorders the <b> title after direct row text. Parse metadata from the
        # row's own text and take the exam title from its bold child.
        metadata_text = row.text()
        text = _node_text(row)
        date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", metadata_text)
        period_match = re.search(r"משיעור\s*(\d+)\s*עד\s*שיעור\s*(\d+)", metadata_text)
        title = _first_tag_value(row, "b")
        class_match = re.search(r"לכיתות:\s*(.*?)(?:\s+בקבוצה\s+של\s+|$)", metadata_text)
        if not date_match or not period_match or not title or not class_match:
            raise ShahafSourceError(f"Shahaf exam row has unsupported format: {text!r}")
        if not _class_number_includes(class_match.group(1), expected_class_number):
            continue
        subject = _candidate_exam_subject(title) if include_all else _exam_subject(title)
        if subject is None:
            continue
        exam_date = date(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
        start_period, end_period = int(period_match.group(1)), int(period_match.group(2))
        if start_period not in PERIOD_TIMES or end_period not in PERIOD_TIMES or start_period > end_period:
            raise ShahafSourceError(f"Shahaf exam row has invalid period range: {text!r}")
        group_match = re.search(r"בקבוצה\s+של\s+(.+)$", metadata_text)
        group = group_match.group(1).strip() if group_match else ""
        room_match = re.search(r"^(.*?),\s*חדר:\s*(.+)$", group)
        teacher = room_match.group(1).strip() if room_match else group
        room = room_match.group(2).strip() if room_match else ""
        if not include_all and not _exam_belongs_to_personal_track(subject, title, group):
            continue
        key = (exam_date, subject, start_period, end_period, teacher, room, title)
        exams.setdefault(
            key,
            Exam(
                exam_date,
                subject,
                start_period,
                end_period,
                text,
                group,
                title,
                class_match.group(1).strip(),
                teacher,
                room,
            ),
        )

    return ExamSnapshot(sorted(exams.values(), key=lambda item: (item.date, item.start_period, item.subject)), update_text, source_url)


def merge_snapshots(snapshots: list[SourceSnapshot]) -> SourceSnapshot:
    if not snapshots:
        raise ShahafSourceError("No usable Shahaf timetable pages were fetched")
    unique_lessons: dict[tuple[date, int, str, str, str], Lesson] = {}
    unique_changes: dict[tuple[object, ...], PublishedChange] = {}
    unique_events: dict[tuple[object, ...], ShahafEvent] = {}
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
        for item in snapshot.events:
            unique_events[
                (
                    item.date,
                    item.title,
                    item.start_period,
                    item.end_period,
                    item.start,
                    item.end,
                    item.class_scope,
                )
            ] = item
    return SourceSnapshot(
        lessons=list(unique_lessons.values()),
        covered_dates=set().union(*(item.covered_dates for item in snapshots)),
        update_text=max(item.update_text for item in snapshots),
        source_url=snapshots[-1].source_url,
        changes=list(unique_changes.values()),
        events=list(unique_events.values()),
    )
