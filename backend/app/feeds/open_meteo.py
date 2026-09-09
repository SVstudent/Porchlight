"""Open-Meteo weather + air-quality API. Free, no key. Used for per-member exposure and threshold detection."""
from __future__ import annotations

from typing import Any

import httpx

WEATHER = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"


def current_conditions(lat: float, lon: float) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,apparent_temperature_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 2,
        "timezone": "auto",
    }
    with httpx.Client(timeout=20.0) as c:
        r = c.get(WEATHER, params=params)
        r.raise_for_status()
        d = r.json()
    cur = d.get("current", {})
    daily = d.get("daily", {})
    return {
        "temp_f": cur.get("temperature_2m"),
        "feels_like_f": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "wind_mph": cur.get("wind_speed_10m"),
        "weather_code": cur.get("weather_code"),
        "today_max_f": (daily.get("temperature_2m_max") or [None])[0],
        "today_feels_max_f": (daily.get("apparent_temperature_max") or [None])[0],
        "tonight_min_f": (daily.get("temperature_2m_min") or [None])[0],
        "tomorrow_max_f": (daily.get("temperature_2m_max") or [None, None])[1],
        "observed_at": cur.get("time"),
        "timezone": d.get("timezone"),
    }


def air_quality(lat: float, lon: float) -> dict[str, Any]:
    params = {"latitude": lat, "longitude": lon, "current": "us_aqi,pm2_5,pm10,ozone", "timezone": "auto"}
    with httpx.Client(timeout=20.0) as c:
        r = c.get(AIR, params=params)
        r.raise_for_status()
        cur = r.json().get("current", {})
    return {
        "us_aqi": cur.get("us_aqi"),
        "pm2_5": cur.get("pm2_5"),
        "pm10": cur.get("pm10"),
        "ozone": cur.get("ozone"),
        "observed_at": cur.get("time"),
    }


def aqi_label(aqi: float | None) -> str:
    if aqi is None:
        return "unknown"
    if aqi <= 50:
        return "good"
    if aqi <= 100:
        return "moderate"
    if aqi <= 150:
        return "unhealthy for sensitive groups"
    if aqi <= 200:
        return "unhealthy"
    if aqi <= 300:
        return "very unhealthy"
    return "hazardous"
