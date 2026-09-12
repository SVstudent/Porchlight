"""Who gets sent to whom, and only once there is evidence they need it.

Run: python -m tests.test_deployments
"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-dep-")
os.environ["SENTINEL_ENABLED"] = "false"

from app import deployments  # noqa: E402
from app.models import Checkin, Episode, HazardEvent  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402

store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
for v in VOLUNTEERS:
    store.put_volunteer(v)

FAKE_ROUTE = {"points": [[33.50, -112.16], [33.499, -112.165], [33.4995, -112.171]],
              "seconds": 186.0, "metres": 1428.0, "steps": ["Drive southwest."], "source": "test"}


def setup(status: str = "needs_help", member_id: str = "mem_rosa") -> Checkin:
    for d in store.deployments():
        store.mutate_deployment(d.id, lambda x: setattr(x, "status", "cancelled"))
    ep = Episode(hazard=HazardEvent(source="test", hazard_type="heat", event_name="Extreme Heat Warning"))
    ep.status = "monitoring"
    store.put_episode(ep)
    c = Checkin(token=f"t_{member_id}_{status}", episode_id=ep.id, member_id=member_id,
                channel="telegram", status=status, note="said: my ac is broken and i feel dizzy",
                reminders_sent=3)
    store.put_checkin(c)
    return c


def patch_route():
    deployments.route = lambda *a, **k: FAKE_ROUTE   # no network in tests


patch_route()


def test_a_request_for_help_proposes_a_visit():
    c = setup("needs_help")
    d = deployments.propose_for(c)
    assert d is not None, "someone asking for help must produce a suggestion"
    assert d.status == "proposed", "it is a suggestion, never an action"
    assert d.trigger == "needs_help"
    assert d.member_id == "mem_rosa" and d.responder_id
    assert len(d.route) >= 2 and d.duration_s > 0, "a suggestion must carry a route to show"
    assert "asked for help" in d.reason and "my ac is broken" in d.reason


def test_running_out_of_reminders_also_proposes_a_visit():
    c = setup("critical")
    d = deployments.propose_for(c)
    assert d is not None and d.trigger == "critical"
    assert "has not answered 3 messages" in d.reason


def test_a_neighbour_who_is_fine_gets_nobody_sent():
    c = setup("ok")
    assert deployments.propose_for(c) is None, "answering 'ok' is not evidence of need"


def test_only_one_trip_per_neighbour_at_a_time():
    c = setup("needs_help")
    first = deployments.propose_for(c)
    assert first is not None
    assert deployments.propose_for(c) is None, "somebody is already going; do not send a second"


def test_a_closed_episode_proposes_nothing():
    c = setup("needs_help")
    store.mutate_episode(c.episode_id, lambda e: setattr(e, "status", "closed"))
    assert deployments.propose_for(c) is None


def test_approving_is_what_starts_the_trip():
    c = setup("needs_help")
    d = deployments.propose_for(c)
    assert not d.approved_at, "nothing starts before the coordinator says so"

    after = deployments.decide(d.id, True, "go now")
    assert after.status == "approved" and after.approved_at
    assert deployments.progress(after, 0)["fraction"] == 0.0

    half = deployments.progress(after, after.duration_s / 2)
    assert 0.4 < half["fraction"] < 0.6, half["fraction"]
    assert half["point"] != after.route[0] and half["point"] != after.route[-1], "should be mid-route"

    done = deployments.progress(after, after.duration_s * 2)
    assert done["fraction"] == 1.0 and done["eta_s"] == 0.0
    assert done["point"] == after.route[-1], "ends at the neighbour's door"


def test_declining_leaves_nobody_travelling():
    c = setup("needs_help")
    d = deployments.propose_for(c)
    after = deployments.decide(d.id, False, "her daughter is already there")
    assert after.status == "declined" and not after.approved_at
    assert deployments.progress(after, 9999)["fraction"] == 0.0, "a declined trip never moves"


def test_a_spanish_speaker_is_preferred_for_a_spanish_speaking_neighbour():
    c = setup("needs_help", "mem_rosa")          # Rosa's language is es
    d = deployments.propose_for(c)
    v = store.volunteer(d.responder_id)
    assert "spanish" in v.skills, f"picked {v.name} with {v.skills}"


def test_a_lift_goes_to_someone_who_can_drive():
    """The nearest volunteer is the wrong answer if the job is a lift and they have no car."""
    c = setup("needs_help", "mem_bettie")
    c.note = "said: my ac stopped working and it is so hot"
    store.put_checkin(c)
    d = deployments.propose_for(c)
    assert d.task == "ride_to_cooling_center", d.task
    assert d.destination_name, "a lift must say where to"
    v = store.volunteer(d.responder_id)
    assert "drive" in v.skills, f"{v.name} cannot drive but was asked to give a lift"


def test_a_medical_need_beats_proximity():
    c = setup("critical", "mem_walter")      # powered medical device on file
    d = deployments.propose_for(c)
    v = store.volunteer(d.responder_id)
    assert "medical" in v.skills, f"picked {v.name} ({v.skills}) for someone on medical equipment"


def test_with_no_driver_free_it_still_sends_someone():
    """Degrade to a visit rather than proposing nothing at all."""
    c = setup("needs_help", "mem_bettie")
    c.note = "said: my ac stopped working"
    store.put_checkin(c)
    drivers = [v for v in store.volunteers() if "drive" in v.skills]
    for v in drivers:
        store.put_volunteer(v.model_copy(update={"available": False}))
    try:
        d = deployments.propose_for(c)
        assert d is not None, "somebody should still go round"
        assert d.task == "wellness_visit", d.task
        assert "nobody free can drive" in d.reason
    finally:
        for v in drivers:
            store.put_volunteer(v)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DEPLOYMENT TESTS PASSED")
