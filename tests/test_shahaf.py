from __future__ import annotations

from datetime import date
import unittest

from shahaf_sync.shahaf import ShahafSourceError, parse_changes_html, parse_events_html, parse_timetable_html


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


EVENTS_HTML = """<!doctype html>
<html><body>
<select name="cls"><option value="11" selected="selected">י״א - 2</option></select>
<div class="UpdateDate">מעודכן ל: 03.09.2026, שעה: 11:04</div>
<ul class="list-unstyled tt-changes-list mb-0">
  <li class="ChangesInfo">07.09.2026, <b>טיול פתיחת שנה</b> משיעור 0 עד שיעור 14 לכיתות: יא-1...יא-9, יא-11, יא-12</li>
  <li class="ChangesInfo">09.09.2026, <b>יום למידה א-סינכרוני</b> משיעור 0 עד שיעור 14 לכיתות: יא-1...יא-9, יא-11, יא-12</li>
  <li class="ChangesInfo">10.09.2026, <b>חגיגות ראש השנה</b> משעה 12:50 עד שעה 13:00 לכיתות: כל הכיתות</li>
  <li class="ChangesInfo">16.09.2026, <b>אסיפת הורים</b> משיעור 14 עד שיעור 21 לכיתות: יא-1...יא-9, יא-11, יא-12</li>
</ul>
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

    def test_parses_roomless_teacher_for_track_filtering(self) -> None:
        html = HTML.replace(
            '<div class="TTLesson"><b>מתמטיקה 5 יח״ל מואץ</b><br/>אפי כהן</div>',
            '<div class="TTLesson"><b>מדעי המחשב 2</b><br/>מן שמרת</div>',
        )
        snapshot = parse_timetable_html(html, reference_date=date(2026, 9, 1))
        self.assertEqual(snapshot.lessons[-1].subject, "מדעי המחשב 2")
        self.assertEqual(snapshot.lessons[-1].teacher, "מן שמרת")

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

    def test_parses_events_period_clock_scope_and_post_school_periods(self) -> None:
        snapshot = parse_events_html(EVENTS_HTML, reference_date=date(2026, 9, 4), expected_class_id="11")
        self.assertEqual(snapshot.update_text, "מעודכן ל: 03.09.2026, שעה: 11:04")
        self.assertEqual(len(snapshot.events), 4)
        async_event = snapshot.events[1]
        self.assertEqual(async_event.title, "יום למידה א-סינכרוני")
        self.assertEqual(async_event.class_scope, "יא-1...יא-9, יא-11, יא-12")
        self.assertEqual((async_event.start_period, async_event.end_period), (0, 14))
        self.assertTrue(async_event.applies_to_class(2))
        self.assertFalse(async_event.applies_to_class(10))
        clock_event = snapshot.events[2]
        self.assertEqual((clock_event.start.isoformat(), clock_event.end.isoformat()), ("12:50:00", "13:00:00"))
        parent_meeting = snapshot.events[3]
        self.assertEqual((parent_meeting.start_period, parent_meeting.end_period), (14, 21))

    def test_empty_events_feed_is_safe(self) -> None:
        empty = EVENTS_HTML[: EVENTS_HTML.index('<ul class="list-unstyled')]
        empty += '<div class="EmptyList">אין אירועים</div></body></html>'
        snapshot = parse_events_html(empty, reference_date=date(2026, 9, 4), expected_class_id="11")
        self.assertEqual(snapshot.events, [])

    def test_unknown_non_empty_events_markup_fails_closed(self) -> None:
        unknown = EVENTS_HTML[: EVENTS_HTML.index('<ul class="list-unstyled')]
        unknown += '<div class="UnexpectedEvent">09.09.2026 async</div></body></html>'
        with self.assertRaises(ShahafSourceError):
            parse_events_html(unknown, reference_date=date(2026, 9, 4), expected_class_id="11")


if __name__ == "__main__":
    unittest.main()
