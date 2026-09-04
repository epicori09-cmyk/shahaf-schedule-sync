from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.exams import reconcile_exam_events
from shahaf_sync.ics import parse_calendar
from shahaf_sync.shahaf import parse_exams_html


EXAMS_HTML = """<!doctype html>
<html><body>
<select name="cls"><option value="11" selected="selected">יא - 2</option></select>
<div class="UpdateDate">מעודכן ל: 02.09.2026, שעה: 11:17</div>
<ul>
  <li class="ChangesInfo">06.09.2026, <b>מבחן במתמטיקה</b> משיעור 4 עד שיעור 6 לכיתות: יא-1...יא-9, יא-11 בקבוצה של מתמטיקה</li>
  <li class="ChangesInfo">08.09.2026, <b>מבחן באנגלית 4 יח״ל</b> משיעור 1 עד שיעור 3 לכיתות: יא-1...יא-9</li>
  <li class="ChangesInfo">10.09.2026, <b>מבחן מעבר במדמ״ח - בודדים</b> משיעור 7 עד שיעור 9 לכיתות: יא-1...יא-4, יא-7, יא-8, יא-11 בקבוצה של מן שמרת</li>
  <li class="ChangesInfo">11.09.2026, <b>מבחן במדעי המחשב 1</b> משיעור 1 עד שיעור 3 לכיתות: יא-2 בקבוצה של מורה אחר</li>
  <li class="ChangesInfo">11.09.2026, <b>מבחן בדיפלומטיה</b> משיעור 1 עד שיעור 3 לכיתות: יא-2 בקבוצה של מורה אחר</li>
  <li class="ChangesInfo">12.09.2026, <b>מבחן באנגלית 5 יח״ל מואץ</b> משיעור 1 עד שיעור 3 לכיתות: יא-1...יא-9</li>
  <li class="ChangesInfo">15.09.2026, <b>מבחן פתיחת שנה בביולוגיה</b> משיעור 1 עד שיעור 3 לכיתות: יא-2</li>
  <li class="ChangesInfo">16.09.2026, <b>מבחן במזרחנות</b> משיעור 1 עד שיעור 3 לכיתות: יא-2 בקבוצה של גלוסקא שירי, חדר: י״א 7 - 214</li>
</ul></body></html>"""


OLD_ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
X-WR-TIMEZONE:Asia/Jerusalem\r
BEGIN:VEVENT\r
UID:old-lesson@example\r
DTSTAMP:20260901T000000Z\r
DTSTART;TZID=Asia/Jerusalem:20260906T104500\r
DTEND;TZID=Asia/Jerusalem:20260906T112500\r
RRULE:FREQ=WEEKLY;UNTIL=20270618T205959Z\r
SUMMARY:מתמטיקה — שעה 4\r
DESCRIPTION:מורה: אפי כהן\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
"""


class ExamTests(unittest.TestCase):
    def test_parser_keeps_personal_tracks_and_rejects_other_tracks(self) -> None:
        snapshot = parse_exams_html(EXAMS_HTML, date(2026, 9, 2), expected_class_number=2, expected_class_id="11")
        self.assertEqual(snapshot.update_text, "מעודכן ל: 02.09.2026, שעה: 11:17")
        self.assertEqual(
            [(item.date, item.subject, item.start_period, item.end_period) for item in snapshot.exams],
            [
                (date(2026, 9, 6), "מתמטיקה", 4, 6),
                (date(2026, 9, 10), "מדעי המחשב 1", 7, 9),
                (date(2026, 9, 12), "אנגלית 5 יח״ל מואץ", 1, 3),
            ],
        )

    def test_include_all_keeps_parallel_major_candidates_for_profile_matching(self) -> None:
        snapshot = parse_exams_html(
            EXAMS_HTML,
            date(2026, 9, 2),
            expected_class_number=2,
            expected_class_id="11",
            include_all=True,
        )
        self.assertEqual(len(snapshot.exams), 7)
        math_groups = [item for item in snapshot.exams if item.subject.startswith("מתמטיקה")]
        self.assertEqual(len(math_groups), 1)
        self.assertEqual(math_groups[0].teacher, "מתמטיקה")
        self.assertEqual(math_groups[0].title, "מבחן במתמטיקה")
        self.assertTrue(any(item.subject == "ביולוגיה" for item in snapshot.exams))
        mizrahnut = next(item for item in snapshot.exams if item.subject == "מזרחנות")
        self.assertEqual(mizrahnut.teacher, "גלוסקא שירי")
        self.assertEqual(mizrahnut.room, "י״א 7 - 214")

    def test_reconcile_adds_four_day_seven_pm_calendar_alarm(self) -> None:
        snapshot = parse_exams_html(EXAMS_HTML, date(2026, 9, 2), expected_class_number=2, expected_class_id="11")
        calendar = parse_calendar(OLD_ICS)
        reconcile_exam_events(calendar, snapshot.exams)
        exams = [event for event in calendar.events if event.get("X-SHAHAF-EXAM") == "1"]
        self.assertEqual(len(exams), 3)
        math = next(event for event in exams if "מתמטיקה" in event.summary)
        self.assertIn("TRIGGER;VALUE=DATE-TIME;TZID=Asia/Jerusalem:20260902T190000", math.lines)
        self.assertIn("DTSTART;TZID=Asia/Jerusalem:20260906T104500", math.lines)
        self.assertIn("X-SHAHAF-EXAM:1", math.lines)


if __name__ == "__main__":
    unittest.main()
