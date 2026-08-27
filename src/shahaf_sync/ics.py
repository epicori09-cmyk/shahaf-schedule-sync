from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Iterable


class CalendarFormatError(ValueError):
    """Raised when input is not a usable RFC 5545 calendar."""


def _split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _unfold(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def _parse_property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        raise CalendarFormatError(f"Malformed calendar property: {line!r}")
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for item in parts[1:]:
        if "=" in item:
            key, param_value = item.split("=", 1)
            params[key.upper()] = param_value.strip('"')
    return name, params, value


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\r\n", r"\n")
        .replace("\n", r"\n")
    )


def unescape(value: str) -> str:
    return (
        value.replace(r"\n", "\n")
        .replace(r"\N", "\n")
        .replace(r"\,", ",")
        .replace(r"\;", ";")
        .replace(r"\\", "\\")
    )


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def parse_datetime(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1]
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise CalendarFormatError(f"Unsupported calendar datetime: {value!r}")


def fold_ical_line(line: str, max_octets: int = 73) -> str:
    """Fold a property without splitting a UTF-8 code point."""
    encoded = line.encode("utf-8")
    if len(encoded) <= max_octets:
        return line
    pieces: list[str] = []
    remaining = line
    first = True
    while remaining:
        budget = max_octets if first else max_octets - 1
        current: list[str] = []
        used = 0
        for char in remaining:
            size = len(char.encode("utf-8"))
            if current and used + size > budget:
                break
            if not current and size > budget:
                current.append(char)
                used += size
                break
            current.append(char)
            used += size
        chunk = "".join(current)
        pieces.append(chunk if first else " " + chunk)
        remaining = remaining[len(chunk) :]
        first = False
    return "\r\n".join(pieces)


def _property_line(name: str, value: str, params: dict[str, str] | None = None) -> str:
    left = name.upper()
    for key, param_value in (params or {}).items():
        left += f";{key.upper()}={param_value}"
    return f"{left}:{value}"


@dataclass
class IcsEvent:
    raw_lines: list[str]
    lines: list[str] = field(init=False)
    dirty: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.lines = _unfold(self.raw_lines)

    @property
    def uid(self) -> str:
        return unescape(self.get("UID") or "")

    @property
    def recurrence_id(self) -> datetime | None:
        value = self.get("RECURRENCE-ID")
        return parse_datetime(value) if value else None

    @property
    def start(self) -> datetime:
        value = self.get("DTSTART")
        if not value:
            raise CalendarFormatError(f"Event {self.uid!r} has no DTSTART")
        return parse_datetime(value)

    @property
    def end(self) -> datetime:
        value = self.get("DTEND")
        if not value:
            return self.start + timedelta(minutes=40)
        return parse_datetime(value)

    @property
    def summary(self) -> str:
        return unescape(self.get("SUMMARY") or "")

    @property
    def description(self) -> str:
        return unescape(self.get("DESCRIPTION") or "")

    @property
    def location(self) -> str:
        return unescape(self.get("LOCATION") or "")

    @property
    def period(self) -> int | None:
        match = re.search(r"(?:שעה|hour)\s*(\d+)", self.summary, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @property
    def subject(self) -> str:
        value = re.sub(
            r"\s*[—-]\s*(?:שעה|hour)\s*\d+\s*$",
            "",
            self.summary,
            flags=re.IGNORECASE,
        ).strip()
        teacher = ""
        for line in self.description.splitlines():
            if line.strip().startswith("מורה:"):
                teacher = line.split(":", 1)[1].strip()
                break
        if teacher:
            value = re.sub(rf"\s*[—-]\s*{re.escape(teacher)}\s*$", "", value).strip()
        return value

    @property
    def is_recurring(self) -> bool:
        return bool(self.get("RRULE")) and self.recurrence_id is None

    def _indices(self, name: str) -> list[int]:
        return [
            index
            for index, line in enumerate(self.lines)
            if _parse_property(line)[0] == name.upper()
        ]

    def get(self, name: str) -> str | None:
        indices = self._indices(name)
        if not indices:
            return None
        return _parse_property(self.lines[indices[0]])[2]

    def get_all(self, name: str) -> list[tuple[dict[str, str], str]]:
        result: list[tuple[dict[str, str], str]] = []
        for line in self.lines:
            property_name, params, value = _parse_property(line)
            if property_name == name.upper():
                result.append((params, value))
        return result

    def _set(self, name: str, value: str, params: dict[str, str] | None = None) -> None:
        line = _property_line(name, value, params)
        indices = self._indices(name)
        if indices:
            self.lines[indices[0]] = line
            for index in reversed(indices[1:]):
                del self.lines[index]
        else:
            end_index = self.lines.index("END:VEVENT")
            self.lines.insert(end_index, line)
        self.dirty = True

    def _remove(self, name: str) -> None:
        indices = self._indices(name)
        if indices:
            for index in reversed(indices):
                del self.lines[index]
            self.dirty = True

    def _set_escaped(self, name: str, value: str, params: dict[str, str] | None = None) -> None:
        self._set(name, _escape(value), params)

    def exdates(self) -> set[datetime]:
        dates: set[datetime] = set()
        for params, value in self.get_all("EXDATE"):
            dates.update(parse_datetime(item) for item in value.split(",") if item)
        return dates

    def auto_exdates(self) -> set[datetime]:
        dates: set[datetime] = set()
        for _params, value in self.get_all("X-SHAHAF-AUTO-EXDATE"):
            dates.update(parse_datetime(item) for item in value.split(",") if item)
        return dates

    def add_exdate(self, occurrence: datetime, automatic: bool = True) -> None:
        all_dates = self.exdates()
        all_dates.add(occurrence)
        self._set(
            "EXDATE",
            ",".join(format_datetime(item) for item in sorted(all_dates)),
            {"TZID": "Asia/Jerusalem"},
        )
        if automatic:
            auto_dates = self.auto_exdates()
            auto_dates.add(occurrence)
            self._set(
                "X-SHAHAF-AUTO-EXDATE",
                ",".join(format_datetime(item) for item in sorted(auto_dates)),
                {"TZID": "Asia/Jerusalem"},
            )

    def remove_auto_exdate(self, occurrence: datetime) -> None:
        auto_dates = self.auto_exdates()
        if occurrence not in auto_dates:
            return
        auto_dates.remove(occurrence)
        if auto_dates:
            self._set(
                "X-SHAHAF-AUTO-EXDATE",
                ",".join(format_datetime(item) for item in sorted(auto_dates)),
                {"TZID": "Asia/Jerusalem"},
            )
        else:
            self._remove("X-SHAHAF-AUTO-EXDATE")
        remaining = self.exdates() - {occurrence}
        if remaining:
            self._set(
                "EXDATE",
                ",".join(format_datetime(item) for item in sorted(remaining)),
                {"TZID": "Asia/Jerusalem"},
            )
        else:
            self._remove("EXDATE")

    def occurrences(
        self, start: datetime, end: datetime, include_exdates: bool = False
    ) -> list[datetime]:
        result: list[datetime] = []
        first = self.start
        if not self.is_recurring:
            return [first] if start <= first <= end and (include_exdates or first not in self.exdates()) else []
        until = first + timedelta(days=3650)
        rule = self.get("RRULE") or ""
        for part in rule.split(";"):
            if part.upper().startswith("UNTIL="):
                until = parse_datetime(part.split("=", 1)[1])
        current = first
        excluded = self.exdates()
        while current <= until and current <= end:
            if current >= start and (include_exdates or current not in excluded):
                result.append(current)
            current += timedelta(weeks=1)
        return result

    def clone_override(
        self,
        original_start: datetime,
        new_start: datetime,
        new_end: datetime,
        summary: str,
        description: str,
        location: str,
    ) -> "IcsEvent":
        lines = [
            line
            for line in self.lines
            if _parse_property(line)[0]
            not in {"RRULE", "EXDATE", "X-SHAHAF-AUTO-EXDATE", "RECURRENCE-ID"}
        ]
        override = IcsEvent(lines)
        override._set("DTSTART", format_datetime(new_start), {"TZID": "Asia/Jerusalem"})
        override._set("DTEND", format_datetime(new_end), {"TZID": "Asia/Jerusalem"})
        override._set("RECURRENCE-ID", format_datetime(original_start), {"TZID": "Asia/Jerusalem"})
        override._set_escaped("SUMMARY", summary)
        override._set_escaped("DESCRIPTION", description)
        if location:
            override._set_escaped("LOCATION", location)
        else:
            override._remove("LOCATION")
        override._set("STATUS", "CONFIRMED")
        override._set("X-SHAHAF-AUTO", "1")
        return override

    def render(self) -> str:
        lines = self.lines if self.dirty else self.raw_lines
        if self.dirty:
            return "\r\n".join(fold_ical_line(line) for line in lines)
        return "\r\n".join(lines)


@dataclass
class Calendar:
    original_text: str
    header_lines: list[str]
    footer_lines: list[str]
    events: list[IcsEvent]
    dirty: bool = False

    def render(self) -> str:
        if not self.dirty and all(not event.dirty for event in self.events):
            return self.original_text
        parts = ["\r\n".join(self.header_lines)]
        parts.extend(event.render() for event in self.events)
        parts.append("\r\n".join(self.footer_lines))
        return "\r\n".join(part for part in parts if part) + "\r\n"

    def add_override(
        self,
        base: IcsEvent,
        original_start: datetime,
        new_start: datetime,
        new_end: datetime,
        summary: str,
        description: str,
        location: str,
    ) -> IcsEvent:
        existing = next(
            (
                event
                for event in self.events
                if event.uid == base.uid and event.recurrence_id == original_start
            ),
            None,
        )
        replacement = base.clone_override(
            original_start, new_start, new_end, summary, description, location
        )
        if existing is None:
            self.events.append(replacement)
        else:
            index = self.events.index(existing)
            self.events[index] = replacement
        self.dirty = True
        return replacement

    def add_generated_event(
        self,
        uid: str,
        start: datetime,
        end: datetime,
        summary: str,
        description: str,
        location: str,
    ) -> IcsEvent:
        existing = next((event for event in self.events if event.uid == uid), None)
        lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            "DTSTAMP:19700101T000000Z",
            f"DTSTART;TZID=Asia/Jerusalem:{format_datetime(start)}",
            f"DTEND;TZID=Asia/Jerusalem:{format_datetime(end)}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
        ]
        if location:
            lines.append(f"LOCATION:{_escape(location)}")
        lines.extend(["STATUS:CONFIRMED", "TRANSP:OPAQUE", "X-SHAHAF-AUTO:1", "END:VEVENT"])
        generated = IcsEvent(lines)
        if existing is None:
            self.events.append(generated)
        else:
            self.events[self.events.index(existing)] = generated
        self.dirty = True
        return generated

    def remove_auto_event(self, uid: str) -> bool:
        for event in list(self.events):
            if event.uid == uid and event.get("X-SHAHAF-AUTO") == "1" and not event.recurrence_id:
                self.events.remove(event)
                self.dirty = True
                return True
        return False

    def remove_auto_override(self, uid: str, recurrence_id: datetime) -> bool:
        for event in list(self.events):
            if (
                event.uid == uid
                and event.recurrence_id == recurrence_id
                and event.get("X-SHAHAF-AUTO") == "1"
            ):
                self.events.remove(event)
                self.dirty = True
                return True
        return False


def parse_calendar(text: str) -> Calendar:
    lines = _split_lines(text)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR" or lines[-1].upper() != "END:VCALENDAR":
        raise CalendarFormatError("Input does not contain a complete VCALENDAR")
    starts = [index for index, line in enumerate(lines) if line.upper() == "BEGIN:VEVENT"]
    if not starts:
        raise CalendarFormatError("Calendar contains no VEVENT records")
    events: list[IcsEvent] = []
    first_start = starts[0]
    cursor = first_start
    while cursor < len(lines):
        if lines[cursor].upper() != "BEGIN:VEVENT":
            cursor += 1
            continue
        end_index = next(
            (index for index in range(cursor + 1, len(lines)) if lines[index].upper() == "END:VEVENT"),
            None,
        )
        if end_index is None:
            raise CalendarFormatError("Unclosed VEVENT record")
        event = IcsEvent(lines[cursor : end_index + 1])
        if not event.uid or not event.get("DTSTART"):
            raise CalendarFormatError("Every VEVENT must have UID and DTSTART")
        events.append(event)
        cursor = end_index + 1
    last_end = max(
        index for index, line in enumerate(lines) if line.upper() == "END:VEVENT"
    )
    return Calendar(text, lines[:first_start], lines[last_end + 1 :], events)
