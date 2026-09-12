"""The two scales the map draws: where the hazard is, and what conditions are on each street.

No network: the NWS zone fetch and the Open-Meteo call are both stubbed, because what is worth pinning
is the shape of the answer and the handling of the two different kinds of alert, not the services.

Run: python -m tests.test_map_layers
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-layers-")
os.environ["SENTINEL_ENABLED"] = "false"

from app.feeds import field as field_mod  # noqa: E402
from app.feeds import footprint as fp_mod  # noqa: E402
from app.feeds.nws import feature_to_hazard  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "app" / "data" / "fixtures"


def hazard(name: str):
    d = json.loads((FIX / f"{name}.json").read_text())
    return feature_to_hazard((d.get("features") or [d])[0])


def test_a_storm_warning_uses_the_forecasters_own_polygon():
    """Flash flood and tornado warnings carry the shape the forecaster drew; use it verbatim."""
    fp = fp_mod.for_hazard(hazard("nws_orlando_flash_flood_warning_2026-09-07"))
    assert fp["kind"] == "alert_polygon", fp["kind"]
    assert len(fp["parts"]) == 1
    assert fp["parts"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert fp["points"] > 0


def test_an_area_warning_falls_back_to_its_forecast_zones():
    """A heat warning has no polygon at all; it names zones, which have to be resolved."""
    h = hazard("nws_phoenix_extreme_heat_warning_2026-09-08")
    assert not (h.metrics.get("geometry") or {}), "this alert genuinely has no geometry of its own"
    assert len(h.metrics["affected_zones"]) > 1

    calls = []

    def fake_zone(url):
        calls.append(url)
        return {"name": f"Zone {url[-3:]}",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}}

    real, fp_mod.zone_geometry = fp_mod.zone_geometry, fake_zone
    try:
        fp = fp_mod.for_hazard(h)
    finally:
        fp_mod.zone_geometry = real

    assert fp["kind"] == "forecast_zones", fp["kind"]
    assert len(fp["parts"]) == len(calls) > 1
    assert all(p["geometry"] for p in fp["parts"])


def test_a_hazard_with_neither_draws_nothing_rather_than_guessing():
    h = hazard("nws_phoenix_extreme_heat_warning_2026-09-08")
    h.metrics["affected_zones"] = []
    fp = fp_mod.for_hazard(h)
    assert fp["kind"] == "none" and fp["parts"] == []


def test_an_unreachable_zone_is_skipped_not_fatal():
    h = hazard("nws_phoenix_extreme_heat_warning_2026-09-08")
    real, fp_mod.zone_geometry = fp_mod.zone_geometry, lambda url: None
    try:
        fp = fp_mod.for_hazard(h)
    finally:
        fp_mod.zone_geometry = real
    assert fp["kind"] == "none", "no outlines resolved, so there is nothing to draw"


def test_the_field_covers_everyone_and_reports_its_range():
    points = [(33.470, -112.20), (33.510, -112.14)]
    grid = []

    def fake_batch(url, cells, params):
        grid.extend(cells)
        # a gradient so min and max are distinguishable
        return [{"current": {"apparent_temperature": 90 + i * 0.5}} for i, _ in enumerate(cells)]

    real, field_mod._batch = field_mod._batch, fake_batch
    field_mod._cache.update({"key": None, "at": 0})
    try:
        f = field_mod.sample(points, "heat", steps=4)
    finally:
        field_mod._batch = real

    assert len(f["cells"]) == 16, f"a 4x4 grid, got {len(f['cells'])}"
    assert f["min"] == 90 and f["max"] == 97.5
    assert f["unit"] == "°F" and "Feels" in f["metric"]
    for c in f["cells"]:
        (s, w), (n, e) = c["bounds"]
        assert s < n and w < e, "each cell needs a south-west and north-east corner"
    lats = [p[0] for p in grid]
    assert min(lats) < 33.470 and max(lats) > 33.510, "the grid must extend past the outermost neighbour"


def test_air_quality_asks_a_different_service_for_a_different_number():
    seen = {}

    def fake_batch(url, cells, params):
        seen["url"], seen["params"] = url, params
        return [{"current": {"us_aqi": 120}} for _ in cells]

    real, field_mod._batch = field_mod._batch, fake_batch
    field_mod._cache.update({"key": None, "at": 0})
    try:
        f = field_mod.sample([(33.5, -112.1)], "air_quality", steps=2)
    finally:
        field_mod._batch = real

    assert "air-quality" in seen["url"] and "us_aqi" in seen["params"]
    assert f["unit"] == "" and "air quality" in f["metric"].lower()
    assert f["min"] == f["max"] == 120


def test_a_dead_weather_service_loses_the_field_not_the_map():
    def boom(*a, **k):
        raise RuntimeError("open-meteo unreachable")

    real, field_mod._batch = field_mod._batch, boom
    field_mod._cache.update({"key": None, "at": 0})
    try:
        f = field_mod.sample([(33.5, -112.1)], "heat", steps=3)
    finally:
        field_mod._batch = real
    assert f["cells"] == [] and "error" in f, "degrade to no overlay, never to an exception"


def test_no_roster_means_no_field():
    assert field_mod.sample([], "heat")["cells"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL MAP LAYER TESTS PASSED")
