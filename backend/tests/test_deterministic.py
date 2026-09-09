"""Deterministic tests (no model, no network). Run: python -m tests.test_deterministic"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="porchlight-test-"))

from app.feeds.nws import classify_event, feature_to_hazard, is_relevant  # noqa: E402
from app.feeds.open_meteo import aqi_label  # noqa: E402
from app.feeds.places import haversine_km  # noqa: E402
from app.models import Episode, HazardEvent, TimelineEntry  # noqa: E402
from app.store import Store  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "app" / "data" / "fixtures"


def test_classification():
    assert classify_event("Extreme Heat Warning") == "heat"
    assert classify_event("Excessive Heat Warning") == "heat"
    assert classify_event("Air Quality Alert") == "air_quality"
    assert classify_event("Wind Chill Warning") == "cold"
    assert classify_event("Winter Storm Warning") == "winter"
    assert classify_event("Flash Flood Warning") == "flood"
    assert classify_event("Tornado Warning") == "storm"
    assert not is_relevant("Small Craft Advisory")
    assert is_relevant("Extreme Heat Warning")


def test_fixture_parses():
    d = json.loads((FIX / "nws_phoenix_extreme_heat_warning_2026-09-08.json").read_text())
    h = feature_to_hazard(d["features"][0], source="replay")
    assert h.hazard_type == "heat" and h.event_name == "Extreme Heat Warning"
    assert "2-1-1" in h.description and h.expires.startswith("2026-09-10")


def test_labels_and_distance():
    assert aqi_label(45) == "good" and aqi_label(175) == "unhealthy" and aqi_label(None) == "unknown"
    assert 4.0 < haversine_km(33.4942, -112.1770, 33.5017, -112.1522) * 4 < 12.0  # ~2.4 km


def test_store_atomic_updates():
    st = Store(path=os.path.join(tempfile.mkdtemp(), "t.db"))
    ep = Episode(hazard=HazardEvent(source="manual", event_name="test"))
    st.put_episode(ep)

    def writer(kind: str):
        for i in range(50):
            st.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(kind=kind, text=str(i))))

    threads = [threading.Thread(target=writer, args=(f"w{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = st.episode(ep.id)
    assert len(got.timeline) == 200, f"lost writes: {len(got.timeline)}"
    st.mutate_episode(ep.id, lambda e: setattr(e, "status", "monitoring"))
    assert st.episode(ep.id).status == "monitoring" and len(st.episode(ep.id).timeline) == 200


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DETERMINISTIC TESTS PASSED")
