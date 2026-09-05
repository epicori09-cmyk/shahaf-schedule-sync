from __future__ import annotations

from datetime import date, time
import unittest

from shahaf_sync.model import Lesson, PublishedChange, Exam
from shahaf_sync.profiles import apply_changes, select_changes, select_exams, select_lessons
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
    def test_teacher_selector_matches_shahaf_first_last_name_order(self) -> None:
        lessons = [
            Lesson(date(2026, 9, 6), 2, time(9, 10), time(9, 50), "מדעי המחשב", "דנישבסקי יונתן", "")
        ]
        spec = {"selectors": [{"subject": "מדעי המחשב", "teacher": "יונתן דנישבסקי"}]}
        selected = select_lessons(lessons, spec)
        self.assertEqual(len(selected), 1)

    def test_change_selector_matches_shahaf_first_last_name_order(self) -> None:
        changes = [
            PublishedChange(
                date(2026, 9, 6),
                2,
                "",
                "cancelled",
                teacher="דנישבסקי יונתן",
            )
        ]
        spec = {"selectors": [{"teacher": "יונתן דנישבסקי", "periods": [2]}]}
        selected = select_changes(changes, spec)
        self.assertEqual(selected, changes)

    def test_teacher_only_change_matches_a_shared_lesson_by_teacher_identity(self) -> None:
        lessons = [
            Lesson(date(2026, 9, 6), 2, time(9, 10), time(9, 50), "חינוך גופני", "יונתן דנישבסקי", "")
        ]
        changes = [
            PublishedChange(
                date(2026, 9, 6),
                2,
                "",
                "cancelled",
                teacher="דנישבסקי יונתן",
            )
        ]
        spec = {"shared_subjects": ["חינוך גופני"]}
        selected = select_changes(changes, spec, lessons=lessons)
        self.assertEqual(selected, changes)

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

    def test_exact_exam_track_excludes_parallel_accelerated_exam(self) -> None:
        exams = [
            Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל", 4, 6, group="מתמטיקה 5 יח״ל"),
            Exam(date(2026, 9, 7), "מתמטיקה 5 יח״ל מואץ", 4, 6, group="מתמטיקה 5 יח״ל מואץ"),
        ]
        selected = select_exams(
            exams,
            {"exam_terms": ["מתמטיקה 5 יח״ל"], "exam_exact_terms": ["מתמטיקה 5 יח״ל"]},
        )
        self.assertEqual([item.subject for item in selected], ["מתמטיקה 5 יח״ל"])

    def test_exam_matching_uses_major_teacher_and_prefers_specific_room(self) -> None:
        exams = [
            Exam(
                date(2026, 9, 6),
                "מתמטיקה 5 יח״ל מואץ",
                4,
                6,
                title="מבחן במתמטיקה",
                group="מתמטיקה",
                teacher="מתמטיקה",
            ),
            Exam(
                date(2026, 9, 6),
                "מתמטיקה 5 יח״ל מואץ",
                4,
                6,
                title="מבחן במתמטיקה",
                group="מלישקביץ יובל, חדר: י״א 2 - 217",
                teacher="מלישקביץ יובל",
                room="י״א 2 - 217",
            ),
            Exam(date(2026, 9, 10), "ביולוגיה", 1, 3, title="מבחן פתיחת שנה בביולוגיה", teacher="מורה אחר"),
            Exam(date(2026, 9, 12), "אנגלית 4 יח״ל", 1, 3, title="מבחן באנגלית 4 יח״ל", teacher="שניאור רני"),
        ]
        lessons = [
            Lesson(date(2026, 9, 7), 4, time(10, 45), time(11, 25), "מתמטיקה 5 יח״ל", "מלישקביץ יובל", "י״א 2 - 217"),
            Lesson(date(2026, 9, 7), 1, time(8, 30), time(9, 10), "אנגלית 5 יח״ל", "שניאור רני", "י״א 4 - 109"),
        ]
        selected = select_exams(exams, {}, lessons=lessons)
        self.assertEqual(
            [(item.subject, item.teacher, item.room) for item in selected],
            [("מתמטיקה 5 יח״ל", "מלישקביץ יובל", "י״א 2 - 217")],
        )

    def test_exam_matching_drops_unconfirmed_math_and_individual_cs_track(self) -> None:
        exams = [
            Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל מואץ", 4, 6, title="מבחן במתמטיקה", teacher="מתמטיקה"),
            Exam(date(2026, 9, 6), "מתמטיקה 5 יח״ל", 4, 6, title="מבחן במתמטיקה 5 יח״ל", teacher="מלישקביץ יובל"),
            Exam(date(2026, 9, 10), "מדעי המחשב 1", 7, 9, title="מבחן מעבר במדמ״ח - בודדים", teacher="מן שמרת"),
        ]
        lessons = [
            Lesson(date(2026, 9, 6), 4, time(10, 45), time(11, 25), "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "י״א 7 - 214"),
            Lesson(date(2026, 9, 8), 1, time(8, 30), time(9, 10), "מדעי המחשב 1", "מן שמרת", ""),
        ]
        selected = select_exams(exams, {}, lessons=lessons)
        self.assertEqual(selected, [])

    def test_generic_math_does_not_become_accelerated_exam(self) -> None:
        exams = [
            Exam(date(2026, 9, 6), "מתמטיקה", 4, 6, title="מבחן במתמטיקה", group="מתמטיקה"),
        ]
        lessons = [
            Lesson(date(2026, 9, 6), 4, time(10, 45), time(11, 25), "מתמטיקה 5 יח״ל מואץ", "אפי כהן", "י״א 7 - 214"),
        ]
        self.assertEqual(select_exams(exams, {}, lessons=lessons), [])

    def test_computer_science_individual_exam_does_not_match_regular_group(self) -> None:
        exams = [
            Exam(
                date(2026, 9, 10),
                "מדעי המחשב 1",
                7,
                9,
                title="מבחן מעבר במדמ״ח - בודדים",
                detail="בקבוצה של מן שמרת",
                teacher="מן שמרת",
            ),
            Exam(
                date(2026, 9, 11),
                "מדעי המחשב 1",
                1,
                3,
                title="מבחן במדעי המחשב 1",
                teacher="מן שמרת",
            ),
        ]
        lessons = [
            Lesson(date(2026, 9, 8), 1, time(8, 30), time(9, 10), "מדעי המחשב 1", "שמרת מן", ""),
        ]
        selected = select_exams(exams, {}, lessons=lessons)
        self.assertEqual([item.date for item in selected], [date(2026, 9, 11)])

    def test_ya1_transcribed_baseline_keeps_the_supplied_periods_and_gaps(self) -> None:
        lessons = build_ya1_schedule(date(2026, 9, 6), date(2026, 9, 10))
        sunday = {(item.period, item.subject) for item in lessons if item.date == date(2026, 9, 6)}
        monday = {(item.period, item.subject, item.teacher) for item in lessons if item.date == date(2026, 9, 7)}
        tuesday = {(item.period, item.subject) for item in lessons if item.date == date(2026, 9, 8)}
        self.assertNotIn((4, "היסטוריה"), sunday)
        for period in (9, 10, 11, 12):
            self.assertFalse(any(item_period == period for item_period, _subject in sunday))
        self.assertEqual(
            sorted(item for item in monday if item[0] in (10, 11, 12)),
            [
                (10, "הערכה חלופית", "צחי"),
                (11, "הערכה חלופית", "צחי"),
                (12, "הערכה חלופית", "צחי"),
            ],
        )
        self.assertIn((1, "מדעי המחשב"), tuesday)
        self.assertIn((6, "פיסיקה"), tuesday)
        self.assertNotIn((0, "פיסיקה"), tuesday)

    def test_mizrahnut_exam_matches_nitay_but_not_profiles_without_that_major(self) -> None:
        exams = [
            Exam(
                date(2026, 9, 14),
                "מזרחנות",
                1,
                3,
                title="מבחן במזרחנות",
                teacher="גלוסקא שירי",
                room="י״א 7 - 214",
            ),
        ]
        nitay_lessons = [
            Lesson(date(2026, 9, 7), 1, time(8, 30), time(9, 10), "מזרחנות", "גלוסקא שירי", "י״א 7 - 214"),
        ]
        ori_lessons = [
            Lesson(date(2026, 9, 7), 1, time(8, 30), time(9, 10), "מדעי המחשב", "מן שמרת", "מעבדת מחשבים 153"),
        ]
        self.assertEqual(select_exams(exams, {}, lessons=nitay_lessons)[0].subject, "מזרחנות")
        self.assertEqual(select_exams(exams, {}, lessons=ori_lessons), [])


if __name__ == "__main__":
    unittest.main()
