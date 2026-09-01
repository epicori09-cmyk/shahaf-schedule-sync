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


# The school timetable uses the same bell slots shown in Shahaf: period 0 is
# the optional early slot, and period 13 is the final afternoon slot.
PERIOD_TIMES: dict[int, tuple[time, time]] = {
    0: (time(7, 45), time(8, 25)),
    1: (time(8, 30), time(9, 10)),
    2: (time(9, 10), time(9, 50)),
    3: (time(10, 5), time(10, 45)),
    4: (time(10, 45), time(11, 25)),
    5: (time(11, 35), time(12, 15)),
    6: (time(12, 15), time(12, 55)),
    7: (time(13, 25), time(14, 5)),
    8: (time(14, 5), time(14, 45)),
    9: (time(14, 50), time(15, 30)),
    10: (time(15, 30), time(16, 10)),
    11: (time(16, 20), time(17, 0)),
    12: (time(17, 0), time(17, 40)),
    13: (time(17, 40), time(18, 20)),
}


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
