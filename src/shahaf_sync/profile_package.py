from __future__ import annotations

"""Validation and expansion for screenshot-derived student profiles.

The package is deliberately strict: an operator can correct a GPT result in
the admin UI, but the publishing pipeline must never turn missing rows into
free periods or silently select a parallel major.
"""

from datetime import date, time, timedelta
from typing import Any

from .model import Lesson


WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday")
WEEKDAY_NUMBER = {name: index for index, name in enumerate(WEEKDAYS)}


class ProfilePackageError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("; ".join(errors))


def _time(value: Any, path: str, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{path} must be HH:MM or null")
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        errors.append(f"{path} must be HH:MM")
        return None
    if parsed.second or parsed.microsecond:
        errors.append(f"{path} must be HH:MM")
        return None
    return parsed.strftime("%H:%M")


def _selector(selector: Any, index: int, errors: list[str]) -> dict[str, Any]:
    if not isinstance(selector, dict):
        errors.append(f"shahaf.selectors[{index}] must be an object")
        return {}
    normalized = {str(key): value for key, value in selector.items()}
    weekdays = normalized.get("weekdays")
    if weekdays is None and normalized.get("weekday") is not None:
        weekdays = [normalized["weekday"]]
    if weekdays is not None:
        if not isinstance(weekdays, list):
            weekdays = [weekdays]
        converted: list[int] = []
        for value in weekdays:
            if isinstance(value, str) and value.casefold() in WEEKDAY_NUMBER:
                converted.append(WEEKDAY_NUMBER[value.casefold()])
            else:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    errors.append(f"shahaf.selectors[{index}].weekdays contains an invalid weekday")
                    continue
                if number not in range(5):
                    errors.append(f"shahaf.selectors[{index}].weekdays contains an invalid weekday")
                    continue
                converted.append(number)
        normalized["weekdays"] = sorted(set(converted))
    periods = normalized.get("periods")
    if periods is not None:
        if not isinstance(periods, list):
            periods = [periods]
        converted_periods: list[int] = []
        for value in periods:
            try:
                period = int(value)
            except (TypeError, ValueError):
                errors.append(f"shahaf.selectors[{index}].periods contains an invalid period")
                continue
            if period not in range(14):
                errors.append(f"shahaf.selectors[{index}].periods contains an invalid period")
                continue
            converted_periods.append(period)
        normalized["periods"] = sorted(set(converted_periods))
    return normalized


def validate_package(raw: Any) -> dict[str, Any]:
    """Validate and normalize an imported GPT package.

    Unknown rows are hard errors. Warnings are retained for operator review,
    but an otherwise complete package can publish automatically.
    """
    if not isinstance(raw, dict):
        raise ProfilePackageError(["The import must be a JSON object"])
    errors: list[str] = []
    warnings: list[str] = []
    if raw.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    student = raw.get("student")
    if not isinstance(student, dict):
        errors.append("student must be an object")
        student = {}
    name = student.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        errors.append("student.name must be a non-empty string or null")

    shahaf = raw.get("shahaf")
    if not isinstance(shahaf, dict):
        errors.append("shahaf must be an object")
        shahaf = {}
    class_id = shahaf.get("class_id")
    class_number = shahaf.get("class_number")
    if class_id is None or str(class_id).strip() == "":
        errors.append("shahaf.class_id is required before publishing")
    if class_number is None:
        errors.append("shahaf.class_number is required before publishing")
    else:
        try:
            class_number = int(class_number)
            if class_number < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("shahaf.class_number must be a positive integer")
            class_number = None

    shared = shahaf.get("shared_subjects", [])
    if not isinstance(shared, list) or not all(isinstance(value, str) and value for value in shared):
        errors.append("shahaf.shared_subjects must be a list of non-empty strings")
        shared = []
    selectors_raw = shahaf.get("selectors", [])
    if not isinstance(selectors_raw, list):
        errors.append("shahaf.selectors must be a list")
        selectors_raw = []
    selectors = [_selector(value, index, errors) for index, value in enumerate(selectors_raw)]
    exam_terms = shahaf.get("exam_terms", [])
    if not isinstance(exam_terms, list) or not all(isinstance(value, str) and value for value in exam_terms):
        errors.append("shahaf.exam_terms must be a list of non-empty strings")
        exam_terms = []

    rows = raw.get("weekly_schedule")
    if not isinstance(rows, list) or not rows:
        errors.append("weekly_schedule must be a non-empty list")
        rows = []
    normalized_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for index, row in enumerate(rows):
        path = f"weekly_schedule[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{path} must be an object")
            continue
        weekday = str(row.get("weekday", "")).casefold()
        if weekday not in WEEKDAY_NUMBER:
            errors.append(f"{path}.weekday is invalid")
            continue
        try:
            period = int(row.get("period"))
        except (TypeError, ValueError):
            errors.append(f"{path}.period must be an integer from 0 to 13")
            continue
        if period not in range(14):
            errors.append(f"{path}.period must be an integer from 0 to 13")
            continue
        key = (weekday, period)
        if key in seen:
            errors.append(f"{path} duplicates {weekday} period {period}")
            continue
        seen.add(key)
        status = row.get("status")
        if status not in {"lesson", "gap", "unknown"}:
            errors.append(f"{path}.status must be lesson, gap, or unknown")
            continue
        start = _time(row.get("start"), f"{path}.start", errors)
        end = _time(row.get("end"), f"{path}.end", errors)
        if start and end and time.fromisoformat(start) >= time.fromisoformat(end):
            errors.append(f"{path} start must be before end")
        values: dict[str, str | None] = {}
        for field in ("subject", "teacher", "room"):
            value = row.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f"{path}.{field} must be a string or null")
                value = None
            values[field] = value
        if status == "unknown":
            errors.append(f"{path} is unknown; fill the row before publishing")
        elif status == "lesson":
            if not start or not end:
                errors.append(f"{path} lesson requires start and end")
            for field in ("subject", "teacher", "room"):
                if not values[field]:
                    errors.append(f"{path} lesson requires {field}; do not guess it")
        else:
            if any(values.values()):
                errors.append(f"{path} gap must have null subject, teacher, and room")
        normalized_rows.append({
            "weekday": weekday,
            "period": period,
            "start": start,
            "end": end,
            **values,
            "status": status,
        })

    extraction = raw.get("extraction")
    if not isinstance(extraction, dict):
        errors.append("extraction must be an object")
        extraction = {}
    visible_weekdays = extraction.get("visible_weekdays", [])
    if not isinstance(visible_weekdays, list):
        errors.append("extraction.visible_weekdays must be a list")
        visible_weekdays = []
    visible_weekdays = [str(value).casefold() for value in visible_weekdays]
    for weekday in visible_weekdays:
        if weekday not in WEEKDAY_NUMBER:
            errors.append(f"extraction.visible_weekdays contains invalid weekday {weekday}")
    for weekday in sorted(set(visible_weekdays)):
        periods = {row["period"] for row in normalized_rows if row["weekday"] == weekday}
        missing = sorted(set(range(14)) - periods)
        if missing:
            errors.append(f"{weekday} is missing periods: {', '.join(map(str, missing))}")
    warnings.extend(str(value) for value in extraction.get("warnings", []) if value)

    transit = raw.get("transit", {})
    if not isinstance(transit, dict):
        errors.append("transit must be an object")
        transit = {}
    enabled = transit.get("enabled", False)
    if not isinstance(enabled, bool):
        errors.append("transit.enabled must be boolean")
        enabled = False
    if enabled:
        if not isinstance(transit.get("origin_address"), str) or not transit.get("origin_address", "").strip():
            errors.append("transit.origin_address is required when transit is enabled")
        for field in ("origin_lat", "origin_lon"):
            try:
                float(transit.get(field))
            except (TypeError, ValueError):
                errors.append(f"transit.{field} is required when transit is enabled")

    if errors:
        raise ProfilePackageError(errors, warnings)
    return {
        "schema_version": 1,
        "student": {"name": name.strip() if isinstance(name, str) else None},
        "shahaf": {
            "class_id": str(class_id),
            "class_number": class_number,
            "shared_subjects": list(shared),
            "selectors": selectors,
            "exam_terms": list(exam_terms),
        },
        "weekly_schedule": normalized_rows,
        "transit": {
            "enabled": enabled,
            "origin_address": transit.get("origin_address"),
            "origin_lat": float(transit["origin_lat"]) if enabled else None,
            "origin_lon": float(transit["origin_lon"]) if enabled else None,
        },
        "extraction": {
            "visible_weekdays": sorted(set(visible_weekdays), key=WEEKDAY_NUMBER.get),
            "visible_periods": extraction.get("visible_periods", {}),
            "warnings": warnings,
        },
    }


def package_to_spec(package: dict[str, Any], public_id: str) -> dict[str, Any]:
    shahaf = package["shahaf"]
    transit = package["transit"]
    return {
        "id": public_id,
        "label": "Student schedule",
        "mark": "STUDENT",
        "class_id": str(shahaf["class_id"]),
        "class_number": int(shahaf["class_number"]),
        "baseline": "package",
        "weekly_schedule": package["weekly_schedule"],
        "shared_subjects": shahaf["shared_subjects"],
        "selectors": shahaf["selectors"],
        "exam_terms": shahaf["exam_terms"],
        "transit": transit,
        "managed_profile": True,
    }


def build_package_schedule(package: dict[str, Any], start_date: date, end_date: date) -> list[Lesson]:
    rows = {
        (row["weekday"], int(row["period"])): row
        for row in package["weekly_schedule"]
        if row["status"] == "lesson"
    }
    result: list[Lesson] = []
    day = start_date
    while day <= end_date:
        weekday_number = (day.weekday() + 1) % 7
        weekday = WEEKDAYS[weekday_number] if weekday_number < len(WEEKDAYS) else None
        if weekday:
            for period in range(14):
                row = rows.get((weekday, period))
                if not row:
                    continue
                result.append(Lesson(
                    day,
                    period,
                    time.fromisoformat(row["start"]),
                    time.fromisoformat(row["end"]),
                    row["subject"],
                    row["teacher"],
                    row["room"],
                ))
        day += timedelta(days=1)
    return result
