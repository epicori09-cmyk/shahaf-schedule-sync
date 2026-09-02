from __future__ import annotations

"""The supplied יא-1 timetable baseline.

Shahaf's public grid contains parallel major rows.  This baseline preserves
the exact day/period choices supplied for the second public page; its changes
feed is still used for dated cancellations and replacements.
"""

from datetime import date

from .model import Lesson, PERIOD_TIMES


# (Python weekday, period, subject, teacher, room)
YA1_WEEKLY_SCHEDULE: tuple[tuple[int, int, str, str, str], ...] = (
    # Sunday
    (6, 1, "ספרות", "ליקובסקי דנה", "י״א 1–215"),
    (6, 2, "תנ״ך", "גלוסקא שירי", "י״א 1–215"),
    (6, 3, "תנ״ך", "גלוסקא שירי", "י״א 1–215"),
    (6, 7, "חינוך גופני", "דולב מיכל", ""),
    (6, 8, "ספרות", "ליקובסקי דנה", "י״א 1–215"),
    # Monday (periods 10–13 were not visible in the supplied screenshots)
    (0, 0, "היסטוריה", "לוי אושרי", "י״א 1–215"),
    (0, 1, "עברית", "אליאס מיכל", "י״א 1–215"),
    (0, 2, "עברית", "אליאס מיכל", "י״א 1–215"),
    (0, 3, "היסטוריה", "לוי אושרי", "י״א 1–215"),
    (0, 4, "היסטוריה", "לוי אושרי", "י״א 1–215"),
    (0, 8, "אנגלית 5 יח״ל מואץ", "שפינל אירין", "י״א 2–217"),
    (0, 9, "אנגלית 5 יח״ל מואץ", "שפינל אירין", "י״א 2–217"),
    (0, 10, "הערכה חלופית", "צחי", ""),
    (0, 11, "הערכה חלופית", "צחי", ""),
    (0, 12, "הערכה חלופית", "צחי", ""),
    # Tuesday (periods 10–13 were not visible in the supplied screenshots)
    (1, 1, "מדעי המחשב", "מן שמרת", ""),
    (1, 2, "מדעי המחשב", "מן שמרת", ""),
    (1, 3, "מדעי המחשב", "מן שמרת", ""),
    (1, 4, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (1, 5, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (1, 6, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (1, 7, "חינוך", "גלוסקא שירי", "י״א 1–215"),
    # Wednesday
    (2, 0, "חינוך", "גלוסקא שירי", "י״א 1–215"),
    (2, 1, "אנגלית 5 יח״ל מואץ", "שפינל אירין", "י״א 2–217"),
    (2, 2, "אנגלית 5 יח״ל מואץ", "שפינל אירין", "י״א 2–217"),
    (2, 3, "היסטוריה", "לוי אושרי", "י״א 1–215"),
    (2, 4, "היסטוריה", "לוי אושרי", "י״א 1–215"),
    (2, 5, "עברית", "אליאס מיכל", "י״א 1–215"),
    (2, 6, "עברית", "אליאס מיכל", "י״א 1–215"),
    (2, 7, "חינוך גופני", "דולב מיכל", ""),
    (2, 10, "סייבר", "לופו רועי משה", "153 מעבדת מחשבים"),
    (2, 11, "סייבר", "לופו רועי משה", "153 מעבדת מחשבים"),
    (2, 12, "סייבר", "לופו רועי משה", "153 מעבדת מחשבים"),
    (2, 13, "סייבר", "לופו רועי משה", "153 מעבדת מחשבים"),
    # Thursday
    (3, 0, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (3, 1, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (3, 2, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (3, 3, "פיסיקה", "שגיא גיא", "308 מע׳ פיסיקה"),
    (3, 4, "מדעי המחשב", "מן שמרת", ""),
    (3, 5, "מדעי המחשב", "מן שמרת", ""),
    (3, 6, "מדעי המחשב", "מן שמרת", ""),
    (3, 7, "תנ״ך", "גלוסקא שירי", "י״א 1–215"),
    (3, 8, "ספרות", "ליקובסקי דנה", "י״א 1–215"),
    (3, 9, "ספרות", "ליקובסקי דנה", "י״א 1–215"),
    (3, 10, "עברית", "אליאס מיכל", "מקוון אינטרנטי"),
    (3, 11, "עברית", "אליאס מיכל", "י״א 1–215"),
)


def build_ya1_schedule(window_start: date, window_end: date) -> list[Lesson]:
    lessons: list[Lesson] = []
    current = window_start
    while current <= window_end:
        for weekday, period, subject, teacher, room in YA1_WEEKLY_SCHEDULE:
            if current.weekday() != weekday:
                continue
            start, end = PERIOD_TIMES[period]
            lessons.append(Lesson(current, period, start, end, subject, teacher, room))
        current = date.fromordinal(current.toordinal() + 1)
    return sorted(lessons, key=lambda item: (item.date, item.period))
