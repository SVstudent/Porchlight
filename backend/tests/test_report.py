"""After-action report: deterministic metrics + GET route (no model, no network). Run: python -m tests.test_report"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-report-")
os.environ["SEND_MODE"] = "console"

from app.feeds.nws import feature_to_hazard
from app.models import (
    Approval,
    Checkin,
    Episode,
    HazardAssessment,
    LogisticsPlan,
    TimelineEntry,
    TriageDecision,
    TriagePlan,
    VolunteerAssignment,
)
from app.report import compute_metrics
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS

FIX = Path(__file__).resolve().parent.parent / "app" / "data" / "fixtures"
T0 = "2026-09-08T20:00:00+00:00"  # hazard detected


def _ts(minutes: float) -> str:
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(T0) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def fixture_hazard():
    d = json.loads(next(FIX.glob("*.json")).read_text())
    h = feature_to_hazard(d["features"][0] if "features" in d else d, source="replay")
    h.detected_at = T0
    return h


def build_episode():
    ep = Episode(hazard=fixture_hazard(), status="escalating", created_at=T0, updated_at=_ts(90))
    ep.assessment = HazardAssessment(activate=True, hazard_type="heat", severity_score=4, plain_summary="Very hot.",
                                     elevated_risk_factors=["no_air_conditioning"], recommended_actions=["Go somewhere cool"], reasoning="r")
    ep.triage = TriagePlan(summary="Rosa and Walter first.", decisions=[
        TriageDecision(member_id="mem_rosa", tier=1, reason="no AC", channel="sms", needs_visit=True),
        TriageDecision(member_id="mem_walter", tier=1, reason="oxygen", channel="voice"),
        TriageDecision(member_id="mem_earl", tier=1, reason="alone", channel="sms"),
        TriageDecision(member_id="mem_thanh", tier=2, reason="works outdoors", channel="sms"),
        TriageDecision(member_id="mem_helen", tier=2, reason="older", channel="email"),
        TriageDecision(member_id="mem_pete", tier=3, reason="info", channel="sms"),
        TriageDecision(member_id="mem_danny", tier=0, reason="volunteer", channel="sms"),
    ])
    ep.logistics = LogisticsPlan(assignments=[
        VolunteerAssignment(volunteer_id="vol_marisol", member_id="mem_rosa", task="wellness_visit", reason="no AC", priority=1),
        VolunteerAssignment(volunteer_id="vol_priya", member_id="mem_walter", task="phone_call", reason="oxygen", priority=1),
        VolunteerAssignment(volunteer_id="vol_marisol", member_id="mem_thanh", task="phone_call", reason="check", priority=2),
    ], recommended_resource_ids=["res_paloverde"], gaps=["Guadalupe needs a ride; no driver free"])
    ep.stats = {"messages_sent": 5, "messages_failed": 1, "brief": "Five neighbors contacted."}
    ep.timeline = [
        TimelineEntry(ts=T0, kind="detected", text="Extreme Heat Warning detected via replay"),
        TimelineEntry(ts=_ts(2), kind="assessment", text="ACTIVATE: Very hot."),
        TimelineEntry(ts=_ts(10), kind="approval_requested", text="Send check-in messages to 6 neighbors"),
        TimelineEntry(ts=_ts(14), kind="approval_approved", text="Send check-in messages to 6 neighbors: approved"),
        TimelineEntry(ts=_ts(15), kind="dispatch", text="Outreach dispatched: 5 sent, 1 failed"),
        TimelineEntry(ts=_ts(50), kind="escalation", text="Earl Jackson escalated (volunteer_visit): No reply after 30 minutes.", data={"detail": "volunteer Pastor Ray Whitfield dispatched: console"}),
        TimelineEntry(ts=_ts(70), kind="escalation", text="Rosa Alvarez escalated (notify_emergency_contact): Reported needing help.", data={"detail": "emergency contact Marisol notified: console"}),
    ]
    checkins = [
        Checkin(token="t_rosa", episode_id=ep.id, member_id="mem_rosa", channel="sms", sent_at=_ts(15), status="escalated", responded_at=_ts(25), note="notify_emergency_contact: Reported needing help."),
        Checkin(token="t_walter", episode_id=ep.id, member_id="mem_walter", channel="voice", sent_at=_ts(15), status="ok", responded_at=_ts(35)),
        Checkin(token="t_earl", episode_id=ep.id, member_id="mem_earl", channel="sms", sent_at=_ts(16), status="escalated", note="volunteer_visit: No reply after 30 minutes."),
        Checkin(token="t_thanh", episode_id=ep.id, member_id="mem_thanh", channel="sms", sent_at=_ts(16), status="ok", responded_at=_ts(21)),
        Checkin(token="t_helen", episode_id=ep.id, member_id="mem_helen", channel="email", sent_at=_ts(17), status="sent"),
        Checkin(token="t_pete", episode_id=ep.id, member_id="mem_pete", channel="sms", sent_at=_ts(17), status="failed", note="no phone"),
    ]
    approvals = [
        Approval(episode_id=ep.id, kind="outreach_dispatch", title="Send check-in messages to 6 neighbors", summary="", payload={"tool": "dispatch_outreach", "input": {}},
                 agent_name="outreach", status="approved", created_at=_ts(10), resolved_at=_ts(14), edits={"messages": {"0": {"body": "edited"}}}),
        Approval(episode_id=ep.id, kind="volunteer_dispatch", title="Dispatch 3 volunteer assignments", summary="", payload={"tool": "assign_volunteers", "input": {}},
                 agent_name="logistics", status="approved", created_at=_ts(11), resolved_at=_ts(13)),
        Approval(episode_id=ep.id, kind="escalation", title="Escalate Earl Jackson: volunteer visit", summary="", agent_name="followup",
                 payload={"tool": "escalate_member", "input": {"member_id": "mem_earl", "action": "volunteer_visit", "reason": "No reply after 30 minutes.", "volunteer_id": "vol_ray"}},
                 status="approved", created_at=_ts(48), resolved_at=_ts(50)),
        Approval(episode_id=ep.id, kind="escalation", title="Escalate Rosa Alvarez: recommend 911", summary="", agent_name="followup",
                 payload={"tool": "escalate_member", "input": {"member_id": "mem_rosa", "action": "recommend_911", "reason": "Reported needing help."}},
                 status="rejected", created_at=_ts(60), resolved_at=_ts(72), decision_note="Marisol is on her way"),
    ]
    return ep, checkins, approvals


def test_compute_metrics():
    ep, cks, aprs = build_episode()
    m = compute_metrics(ep, cks, aprs, MEMBERS, VOLUNTEERS)
    o, t = m["outreach"], m["timing"]
    assert o["contacted"] == 5 and o["failed"] == 1 and o["messages_attempted"] == 6, o
    assert o["sent_by_channel"] == {"email": 1, "sms": 3, "voice": 1} and o["failed_by_channel"] == {"sms": 1}
    assert o["contacted_by_tier"] == {"tier_1": 3, "tier_2": 2}
    assert o["replied"] == 3 and o["response_rate_pct"] == 60.0, o  # Rosa (escalated after replying) still counts as replied
    assert o["replied_ok"] == 2 and o["needed_help"] == 2 and o["no_reply"] == 1
    assert o["tier1_contacted"] == 3 and o["tier1_replied"] == 2 and o["tier1_response_rate_pct"] == 66.7
    # detection 20:00 -> first message 20:15; replies took 10, 20, 5 min -> median 10
    assert t["minutes_detection_to_first_message"] == 15.0 and t["minutes_approval_to_first_message"] == 1.0
    assert t["median_minutes_to_reply"] == 10.0 and t["max_minutes_to_reply"] == 20.0
    assert t["minutes_detection_to_assessment"] == 2.0 and t["minutes_detection_to_first_reply"] == 21.0
    assert t["first_message_at"] == _ts(15) and t["first_reply_at"] == _ts(21)
    # approvals: decision latencies 4, 2, 2, 12 -> median 3
    a = m["approvals"]
    assert a["total"] == 4 and a["approved"] == 3 and a["declined"] == 1 and a["edited"] == 1 and a["pending"] == 0
    assert a["median_decision_minutes"] == 3.0 and a["max_decision_minutes"] == 12.0 and t["median_coordinator_decision_minutes"] == 3.0
    # escalations: 2 approval rows + 1 policy-only timeline entry (Rosa notify_emergency_contact)
    e = m["escalations"]
    assert e["count"] == 3 and e["by_action"] == {"notify_emergency_contact": 1, "recommend_911": 1, "volunteer_visit": 1}, e
    assert e["by_decision"] == {"approved": 1, "declined": 1, "policy": 1} and e["members_escalated"] == 2
    earl = next(x for x in e["items"] if x["member_id"] == "mem_earl")
    assert earl["decision_minutes"] == 2.0 and "Pastor Ray" in earl["outcome"]
    rosa911 = next(x for x in e["items"] if x["action"] == "recommend_911")
    assert rosa911["decision"] == "declined" and rosa911["outcome"] == "declined by coordinator"
    # volunteers and gaps
    v = m["volunteers"]
    assert v["assignments"] == 3 and v["by_task"] == {"phone_call": 2, "wellness_visit": 1} and v["volunteers_used"] == 2
    assert v["by_volunteer"] == {"Marisol Alvarez": 2, "Priya Natarajan (RN)": 1}
    assert m["gaps"] == ["Guadalupe needs a ride; no driver free"]
    assert m["unresolved"]["no_reply"] == ["Helen Park"] and m["unresolved"]["failed_delivery"] == ["Pete Kowalski"]
    # per-member table
    rows = {r["member_id"]: r for r in m["per_member"]}
    assert rows["mem_rosa"]["tier"] == 1 and rows["mem_rosa"]["reply_minutes"] == 10.0 and rows["mem_rosa"]["escalation"] == "notify_emergency_contact"
    assert rows["mem_earl"]["replied_at"] is None and rows["mem_earl"]["escalation"] == "volunteer_visit"
    assert rows["mem_walter"]["name"] == "Walter Boyd" and rows["mem_walter"]["channel"] == "voice"
    assert "mem_danny" not in rows  # tier 0: no action planned
    assert [r["member_id"] for r in m["per_member"]][:3] == ["mem_earl", "mem_rosa", "mem_walter"]  # tier 1 first, then by name
    assert m["roster"]["planned_by_tier"] == {"tier_0": 1, "tier_1": 3, "tier_2": 2, "tier_3": 1}
    assert m["brief"] == "Five neighbors contacted."
    json.dumps(m)  # must be JSON-serialisable for the API


def test_partial_episodes():
    from app.models import HazardEvent

    fresh = Episode(hazard=HazardEvent(source="manual", event_name="Air Quality Alert", hazard_type="air_quality"))
    m = compute_metrics(fresh, [], [], MEMBERS, VOLUNTEERS)
    assert m["outreach"]["contacted"] == 0 and m["outreach"]["response_rate_pct"] is None
    assert m["timing"]["minutes_detection_to_first_message"] is None and m["timing"]["median_minutes_to_reply"] is None
    assert m["escalations"]["count"] == 0 and m["volunteers"]["assignments"] == 0 and m["per_member"] == [] and m["gaps"] == []
    down = Episode(hazard=fixture_hazard(), status="stood_down")
    down.assessment = HazardAssessment(activate=False, hazard_type="heat", severity_score=1, plain_summary="Mild.", elevated_risk_factors=[], recommended_actions=[], reasoning="r")
    m2 = compute_metrics(down, [], [], [], [])
    assert m2["activated"] is False and m2["status"] == "stood_down" and m2["roster"]["members_total"] == 0
    # bad timestamps never raise
    odd = Checkin(token="x", episode_id=fresh.id, member_id="mem_rosa", sent_at="not a date", responded_at="", channel="sms")
    m3 = compute_metrics(fresh, [odd], [Approval(episode_id=fresh.id, kind="escalation", title="t", summary="", payload={})], MEMBERS, VOLUNTEERS)
    assert m3["outreach"]["contacted"] == 1 and m3["per_member"][0]["reply_minutes"] is None and m3["escalations"]["count"] == 1
    assert m3["escalations"]["items"][0]["decision"] == "pending" and m3["approvals"]["pending"] == 1


def test_report_route():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.store import store

    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    ep, cks, aprs = build_episode()
    store.put_episode(ep)
    for c in cks:
        store.put_checkin(c)
    for a in aprs:
        store.put_approval(a)
    client = TestClient(app)  # no `with`: startup (scheduler, seeding) must not run in tests
    r = client.get(f"/api/episodes/{ep.id}/report")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative"] is None and body["narrative_reason"] == "not_generated"
    assert body["hazard"]["event_name"] == ep.hazard.event_name and body["episode"]["community"]
    assert body["metrics"]["outreach"]["contacted"] == 5 and body["metrics"]["outreach"]["response_rate_pct"] == 60.0
    assert body["metrics"]["timing"]["minutes_detection_to_first_message"] == 15.0
    assert len(body["metrics"]["per_member"]) == 6
    assert client.get("/api/episodes/ep_nope/report").status_code == 404

    # Narrative endpoint degrades cleanly when no model can be built (never calls a model here).
    from app.agents import report_agent

    orig = report_agent.build_model
    report_agent.build_model = lambda: (_ for _ in ()).throw(RuntimeError("no provider in tests"))
    try:
        r2 = client.post(f"/api/episodes/{ep.id}/report/narrative")
    finally:
        report_agent.build_model = orig
    assert r2.status_code == 200, r2.text
    assert r2.json()["narrative"] is None and r2.json()["narrative_reason"].startswith("narrative_unavailable")
    assert store.episode(ep.id).stats["report"]["reason"].startswith("narrative_unavailable")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL REPORT TESTS PASSED")
