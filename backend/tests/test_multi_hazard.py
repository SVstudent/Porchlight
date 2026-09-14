"""Multi-hazard tests (no model, no network). Run: python -m tests.test_multi_hazard"""
from __future__ import annotations

import json
import os
import tempfile
import typing
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="porchlight-test-"))

from app.agents.playbooks import PLAYBOOKS, get_playbook, playbook_summary, playbook_text
from app.agents.sentinel import list_fixtures, replay_fixture
from app.feeds.nws import feature_to_hazard
from app.models import Episode, HazardEvent, HazardType, RiskFactor

FIX = Path(__file__).resolve().parent.parent / "app" / "data" / "fixtures"

EXPECTED = {
    "nws_phoenix_extreme_heat_warning_2026-09-08": ("heat", "Extreme Heat Warning"),
    "nws_northern_new_jersey_air_quality_alert_2023-06-07": ("air_quality", "Air Quality Alert"),
    "nws_fort_worth_winter_storm_warning_2021-02-12": ("winter", "Winter Storm Warning"),
    "nws_orlando_flash_flood_warning_2026-09-07": ("flood", "Flash Flood Warning"),
    "nws_mclean_county_nd_tornado_warning_2026-09-07": ("storm", "Tornado Warning"),
}
REQUIRED_PROPS = ("id", "event", "severity", "headline", "description", "instruction", "areaDesc", "onset", "expires", "senderName")


def test_every_fixture_parses_with_expected_type():
    for stem, (kind, event) in EXPECTED.items():
        d = json.loads((FIX / f"{stem}.json").read_text())
        feat = d["features"][0] if "features" in d else d
        for k in REQUIRED_PROPS:
            assert k in feat["properties"], f"{stem}: missing property {k}"
        h = feature_to_hazard(feat, source="replay")
        assert h.hazard_type == kind, f"{stem}: {h.hazard_type} != {kind}"
        assert h.event_name == event
        assert h.headline and h.description and h.area and h.onset and h.expires, stem
        assert h.external_id, stem


def test_fixture_text_is_real_alert_text():
    """Spot-check phrases that only exist in the real products (guards against placeholder text)."""
    d = json.loads((FIX / "nws_northern_new_jersey_air_quality_alert_2023-06-07.json").read_text())
    assert "wildfire smoke transport from eastern Canadian wildfires" in d["features"][0]["properties"]["description"]
    d = json.loads((FIX / "nws_fort_worth_winter_storm_warning_2021-02-12.json").read_text())
    p = d["features"][0]["properties"]
    assert "HISTORIC WINTER STORM" in p["description"] and "drivetexas.org" in p["instruction"]
    assert p["onset"].startswith("2021-02-13") and p["expires"].startswith("2021-02-16")
    d = json.loads((FIX / "nws_orlando_flash_flood_warning_2026-09-07.json").read_text())
    assert "Turn around, don't drown" in d["features"][0]["properties"]["instruction"]


def test_list_fixtures_exposes_hazard_type_and_place():
    fx = {f["id"]: f for f in list_fixtures()}
    for stem, (kind, _) in EXPECTED.items():
        assert stem in fx, stem
        assert fx[stem]["hazard_type"] == kind
        assert fx[stem]["place"] and fx[stem]["date"] and fx[stem]["source_url"], stem
        assert "event" in fx[stem] and "headline" in fx[stem]  # existing keys still present
    assert {f["hazard_type"] for f in fx.values()} >= {"heat", "air_quality", "winter", "flood", "storm"}


def test_replay_fixture_still_works_for_every_fixture():
    for stem, (kind, _) in EXPECTED.items():
        h = replay_fixture(stem)
        assert h.source == "replay" and h.hazard_type == kind and "#replay-" in h.external_id


def test_playbooks_cover_every_hazard_type():
    kinds = typing.get_args(HazardType)
    factors = set(typing.get_args(RiskFactor))
    for k in kinds:
        assert k in PLAYBOOKS, f"no playbook for {k}"
        pb = PLAYBOOKS[k]
        assert pb["elevated_risk_factors"] and set(pb["elevated_risk_factors"]) <= factors, k
        assert pb["protective_actions"] and pb["spanish_phrases"] and pb["safe_place"] and pb["safe_place_es"], k
        assert pb["volunteer_tasks"] and pb["escalation_triggers"] and pb["sources"], k
        assert playbook_summary(k)["hazard_type"] == k
    assert get_playbook("not-a-hazard") is PLAYBOOKS["other"]
    assert "cooling center" in PLAYBOOKS["heat"]["safe_place"]
    assert "warming center" in PLAYBOOKS["cold"]["safe_place"]
    assert "clean-air" in PLAYBOOKS["air_quality"]["safe_place"]
    assert "higher ground" in PLAYBOOKS["flood"]["safe_place"]


def test_graph_task_includes_playbook():
    from app.agents.pipeline import graph_task

    for kind in ("heat", "air_quality", "winter", "flood", "storm", "outage"):
        ep = Episode(hazard=HazardEvent(source="manual", event_name="x", hazard_type=kind))
        task = graph_task(ep)
        assert "PLAYBOOK FOR THIS HAZARD" in task and f"hazard_type={kind}" in task
        assert PLAYBOOKS[kind]["safe_place"] in task
        assert PLAYBOOKS[kind]["spanish_phrases"][0] in task
    assert playbook_text("air_quality") != playbook_text("heat")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all multi-hazard tests passed")
