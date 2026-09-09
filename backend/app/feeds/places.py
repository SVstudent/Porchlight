"""OpenStreetMap Overpass lookup for public cooled/heated buildings near a member (libraries, community centres)."""
from __future__ import annotations

import math
from typing import Any

import httpx

OVERPASS = "https://overpass-api.de/api/interpreter"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_public_buildings(lat: float, lon: float, radius_m: int = 3000, limit: int = 6) -> list[dict[str, Any]]:
    q = (
        f'[out:json][timeout:25];('
        f'node["amenity"~"library|community_centre|social_facility|place_of_worship"](around:{radius_m},{lat},{lon});'
        f'way["amenity"~"library|community_centre|social_facility"](around:{radius_m},{lat},{lon});'
        f');out center 40;'
    )
    with httpx.Client(timeout=40.0) as c:
        r = c.post(OVERPASS, data={"data": q})
        r.raise_for_status()
        elements = r.json().get("elements", [])
    out = []
    for e in elements:
        tags = e.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        plat = e.get("lat") or (e.get("center") or {}).get("lat")
        plon = e.get("lon") or (e.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        out.append({
            "name": name,
            "amenity": tags.get("amenity"),
            "lat": plat,
            "lon": plon,
            "distance_km": round(haversine_km(lat, lon, plat, plon), 2),
            "opening_hours": tags.get("opening_hours", ""),
            "phone": tags.get("phone", ""),
            "address": " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")])),
        })
    out.sort(key=lambda x: x["distance_km"])
    return out[:limit]
