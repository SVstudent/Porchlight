"""Road routes between two points, for showing a responder's path on the map.

One call to a public routing service returns the road geometry and a travel time that already accounts
for road types, turns, stop signs and traffic lights. No API key, no account.

Valhalla is tried first because its car costing model includes stop and turn penalties, which matters
over the short distances a neighbourhood responder actually travels: for a 1.6 km hop it says four
minutes where a straight-line estimate says one. OSRM is the fallback. If both are unreachable the
caller still gets a usable straight line, flagged as such, because a missing route should degrade the
map rather than block a dispatch.

What this is not: live traffic, and not a GPS position. The progress shown on the map is computed from
the route's own estimate, and the UI says so.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

log = logging.getLogger("porchlight.routing")

VALHALLA = "https://valhalla1.openstreetmap.de/route"
OSRM = "https://router.project-osrm.org/route/v1/driving"
UA = {"User-Agent": "Porchlight/1.0 (neighbourhood check-in agent)"}

_cache: dict[tuple, dict[str, Any]] = {}
_CACHE_TTL_S = 3600


def _decode(shape: str, precision: int = 6) -> list[list[float]]:
    """Valhalla's polyline, which uses six decimal places where most encoders use five."""
    points: list[list[float]] = []
    index = lat = lng = 0
    factor = 10 ** precision
    while index < len(shape):
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(shape[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append([lat / factor, lng / factor])
    return points


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _valhalla(a_lat, a_lon, b_lat, b_lon) -> dict[str, Any] | None:
    body = {
        "locations": [{"lat": a_lat, "lon": a_lon}, {"lat": b_lat, "lon": b_lon}],
        "costing": "auto",
        "directions_options": {"units": "kilometers"},
    }
    with httpx.Client(timeout=20.0, headers=UA) as c:
        j = c.post(VALHALLA, json=body).json()
    leg = (j.get("trip") or {}).get("legs", [{}])[0]
    if not leg.get("shape"):
        return None
    summary = (j["trip"].get("summary") or {})
    steps = [m.get("instruction", "") for m in leg.get("maneuvers", []) if m.get("instruction")]
    return {
        "points": _decode(leg["shape"]),
        "seconds": float(summary.get("time") or 0),
        "metres": float(summary.get("length") or 0) * 1000.0,
        "steps": steps[:8],
        "source": "valhalla",
    }


def _osrm(a_lat, a_lon, b_lat, b_lon) -> dict[str, Any] | None:
    url = f"{OSRM}/{a_lon},{a_lat};{b_lon},{b_lat}?overview=full&geometries=geojson&steps=true"
    with httpx.Client(timeout=20.0, headers=UA) as c:
        j = c.get(url).json()
    if j.get("code") != "Ok" or not j.get("routes"):
        return None
    route = j["routes"][0]
    steps = [s.get("name", "") for s in route["legs"][0].get("steps", []) if s.get("name")]
    return {
        "points": [[lat, lon] for lon, lat in route["geometry"]["coordinates"]],
        "seconds": float(route.get("duration") or 0),
        "metres": float(route.get("distance") or 0),
        "steps": steps[:8],
        "source": "osrm",
    }


def _straight(a_lat, a_lon, b_lat, b_lon) -> dict[str, Any]:
    """Last resort: the line a bird would take, at a walking-ish pace, clearly labelled."""
    metres = haversine_m(a_lat, a_lon, b_lat, b_lon)
    return {
        "points": [[a_lat, a_lon], [b_lat, b_lon]],
        "seconds": metres / 6.0,  # ~21 km/h, deliberately pessimistic for a short urban hop
        "metres": metres,
        "steps": [],
        "source": "straight_line",
    }


def route(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> dict[str, Any]:
    """The road route from A to B: a list of [lat, lon] points, a distance and a travel time.

    `source` says which service answered, or "straight_line" when neither could be reached. A caller
    that shows this on a map should show that too, rather than presenting a guess as a route.
    """
    key = (round(a_lat, 5), round(a_lon, 5), round(b_lat, 5), round(b_lon, 5))
    hit = _cache.get(key)
    if hit and time.time() - hit["_at"] < _CACHE_TTL_S:
        return {k: v for k, v in hit.items() if k != "_at"}

    for name, fn in (("valhalla", _valhalla), ("osrm", _osrm)):
        try:
            got = fn(a_lat, a_lon, b_lat, b_lon)
            if got and len(got["points"]) >= 2:
                _cache[key] = {**got, "_at": time.time()}
                return got
        except Exception as e:  # noqa: BLE001 — a routing outage must not stop a dispatch
            log.warning("%s routing failed: %s", name, e)

    log.warning("no routing service answered; falling back to a straight line")
    got = _straight(a_lat, a_lon, b_lat, b_lon)
    _cache[key] = {**got, "_at": time.time()}
    return got
