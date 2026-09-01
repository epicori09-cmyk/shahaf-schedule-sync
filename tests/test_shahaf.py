from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.shahaf import ShahafSourceError, parse_changes_html, parse_timetable_html


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


CHANGES_HTML = """<!doctype html>
<html><body>
<select name="cls"><option value="17" selected="selected">י״א - 8</option></select>
<div class="UpdateDate">מעודכן ל: 01.09.2026, שעה: 06:00</div>
<div class="ChangeRow" data-date="02.09.2026" data-period="1" data-kind="cancelled">
  <span class="ChangeSubject">מתמטיקה</span><span class="ChangeAction">בוטל</span>
</div>
<div class="ChangeRow" data-date="03.09.2026" data-period="2" data-new-period="4"
     data-kind="changed" data-teacher="מורה מחליף" data-room="208" data-start="10:45" data-end="11:25">
  <span class="ChangeSubject">ספרות</span><span class="ChangeAction">מורה מחליף</span>
</div>
<div class="ChangeRow" data-date="04.09.2026" data-period="3" data-kind="added" data-start="10:05" data-end="10:45">
  <span class="ChangeSubject">היסטוריה</span><span class="ChangeAction">שיעור נוסף</span>
</div>
</body></html>"""


NEW_CHANGES_HTML = """<!doctype html>
<html><body>
<select name="cls"><option value="17" selected="selected">י״א - 8</option></select>
<div class="UpdateDate">מעודכן ל: 01.09.2026, שעה: 15:20</div>
<ul><li class="ChangesInfo">01.09.2026, שיעור 1, מן שמרת, ביטול שעור</li></ul>
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

    def test_parses_explicit_changes_without_treating_other_lessons_as_missing(self) -> None:
        snapshot = parse_changes_html(CHANGES_HTML, reference_date=date(2026, 9, 1))
        self.assertEqual(snapshot.update_text, "מעודכן ל: 01.09.2026, שעה: 06:00")
        self.assertEqual([item.kind for item in snapshot.changes], ["cancelled", "changed", "added"])
        self.assertEqual(snapshot.changes[0].period, 1)
        self.assertEqual(snapshot.changes[0].subject, "מתמטיקה")
        self.assertEqual(snapshot.changes[1].new_period, 4)
        self.assertEqual(snapshot.changes[1].teacher, "מורה מחליף")
        self.assertEqual(snapshot.changes[1].room, "208")
        self.assertEqual(snapshot.covered_dates, {date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)})

    def test_empty_changes_feed_is_safe(self) -> None:
        empty = CHANGES_HTML[: CHANGES_HTML.index('<div class="ChangeRow"')]
        empty += '<div class="EmptyList">אין שינויים</div></body></html>'
        snapshot = parse_changes_html(empty, reference_date=date(2026, 9, 1))
        self.assertEqual(snapshot.changes, [])
        self.assertEqual(snapshot.covered_dates, set())

    def test_unknown_non_empty_changes_markup_fails_closed(self) -> None:
        unknown = CHANGES_HTML[: CHANGES_HTML.index('<div class="ChangeRow"')]
        unknown += '<div class="UnexpectedThing">02.09.2026 שעה 1 מתמטיקה בוטל</div></body></html>'
        with self.assertRaises(ShahafSourceError):
            parse_changes_html(unknown, reference_date=date(2026, 9, 1))

    def test_parses_current_changes_list_rows_with_teacher_and_cancellation(self) -> None:
        snapshot = parse_changes_html(NEW_CHANGES_HTML, reference_date=date(2026, 9, 1))
        self.assertEqual(len(snapshot.changes), 1)
        change = snapshot.changes[0]
        self.assertEqual(change.date, date(2026, 9, 1))
        self.assertEqual(change.period, 1)
        self.assertEqual(change.teacher, "מן שמרת")
        self.assertEqual(change.kind, "cancelled")
        self.assertEqual(change.subject, "")


if __name__ == "__main__":
    unittest.main()
