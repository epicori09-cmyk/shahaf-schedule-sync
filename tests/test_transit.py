from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from shahaf_sync.transit import (
    StopTime,
    TransitSchedule,
    TransitStop,
    TransitTrip,
    build_ya1_transit_wake,
    download_gtfs,
    google_maps_url,
    load_gtfs,
    TransitSourceError,
)


ORIGIN = (32.1965369, 34.8627789)
DESTINATION = (32.1779021, 34.8738483)
DAY = date(2026, 9, 6)


def trip(trip_id: str, departure: time, arrival: time, route: str = "A") -> TransitTrip:
    return TransitTrip(
        trip_id=trip_id,
        route_id=route,
        route_name=f"Route {route}",
        stop_times=(
            StopTime("origin-stop", departure, departure, 1),
            StopTime("school-stop", arrival, arrival, 2),
        ),
    )


def schedule(*trips: TransitTrip) -> TransitSchedule:
    return TransitSchedule(
        stops={
            "origin-stop": TransitStop("origin-stop", "Origin", *ORIGIN),
            "school-stop": TransitStop("school-stop", "Ostrovsky", *DESTINATION),
        },
        trips=tuple(trips),
        source_timestamp="2026-09-02T03:50:00+03:00",
    )


class TransitWakeTests(unittest.TestCase):
    def test_chooses_latest_route_arriving_five_minutes_early(self) -> None:
        result = build_ya1_transit_wake(
            schedule(
                trip("early", time(7, 0), time(8, 0)),
                trip("latest-safe", time(7, 20), time(8, 25)),
                trip("too-late", time(7, 25), time(8, 26)),
            ),
            [{"date": DAY.isoformat(), "start": "08:30", "subject": "ספרות"}],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
        )
        self.assertEqual(result["route_departure"], "07:15")
        self.assertEqual(result["route_arrival"], "08:25")
        self.assertEqual(result["wake_time"], "06:00")
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["subject"], "ספרות")

    def test_origin_walk_is_never_less_than_five_minutes(self) -> None:
        result = build_ya1_transit_wake(
            schedule(trip("bus", time(7, 20), time(8, 25))),
            [{"date": DAY.isoformat(), "start": "08:30", "subject": "ספרות"}],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
        )
        self.assertEqual(result["route_departure"], "07:15")
        self.assertEqual(result["route"][0]["type"], "walk")
        self.assertEqual(result["route"][0]["minutes"], 5)

    def test_requires_a_safe_route_and_leaves_alarm_when_none_exists(self) -> None:
        result = build_ya1_transit_wake(
            schedule(trip("late", time(7, 30), time(8, 26))),
            [{"date": DAY.isoformat(), "start": "08:30", "subject": "ספרות"}],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
        )
        self.assertFalse(result["enabled"])
        self.assertEqual(result["shortcut_action"], "leave")
        self.assertEqual(result["fallback_status"], "no-safe-route")

    def test_stale_data_leaves_alarm_unchanged(self) -> None:
        result = build_ya1_transit_wake(
            schedule(trip("unused", time(7, 0), time(8, 0))),
            [{"date": DAY.isoformat(), "start": "08:30", "subject": "ספרות"}],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
            stale=True,
        )
        self.assertTrue(result["stale"])
        self.assertEqual(result["shortcut_action"], "leave")

    def test_no_lessons_clears_only_the_ya1_alarm(self) -> None:
        result = build_ya1_transit_wake(
            schedule(trip("unused", time(7, 0), time(8, 0))),
            [],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
        )
        self.assertFalse(result["enabled"])
        self.assertEqual(result["shortcut_action"], "clear")
        self.assertEqual(result["fallback_status"], "no-lessons")
        self.assertEqual(result["alarm_label"], "Shahaf Ya1 Wake")

    def test_load_gtfs_selects_active_service_and_parses_stop_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "fixture.zip"
            with ZipFile(archive, "w") as zf:
                zf.writestr(
                    "calendar.txt",
                    "service_id,sunday,monday,tuesday,wednesday,thursday,friday,saturday,start_date,end_date\n"
                    "weekday,1,1,1,1,1,0,0,20260901,20260930\n",
                )
                zf.writestr("calendar_dates.txt", "service_id,date,exception_type\n")
                zf.writestr("routes.txt", "route_id,route_short_name,route_long_name\nR1,1,School bus\n")
                zf.writestr("trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
                zf.writestr(
                    "stops.txt",
                    "stop_id,stop_name,stop_lat,stop_lon\n"
                    "origin-stop,Origin,32.1965369,34.8627789\n"
                    "school-stop,School,32.1779021,34.8738483\n",
                )
                zf.writestr(
                    "stop_times.txt",
                    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                    "T1,07:20:00,07:20:00,origin-stop,1\n"
                    "T1,08:25:00,08:25:00,school-stop,2\n",
                )
            loaded = load_gtfs(archive, DAY, source_timestamp="fixture")
        self.assertEqual(loaded.source_timestamp, "fixture")
        self.assertEqual(len(loaded.trips), 1)
        self.assertEqual(loaded.trips[0].route_name, "1")
        self.assertEqual(loaded.trips[0].stop_times[1].arrival, time(8, 25))

    def test_load_gtfs_rejects_an_invalid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.zip"
            archive.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(TransitSourceError):
                load_gtfs(archive, DAY)

    def test_transfer_route_is_supported(self) -> None:
        transfer = (32.187, 34.868)
        transit_schedule = TransitSchedule(
            stops={
                "origin-stop": TransitStop("origin-stop", "Origin", *ORIGIN),
                "transfer-stop": TransitStop("transfer-stop", "Transfer", *transfer),
                "school-stop": TransitStop("school-stop", "School", *DESTINATION),
            },
            trips=(
                TransitTrip(
                    "first-leg", "A", "Route A",
                    (StopTime("origin-stop", time(7, 20), time(7, 20), 1), StopTime("transfer-stop", time(7, 30), time(7, 30), 2)),
                ),
                TransitTrip(
                    "second-leg", "B", "Route B",
                    (StopTime("transfer-stop", time(7, 33), time(7, 33), 1), StopTime("school-stop", time(7, 38), time(7, 38), 2)),
                ),
            ),
        )
        result = build_ya1_transit_wake(
            transit_schedule,
            [{"date": DAY.isoformat(), "start": "07:45", "subject": "פיסיקה"}],
            now=datetime(2026, 9, 5, 12, 0),
            origin=ORIGIN,
            destination=DESTINATION,
            max_walk_m=100,
        )
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["route_arrival"], "07:38")
        self.assertEqual(len([leg for leg in result["route"] if leg["type"] == "transit"]), 2)

    def test_google_maps_link_contains_both_addresses_and_transit_mode(self) -> None:
        link = google_maps_url("Home", "School")
        self.assertIn("origin=Home", link)
        self.assertIn("destination=School", link)
        self.assertIn("travelmode=transit", link)

    def test_passed_today_is_not_selected_as_a_new_alarm(self) -> None:
        result = build_ya1_transit_wake(
            schedule(trip("past", time(6, 0), time(7, 0))),
            [{"date": DAY.isoformat(), "start": "07:45", "subject": "פיסיקה"}],
            now=datetime(2026, 9, 6, 9, 0),
            origin=ORIGIN,
            destination=DESTINATION,
        )
        self.assertEqual(result["shortcut_action"], "clear")
        self.assertEqual(result["fallback_status"], "no-lessons")

    def test_download_gtfs_rejects_a_small_response(self) -> None:
        class SmallResponse:
            headers = {}

            def __init__(self):
                self.read_once = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                if self.read_once:
                    return b""
                self.read_once = True
                return b"too small"

        with tempfile.TemporaryDirectory() as directory, patch("shahaf_sync.transit.urlopen", return_value=SmallResponse()):
            with self.assertRaises(TransitSourceError):
                download_gtfs("https://example.invalid/feed.zip", directory=Path(directory))


if __name__ == "__main__":
    unittest.main()
