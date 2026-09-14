"""Deterministic tests (no model, no network). Run: python -m tests.test_deterministic"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="porchlight-test-"))

from app.feeds.nws import classify_event, feature_to_hazard, is_relevant
from app.feeds.open_meteo import aqi_label
from app.feeds.places import haversine_km
from app.models import Episode, HazardEvent, TimelineEntry
from app.store import Store

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
            st.mutate_episode(ep.id, lambda e, i=i: e.timeline.append(TimelineEntry(kind=kind, text=str(i))))

    threads = [threading.Thread(target=writer, args=(f"w{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = st.episode(ep.id)
    assert len(got.timeline) == 200, f"lost writes: {len(got.timeline)}"
    st.mutate_episode(ep.id, lambda e: setattr(e, "status", "monitoring"))
    assert st.episode(ep.id).status == "monitoring" and len(st.episode(ep.id).timeline) == 200


def test_member_conditions_is_one_call_for_the_whole_roster():
    """Triage used to ask about each neighbour separately: a model round trip and two HTTP calls per person.

    Asking once for everyone is the point of the batched signature. This checks that it really is one call,
    that neighbours close enough to share a forecast grid cell are not fetched twice, and that one unknown id
    is reported rather than losing the rest of the answer. open_meteo is stubbed, so no network is used.
    """
    import app.agents.tools as tools
    from app.models import Member

    st = Store(path=os.path.join(tempfile.mkdtemp(), "cond.db"))
    here, next_door, across_town = (33.5000, -112.1700), (33.5001, -112.1701), (33.6500, -112.0100)
    for i, (lat, lon) in enumerate([here, next_door, across_town]):
        st.put_member(Member(id=f"m{i}", name=f"Neighbour {i}", lat=lat, lon=lon))

    calls = []

    class Stub:
        @staticmethod
        def current_conditions(lat, lon):
            calls.append((lat, lon))
            return {"temp_f": 101.0}

        @staticmethod
        def air_quality(lat, lon):
            return {"us_aqi": 42}

        @staticmethod
        def aqi_label(v):
            return "Good"

    real_store, real_meteo = tools.store, tools.open_meteo
    tools.store, tools.open_meteo = st, Stub()
    try:
        fn = getattr(tools.get_member_conditions, "_tool_func", None) or tools.get_member_conditions
        out = fn(["m0", "m1", "m2", "nobody"])
    finally:
        tools.store, tools.open_meteo = real_store, real_meteo

    assert set(out) == {"m0", "m1", "m2", "nobody"}, f"not every id came back: {sorted(out)}"
    assert "error" in out["nobody"], "an unknown id should be reported, not silently dropped"
    assert out["m0"]["weather"]["temp_f"] == 101.0
    assert len(calls) == 2, (
        f"expected one forecast per location (two doors apart share one), got {len(calls)}: {calls}")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DETERMINISTIC TESTS PASSED")
