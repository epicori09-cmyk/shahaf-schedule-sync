from __future__ import annotations

"""Settings and safety policy for Worker-managed wake alarms.

The legacy root and ``ya1`` profiles intentionally do not use this module.
Managed profiles receive an effective, already-resolved policy from the
private Worker and publish only the small, safe subset needed by Shortcuts.
"""

from datetime import datetime, time, timezone
import json
import math
from typing import Any, Mapping


DEFAULT_ALARM_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "wake_buffer_minutes": 75,
    "min_wake_time": None,
    "max_wake_time": None,
    "round_to_minutes": 1,
    "stale_policy": "leave",
    "no_lessons_policy": "clear",
    "fallback_wake_time": "07:15",
    "label_template": "Shahaf",
    "alarm_label": "Shahaf",
    "transit_min_arrival_margin": 5,
    "transit_walk_buffer_minutes": 0,
    "transit_route_preference": None,
}

ROUND_OPTIONS = {1, 5, 10, 15}
STALE_POLICIES = {"leave", "set_fixed"}
NO_LESSONS_POLICIES = {"clear", "leave"}


def _clock(value: Any, field: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be HH:MM or null")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be HH:MM or null") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field} must be HH:MM or null")
    return parsed.strftime("%H:%M")


def _integer(value: Any, field: str, low: int, high: int, *, allow_none: bool = True) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be an integer")
    try:
        number = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not math.isfinite(numeric) or number != numeric or not low <= number <= high:
        raise ValueError(f"{field} must be between {low} and {high}")
    return number


def _label(value: Any, field: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if not value or len(value) > 80 or any(char in value for char in "\r\n"):
        raise ValueError(f"{field} must be 1–80 characters without line breaks")
    return value


def normalize_alarm_settings(raw: Mapping[str, Any] | None, *, partial: bool = False) -> dict[str, Any]:
    """Validate settings from the Worker or an API request.

    ``partial=True`` preserves nulls as inheritance markers for per-profile
    overrides.  A full settings object receives all safe defaults.
    """

    raw = dict(raw or {})
    result: dict[str, Any] = {}
    fields = {
        "enabled": raw.get("enabled"),
        "wake_buffer_minutes": raw.get("wake_buffer_minutes"),
        "min_wake_time": raw.get("min_wake_time"),
        "max_wake_time": raw.get("max_wake_time"),
        "round_to_minutes": raw.get("round_to_minutes"),
        "stale_policy": raw.get("stale_policy"),
        "no_lessons_policy": raw.get("no_lessons_policy"),
        "fallback_wake_time": raw.get("fallback_wake_time"),
        "label_template": raw.get("label_template"),
        "alarm_label": raw.get("alarm_label"),
        "transit_min_arrival_margin": raw.get("transit_min_arrival_margin"),
        "transit_walk_buffer_minutes": raw.get("transit_walk_buffer_minutes"),
        "transit_route_preference": raw.get("transit_route_preference"),
    }
    for field, value in fields.items():
        if not partial and field not in raw:
            value = DEFAULT_ALARM_SETTINGS[field]
        if partial and field not in raw:
            result[field] = None
            continue
        if partial and value is None:
            result[field] = None
            continue
        if field == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled must be true or false")
            result[field] = value
        elif field == "wake_buffer_minutes":
            result[field] = _integer(value, field, 0, 240, allow_none=False)
        elif field in {"min_wake_time", "max_wake_time", "fallback_wake_time"}:
            result[field] = _clock(value, field, allow_none=field != "fallback_wake_time")
        elif field == "round_to_minutes":
            number = _integer(value, field, 1, 15, allow_none=False)
            if number not in ROUND_OPTIONS:
                raise ValueError("round_to_minutes must be 1, 5, 10, or 15")
            result[field] = number
        elif field == "stale_policy":
            if value not in STALE_POLICIES:
                raise ValueError("stale_policy must be leave or set_fixed")
            result[field] = value
        elif field == "no_lessons_policy":
            if value not in NO_LESSONS_POLICIES:
                raise ValueError("no_lessons_policy must be clear or leave")
            result[field] = value
        elif field == "label_template":
            result[field] = _label(value, field, allow_none=partial)
        elif field == "alarm_label":
            result[field] = _label(value, field, allow_none=partial)
        elif field == "transit_min_arrival_margin":
            number = _integer(value, field, 5, 120, allow_none=False)
            result[field] = number
        elif field == "transit_walk_buffer_minutes":
            result[field] = _integer(value, field, 0, 60, allow_none=False)
        elif field == "transit_route_preference":
            if value is not None and not isinstance(value, dict):
                raise ValueError("transit_route_preference must be an object or null")
            result[field] = value
    if not partial:
        merged = dict(DEFAULT_ALARM_SETTINGS)
        merged.update(result)
        if merged.get("min_wake_time") and merged.get("max_wake_time") and merged["min_wake_time"] > merged["max_wake_time"]:
            raise ValueError("min_wake_time cannot be later than max_wake_time")
        return merged
    return result


def resolve_alarm_settings(
    global_settings: Mapping[str, Any] | None,
    profile_settings: Mapping[str, Any] | None,
    public_id: str,
) -> dict[str, Any]:
    """Resolve profile overrides over managed-profile global defaults."""

    merged = dict(DEFAULT_ALARM_SETTINGS)
    merged.update(normalize_alarm_settings(global_settings, partial=False))
    overrides = normalize_alarm_settings(profile_settings, partial=True)
    for key, value in overrides.items():
        if value is not None:
            merged[key] = value
    template = str(merged.get("label_template") or "Shahaf")
    label = merged.get("alarm_label") or template
    label = str(label).replace("{public_id}", public_id).replace("{profile_id}", public_id)
    merged["alarm_label"] = label[:80]
    merged["public_id"] = public_id
    return merged


def _override_is_active(override: Mapping[str, Any] | None, now: datetime) -> bool:
    if not override:
        return False
    expires = str(override.get("expires_at") or "")
    if not expires:
        return False
    try:
        expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return expiry >= current.astimezone(expiry.tzinfo or timezone.utc)


def apply_alarm_controls(
    wake: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    override: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply managed-profile action policy without exposing admin metadata."""

    result = dict(wake)
    current = now or datetime.now(timezone.utc)
    active_override = _override_is_active(override, current)
    override_matches_day = active_override and (
        not override.get("target_date")
        or override.get("target_date") == result.get("next_school_day")
    )
    result["alarm_label"] = str(settings.get("alarm_label") or "Shahaf")
    result["alarm_control"] = {
        "enabled": bool(settings.get("enabled", True)),
        "wake_buffer_minutes": int(settings.get("wake_buffer_minutes", 75)),
        "round_to_minutes": int(settings.get("round_to_minutes", 1)),
        "override_active": override_matches_day,
        "override_pending": bool(active_override and not override_matches_day),
        "transit_min_arrival_margin": int(settings.get("transit_min_arrival_margin", 5)),
    }

    if override_matches_day:
        restore_snapshot = override.get("restore_json")
        if isinstance(restore_snapshot, str):
            try:
                restore_snapshot = json.loads(restore_snapshot)
            except json.JSONDecodeError:
                restore_snapshot = None
        if isinstance(restore_snapshot, Mapping) and restore_snapshot.get("next_school_day") == result.get("next_school_day"):
            restore_action = str(restore_snapshot.get("shortcut_action") or "leave")
            unsafe_statuses = {"stale", "unavailable", "no-safe-route", "wake-time-bound"}
            restore_unsafe = bool(restore_snapshot.get("stale")) or str(restore_snapshot.get("fallback_status") or "") in unsafe_statuses
            restore_valid = restore_action in {"set", "clear", "leave"}
            if restore_action == "set":
                try:
                    restore_valid = restore_valid and datetime.fromisoformat(str(restore_snapshot.get("wake_at", "")).replace("Z", "+00:00")) is not None
                except ValueError:
                    restore_valid = False
            if restore_valid and not restore_unsafe:
                for key in ("next_school_day", "wake_time", "wake_at", "subject", "enabled", "shortcut_action", "fallback_status", "alarm_for_today"):
                    if key in restore_snapshot:
                        result[key] = restore_snapshot[key]
                result["alarm_control"]["override_active"] = True
                result["alarm_control"]["override_pending"] = False
                return result
        action = str(override.get("action") or "leave")
        target_date = override.get("target_date")
        unsafe_statuses = {"stale", "unavailable", "no-safe-route", "wake-time-bound"}
        unsafe = bool(result.get("stale")) or str(result.get("fallback_status") or "") in unsafe_statuses
        force = bool(override.get("force"))
        if unsafe and action in {"set", "clear"} and not force:
            result["shortcut_action"] = "leave"
            result["fallback_status"] = "unsafe-override-blocked"
        elif action == "clear":
            result.update(
                {
                    "next_school_day": target_date,
                    "wake_time": None,
                    "wake_at": None,
                    "subject": None,
                    "enabled": False,
                    "shortcut_action": "clear",
                    "fallback_status": "manual-clear",
                }
            )
        elif action == "set" and override.get("wake_at"):
            wake_at = str(override["wake_at"])
            try:
                parsed = datetime.fromisoformat(wake_at.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None:
                result.update(
                    {
                        "next_school_day": target_date or parsed.date().isoformat(),
                        "wake_time": parsed.strftime("%H:%M"),
                        "wake_at": parsed.isoformat(),
                        "subject": override.get("subject") or result.get("subject"),
                        "enabled": True,
                        "shortcut_action": "set",
                        "fallback_status": "manual-set",
                    }
                )
        else:
            result["shortcut_action"] = "leave"
            result["fallback_status"] = "manual-leave"
    elif not bool(settings.get("enabled", True)):
        result["enabled"] = False
        result["shortcut_action"] = "leave"
        result["fallback_status"] = "paused"
    elif bool(result.get("stale")) and settings.get("stale_policy", "leave") == "leave":
        result["shortcut_action"] = "leave"
    elif bool(result.get("stale")) and settings.get("stale_policy") == "set_fixed":
        target_date = result.get("next_school_day")
        fallback_time = settings.get("fallback_wake_time")
        if target_date and fallback_time:
            try:
                fallback_at = datetime.fromisoformat(f"{target_date}T{fallback_time}:00+03:00")
            except ValueError:
                result["shortcut_action"] = "leave"
            else:
                result.update(
                    {
                        "wake_time": fallback_at.strftime("%H:%M"),
                        "wake_at": fallback_at.isoformat(),
                        "enabled": True,
                        "shortcut_action": "set",
                        "fallback_status": "stale-fixed",
                    }
                )
        else:
            result["shortcut_action"] = "leave"
    elif result.get("fallback_status") == "no-lessons" and settings.get("no_lessons_policy", "clear") == "leave":
        result["shortcut_action"] = "leave"

    return result


def public_alarm_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields safe to publish beside a managed wake payload."""

    return {
        "enabled": bool(settings.get("enabled", True)),
        "wake_buffer_minutes": int(settings.get("wake_buffer_minutes", 75)),
        "min_wake_time": settings.get("min_wake_time"),
        "max_wake_time": settings.get("max_wake_time"),
        "round_to_minutes": int(settings.get("round_to_minutes", 1)),
        "stale_policy": str(settings.get("stale_policy", "leave")),
        "no_lessons_policy": str(settings.get("no_lessons_policy", "clear")),
        "transit_min_arrival_margin": int(settings.get("transit_min_arrival_margin", 5)),
    }
