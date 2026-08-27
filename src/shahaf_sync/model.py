from __future__ import annotations

from dataclasses import dataclass
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
class SourceSnapshot:
    lessons: list[Lesson]
    covered_dates: set[date]
    update_text: str
    source_url: str

