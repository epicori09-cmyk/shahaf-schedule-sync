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
class Exam:
    date: date
    subject: str
    start_period: int
    end_period: int
    detail: str = ""
    group: str = ""
    title: str = ""
    class_scope: str = ""
    teacher: str = ""
    room: str = ""


@dataclass(frozen=True, slots=True)
class ExamSnapshot:
    exams: list[Exam]
    update_text: str
    source_url: str


@dataclass(frozen=True, slots=True)
class ShahafEvent:
    """One date-scoped event published by Shahaf.

    Shahaf uses period 14 as the end sentinel for an all-day school event,
    while lessons themselves only occupy periods 0 through 13.
    """

    date: date
    title: str
    start_period: int | None = None
    end_period: int | None = None
    start: time | None = None
    end: time | None = None
    class_scope: str = ""
    detail: str = ""
    class_numbers: tuple[int, ...] = ()
    all_classes: bool = False

    def applies_to_class(self, class_number: int) -> bool:
        return self.all_classes or class_number in self.class_numbers


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    events: list[ShahafEvent]
    update_text: str
    source_url: str


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    lessons: list[Lesson]
    covered_dates: set[date]
    update_text: str
    source_url: str
    changes: list[PublishedChange] = field(default_factory=list)
    events: list[ShahafEvent] = field(default_factory=list)
