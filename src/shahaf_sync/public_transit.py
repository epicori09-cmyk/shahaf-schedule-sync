"""Remove private origin details from managed students' public route payloads."""

from typing import Any


def public_transit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    private_keys = {"origin_address", "origin", "origin_coordinates", "google_maps_url"}

    def sanitize(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {key: sanitize(item) for key, item in value.items() if key not in private_keys}
            route = cleaned.get("route")
            if isinstance(route, list) and route and isinstance(route[0], dict) and route[0].get("type") == "walk":
                # The first walking leg starts at home, unlike transfer legs.
                route[0]["from"] = "Home"
            return cleaned
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return sanitize(payload)
