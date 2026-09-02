# Ya1 transit wake integration TDD evidence

## Source plan

Derived from the Ya1 Transit Wake Alarm implementation request.

## User journeys

- As the יא-1 profile, I want the latest safe scheduled route from מרדכי זעירא 5 to Ostrovsky so that I arrive five minutes before my first lesson.
- As the יא-1 profile, I want a separate wake alarm 75 minutes before leaving home so that יא-1 changes cannot modify the יא-2 alarm.
- As the user, I want stale, malformed, or unsafe transit data to leave the existing יא-1 alarm unchanged.

## Evidence

| Guarantee | Test or command | Result |
|---|---|---|
| Latest safe route is selected, including an exact five-minute deadline | `tests/test_transit.py:test_chooses_latest_route_arriving_five_minutes_early` | PASS |
| Home-to-stop walking time is never budgeted below five minutes | `tests/test_transit.py:test_origin_walk_is_never_less_than_five_minutes` | PASS |
| Transfers are represented as separate route legs | `tests/test_transit.py:test_transfer_route_is_supported` | PASS |
| No safe route returns `leave` | `tests/test_transit.py:test_requires_a_safe_route_and_leaves_alarm_when_none_exists` | PASS |
| Stale data returns `leave` | `tests/test_transit.py:test_stale_data_leaves_alarm_unchanged` | PASS |
| No lessons returns `clear` with only the יא-1 alarm label | `tests/test_transit.py:test_no_lessons_clears_only_the_ya1_alarm` | PASS |
| Ministry GTFS fixture is parsed and malformed archives are rejected | `tests/test_transit.py` GTFS tests | PASS |
| Ya1 endpoint is separate from root `wake.json` | `tests/test_github_and_site.py:test_site_publishes_only_the_ya1_transit_wake_endpoint` | PASS |
| Ya1 page displays the selected bus plan and early-departure policy | `tests/test_github_and_site.py:test_ya1_site_exposes_the_selected_bus_plan` | PASS |
| Live Ministry archive contains usable service data | Live `load_gtfs` smoke test | PASS: 123,704 trips and 30,615 stops |
| Live route calculation produces a safe ya1 result | Live route smoke test | PASS: bus 17 from אהוד מנור/משה וילנסקי at 07:22, 07:14 leave, 07:34 arrival, 05:59 wake for 07:45 first lesson; 8-minute home walk |
| Full integration dry-run does not write the Gist | `python -m shahaf_sync --config config.json --dry-run` | PASS: 0 changes, Gist write skipped |

## Coverage and known gaps

The final test run passed 75 tests. The updated `transit.py` module reached 85%
line coverage and the updated `site.py` module reached 85% in the focused
coverage report. Overall repository coverage remains lower because older modules are
not fully covered by the existing suite. The planner uses scheduled GTFS only;
live delays and vehicle cancellations are intentionally not inferred.
