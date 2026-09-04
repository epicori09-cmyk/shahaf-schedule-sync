from __future__ import annotations

"""Small, deterministic transit planner for the isolated יא-1 wake alarm.

The planner consumes a validated subset of Israeli GTFS.  It deliberately
does not call Moovit or Google for routing, so the alarm remains free and the
main יא-2 alarm never depends on a third-party credential.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import csv
import io
import math
from pathlib import Path
import tempfile
from collections.abc import Callable, Mapping
from typing import Iterable
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo


ZONE = ZoneInfo("Asia/Jerusalem")
DEFAULT_GTFS_URL = "https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip"
ORIGIN_ADDRESS = "מרדכי זעירא 5, רעננה"
DESTINATION_ADDRESS = "אוסטרובסקי 26, רעננה"
YA1_ALARM_LABEL = "Shahaf Ya1 Wake"
MIN_ORIGIN_WALK_MINUTES = 5
ISRAEL_WEEKEND_WEEKDAYS = frozenset({4, 5})  # Friday and Saturday


class TransitSourceError(RuntimeError):
    """Raised when GTFS is missing, malformed, or not usable."""


@dataclass(frozen=True, slots=True)
class TransitStop:
    stop_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class StopTime:
    stop_id: str
    arrival: time
    departure: time
    sequence: int


@dataclass(frozen=True, slots=True)
class TransitTrip:
    trip_id: str
    route_id: str
    route_name: str
    stop_times: tuple[StopTime, ...]


@dataclass(frozen=True, slots=True)
class TransitSchedule:
    stops: dict[str, TransitStop]
    trips: tuple[TransitTrip, ...]
    source_timestamp: str = ""


@dataclass(frozen=True, slots=True)
class TransitRoute:
    departure: datetime
    first_bus_departure: datetime
    arrival: datetime
    transfers: int
    legs: tuple[dict[str, object], ...]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=ZONE) if value.tzinfo is None else value.astimezone(ZONE)


def _parse_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise TransitSourceError(f"Invalid GTFS time: {value!r}")
    hour, minute, second = (int(part) for part in parts)
    if not 0 <= minute < 60 or not 0 <= second < 60 or not 0 <= hour <= 47:
        raise TransitSourceError(f"Invalid GTFS time: {value!r}")
    return time(hour % 24, minute, second)


def _gtfs_datetime(target: date, value: time) -> datetime:
    # The planner only needs school-morning service times.  A GTFS 24:00:00
    # value is normalized by _parse_time to midnight on the service date;
    # retaining that distinction would require carrying a day offset through
    # every StopTime and is irrelevant to this use case.
    return datetime.combine(target, value).replace(tzinfo=ZONE)


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(haversine))


def _walk_minutes(distance_m: float) -> int:
    # Conservative 1.25 m/s walking speed; the route start includes walking
    # from the address to the first stop and the route end includes walking
    # from the final stop to school.
    return int(math.ceil(distance_m / 75.0))


def _nearby_stops(
    schedule: TransitSchedule,
    point: tuple[float, float],
    max_walk_m: int,
    *,
    minimum_walk_minutes: int = 0,
) -> list[tuple[str, int]]:
    candidates = [
        (stop_id, max(minimum_walk_minutes, _walk_minutes(_distance_m(point, (stop.lat, stop.lon)))))
        for stop_id, stop in schedule.stops.items()
        if _distance_m(point, (stop.lat, stop.lon)) <= max_walk_m
    ]
    return sorted(candidates, key=lambda item: (item[1], item[0]))


def _trip_index(schedule: TransitSchedule) -> dict[str, list[tuple[TransitTrip, int]]]:
    index: dict[str, list[tuple[TransitTrip, int]]] = {}
    for trip in schedule.trips:
        for position, stop_time in enumerate(trip.stop_times):
            index.setdefault(stop_time.stop_id, []).append((trip, position))
    for departures in index.values():
        departures.sort(key=lambda item: item[0].stop_times[item[1]].departure)
    return index


def plan_route(
    schedule: TransitSchedule,
    target_date: date,
    arrival_deadline: time,
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    not_before: datetime | None = None,
    max_walk_m: int = 1800,
    max_transfers: int = 2,
    preferred_route_ids: set[str] | None = None,
    latest_home_departure: datetime | None = None,
) -> TransitRoute | None:
    """Find the latest route whose final walk ends by ``arrival_deadline``."""

    origin_stops = _nearby_stops(
        schedule,
        origin,
        max_walk_m,
        minimum_walk_minutes=MIN_ORIGIN_WALK_MINUTES,
    )
    destination_stops = dict(_nearby_stops(schedule, destination, max_walk_m))
    if not origin_stops or not destination_stops:
        return None

    deadline = _gtfs_datetime(target_date, arrival_deadline)
    earliest = _aware(not_before) if not_before else _gtfs_datetime(target_date, time(0, 0))
    departures = _trip_index(schedule)
    # Search initial boardings in descending home-departure order.  The first
    # start that produces a safe route is therefore the latest possible start;
    # this avoids a global state cap biasing the answer toward early buses.
    starts: list[tuple[datetime, datetime, str, int, int, TransitTrip]] = []
    for origin_stop_id, walk_to_origin in origin_stops:
        for trip, position in departures.get(origin_stop_id, ()):
            if preferred_route_ids and trip.route_id not in preferred_route_ids:
                continue
            first_bus = _gtfs_datetime(target_date, trip.stop_times[position].departure)
            home_departure = first_bus - timedelta(minutes=walk_to_origin)
            if earliest <= home_departure and first_bus <= deadline and (latest_home_departure is None or home_departure <= latest_home_departure):
                starts.append((home_departure, first_bus, origin_stop_id, walk_to_origin, position, trip))
    starts.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    for home_departure, first_bus, origin_stop_id, walk_to_origin, position, initial_trip in starts:
        candidates: list[TransitRoute] = []
        states = 0

        def finish(
            stop_id: str,
            arrival: datetime,
            transfers: int,
            legs: tuple[dict[str, object], ...],
        ) -> None:
            walk = destination_stops.get(stop_id)
            if walk is None:
                return
            final_arrival = arrival + timedelta(minutes=walk)
            if final_arrival > deadline:
                return
            candidates.append(
                TransitRoute(
                    departure=home_departure,
                    first_bus_departure=first_bus,
                    arrival=final_arrival,
                    transfers=transfers,
                    legs=legs
                    + ((
                        {
                            "type": "walk",
                            "from": "final stop",
                            "to": DESTINATION_ADDRESS,
                            "minutes": walk,
                        },
                    ) if walk else ()),
                )
            )

        def ride(
            trip: TransitTrip,
            position: int,
            arrival: datetime,
            transfers: int,
            legs: tuple[dict[str, object], ...],
            used_routes: frozenset[str],
        ) -> None:
            nonlocal states
            states += 1
            if states > 2_000:
                return
            board = trip.stop_times[position]
            for end_position in range(position + 1, len(trip.stop_times)):
                end_stop_time = trip.stop_times[end_position]
                end_arrival = _gtfs_datetime(target_date, end_stop_time.arrival)
                if end_arrival < arrival:
                    continue
                transit_leg = {
                    "type": "transit",
                    "route": trip.route_name,
                    "route_id": trip.route_id,
                    "trip_id": trip.trip_id,
                    "from_stop": schedule.stops.get(board.stop_id, TransitStop(board.stop_id, board.stop_id, 0, 0)).name,
                    "to_stop": schedule.stops.get(end_stop_time.stop_id, TransitStop(end_stop_time.stop_id, end_stop_time.stop_id, 0, 0)).name,
                    "departure": _gtfs_datetime(target_date, board.departure).strftime("%H:%M"),
                    "arrival": end_arrival.strftime("%H:%M"),
                }
                next_legs = legs + (transit_leg,)
                finish(end_stop_time.stop_id, end_arrival, transfers, next_legs)
                if transfers >= max_transfers or end_arrival >= deadline:
                    continue
                transfer_ready = end_arrival + timedelta(minutes=2)
                for next_trip, next_position in departures.get(end_stop_time.stop_id, ()):
                    if next_trip.route_id in used_routes:
                        continue
                    next_departure = _gtfs_datetime(target_date, next_trip.stop_times[next_position].departure)
                    if next_departure < transfer_ready:
                        continue
                    if next_departure > deadline:
                        break
                    ride(
                        next_trip,
                        next_position,
                        next_departure,
                        transfers + 1,
                        next_legs,
                        used_routes | {next_trip.route_id},
                    )

        start_leg: tuple[dict[str, object], ...] = (
            {
                "type": "walk",
                "from": ORIGIN_ADDRESS,
                "to": schedule.stops[origin_stop_id].name,
                "minutes": walk_to_origin,
            },
        ) if walk_to_origin else ()
        ride(initial_trip, position, first_bus, 0, start_leg, frozenset({initial_trip.route_id}))
        if candidates:
            return max(
                candidates,
                key=lambda item: (-item.transfers, -int((item.arrival - item.departure).total_seconds())),
            )
    return None


def google_maps_url(origin_address: str = ORIGIN_ADDRESS, destination_address: str = DESTINATION_ADDRESS) -> str:
    query = urlencode(
        {
            "api": "1",
            "origin": origin_address,
            "destination": destination_address,
            "travelmode": "transit",
        }
    )
    return f"https://www.google.com/maps/dir/?{query}"


def build_ya1_transit_wake(
    schedule: TransitSchedule | Mapping[date, TransitSchedule] | Callable[[date], TransitSchedule | None] | None,
    lessons: list[dict[str, object]],
    *,
    now: datetime,
    origin: tuple[float, float],
    destination: tuple[float, float],
    stale: bool = False,
    max_walk_m: int = 1800,
    source_timestamp: str = "",
    origin_address: str = ORIGIN_ADDRESS,
    destination_address: str = DESTINATION_ADDRESS,
    arrival_margin_minutes: int = 5,
    wake_buffer_minutes: int = 75,
    walk_buffer_minutes: int = 0,
    route_preference: Mapping[str, object] | None = None,
    round_to_minutes: int = 1,
    min_wake_time: str | None = None,
    max_wake_time: str | None = None,
    managed_controls: bool = False,
) -> dict[str, object]:
    base: dict[str, object] = {
        "profile": "ya1",
        "alarm_label": YA1_ALARM_LABEL,
        "next_school_day": None,
        "first_lesson_start": None,
        "arrival_deadline": None,
        "route_departure": None,
        "first_bus_departure": None,
        "route_arrival": None,
        "route": [],
        "google_maps_url": google_maps_url(origin_address, destination_address),
        "wake_time": None,
        "wake_at": None,
        "subject": None,
        "enabled": False,
        "stale": stale,
        "fallback_status": "stale" if stale else "none",
        "shortcut_action": "leave" if stale else "clear",
        "source_timestamp": source_timestamp or (schedule.source_timestamp if isinstance(schedule, TransitSchedule) else ""),
        "timezone": "Asia/Jerusalem",
        "error": "",
    }
    if managed_controls:
        base.update(
            {
                "route_alternatives": [],
                "arrival_margin_minutes": arrival_margin_minutes,
                "wake_buffer_minutes": wake_buffer_minutes,
                "round_to_minutes": round_to_minutes,
                "route_preference_used": False,
                "route_preference_fallback": False,
            }
        )
    if stale or schedule is None:
        return base

    current = _aware(now)
    by_date: dict[date, list[dict[str, object]]] = {}
    for lesson in lessons:
        try:
            lesson_date = date.fromisoformat(str(lesson["date"]))
            time.fromisoformat(str(lesson["start"]))
        except (KeyError, TypeError, ValueError):
            continue
        if lesson_date.weekday() in ISRAEL_WEEKEND_WEEKDAYS:
            continue
        if lesson_date >= current.date():
            by_date.setdefault(lesson_date, []).append(lesson)

    for school_day in sorted(by_date):
        first = min(by_date[school_day], key=lambda item: (str(item["start"]), int(item.get("period", 0))))
        first_start = time.fromisoformat(str(first["start"]))
        if school_day == current.date() and datetime.combine(school_day, first_start).replace(tzinfo=ZONE) <= current:
            continue
        deadline = (datetime.combine(school_day, first_start) - timedelta(minutes=arrival_margin_minutes)).time()
        not_before = current if school_day == current.date() else _gtfs_datetime(school_day, time(0, 0))
        if isinstance(schedule, TransitSchedule):
            day_schedule = schedule
        elif isinstance(schedule, Mapping):
            day_schedule = schedule.get(school_day)
        else:
            day_schedule = schedule(school_day) if schedule else None
        if day_schedule is None:
            base.update(
                {
                    "next_school_day": school_day.isoformat(),
                    "first_lesson_start": first_start.strftime("%H:%M"),
                    "arrival_deadline": deadline.strftime("%H:%M"),
                    "subject": str(first.get("subject", "")),
                    "fallback_status": "no-safe-route",
                    "shortcut_action": "leave",
                }
            )
            return base
        preferred_route_ids = None
        if route_preference and isinstance(route_preference.get("route_ids"), list):
            preferred_route_ids = {str(value) for value in route_preference["route_ids"] if str(value)}
        route = plan_route(
            day_schedule,
            school_day,
            deadline,
            origin,
            destination,
            not_before=not_before,
            max_walk_m=max_walk_m,
            preferred_route_ids=preferred_route_ids,
        )
        if route is None and preferred_route_ids:
            # A pinned route is only a preference. If GTFS changed, safely
            # return to the latest automatic route instead of leaving a stale
            # route in the public endpoint.
            route = plan_route(
                day_schedule,
                school_day,
                deadline,
                origin,
                destination,
                not_before=not_before,
                max_walk_m=max_walk_m,
            )
        if route is None:
            base.update(
                {
                    "next_school_day": school_day.isoformat(),
                    "first_lesson_start": first_start.strftime("%H:%M"),
                    "arrival_deadline": deadline.strftime("%H:%M"),
                    "subject": str(first.get("subject", "")),
                    "fallback_status": "no-safe-route",
                    "shortcut_action": "leave",
                }
            )
            return base
        alternatives: list[dict[str, object]] = []
        if managed_controls:
            alternative_cutoff = route.departure - timedelta(minutes=1)
            for _ in range(3):
                alternative = plan_route(
                    day_schedule,
                    school_day,
                    deadline,
                    origin,
                    destination,
                    not_before=not_before,
                    max_walk_m=max_walk_m,
                    latest_home_departure=alternative_cutoff,
                )
                if alternative is None:
                    break
                alternatives.append(
                    {
                        "route_departure": alternative.departure.strftime("%H:%M"),
                        "first_bus_departure": alternative.first_bus_departure.strftime("%H:%M"),
                        "route_arrival": alternative.arrival.strftime("%H:%M"),
                        "transfers": alternative.transfers,
                        "route": list(alternative.legs),
                    }
                )
                alternative_cutoff = alternative.departure - timedelta(minutes=1)
        selected_route_ids = {
            str(leg.get("route_id"))
            for leg in route.legs
            if isinstance(leg, dict) and leg.get("type") == "transit" and leg.get("route_id")
        }
        # iPhone Clock alarms have minute precision. Round down before
        # subtracting the 75-minute buffer so the alarm is never later than
        # the calculated safe wake time.
        wake_at = route.departure.replace(second=0, microsecond=0) - timedelta(minutes=wake_buffer_minutes + walk_buffer_minutes)
        if round_to_minutes > 1:
            rounded_minutes = (wake_at.hour * 60 + wake_at.minute) // round_to_minutes * round_to_minutes
            wake_at = wake_at.replace(hour=rounded_minutes // 60, minute=rounded_minutes % 60)
        if min_wake_time and wake_at.time() < time.fromisoformat(min_wake_time):
            base.update({"next_school_day": school_day.isoformat(), "fallback_status": "wake-time-bound", "shortcut_action": "leave"})
            return base
        if max_wake_time and wake_at.time() > time.fromisoformat(max_wake_time):
            base.update({"next_school_day": school_day.isoformat(), "fallback_status": "wake-time-bound", "shortcut_action": "leave"})
            return base
        if school_day == current.date() and wake_at <= current:
            continue
        payload = {
            "next_school_day": school_day.isoformat(),
            "first_lesson_start": first_start.strftime("%H:%M"),
            "arrival_deadline": deadline.strftime("%H:%M"),
            "route_departure": route.departure.strftime("%H:%M"),
            "first_bus_departure": route.first_bus_departure.strftime("%H:%M"),
            "route_arrival": route.arrival.strftime("%H:%M"),
            "route": list(route.legs),
            "wake_time": wake_at.strftime("%H:%M"),
            "wake_at": wake_at.isoformat(),
            "subject": str(first.get("subject", "")),
            "enabled": True,
            "shortcut_action": "set",
            "fallback_status": "none",
        }
        if managed_controls:
            payload.update(
                {
                    "route_alternatives": alternatives,
                    "route_preference_used": bool(preferred_route_ids and selected_route_ids.intersection(preferred_route_ids)),
                    "route_preference_fallback": bool(preferred_route_ids and not selected_route_ids.intersection(preferred_route_ids)),
                }
            )
        base.update(payload)
        return base

    base["fallback_status"] = "no-lessons"
    base["shortcut_action"] = "clear"
    return base


def _read_csv(zf: ZipFile, name: str) -> list[dict[str, str]]:
    try:
        raw = zf.read(name)
    except KeyError as exc:
        raise TransitSourceError(f"GTFS is missing {name}") from exc
    try:
        return list(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise TransitSourceError(f"GTFS file {name} is malformed") from exc


def _iter_csv(zf: ZipFile, name: str):
    try:
        raw = zf.open(name, "r")
    except KeyError as exc:
        raise TransitSourceError(f"GTFS is missing {name}") from exc
    try:
        with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from csv.DictReader(text)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise TransitSourceError(f"GTFS file {name} is malformed") from exc


def _active_services(zf: ZipFile, target_date: date) -> set[str]:
    stamp = target_date.strftime("%Y%m%d")
    services = {
        row["service_id"]
        for row in _read_csv(zf, "calendar.txt")
        if row.get("start_date", "") <= stamp <= row.get("end_date", "") and row.get(target_date.strftime("%A").lower(), "0") == "1"
    }
    try:
        exceptions = _read_csv(zf, "calendar_dates.txt")
    except TransitSourceError:
        exceptions = []
    for row in exceptions:
        if row.get("date") != stamp:
            continue
        if row.get("exception_type") == "1":
            services.add(row.get("service_id", ""))
        elif row.get("exception_type") == "2":
            services.discard(row.get("service_id", ""))
    return {service for service in services if service}


def load_gtfs(path: Path, target_date: date, *, source_timestamp: str = "") -> TransitSchedule:
    """Load only active trips and their stops from a Ministry GTFS zip."""

    try:
        zf = ZipFile(path)
    except (OSError, BadZipFile) as exc:
        raise TransitSourceError(f"GTFS archive cannot be opened: {exc}") from exc
    with zf:
        active = _active_services(zf, target_date)
        if not active:
            raise TransitSourceError(f"GTFS has no active service for {target_date.isoformat()}")
        route_names = {
            row.get("route_id", ""): row.get("route_short_name") or row.get("route_long_name") or row.get("route_id", "")
            for row in _read_csv(zf, "routes.txt")
        }
        active_trips = {
            row.get("trip_id", ""): (row.get("route_id", ""), row.get("service_id", ""))
            for row in _read_csv(zf, "trips.txt")
            if row.get("service_id") in active and row.get("trip_id") and row.get("route_id")
        }
        stops = {
            row.get("stop_id", ""): TransitStop(
                row.get("stop_id", ""),
                row.get("stop_name", "") or row.get("stop_id", ""),
                float(row["stop_lat"]),
                float(row["stop_lon"]),
            )
            for row in _read_csv(zf, "stops.txt")
            if row.get("stop_id") and row.get("stop_lat") and row.get("stop_lon")
        }
        grouped: dict[str, list[StopTime]] = {}
        # stop_times.txt is hundreds of megabytes uncompressed in the
        # Ministry archive. Stream it instead of materializing the entire
        # table, while still filtering to the active service trips.
        for row in _iter_csv(zf, "stop_times.txt"):
            trip_id = row.get("trip_id", "")
            if trip_id not in active_trips:
                continue
            try:
                grouped.setdefault(trip_id, []).append(
                    StopTime(
                        row["stop_id"],
                        _parse_time(row["arrival_time"]),
                        _parse_time(row["departure_time"]),
                        int(row["stop_sequence"]),
                    )
                )
            except (KeyError, TypeError, ValueError, TransitSourceError) as exc:
                raise TransitSourceError(f"GTFS stop_times row is malformed: {exc}") from exc
        trips: list[TransitTrip] = []
        referenced: set[str] = set()
        for trip_id, stop_times in grouped.items():
            ordered = tuple(sorted(stop_times, key=lambda item: item.sequence))
            if len(ordered) < 2 or any(item.stop_id not in stops for item in ordered):
                continue
            route_id, _ = active_trips[trip_id]
            trips.append(TransitTrip(trip_id, route_id, route_names.get(route_id, route_id), ordered))
            referenced.update(item.stop_id for item in ordered)
        if not trips:
            raise TransitSourceError(f"GTFS has no usable trips for {target_date.isoformat()}")
        return TransitSchedule(
            stops={stop_id: stops[stop_id] for stop_id in referenced},
            trips=tuple(trips),
            source_timestamp=source_timestamp,
        )


def download_gtfs(url: str = DEFAULT_GTFS_URL, *, directory: Path | None = None) -> tuple[Path, str]:
    """Download GTFS into a temporary/cache directory and return its timestamp."""

    target_dir = directory or Path(tempfile.gettempdir()) / "shahaf-schedule-sync"
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / "israel-public-transportation.zip"
    partial = archive.with_suffix(".zip.part")
    request = Request(url, headers={"User-Agent": "shahaf-schedule-sync/1.0"})
    try:
        with urlopen(request, timeout=180) as response, partial.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                output.write(chunk)
            if total < 1_000_000:
                raise TransitSourceError("GTFS download is unexpectedly small")
            timestamp = response.headers.get("Last-Modified") or datetime.now(ZONE).isoformat()
        partial.replace(archive)
    except TransitSourceError:
        raise
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise TransitSourceError(f"Could not download GTFS: {exc}") from exc
    return archive, timestamp
