from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.shahaf import ShahafSourceError, parse_timetable_html


HTML = """<!doctype html>
<html><body>
<select name="cls"><option value="17" selected="selected">י״א - 8</option></select>
<div class="UpdateDate">מעודכן ל: 01.09.2026, שעה: 06:00</div>
<table class="TTTable">
  <tr>
    <td class="CTitle" data-day="0">יום ראשון 06.09</td>
    <td class="CTitle" data-day="1">יום שני 07.09</td>
  </tr>
  <tr>
    <td class="CName"><b>1<br/><span class="hour-time">08:30</span><br/><span class="hour-time">09:10</span></b></td>
    <td class="TTCell" data-day="0">
      <div class="TTLesson"><b>ספרות</b>&nbsp;&nbsp;(208 — י״א 8)<br/>בר סבן</div>
    </td>
    <td class="TTCell" data-day="1"></td>
  </tr>
  <tr>
    <td class="CName"><b>2<br/><span class="hour-time">09:10</span><br/><span class="hour-time">09:50</span></b></td>
    <td class="TTCell" data-day="0"></td>
    <td class="TTCell" data-day="1">
      <div class="TTLesson"><b>מתמטיקה 5 יח״ל מואץ</b><br/>אפי כהן</div>
    </td>
  </tr>
</table>
</body></html>"""


class ShahafParserTests(unittest.TestCase):
    def test_parses_dates_periods_lessons_and_update_timestamp(self) -> None:
        snapshot = parse_timetable_html(HTML, reference_date=date(2026, 9, 1))
        self.assertEqual(snapshot.update_text, "מעודכן ל: 01.09.2026, שעה: 06:00")
        self.assertEqual(len(snapshot.lessons), 2)
        first = snapshot.lessons[0]
        self.assertEqual(first.date, date(2026, 9, 6))
        self.assertEqual(first.period, 1)
        self.assertEqual(first.subject, "ספרות")
        self.assertEqual(first.room, "208 — י״א 8")
        self.assertEqual(first.teacher, "בר סבן")
        self.assertEqual(snapshot.covered_dates, {date(2026, 9, 6), date(2026, 9, 7)})

    def test_rejects_missing_or_empty_grid(self) -> None:
        with self.assertRaises(ShahafSourceError):
            parse_timetable_html("<html><body>אין נתונים</body></html>", date(2026, 9, 1))

        empty = HTML.replace('<div class="TTLesson"><b>ספרות</b>&nbsp;&nbsp;(208 — י״א 8)<br/>בר סבן</div>', "")
        empty = empty.replace('<div class="TTLesson"><b>מתמטיקה 5 יח״ל מואץ</b><br/>אפי כהן</div>', "")
        with self.assertRaises(ShahafSourceError):
            parse_timetable_html(empty, date(2026, 9, 1))


if __name__ == "__main__":
    unittest.main()
