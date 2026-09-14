"""Conditions across the neighbourhood, not just at its centre.

A single reading for "Maryvale" hides the thing that matters. Sampling a grid over the roster on one
recent afternoon gave 93.3°F on the east side and 99.7°F on the west, three miles apart: the same
alert, six degrees of difference, and it is the west side where the neighbours with swamp coolers
live. That gradient is why this is drawn on the map rather than printed as a number.

Open-Meteo accepts many coordinates in one request, so a whole grid costs one call. Results are cached
for a few minutes because the underlying model updates hourly and a coordinator refreshing the page
should not re-fetch a field that cannot have changed.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger("porchlight.field")

WEATHER = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"

_cache: dict[str, Any] = {"at": 0.0, "key": None, "value": None}
_TTL_S = 300
_TIMEOUT_S = 25.0


def _grid(points: list[tuple[float, float]], steps: int, pad_deg: float):
    """A regular lattice covering everyone, with a margin so the edges are not cut off."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat0, lat1 = min(lats) - pad_deg, max(lats) + pad_deg
    lon0, lon1 = min(lons) - pad_deg, max(lons) + pad_deg
    dlat = (lat1 - lat0) / max(1, steps - 1)
    dlon = (lon1 - lon0) / max(1, steps - 1)
    cells = [(round(lat0 + r * dlat, 4), round(lon0 + c * dlon, 4))
             for r in range(steps) for c in range(steps)]
    return cells, (dlat, dlon)


def _batch(url: str, cells, params: str) -> list[dict[str, Any]]:
    lat = ",".join(str(c[0]) for c in cells)
    lon = ",".join(str(c[1]) for c in cells)
    with httpx.Client(timeout=_TIMEOUT_S) as c:
        j = c.get(f"{url}?latitude={lat}&longitude={lon}&{params}").json()
    return j if isinstance(j, list) else [j]


def sample(points: list[tuple[float, float]], hazard_type: str = "heat",
           steps: int = 5, pad_deg: float = 0.012) -> dict[str, Any]:
    """The conditions field over a roster: one cell per grid point, with the value that matters.

    For heat and outage that is the apparent temperature — what it feels like, which is what hurts
    people. For air quality it is the US AQI. Returns cells with a value and the size of each cell so
    the map can draw them as rectangles.
    """
    if not points:
        return {"cells": [], "metric": "", "unit": "", "min": None, "max": None}

    key = f"{hazard_type}|{steps}|{round(min(p[0] for p in points), 3)}|{round(min(p[1] for p in points), 3)}|{len(points)}"
    if _cache["key"] == key and time.time() - _cache["at"] < _TTL_S:
        return _cache["value"]

    cells, (dlat, dlon) = _grid(points, steps, pad_deg)
    air = hazard_type == "air_quality"
    try:
        if air:
            rows = _batch(AIR, cells, "current=us_aqi")
            values = [(r.get("current") or {}).get("us_aqi") for r in rows]
            metric, unit = "US air quality index", ""
        else:
            rows = _batch(WEATHER, cells,
                          "current=apparent_temperature&temperature_unit=fahrenheit")
            values = [(r.get("current") or {}).get("apparent_temperature") for r in rows]
            metric, unit = "Feels like", "°F"
    except Exception as e:  # noqa: BLE001 — the map is still useful without the field
        log.warning("conditions field unavailable: %s", e)
        return {"cells": [], "metric": "", "unit": "", "min": None, "max": None, "error": str(e)[:120]}

    out = []
    for (lat, lon), _row, value in zip(cells, rows, values, strict=False):
        if value is None:
            continue
        out.append({
            # Open-Meteo answers at its own grid point, which is close to but not exactly what we asked
            # for. Use the cell we asked for so the rectangles tile evenly.
            "lat": lat, "lon": lon, "value": value,
            "bounds": [[lat - dlat / 2, lon - dlon / 2], [lat + dlat / 2, lon + dlon / 2]],
        })
    got = [c["value"] for c in out]
    value = {"cells": out, "metric": metric, "unit": unit,
             "min": min(got) if got else None, "max": max(got) if got else None,
             "source": "Open-Meteo"}
    _cache.update({"at": time.time(), "key": key, "value": value})
    return value
