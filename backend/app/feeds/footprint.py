"""The shape of a hazard on the ground, as the National Weather Service draws it.

Two kinds of alert, and the difference matters for what can be drawn:

* **Storm-based warnings** — tornado, flash flood, severe thunderstorm — carry their own polygon, the
  actual area the forecaster drew around the threat.
* **Area warnings** — heat, winter storm, air quality — carry no polygon at all. They name forecast
  zones instead, and each zone has to be fetched to get its outline. A heat warning for Phoenix is
  eleven zones with names like "Northwest Valley".

So the footprint is the alert's own polygon when it has one, and the union of its zones' outlines when
it does not. Both are the NWS's own geometry; neither is drawn or approximated here.

Zone outlines change rarely and are large, so they are cached for the life of the process.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger("porchlight.footprint")

_zone_cache: dict[str, dict[str, Any]] = {}
_MAX_ZONES = 14          # a statewide alert can name dozens; enough to show the shape, not the whole state
_TIMEOUT_S = 12.0


def _headers() -> dict[str, str]:
    # The NWS asks for a contact address in the User-Agent and rate-limits requests without one.
    return {"User-Agent": settings.NWS_USER_AGENT or "Porchlight/1.0 (neighbourhood check-in agent)",
            "Accept": "application/geo+json"}


def _ring_count(coords: Any) -> int:
    if not coords:
        return 0
    if isinstance(coords[0], (int, float)):
        return 1
    return sum(_ring_count(c) for c in coords)


def zone_geometry(url: str) -> dict[str, Any] | None:
    """One forecast zone's outline, fetched once and remembered."""
    if url in _zone_cache:
        return _zone_cache[url]
    try:
        with httpx.Client(timeout=_TIMEOUT_S, headers=_headers(), follow_redirects=True) as c:
            j = c.get(url).json()
    except Exception as e:  # noqa: BLE001 — a missing outline must not break the map
        log.warning("could not fetch zone %s: %s", url.rsplit("/", 1)[-1], e)
        return None
    geometry = j.get("geometry")
    if not geometry:
        return None
    out = {"geometry": geometry, "name": (j.get("properties") or {}).get("name", "")}
    _zone_cache[url] = out
    return out


def for_hazard(hazard) -> dict[str, Any]:
    """The drawable footprint of one hazard.

    Returns {"kind", "parts": [{"name", "geometry"}], "points"}. `kind` says where the shape came from,
    so the interface can be honest about whether it is showing the forecaster's own polygon or the
    outlines of the zones the alert named.
    """
    raw = (hazard.metrics or {}).get("geometry")
    if raw and raw.get("coordinates"):
        return {"kind": "alert_polygon", "parts": [{"name": hazard.area or hazard.event_name,
                                                    "geometry": raw}],
                "points": _ring_count(raw.get("coordinates"))}

    zones = (hazard.metrics or {}).get("affected_zones") or []
    parts = []
    for url in zones[:_MAX_ZONES]:
        got = zone_geometry(url)
        if got:
            parts.append(got)
    if parts:
        return {"kind": "forecast_zones", "parts": parts,
                "points": sum(_ring_count(p["geometry"].get("coordinates")) for p in parts)}
    return {"kind": "none", "parts": [], "points": 0}
