"""National Weather Service public API (api.weather.gov). Free, no key; requires a User-Agent."""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..models import HazardEvent, HazardType

BASE = "https://api.weather.gov"
HEADERS = {"User-Agent": settings.NWS_USER_AGENT, "Accept": "application/geo+json"}

# Deterministic mapping from NWS event names to our hazard categories.
_EVENT_MAP: list[tuple[str, HazardType]] = [
    ("heat", "heat"),
    ("air quality", "air_quality"),
    ("smoke", "air_quality"),
    ("dust", "air_quality"),
    ("freeze", "cold"),
    ("wind chill", "cold"),
    ("cold", "cold"),
    ("blizzard", "winter"),
    ("winter", "winter"),
    ("ice", "winter"),
    ("snow", "winter"),
    ("flood", "flood"),  # also matches "flash flood"; order matters, so keep specific terms above general ones
    ("hurricane", "storm"),
    ("tropical", "storm"),
    ("tornado", "storm"),
    ("thunderstorm", "storm"),
    ("wind", "storm"),
    ("fire", "other"),
]

# Alerts that rarely warrant neighbor outreach are filtered before the LLM sees anything.
_IGNORE_EVENTS = {
    "small craft advisory", "gale warning", "marine weather statement", "rip current statement",
    "beach hazards statement", "special marine warning", "hazardous seas warning", "lake wind advisory",
    "test message", "child abduction emergency", "coastal flood statement", "hydrologic outlook",
    "fire weather watch", "red flag warning", "frost advisory", "dense fog advisory",
}


def classify_event(event_name: str) -> HazardType:
    e = event_name.lower()
    for needle, kind in _EVENT_MAP:
        if needle in e:
            return kind
    return "other"


def is_relevant(event_name: str) -> bool:
    return event_name.lower() not in _IGNORE_EVENTS


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, headers=HEADERS, timeout=20.0)


def point_metadata(lat: float, lon: float) -> dict[str, Any]:
    with _client() as c:
        r = c.get(f"/points/{lat:.4f},{lon:.4f}")
        r.raise_for_status()
        p = r.json()["properties"]
    return {
        "forecast_zone": p.get("forecastZone", "").split("/")[-1],
        "county_zone": p.get("county", "").split("/")[-1],
        "grid_id": p.get("gridId"),
        "city": (p.get("relativeLocation") or {}).get("properties", {}).get("city"),
        "state": (p.get("relativeLocation") or {}).get("properties", {}).get("state"),
    }


def active_alerts_for_point(lat: float, lon: float) -> list[dict[str, Any]]:
    with _client() as c:
        r = c.get("/alerts/active", params={"point": f"{lat:.4f},{lon:.4f}", "status": "actual"})
        r.raise_for_status()
        return r.json().get("features", [])


def active_alerts_for_zone(zone_id: str) -> list[dict[str, Any]]:
    with _client() as c:
        r = c.get(f"/alerts/active/zone/{zone_id}")
        r.raise_for_status()
        return r.json().get("features", [])


def feature_to_hazard(feature: dict[str, Any], source: str = "nws") -> HazardEvent:
    p = feature.get("properties", feature)
    event_name = p.get("event", "Weather Alert")
    return HazardEvent(
        source=source,
        external_id=p.get("id", feature.get("id", "")),
        hazard_type=classify_event(event_name),
        event_name=event_name,
        severity=p.get("severity", ""),
        headline=p.get("headline", "") or (p.get("parameters", {}).get("NWSheadline", [""]) or [""])[0],
        description=p.get("description", "") or "",
        instruction=p.get("instruction", "") or "",
        area=p.get("areaDesc", ""),
        onset=p.get("onset", "") or p.get("effective", "") or "",
        expires=p.get("ends", "") or p.get("expires", "") or "",
        metrics={
            "urgency": p.get("urgency"),
            "certainty": p.get("certainty"),
            "sender": p.get("senderName"),
        },
    )
