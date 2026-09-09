"""Power-outage feature without a model (no LLM, no network). Run: python -m tests.test_outage"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-outage-")
os.environ["SEND_MODE"] = "console"

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import sentinel  # noqa: E402
from app.agents.runner import runner  # noqa: E402
from app.agents.tools_outage import electricity_dependent_members  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Episode, HazardEvent, Member  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402

STARTED: list[Episode] = []


async def _fake_start(hazard: HazardEvent) -> Episode:
    """Stand-in for runner.start: records the episode without launching the (model-backed) graph task."""
    store.put_hazard(hazard)
    ep = Episode(hazard=hazard, session_id=f"graph-{hazard.id}")
    store.put_episode(ep)
    STARTED.append(ep)
    return ep


runner.start = _fake_start  # type: ignore[method-assign]
client = TestClient(app)  # no context manager: startup (scheduler, real sentinel scans) does not run


def setup():
    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    store.reset_runtime()
    STARTED.clear()


def test_member_defaults_and_seed():
    setup()
    m = Member(name="x", lat=0, lon=0)
    assert m.devices == [] and m.backup_power_hours == 0 and m.utility == "" and m.backup_plan == ""
    walter = store.member("mem_walter")
    assert walter.devices == ["oxygen_concentrator"] and walter.backup_power_hours == 2 and walter.utility == "APS"


def test_electricity_dependent_sorted():
    setup()
    rows = electricity_dependent_members()
    ids = [r["member_id"] for r in rows]
    assert ids == ["mem_thanh", "mem_walter", "mem_helen"], ids  # 0h, 2h, 6h
    hours = [r["backup_power_hours"] for r in rows]
    assert hours == sorted(hours)
    assert rows[1]["emergency_contact_phone"] == "+16025550104" and rows[1]["device_labels"] == ["oxygen concentrator"]
    # risk factor alone (no declared devices) is enough to be listed; opted-out members are not
    store.put_member(Member(id="mem_rf", name="Aaron Zed", lat=33.5, lon=-112.18, risk_factors=["powered_medical_device"]))
    store.put_member(Member(id="mem_out", name="Opted Out", lat=33.5, lon=-112.18, devices=["ventilator"], opted_in=False))
    ids = [r["member_id"] for r in electricity_dependent_members()]
    assert ids == ["mem_rf", "mem_thanh", "mem_walter", "mem_helen"], ids
    r = client.get("/api/outage/electricity-dependent").json()
    assert r["count"] == 4 and r["under_4h"] == 3 and [m["member_id"] for m in r["members"]] == ids
    store.delete_member("mem_rf")
    store.delete_member("mem_out")


def test_report_plain_outage():
    setup()
    r = client.post("/api/outage/report", json={"utility": "SRP", "area": "85033", "description": "Transformer fire on 51st Ave."}).json()
    assert r["compound_with"] is None
    h = r["episode"]["hazard"]
    assert h["source"] == "manual" and h["hazard_type"] == "outage" and h["event_name"] == "Power outage — SRP"
    assert "compound_with" not in h["metrics"] and h["metrics"]["utility"] == "SRP" and h["metrics"]["under_4h_backup"] == 2
    assert "Transformer fire" in h["description"] and h["area"] == "85033"
    assert len(STARTED) == 1 and store.episode(STARTED[0].id) is not None


def test_report_compound_with_active_heat():
    setup()
    heat = Episode(hazard=HazardEvent(source="replay", event_name="Extreme Heat Warning", hazard_type="heat", headline="Feels like 112 F"), status="monitoring")
    store.put_episode(heat)
    r = client.post("/api/outage/report", json={"utility": "APS", "area": "85031", "estimated_restoration_iso": "2026-09-08T23:00:00-07:00"}).json()
    assert r["compound_with"] == heat.id
    h = r["episode"]["hazard"]
    assert h["metrics"]["compound_with"] == heat.id and h["metrics"]["compound_hazard"] == "heat"
    assert h["severity"] == "Extreme" and h["expires"].startswith("2026-09-08T23")
    assert "during an active heat event" in h["description"] and "life-threatening" in h["description"]
    assert "Extreme Heat Warning" in h["headline"]
    # a closed heat episode must not count as active
    store.mutate_episode(heat.id, lambda e: setattr(e, "status", "closed"))
    r2 = client.post("/api/outage/report", json={"utility": "APS"}).json()
    assert r2["compound_with"] is None and "compound_with" not in r2["episode"]["hazard"]["metrics"]


def test_sentinel_never_filters_outage():
    setup()
    heat = HazardEvent(source="nws", external_id="nws-heat-1", hazard_type="heat", event_name="Extreme Heat Warning")
    outage = HazardEvent(source="manual", external_id="utility-outage-1", hazard_type="outage", event_name="Power outage — APS")
    store.mark_alert_seen(heat.external_id, "ep_x")
    store.mark_alert_seen(outage.external_id, "ep_y")
    orig_nws, orig_th = sentinel.scan_nws, sentinel.scan_thresholds
    try:
        sentinel.scan_nws = lambda: [heat]
        sentinel.scan_thresholds = lambda: [outage]
        fresh = sentinel.new_hazards()
        assert [h.hazard_type for h in fresh] == ["outage"], fresh  # seen heat is deduped; outage never is
        sentinel.scan_nws = lambda: [heat, outage]
        sentinel.scan_thresholds = lambda: [outage]
        assert [h.hazard_type for h in sentinel.new_hazards()] == ["outage", "outage"]
    finally:
        sentinel.scan_nws, sentinel.scan_thresholds = orig_nws, orig_th


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL OUTAGE TESTS PASSED")
