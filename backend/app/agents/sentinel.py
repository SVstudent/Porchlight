"""Deterministic hazard detection. No LLM here: thresholds and official alerts decide when the agents wake up."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings
from ..feeds import nws, open_meteo
from ..models import HazardEvent
from ..store import store

log = logging.getLogger("porchlight.sentinel")

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def _clusters(max_points: int = 3) -> list[tuple[float, float]]:
    """Distinct member locations (rounded to ~1 km) so one NWS query covers a cluster."""
    seen: dict[tuple[float, float], int] = {}
    for m in store.members():
        key = (round(m.lat, 2), round(m.lon, 2))
        seen[key] = seen.get(key, 0) + 1
    pts = sorted(seen.items(), key=lambda kv: -kv[1])
    return [k for k, _ in pts[:max_points]] or [(33.4942, -112.1770)]


def scan_nws() -> list[HazardEvent]:
    found: dict[str, HazardEvent] = {}
    for lat, lon in _clusters():
        try:
            feats = nws.active_alerts_for_point(lat, lon)
        except Exception as e:  # noqa: BLE001
            log.warning("NWS query failed for %s,%s: %s", lat, lon, e)
            continue
        for f in feats:
            p = f.get("properties", {})
            if not nws.is_relevant(p.get("event", "")):
                continue
            h = nws.feature_to_hazard(f)
            if h.external_id and h.external_id not in found:
                found[h.external_id] = h
    return list(found.values())


def scan_thresholds() -> list[HazardEvent]:
    """Threshold-based detection from live conditions, for places/hazards without an official alert."""
    out: list[HazardEvent] = []
    lat, lon = _clusters(1)[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        wx = open_meteo.current_conditions(lat, lon)
        feels = wx.get("feels_like_f") or wx.get("temp_f")
        if feels is not None and feels >= settings.HEAT_INDEX_ACTIVATE_F:
            out.append(HazardEvent(source="open-meteo", external_id=f"om-heat-{today}", hazard_type="heat",
                                   event_name="Dangerous heat (threshold)", severity="Severe",
                                   headline=f"Feels like {feels:.0f} F right now near the community",
                                   description=f"Live Open-Meteo reading: temperature {wx.get('temp_f')} F, feels like {feels} F, humidity {wx.get('humidity_pct')}%. Today's max {wx.get('today_max_f')} F.",
                                   metrics=wx))
        if wx.get("temp_f") is not None and wx["temp_f"] <= settings.COLD_ACTIVATE_F:
            out.append(HazardEvent(source="open-meteo", external_id=f"om-cold-{today}", hazard_type="cold",
                                   event_name="Dangerous cold (threshold)", severity="Severe",
                                   headline=f"{wx['temp_f']:.0f} F right now near the community", metrics=wx))
    except Exception as e:  # noqa: BLE001
        log.warning("Open-Meteo weather failed: %s", e)
    try:
        aq = open_meteo.air_quality(lat, lon)
        if aq.get("us_aqi") is not None and aq["us_aqi"] >= settings.AQI_ACTIVATE:
            out.append(HazardEvent(source="open-meteo", external_id=f"om-aqi-{today}", hazard_type="air_quality",
                                   event_name="Unhealthy air quality (threshold)", severity="Moderate",
                                   headline=f"US AQI {aq['us_aqi']} ({open_meteo.aqi_label(aq['us_aqi'])})", metrics=aq))
    except Exception as e:  # noqa: BLE001
        log.warning("Open-Meteo air quality failed: %s", e)
    return out


def new_hazards() -> list[HazardEvent]:
    """Everything active right now that we have not already opened an episode for."""
    hazards = scan_nws()
    active_types = {h.hazard_type for h in hazards}
    hazards += [h for h in scan_thresholds() if h.hazard_type not in active_types]
    fresh = [h for h in hazards if not store.alert_seen(h.external_id)]
    return fresh


def list_fixtures() -> list[dict[str, Any]]:
    out = []
    for p in sorted(FIXTURES.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            feat = d["features"][0] if "features" in d else d
            props = feat.get("properties", feat)
            meta = d.get("porchlight", {}) if isinstance(d, dict) else {}
            sender = props.get("senderName") or ""
            out.append({
                "id": p.stem,
                "event": props.get("event"),
                "hazard_type": nws.classify_event(props.get("event") or ""),
                "place": meta.get("place") or sender.removeprefix("NWS ").strip(),
                "date": (props.get("sent") or props.get("onset") or props.get("effective") or "")[:10],
                "source_url": meta.get("source_url") or props.get("id"),
                "headline": props.get("headline"),
                "sender": sender,
                "area": (props.get("areaDesc") or "")[:80],
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def replay_fixture(fixture_id: str) -> HazardEvent:
    """Re-run a real archived NWS alert through the identical code path (clearly labelled as a replay)."""
    p = FIXTURES / f"{fixture_id}.json"
    d = json.loads(p.read_text())
    feat = d["features"][0] if "features" in d else d
    h = nws.feature_to_hazard(feat, source="replay")
    h.external_id = f"{h.external_id}#replay-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    return h
