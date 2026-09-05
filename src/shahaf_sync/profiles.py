from __future__ import annotations

"""Track-aware selectors for additional public Shahaf schedule profiles.

The public class timetable contains parallel major groups.  A profile must
therefore select only the confirmed group(s), while retaining subjects that
are shared by the whole class.  This module intentionally keeps the selector
explicit rather than guessing from a subject name alone.
"""

from dataclasses import replace
from datetime import time
import re
from typing import Any, Mapping

from .model import Exam, Lesson, PERIOD_TIMES, PublishedChange


def _text(value: str) -> str:
    value = value.replace("״", '"').replace("׳", "'")
    value = value.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _matches(value: str, expected: str) -> bool:
    return _text(value) == _text(expected)


def _person_matches(left: str, right: str) -> bool:
    """Match Hebrew names even when Shahaf reverses first/last-name order."""
    left_tokens = set(re.findall(r"[\wא-ת]+", _text(left), flags=re.UNICODE))
    right_tokens = set(re.findall(r"[\wא-ת]+", _text(right), flags=re.UNICODE))
    return bool(left_tokens and right_tokens and left_tokens == right_tokens)


def _value(item: object, name: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _exam_family(value: str) -> str:
    text = _text(value)
    if "מתמט" in text:
        return "math"
    if "אנגלית" in text:
        return "english"
    if "מדעי המחשב" in text or "מדמח" in text or "מדמ" in text:
        return "computer-science"
    if "סייבר" in text:
        return "cyber"
    for needle, family in (
        ("פיסיק", "physics"),
        ("דיפלומט", "diplomacy"),
        ("ספרות", "literature"),
        ("עברית", "hebrew"),
        ("תנך", "bible"),
        ("היסטור", "history"),
        ("חינוך", "education"),
        ("ביולוג", "biology"),
        ("כימ", "chemistry"),
        ("מזרחנות", "mizrahnut"),
        ("ערבית", "arabic"),
        ("אזרחות", "civics"),
        ("גיאוגרפ", "geography"),
        ("מדעי החברה", "social-sciences"),
    ):
        if needle in text:
            return family
    return ""


def _profile_track_subjects(lessons: list[object]) -> dict[str, list[str]]:
    tracks: dict[str, list[str]] = {}
    for lesson in lessons:
        subject = str(_value(lesson, "subject", ""))
        family = _exam_family(subject)
        if family:
            tracks.setdefault(family, []).append(subject)
    return tracks


def _track_subject(family: str, subjects: list[str]) -> str:
    """Choose the useful profile label to display for a matched exam."""
    unique = list(dict.fromkeys(subjects))
    if not unique:
        return ""
    if family == "computer-science":
        plain = [item for item in unique if "הערכה" not in _text(item)]
        return min(plain or unique, key=lambda item: (len(_text(item)), _text(item)))
    if family == "cyber":
        return max(unique, key=lambda item: (len(_text(item)), _text(item)))
    return max(unique, key=lambda item: (len(_text(item)), _text(item)))


def _exam_group_parts(exam: Exam) -> tuple[str, str]:
    teacher = str(exam.teacher or "").strip()
    room = str(exam.room or "").strip()
    group = str(exam.group or "").strip()
    if not teacher:
        room_match = re.match(r"^(.*?),\s*חדר:\s*(.+)$", group)
        if room_match:
            teacher, room = room_match.group(1).strip(), room_match.group(2).strip()
        else:
            teacher = group
    return teacher, room


def _exam_level_conflict(exam: Exam, subject: str, family: str) -> bool:
    if family not in {"math", "english"}:
        return False
    exam_text = _text(exam.title or exam.subject)
    profile_text = _text(subject)
    exam_four = bool(re.search(r"\b4\s*יח", exam_text))
    exam_five = bool(re.search(r"\b5\s*יח", exam_text))
    profile_four = bool(re.search(r"\b4\s*יח", profile_text))
    profile_five = bool(re.search(r"\b5\s*יח", profile_text))
    if exam_four and not profile_four:
        return True
    if exam_five and profile_four:
        return True
    exam_accelerated = "מואץ" in exam_text
    profile_accelerated = "מואץ" in profile_text
    if exam_accelerated and not profile_accelerated:
        return True
    if profile_accelerated and exam_five and not exam_accelerated:
        return True
    return False


def _exam_is_individual_cs_candidate(exam: Exam, family: str) -> bool:
    """Reject Computer Science exams explicitly limited to individual students."""
    if family != "computer-science":
        return False
    text = _text(" ".join((exam.title, exam.detail, exam.group)))
    return any(term in text for term in ("בודדים", "בודד", "יחידים", "יחידני"))


def _has_level_marker(value: str) -> bool:
    text = _text(value)
    return bool(re.search(r"\b[45]\s*יח", text)) or "מואץ" in text


def _exam_specificity(exam: Exam, profile_lessons: list[object], family: str) -> int | None:
    if _exam_is_individual_cs_candidate(exam, family):
        return None
    matching_lessons = [
        lesson
        for lesson in profile_lessons
        if _exam_family(str(_value(lesson, "subject", ""))) == family
        and not _exam_level_conflict(exam, str(_value(lesson, "subject", "")), family)
    ]
    if not matching_lessons:
        return None
    teacher, room = _exam_group_parts(exam)
    normalized_teacher = _text(teacher)
    generic_groups = {"math": {"מתמטיקה"}, "english": {"אנגלית"}}
    is_generic = not teacher or normalized_teacher in generic_groups.get(family, set())
    # A generic Math/English row cannot be assigned to a level-specific track
    # when Shahaf did not publish the level. A named teacher or room is useful
    # evidence and may still match a specific track.
    if (
        is_generic
        and family in {"math", "english"}
        and not _has_level_marker(exam.title)
        and any(_has_level_marker(str(_value(lesson, "subject", ""))) for lesson in matching_lessons)
    ):
        return None
    teacher_match = any(
        _person_matches(teacher, str(_value(lesson, "teacher", "")))
        for lesson in matching_lessons
        if teacher and not is_generic
    )
    room_match = any(
        _matches(room, str(_value(lesson, "room", "")))
        for lesson in matching_lessons
        if room and not is_generic
    )
    if not is_generic and not teacher_match and not room_match:
        return None
    score = 3 if is_generic else 7
    if teacher_match:
        score += 4
    if room_match:
        score += 2
    if any(_matches(str(_value(lesson, "subject", "")), exam.subject) for lesson in matching_lessons):
        score += 2
    return score


def _selector_matches(lesson: Lesson, selector: dict[str, Any]) -> bool:
    periods = selector.get("periods")
    weekdays = selector.get("weekdays")
    if periods and lesson.period not in {int(value) for value in periods}:
        return False
    if weekdays and lesson.date.weekday() not in {int(value) for value in weekdays}:
        return False
    subject = selector.get("subject")
    teacher = selector.get("teacher")
    room = selector.get("room")
    return (
        (not subject or _matches(lesson.subject, str(subject)))
        # Shahaf may publish a teacher as either first-name/last-name or
        # last-name/first-name. Treat the person's token set as the identity
        # while keeping subject and room matching exact.
        and (not teacher or _person_matches(lesson.teacher, str(teacher)))
        and (not room or _matches(lesson.room, str(room)))
    )


def select_lessons(lessons: list[Lesson], spec: dict[str, Any]) -> list[Lesson]:
    """Select one profile's lessons from a whole-class Shahaf timetable."""

    shared = {_text(str(value)) for value in spec.get("shared_subjects", [])}
    selectors = [item for item in spec.get("selectors", []) if isinstance(item, dict)]
    selected: list[Lesson] = []
    for lesson in lessons:
        if _text(lesson.subject) in shared or any(
            _selector_matches(lesson, selector) for selector in selectors
        ):
            selected.append(lesson)

    # Physical education and a few other shared rows can be repeated for
    # parallel groups.  One period must produce one personal lesson.
    deduped: dict[tuple[Any, ...], Lesson] = {}
    for lesson in selected:
        key = (lesson.date, lesson.period, _text(lesson.subject))
        previous = deduped.get(key)
        if previous is None or (not previous.teacher and lesson.teacher):
            deduped[key] = lesson
    return sorted(
        deduped.values(), key=lambda item: (item.date, item.period, _text(item.subject))
    )


def _change_matches(change: PublishedChange, spec: dict[str, Any]) -> bool:
    shared = {_text(str(value)) for value in spec.get("shared_subjects", [])}
    if change.subject and _text(change.subject) in shared:
        return True
    selectors = [item for item in spec.get("selectors", []) if isinstance(item, dict)]
    for selector in selectors:
        periods = selector.get("periods")
        weekdays = selector.get("weekdays")
        if periods and change.period not in {int(value) for value in periods}:
            continue
        if weekdays and change.date.weekday() not in {int(value) for value in weekdays}:
            continue
        subject = str(selector.get("subject", ""))
        teacher = str(selector.get("teacher", ""))
        room = str(selector.get("room", ""))
        if subject and not _matches(change.subject, subject):
            continue
        if change.teacher and teacher and not _person_matches(change.teacher, teacher):
            continue
        if change.room and room and not _matches(change.room, room):
            continue
        if change.subject or change.teacher or change.room:
            return True
    return not change.subject and not change.teacher and not change.room


def select_changes(changes: list[PublishedChange], spec: dict[str, Any]) -> list[PublishedChange]:
    return [change for change in changes if _change_matches(change, spec)]


def apply_changes(lessons: list[Lesson], changes: list[PublishedChange]) -> list[Lesson]:
    """Apply selected, date-scoped changes to dated public timetable rows."""

    result = list(lessons)
    for change in sorted(changes, key=lambda item: (item.date, item.period, item.kind)):
        matches = [
            index
            for index, lesson in enumerate(result)
            if lesson.date == change.date and lesson.period == change.period
        ]
        if change.kind == "cancelled":
            result = [
                lesson
                for index, lesson in enumerate(result)
                if index not in matches
            ]
            continue
        if change.kind == "added":
            start, end = _change_times(change)
            result.append(
                Lesson(
                    change.date,
                    change.period,
                    start,
                    end,
                    change.subject,
                    change.teacher or "",
                    change.room or "",
                )
            )
            continue
        if not matches:
            continue
        index = matches[0]
        old = result[index]
        target_period = change.new_period or old.period
        default_start, default_end = PERIOD_TIMES.get(target_period, (old.start, old.end))
        result[index] = replace(
            old,
            period=target_period,
            start=change.start or default_start,
            end=change.end or default_end,
            subject=change.subject or old.subject,
            teacher=change.teacher if change.teacher is not None else old.teacher,
            room=change.room if change.room is not None else old.room,
        )
    return sorted(result, key=lambda item: (item.date, item.period, _text(item.subject)))


def _change_times(change: PublishedChange) -> tuple[time, time]:
    default_start, default_end = PERIOD_TIMES.get(change.new_period or change.period, (time(0), time(0)))
    return change.start or default_start, change.end or default_end


def select_exams(
    exams: list[Exam],
    spec: dict[str, Any],
    lessons: list[object] | None = None,
) -> list[Exam]:
    """Select each student's exams from Shahaf's mixed major-group feed.

    When lessons are available, schedule evidence is authoritative: a test
    must belong to one of the student's subject families, and a named Shahaf
    group must match that student's teacher or room. If several rows describe
    the same test, the most specific match wins over the generic grade-wide
    row. The old term-only behavior remains as a compatibility fallback for
    callers that do not provide a schedule.
    """
    terms = [_text(str(value)) for value in spec.get("exam_terms", [])]
    exact_terms = {_text(str(value)) for value in spec.get("exam_exact_terms", [])}
    if lessons is None:
        return [
            exam
            for exam in exams
            if (not exact_terms or _text(exam.subject) in exact_terms)
            and any(term and (term in _text(exam.subject) or term in _text(exam.group)) for term in terms)
        ]

    tracks = _profile_track_subjects(lessons)
    candidates: list[tuple[int, Exam, str]] = []
    for exam in exams:
        family = _exam_family(exam.subject or exam.title)
        if not family or family not in tracks:
            continue
        scores: list[int] = []
        for subject in tracks[family]:
            score = _exam_specificity(exam, lessons, family)
            if score is not None:
                if _matches(subject, exam.subject):
                    score += 2
                scores.append(score)
        if not scores:
            continue
        # A generic Shahaf title such as "מבחן במתמטיקה" does not identify
        # the student's level. Label it with the matched profile track while
        # retaining the original title and detail in the exam record.
        display_subject = _track_subject(family, tracks[family]) or exam.subject
        if exact_terms and _text(exam.subject) not in exact_terms and _text(display_subject) not in exact_terms:
            # Exact terms are an explicit administrator restriction, but a
            # generic source title may still be represented by the profile's
            # exact track label.
            continue
        candidates.append((max(scores), replace(exam, subject=display_subject), family))

    best: dict[tuple[object, ...], tuple[int, Exam]] = {}
    for score, exam, family in candidates:
        key = (exam.date, family, exam.start_period, exam.end_period)
        previous = best.get(key)
        tie_break = (_text(exam.teacher or exam.group), _text(exam.room), _text(exam.title))
        previous_tie = (
            _text(previous[1].teacher or previous[1].group),
            _text(previous[1].room),
            _text(previous[1].title),
        ) if previous else None
        if previous is None or score > previous[0] or (score == previous[0] and tie_break < previous_tie):
            best[key] = (score, exam)
    return sorted(
        (item[1] for item in best.values()),
        key=lambda exam: (exam.date, exam.start_period, _text(exam.subject), _text(exam.group)),
    )


def lesson_to_dict(lesson: Lesson) -> dict[str, Any]:
    return {
        "date": lesson.date.isoformat(),
        "period": lesson.period,
        "subject": lesson.subject,
        "teacher": lesson.teacher,
        "room": lesson.room,
        "start": lesson.start.strftime("%H:%M"),
        "end": lesson.end.strftime("%H:%M"),
    }
