from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True, slots=True)
class Lesson:
    date: date
    period: int
    start: time
    end: time
    subject: str
    teacher: str = ""
    room: str = ""


@dataclass(frozen=True, slots=True)
class PublishedChange:
    """One explicit, date-scoped change published by Shahaf."""

    date: date
    period: int
    subject: str
    kind: str
    new_period: int | None = None
    start: time | None = None
    end: time | None = None
    teacher: str | None = None
    room: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    lessons: list[Lesson]
    covered_dates: set[date]
    update_text: str
    source_url: str
    changes: list[PublishedChange] = field(default_factory=list)
