# Alexa wake-up integration TDD evidence

## Source plan

Derived from the user-approved Alexa School Wake-Up Integration plan.

## User journeys

- As a student, I want a wake-up reminder 75 minutes before my first confirmed lesson.
- As a student, I want a cancellation or later first lesson to move the reminder later.
- As a student, I want no reminder on a day with no lessons.
- As a student, I want stale or malformed schedule data to use the safe 07:15 default.

## RED and GREEN evidence

- RED: `python -m unittest tests.test_alexa -v` failed with `ModuleNotFoundError: No module named 'shahaf_sync.alexa'` before implementation.
- GREEN: `python -m unittest discover -s tests -v` completed with `Ran 33 tests ... OK`.
- Syntax: `python -m py_compile src/shahaf_sync/alexa.py scripts/update_alexa_reminder.py alexa/lambda_function.py` completed successfully.
- Coverage: `python -m coverage report -m` completed at `TOTAL 83%`.

## Guarantees

| Guarantee | Test or validation | Result |
|---|---|---|
| 08:30 first lesson produces 07:15 wake-up | `tests/test_alexa.py` | PASS |
| Later first lesson moves wake-up later | `tests/test_alexa.py` | PASS |
| No upcoming lessons produce no reminder | `tests/test_alexa.py` | PASS |
| Stale or invalid schedule uses default 07:15 | `tests/test_alexa.py` | PASS |
| Reminder payload is timezone-aware and deterministic in date | `tests/test_alexa.py` | PASS |
| Existing Shahaf/Gist/cancellation behavior remains green | Full test suite | PASS |

## Known gaps

- Alexa Developer Console skill creation, reminder permission approval, and Echo playback require the user’s Amazon account and cannot be completed from the repository.
- The GitHub updater intentionally does not create the first managed reminder; this prevents duplicate reminders. The first reminder must be created from the Alexa skill before `ALEXA_LWA_ACCESS_TOKEN` is added as a repository secret.
- Live Alexa reminder delivery remains a manual device test.
