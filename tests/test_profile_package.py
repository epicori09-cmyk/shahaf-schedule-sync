from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.profile_package import ProfilePackageError, build_package_schedule, package_to_spec, validate_package


def package() -> dict:
    rows = []
    for weekday in ("sunday", "monday"):
        for period in range(14):
            rows.append({
                "weekday": weekday,
                "period": period,
                "start": "08:30" if period == 1 else None,
                "end": "09:10" if period == 1 else None,
                "subject": "מתמטיקה" if period == 1 else None,
                "teacher": "מורה" if period == 1 else None,
                "room": "101" if period == 1 else None,
                "status": "lesson" if period == 1 else "gap",
            })
    return {
        "schema_version": 1,
        "student": {"name": None},
        "shahaf": {"class_id": "11", "class_number": 2, "shared_subjects": [], "selectors": [], "exam_terms": ["מתמטיקה"], "english_level": "5_accelerated", "math_level": "5", "majors": ["computer_science", "diplomacy"]},
        "weekly_schedule": rows,
        "transit": {"enabled": False, "origin_address": None, "origin_lat": None, "origin_lon": None},
        "extraction": {"visible_weekdays": ["sunday", "monday"], "visible_periods": {}, "warnings": []},
    }


class ProfilePackageTests(unittest.TestCase):
    def test_valid_package_preserves_hebrew_and_expands_only_lessons(self) -> None:
        normalized = validate_package(package())
        self.assertEqual(normalized["weekly_schedule"][1]["subject"], "מתמטיקה")
        self.assertEqual(normalized["shahaf"]["english_level"], "5_accelerated")
        self.assertEqual(normalized["shahaf"]["majors"], ["computer_science", "diplomacy"])
        lessons = build_package_schedule(normalized, date(2026, 9, 6), date(2026, 9, 7))
        self.assertEqual([(lesson.date, lesson.period) for lesson in lessons], [(date(2026, 9, 6), 1), (date(2026, 9, 7), 1)])
        self.assertEqual(package_to_spec(normalized, "A" * 22)["id"], "A" * 22)

    def test_unknown_clipped_row_blocks_publish(self) -> None:
        value = package()
        value["weekly_schedule"][0]["status"] = "unknown"
        with self.assertRaises(ProfilePackageError) as caught:
            validate_package(value)
        self.assertIn("unknown", str(caught.exception))

    def test_missing_period_duplicate_and_invalid_time_block(self) -> None:
        value = package()
        value["weekly_schedule"] = value["weekly_schedule"][:-1]
        value["weekly_schedule"][0]["start"] = "25:00"
        value["weekly_schedule"].append(dict(value["weekly_schedule"][0]))
        with self.assertRaises(ProfilePackageError) as caught:
            validate_package(value)
        message = str(caught.exception)
        self.assertIn("HH:MM", message)
        self.assertIn("duplicates", message)

    def test_missing_class_id_blocks_automatic_publication(self) -> None:
        value = package()
        value["shahaf"]["class_id"] = None
        with self.assertRaises(ProfilePackageError):
            validate_package(value)

    def test_enabled_transit_requires_origin_coordinates(self) -> None:
        value = package()
        value["transit"] = {"enabled": True, "origin_address": "home", "origin_lat": None, "origin_lon": None}
        with self.assertRaises(ProfilePackageError):
            validate_package(value)

    def test_missing_room_is_allowed_when_the_screenshot_did_not_show_one(self) -> None:
        value = package()
        value["weekly_schedule"][1]["room"] = None
        normalized = validate_package(value)
        self.assertIsNone(normalized["weekly_schedule"][1]["room"])
        lessons = build_package_schedule(normalized, date(2026, 9, 6), date(2026, 9, 6))
        self.assertEqual(lessons[0].room, "")


if __name__ == "__main__":
    unittest.main()
