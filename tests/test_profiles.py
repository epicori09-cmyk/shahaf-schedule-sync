from __future__ import annotations

from datetime import date, time
import unittest

from shahaf_sync.model import Lesson, PublishedChange, Exam
from shahaf_sync.profiles import apply_changes, select_exams, select_lessons
from shahaf_sync.ya1_schedule import build_ya1_schedule


SPEC = {
    "shared_subjects": ["עברית", "חינוך גופני"],
    "selectors": [
        {"subject": "פיסיקה 1", "teacher": "שגיא גיא", "room": "308 מע׳ פיסיקה"},
        {"subject": "מדעי המחשב 2"},
        {
            "subject": "הערכה חלופית - מדעי המחשב2",
            "teacher": "ויסברט רועי",
            "room": "152 מעבדת מחשבים",
        },
    ],
    "exam_terms": ["פיסיקה", "מדעי המחשב 2"],
}


class ProfileTests(unittest.TestCase):
    def test_selects_confirmed_tracks_and_shared_lessons_only(self) -> None:
        lessons = [
            Lesson(date(2026, 9, 10), 1, time(8, 30), time(9, 10), "פיסיקה 1", "שגיא גיא", "308 מע׳ פיסיקה"),
            Lesson(date(2026, 9, 10), 1, time(8, 30), time(9, 10), "פיסיקה 1", "טורניאנסקי אבנר", "306 מע׳ פיסיקה"),
            Lesson(date(2026, 9, 10), 4, time(10, 45), time(11, 25), "מדעי המחשב 2", "מן שמרת", ""),
            Lesson(date(2026, 9, 10), 4, time(10, 45), time(11, 25), "פיסיקה 2", "טורניאנסקי אבנר", "306 מע׳ פיסיקה"),
            Lesson(date(2026, 9, 10), 7, time(13, 25), time(14, 5), "עברית", "אליאס מיכל", "י״א 1 - 215"),
        ]
        selected = select_lessons(lessons, SPEC)
        self.assertEqual(
            [(item.period, item.subject, item.teacher) for item in selected],
            [(1, "פיסיקה 1", "שגיא גיא"), (4, "מדעי המחשב 2", "מן שמרת"), (7, "עברית", "אליאס מיכל")],
        )

    def test_selected_changes_are_date_scoped(self) -> None:
        lessons = [
            Lesson(date(2026, 9, 10), 4, time(10, 45), time(11, 25), "מדעי המחשב 2", "מן שמרת", ""),
            Lesson(date(2026, 9, 17), 4, time(10, 45), time(11, 25), "מדעי המחשב 2", "מן שמרת", ""),
        ]
        changes = [
            PublishedChange(date(2026, 9, 10), 4, "מדעי המחשב 2", "cancelled"),
        ]
        result = apply_changes(lessons, changes)
        self.assertEqual([item.date for item in result], [date(2026, 9, 17)])

    def test_exam_filter_does_not_pull_math_or_cs1(self) -> None:
        exams = [
            Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל מואץ", 4, 6, group="מתמטיקה"),
            Exam(date(2026, 9, 10), "מדעי המחשב 1", 7, 9, group="מן שמרת"),
            Exam(date(2026, 9, 20), "מדעי המחשב 2", 7, 9, group="מן שמרת"),
        ]
        selected = select_exams(exams, SPEC)
        self.assertEqual([item.subject for item in selected], ["מדעי המחשב 2"])

    def test_ya1_transcribed_baseline_keeps_the_supplied_periods_and_gaps(self) -> None:
        lessons = build_ya1_schedule(date(2026, 9, 6), date(2026, 9, 10))
        sunday = {(item.period, item.subject) for item in lessons if item.date == date(2026, 9, 6)}
        tuesday = {(item.period, item.subject) for item in lessons if item.date == date(2026, 9, 8)}
        self.assertIn((9, "אנגלית 5 יח״ל מואץ"), sunday)
        self.assertIn((10, "הערכה חלופית – מדעי המחשב"), sunday)
        self.assertIn((1, "מדעי המחשב"), tuesday)
        self.assertIn((6, "פיסיקה"), tuesday)
        self.assertNotIn((0, "פיסיקה"), tuesday)


if __name__ == "__main__":
    unittest.main()
