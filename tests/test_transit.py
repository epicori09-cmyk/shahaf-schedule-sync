from __future__ import annotations

from datetime import date, datetime, time
import unittest

from shahaf_sync.transit import (
    StopTime,
    TransitSchedule,
    TransitStop,
    TransitTrip,
    build_ya1_transit_wake,
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
        self.assertEqual(result["route_departure"], "07:20")
        self.assertEqual(result["route_arrival"], "08:25")
        self.assertEqual(result["wake_time"], "06:05")
        self.assertEqual(result["shortcut_action"], "set")
        self.assertEqual(result["subject"], "ספרות")

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


if __name__ == "__main__":
    unittest.main()
