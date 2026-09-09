"""Action-tool bodies without a model (SEND_MODE=console). Run: python -m tests.test_actions"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-actions-")
os.environ["SEND_MODE"] = "console"

from app.agents.tools import (  # noqa: E402
    assign_volunteers_impl,
    dispatch_outreach_impl,
    escalate_member_impl,
    record_coordinator_brief_impl,
)
from app.config import settings  # noqa: E402
from app.models import Episode, HazardEvent  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402


def setup():
    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    ep = Episode(hazard=HazardEvent(source="manual", event_name="Extreme Heat Warning", hazard_type="heat"))
    store.put_episode(ep)
    return ep


def test_dispatch_outreach():
    ep = setup()
    r = dispatch_outreach_impl(ep.id, [
        {"member_id": "mem_rosa", "channel": "sms", "language": "es", "body": "Rosa, hace mucho calor. Vaya a la Biblioteca Palo Verde. {checkin_link}"},
        {"member_id": "mem_walter", "channel": "voice", "language": "en", "body": "Walter, if the power fails call Denise. {checkin_link}", "call_script": "Hi Walter…"},
        {"member_id": "mem_nobody", "channel": "sms", "language": "en", "body": "x {checkin_link}"},
    ], "Contacting the two highest-risk neighbors.")
    assert r["sent"] == 2 and r["failed"] == 1, r
    cks = store.checkins(ep.id)
    assert len(cks) == 2 and all(c.status == "sent" for c in cks)
    link = r["deliveries"][0]["checkin_link"]
    assert link.startswith(settings.PUBLIC_BASE_URL + "/checkin/") and "{checkin_link}" not in link
    cur = store.episode(ep.id)
    assert cur.status == "monitoring" and cur.outreach and len(cur.outreach.messages) == 3 and cur.stats["messages_sent"] == 2
    bad = dispatch_outreach_impl(ep.id, [{"member_id": "mem_rosa", "channel": "pigeon", "language": "es", "body": "x"}], "n")
    assert "invalid messages" in bad["error"]


def test_assign_volunteers_and_brief():
    ep = setup()
    r = assign_volunteers_impl(ep.id, [
        {"volunteer_id": "vol_marisol", "member_id": "mem_rosa", "task": "wellness_visit", "reason": "no AC, Spanish", "priority": 1},
        {"volunteer_id": "vol_priya", "member_id": "mem_walter", "task": "phone_call", "reason": "oxygen concentrator", "priority": 1},
    ], ["res_paloverde"], ["Guadalupe needs a ride; no driver free"])
    assert r["assigned"] == 2 and r["gaps"] == ["Guadalupe needs a ride; no driver free"]
    cur = store.episode(ep.id)
    assert cur.logistics and len(cur.logistics.assignments) == 2 and cur.stats["volunteer_assignments"] == 2
    assert record_coordinator_brief_impl(ep.id, "Two neighbors contacted.")["saved"]
    assert store.episode(ep.id).stats["brief"] == "Two neighbors contacted."


def test_escalation_paths():
    ep = setup()
    dispatch_outreach_impl(ep.id, [{"member_id": "mem_earl", "channel": "sms", "language": "en", "body": "Earl {checkin_link}"}], "n")
    r = escalate_member_impl(ep.id, "mem_earl", "volunteer_visit", "No reply after 25 minutes.", "vol_ray")
    assert "dispatched" in r["detail"], r
    assert store.checkins(ep.id)[0].status == "escalated"
    r2 = escalate_member_impl(ep.id, "mem_earl", "notify_emergency_contact", "Still unreachable.")
    assert "Pastor Ray" in r2["detail"]
    r3 = escalate_member_impl(ep.id, "mem_thanh", "notify_emergency_contact", "x")
    assert "no emergency contact" in r3["error"]
    cur = store.episode(ep.id)
    assert cur.status == "escalating" and cur.stats["escalations"] == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL ACTION TESTS PASSED")
