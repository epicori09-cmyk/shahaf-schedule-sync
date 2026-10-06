from datetime import date, datetime, time
import unittest
import re
from zoneinfo import ZoneInfo

from test_shahaf import HTML, CHANGES_HTML, EVENTS_HTML
from test_exams import EXAMS_HTML
from shahaf_sync.shahaf import parse_timetable_html, parse_changes_html, parse_events_html, parse_exams_html, ShahafSourceError
from shahaf_sync.site import build_wake_data
from shahaf_sync.model import Lesson, PublishedChange
from shahaf_sync.profiles import select_changes


class SourceSafetyTests(unittest.TestCase):
    def test_partial_or_duplicate_timetable_cells_are_rejected(self):
        for html in (HTML.replace('<td class="TTCell" data-day="1"></td>', ''),
                     HTML.replace('<td class="TTCell" data-day="1"></td>', '<td class="TTCell" data-day="0"></td>'),
                     HTML.replace('data-day="1">יום שני', 'data-day="0">יום שני')):
            with self.subTest(html=html), self.assertRaises(ShahafSourceError):
                parse_timetable_html(html, date(2026, 9, 1))

    def test_live_weekly_import_cannot_accept_a_truncated_grid(self):
        with self.assertRaisesRegex(ShahafSourceError, "weekly timetable grid is incomplete"):
            parse_timetable_html(HTML, date(2026, 9, 1), require_complete_grid=True)

    def test_empty_corner_header_is_not_a_malformed_period(self):
        html = HTML.replace('<td class="CTitle" data-day="0">', '<td class="CName"></td><td class="CTitle" data-day="0">', 1)
        self.assertEqual(len(parse_timetable_html(html, date(2026, 9, 1)).lessons), 2)

    def test_weekly_grid_must_match_requested_class_identity(self):
        for html in (HTML, HTML.replace('name="cls"', 'name="other"')):
            with self.assertRaisesRegex(ShahafSourceError, "not selected for class 61"):
                parse_timetable_html(html, date(2026, 9, 1), expected_class_id="61")
        self.assertEqual(len(parse_timetable_html(HTML, date(2026, 9, 1), expected_class_id="17").lessons), 2)

    def test_obsolete_source_year_is_not_relabeled_as_current(self):
        with self.assertRaises(ShahafSourceError):
            parse_timetable_html(HTML.replace("01.09.2026", "01.09.2020"), date(2026, 10, 6))

    def test_unchanged_current_academic_year_is_still_valid(self):
        self.assertTrue(parse_timetable_html(HTML, date(2026, 10, 6)).lessons)

    def test_malformed_early_period_cannot_disappear_into_later_wake(self):
        malformed = HTML.replace('<span class="hour-time">08:30</span>', '<span class="hour-time">bad-time</span>')
        with self.assertRaises(ShahafSourceError):
            parse_timetable_html(malformed, date(2026, 9, 1))
        with self.assertRaises(ShahafSourceError):
            parse_timetable_html(HTML.replace("<b>ספרות</b>", "ספרות"), date(2026, 9, 1))

    def test_changes_without_selected_class_are_not_trusted(self):
        html = CHANGES_HTML.replace('<select name="cls"><option value="17" selected="selected">י״א - 8</option></select>', '')
        with self.assertRaises(ShahafSourceError):
            parse_changes_html(html, date(2026, 9, 1), expected_class_id="17")

    def test_events_and_exams_require_selected_class_identity(self):
        for parser, html in ((parse_events_html, EVENTS_HTML), (parse_exams_html, EXAMS_HTML)):
            for invalid in (re.sub(r'<select.*?</select>', '', html), html.replace('value="11"', 'value="61"')):
                with self.subTest(parser=parser.__name__), self.assertRaises(ShahafSourceError):
                    parser(invalid, date(2026, 10, 6), expected_class_id="11")

    def test_wrong_teacher_cannot_enter_period_only_cancellation_output(self):
        day = date(2026, 10, 7)
        lessons = [Lesson(day, 2, time(9, 10), time(9, 50), "Math", "Teacher B", "")]
        change = PublishedChange(day, 2, "", "cancelled", teacher="Teacher A")
        self.assertEqual(select_changes([change], {"selectors": [{"periods": [2]}]}, lessons=lessons), [])

    def test_malformed_fixed_fallback_preserves_existing_alarm(self):
        for clock in ("broken", "07:15+03:00"):
            result = build_wake_data([{"date": "2026-10-07", "start": "07:45"}], schedule_available=True, stale=True,
                now=datetime(2026, 10, 6, 5, tzinfo=ZoneInfo("Asia/Jerusalem")), stale_policy="set_fixed", fallback_wake_time=clock)
            self.assertEqual(result["shortcut_action"], "leave")

    def test_orphan_cancellation_cannot_enter_selector_output(self):
        lessons = [Lesson(date(2026, 10, 7), 2, time(9, 10), time(9, 50), "Math", "Teacher A", "")]
        change = PublishedChange(date(2026, 10, 8), 2, "", "cancelled", teacher="Teacher A")
        self.assertEqual(select_changes([change], {"selectors": [{"periods": [2]}]}, lessons=lessons), [])


if __name__ == "__main__":
    unittest.main()
