from __future__ import annotations

from datetime import date, time
import unittest

from shahaf_sync.model import Lesson, PublishedChange
from shahaf_sync.profiles import (
    apply_changes,
    change_matching_is_ambiguous,
    select_changes,
)


DAY = date(2026, 10, 7)


def lesson(subject: str, teacher: str, room: str = "101") -> Lesson:
    return Lesson(DAY, 2, time(9, 10), time(9, 50), subject, teacher, room)


class CancellationIdentityTests(unittest.TestCase):
    def test_shared_subject_change_accepts_reversed_teacher_tokens(self) -> None:
        selected_lesson = lesson("חינוך גופני", "דני כהן")
        change = PublishedChange(DAY, 2, "חינוך גופני", "cancelled", teacher="כהן דני")

        selected = select_changes(
            [change],
            {"shared_subjects": ["חינוך גופני"]},
            lessons=[selected_lesson],
        )

        self.assertEqual(selected, [change])

    def test_shared_subject_change_with_wrong_teacher_is_rejected(self) -> None:
        selected_lesson = lesson("חינוך גופני", "דני כהן")
        change = PublishedChange(DAY, 2, "חינוך גופני", "cancelled", teacher="מורה אחרת")

        selected = select_changes(
            [change],
            {"shared_subjects": ["חינוך גופני"]},
            lessons=[selected_lesson],
        )

        self.assertEqual(selected, [])

    def test_subject_only_selector_rejects_change_from_wrong_selected_teacher(self) -> None:
        selected_lesson = lesson("פיסיקה 1", "מורה ב")
        change = PublishedChange(DAY, 2, "פיסיקה 1", "cancelled", teacher="מורה א")

        selected = select_changes(
            [change],
            {"selectors": [{"subject": "פיסיקה 1"}]},
            lessons=[selected_lesson],
        )

        self.assertEqual(selected, [])

    def test_room_move_does_not_block_subject_and_teacher_change(self) -> None:
        selected_lesson = lesson("פיסיקה 1", "דני כהן", room="old room")
        change = PublishedChange(
            DAY,
            2,
            "פיסיקה 1",
            "changed",
            teacher="כהן דני",
            room="new room",
        )
        spec = {
            "selectors": [
                {"subject": "פיסיקה 1", "teacher": "דני כהן", "room": "old room"}
            ]
        }

        selected = select_changes([change], spec, lessons=[selected_lesson])
        updated = apply_changes([selected_lesson], selected)

        self.assertEqual(selected, [change])
        self.assertEqual(updated[0].room, "new room")

    def test_teacher_only_cancellation_preserves_unrelated_same_period_lesson(self) -> None:
        target = lesson("מתמטיקה", "דני כהן")
        unrelated = lesson("ספרות", "רוני לוי")
        change = PublishedChange(DAY, 2, "", "cancelled", teacher="כהן דני")

        result = apply_changes([target, unrelated], [change])

        self.assertEqual(result, [unrelated])

    def test_single_occurrence_changed_subject_and_teacher_replacement_still_applies(self) -> None:
        original = lesson("מתמטיקה", "מורה קודם", room="101")
        change = PublishedChange(
            DAY,
            2,
            "פיסיקה",
            "changed",
            teacher="מורה חדש",
            room="202",
            start=time(9, 15),
            end=time(9, 55),
        )

        result = apply_changes([original], [change])

        self.assertEqual(
            result,
            [Lesson(DAY, 2, time(9, 15), time(9, 55), "פיסיקה", "מורה חדש", "202")],
        )

    def test_subject_cancellation_without_teacher_preserves_parallel_same_subjects(self) -> None:
        first = lesson("חינוך גופני", "דני כהן")
        second = lesson("חינוך גופני", "רוני לוי", room="102")
        change = PublishedChange(DAY, 2, "חינוך גופני", "cancelled")

        result = apply_changes([first, second], [change])

        self.assertEqual(result, [first, second])

    def test_period_only_cancellation_preserves_ambiguous_parallel_teachers(self) -> None:
        first = lesson("מתמטיקה", "דני כהן")
        second = lesson("ספרות", "רוני לוי")
        change = PublishedChange(DAY, 2, "", "cancelled")

        result = apply_changes([first, second], [change])

        self.assertEqual(result, [first, second])

    def test_ambiguous_cancellation_is_reported_for_future_safe_failure_gate(self) -> None:
        first = lesson("מתמטיקה", "דני כהן")
        second = lesson("ספרות", "רוני לוי")
        change = PublishedChange(DAY, 2, "", "cancelled")

        self.assertTrue(change_matching_is_ambiguous([first, second], [change]))

    def test_definite_teacher_cancellation_is_not_reported_as_ambiguous(self) -> None:
        target = lesson("מתמטיקה", "דני כהן")
        unrelated = lesson("ספרות", "רוני לוי")
        change = PublishedChange(DAY, 2, "", "cancelled", teacher="כהן דני")

        self.assertFalse(change_matching_is_ambiguous([target, unrelated], [change]))


if __name__ == "__main__":
    unittest.main()
