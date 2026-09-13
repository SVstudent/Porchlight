"""Neighbor memory without a model or AWS. Run: python -m tests.test_memory"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-memory-")
os.environ["SEND_MODE"] = "console"
os.environ.pop("AGENTCORE_MEMORY_ID", None)  # local history only in tests

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import agentcore_memory  # noqa: E402
from app.agents.tools import dispatch_outreach_impl, escalate_member_impl  # noqa: E402
from app.agents.tools_memory import (  # noqa: E402
    community_history,
    compact_history,
    get_community_history,
    get_neighbor_history,
    neighbor_history,
    sync_to_agentcore,
)
from app.main import app  # noqa: E402
from app.models import Episode, HazardEvent, TriageDecision, TriagePlan  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)


def past_episode(event_name: str, hazard_type: str, created_at: str, decisions: list[dict]) -> Episode:
    ep = Episode(hazard=HazardEvent(source="replay", event_name=event_name, hazard_type=hazard_type), created_at=created_at,
                 triage=TriagePlan(decisions=[TriageDecision(**d) for d in decisions], summary="test"), status="monitoring")
    store.put_episode(ep)
    return ep


def reply(ep: Episode, member_id: str, status: str, minutes: int, sent_at: str, note: str = "") -> None:
    c = next(c for c in store.checkins(ep.id) if c.member_id == member_id)
    c.status = status  # type: ignore[assignment]
    c.responded_at = sent_at[:14] + f"{int(sent_at[14:16]) + minutes:02d}" + sent_at[16:]
    c.note = note
    store.put_checkin(c)


def setup() -> tuple[Episode, Episode]:
    store.reset_runtime()
    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    tiers = [
        {"member_id": "mem_rosa", "tier": 1, "reason": "no AC, lives alone", "channel": "sms", "needs_visit": False},
        {"member_id": "mem_walter", "tier": 1, "reason": "oxygen concentrator", "channel": "sms", "needs_visit": False},
        {"member_id": "mem_earl", "tier": 1, "reason": "dementia, lives alone", "channel": "sms", "needs_visit": True},
    ]
    eps = []
    for name, created, sent in (("Excessive Heat Warning", "2025-07-10T18:00:00+00:00", "2025-07-10T18:10:00+00:00"),
                                ("Extreme Heat Warning", "2025-08-02T18:00:00+00:00", "2025-08-02T18:10:00+00:00")):
        ep = past_episode(name, "heat", created, tiers)
        dispatch_outreach_impl(ep.id, [{"member_id": m, "channel": "sms", "language": "en", "body": "Check in {checkin_link}"} for m in ("mem_rosa", "mem_walter", "mem_earl")], "n")
        for c in store.checkins(ep.id):  # pin send times so minutes-to-reply is deterministic
            c.sent_at = sent
            store.put_checkin(c)
        eps.append(ep)
    ep1, ep2 = eps
    # Walter replies OK both times (5 min, then 7 min). Rosa never replies; her emergency contact is notified both times.
    reply(ep1, "mem_walter", "ok", 5, "2025-07-10T18:10:00+00:00")
    reply(ep2, "mem_walter", "ok", 7, "2025-08-02T18:10:00+00:00")
    escalate_member_impl(ep1.id, "mem_rosa", "notify_emergency_contact", "No reply after 25 minutes.")
    escalate_member_impl(ep2.id, "mem_rosa", "notify_emergency_contact", "Still no reply.")
    # Earl needed a visit both times; the visiting volunteer is Danny Tran, who is also a roster member.
    escalate_member_impl(ep2.id, "mem_earl", "volunteer_visit", "No reply and it is 112 F.", "vol_danny")
    return ep1, ep2


def test_member_summaries():
    ep1, ep2 = setup()
    rosa = neighbor_history("mem_rosa")
    rel = rosa["reliability"]
    assert [e["episode_id"] for e in rosa["episodes"]] == [ep2.id, ep1.id], "newest first"
    assert rel["episodes"] == 2 and rel["contacted"] == 2 and rel["replied"] == 0 and rel["reply_rate"] == 0.0
    assert rel["escalations"] == 2 and rel["emergency_contact_notified"] == 2 and rel["median_minutes_to_reply"] is None
    assert rosa["episodes"][0]["outcome"] == "no_reply" and rosa["episodes"][0]["escalations"][0]["action"] == "notify_emergency_contact"
    assert rosa["insight"] == "Rosa has never replied to sms (2 of 2 unanswered). Emergency contact Marisol Alvarez was notified 2 times.", rosa["insight"]

    walter = neighbor_history("mem_walter")
    rel = walter["reliability"]
    assert rel["contacted"] == 2 and rel["replied"] == 2 and rel["reply_rate"] == 1.0 and rel["median_minutes_to_reply"] == 6
    assert [e["minutes_to_reply"] for e in walter["episodes"]] == [7, 5]
    assert walter["insight"] == "Walter replied every time (2 of 2), usually within 6 minutes via sms.", walter["insight"]

    earl = neighbor_history("mem_earl")
    assert earl["reliability"]["visits_needed"] == 2 and earl["reliability"]["escalations"] == 1
    assert "Needed a visit in 2 of 2 past heat events." in earl["insight"], earl["insight"]

    # Danny Tran is named in Earl's escalation detail as the volunteer; he must not inherit it as a member.
    danny = neighbor_history("mem_danny")
    assert danny["episodes"] == [] and danny["insight"] == "No past episodes on record for Danny."

    # Someone with no history at all
    assert neighbor_history("mem_nobody")["error"].startswith("unknown member")


def test_current_episode_excluded_and_compact():
    ep1, ep2 = setup()
    cur = Episode(hazard=HazardEvent(source="manual", event_name="Heat Advisory", hazard_type="heat"))
    store.put_episode(cur)
    dispatch_outreach_impl(cur.id, [{"member_id": "mem_walter", "channel": "sms", "language": "en", "body": "x {checkin_link}"}], "n")
    assert len(neighbor_history("mem_walter")["episodes"]) == 3
    assert len(neighbor_history("mem_walter", exclude_episode_id=cur.id)["episodes"]) == 2
    c = compact_history("mem_walter", exclude_episode_id=cur.id)
    assert c["last"]["outcome"] == "ok" and c["last"]["minutes_to_reply"] == 7 and c["episodes"] == 2
    assert compact_history("mem_rosa", exclude_episode_id=cur.id)["last"]["escalated"] is True
    assert compact_history("mem_danny") is None
    # The Strands tools expose the same data and hide the current episode via invocation_state
    assert get_neighbor_history.tool_name == "get_neighbor_history" and get_community_history.tool_name == "get_community_history"
    spec = get_neighbor_history.tool_spec
    assert "member_ids" in spec["inputSchema"]["json"]["properties"] and "tool_context" not in spec["inputSchema"]["json"]["properties"]
    # One call covers the whole shortlist, and an id with no history is reported rather than dropped.
    fn = getattr(get_neighbor_history, "_tool_func", None) or get_neighbor_history
    class _Ctx:
        invocation_state = {"episode_id": cur.id}
    many = fn(_Ctx(), ["mem_rosa", "mem_walter", "nobody"])
    assert set(many) == {"mem_rosa", "mem_walter", "nobody"}, f"batch lost an id: {sorted(many)}"
    assert "error" in many["nobody"]
    assert many["mem_rosa"].get("name"), "a known neighbour should come back with their history"


def test_lessons_endpoint_and_community_history():
    ep1, ep2 = setup()
    r = client.post(f"/api/episodes/{ep2.id}/lessons", json={"member_id": "mem_rosa", "text": "Rosa never answers texts; her daughter Marisol answered when we called."})
    assert r.status_code == 200 and len(r.json()["lessons"]) == 1, r.text
    assert client.post(f"/api/episodes/{ep2.id}/lessons", json={"text": "   "}).status_code == 400
    assert client.post("/api/episodes/ep_missing/lessons", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/episodes/{ep2.id}/lessons", json={"member_id": "mem_nobody", "text": "x"}).status_code == 404
    r = client.post(f"/api/episodes/{ep1.id}/lessons", json={"text": "Send outreach before 10am next time."})
    assert r.status_code == 200
    assert client.get(f"/api/episodes/{ep2.id}/lessons").json()["lessons"][0]["member_id"] == "mem_rosa"
    cur = store.episode(ep2.id)
    assert cur.timeline[-1].kind == "lesson" and cur.stats["lessons"][0]["text"].startswith("Rosa never")

    # The local history is the source of truth and must stand on its own, whether or not this machine
    # happens to have AgentCore Memory configured. Force it off rather than inheriting backend/.env.
    import app.agents.agentcore_memory as agentcore

    previous_id = agentcore.MEMORY_ID
    agentcore.MEMORY_ID = ""
    try:
        rosa = client.get("/api/roster/mem_rosa/history").json()
    finally:
        agentcore.MEMORY_ID = previous_id
    assert rosa["episodes"][0]["lessons"] == ["Rosa never answers texts; her daughter Marisol answered when we called."]
    assert rosa["insight"].endswith('Coordinator note: "Rosa never answers texts; her daughter Marisol answered when we called."'), rosa["insight"]
    assert rosa["agentcore_memories"] == [] and rosa["agentcore"]["enabled"] is False
    assert client.get("/api/roster/mem_nobody/history").status_code == 404

    tiles = client.get(f"/api/roster/history?exclude={ep2.id}").json()["members"]
    assert tiles["mem_walter"]["last"]["minutes_to_reply"] == 5 and tiles["mem_walter"]["episodes"] == 1
    assert "mem_danny" not in tiles

    ch = community_history()
    assert ch["totals"] == {"episodes": 2, "contacted": 6, "replied": 2, "escalated": 3, "lessons": 2}, ch["totals"]
    newest = ch["episodes"][0]
    assert newest["episode_id"] == ep2.id and newest["contacted"] == 3 and newest["replied"] == 1 and newest["escalated"] == 2
    assert newest["lessons"][0]["member_id"] == "mem_rosa"
    assert community_history(exclude_episode_id=ep2.id)["totals"]["episodes"] == 1
    assert client.get("/api/community/history?limit=1").json()["totals"]["episodes"] == 1


def test_agentcore_is_silent_when_not_configured():
    """Without AGENTCORE_MEMORY_ID the whole integration must be inert, not merely quiet.

    MEMORY_ID is forced empty here rather than read from backend/.env, so this keeps testing the
    not-configured path on a machine where AgentCore Memory is in fact configured.
    """
    ep1, _ = setup()
    previous_id = agentcore_memory.MEMORY_ID
    agentcore_memory.MEMORY_ID = ""
    try:
        assert agentcore_memory.enabled() is False and agentcore_memory.status()["enabled"] is False
        assert agentcore_memory.retrieve_member_memories("mem_rosa", "anything") == []
        assert sync_to_agentcore(ep1.id) == {"skipped": "not configured"}
        assert "agentcore_events" not in store.episode(ep1.id).stats
    finally:
        agentcore_memory.MEMORY_ID = previous_id


def test_agentcore_write_and_retrieve_with_stub_client():
    """Exercise the AgentCore path against a stub that records calls (no AWS). Verifies the create_event shape
    the SDK expects, one-event-per-member idempotency, and how retrieved records are flattened."""
    ep1, _ = setup()

    class Stub:
        def __init__(self):
            self.events = []
        def create_event(self, memory_id, actor_id, session_id, messages, **kw):
            assert memory_id == "mem-test" and all(len(m) == 2 and m[1] in ("USER", "ASSISTANT") for m in messages)
            self.events.append((actor_id, session_id, messages))
            return {"eventId": f"evt{len(self.events)}"}
        def retrieve_memories(self, memory_id, namespace_path, query, top_k, **kw):
            assert namespace_path == "/porchlight/neighbors/mem_rosa/"
            return [{"content": {"text": "Rosa never answers SMS; her daughter Marisol answers."}, "namespaces": [namespace_path], "createdAt": "2025-08-03"}]
        def get_memory_strategies(self, memory_id):
            raise AssertionError("not needed when the configured namespace has results")

    stub = Stub()
    saved = (agentcore_memory.MEMORY_ID, agentcore_memory.REGION, agentcore_memory._client)
    agentcore_memory.MEMORY_ID, agentcore_memory.REGION, agentcore_memory._client = "mem-test", "us-east-1", stub
    try:
        assert agentcore_memory.enabled()
        assert sync_to_agentcore(ep1.id) == {"written": 3}
        assert sorted(a for a, _, _ in stub.events) == ["mem_earl", "mem_rosa", "mem_walter"]
        rosa_msg = next(m for a, _, m in stub.events if a == "mem_rosa")[0][0]
        assert "did not reply to the sms check-in" in rosa_msg and "notify emergency contact" in rosa_msg, rosa_msg
        assert sync_to_agentcore(ep1.id) == {"written": 0}, "second sync must not duplicate events"
        assert set(store.episode(ep1.id).stats["agentcore_events"]) == {"mem_earl", "mem_rosa", "mem_walter"}
        mems = agentcore_memory.retrieve_member_memories("mem_rosa", "reply behaviour")
        assert mems == [{"text": "Rosa never answers SMS; her daughter Marisol answers.", "namespaces": ["/porchlight/neighbors/mem_rosa/"], "created_at": "2025-08-03"}]
        assert client.post(f"/api/episodes/{ep1.id}/lessons", json={"member_id": "mem_rosa", "text": "Call Marisol first."}).status_code == 200
        assert stub.events[-1][0] == "mem_rosa" and "Call Marisol first." in stub.events[-1][2][0][0]
    finally:
        agentcore_memory.MEMORY_ID, agentcore_memory.REGION, agentcore_memory._client = saved


def test_an_outcome_reaches_long_term_memory_without_anyone_asking():
    """The integration is worthless if it is a function nobody calls.

    A neighbour answering, and an episode finishing, both have to push what happened into AgentCore
    Memory on their own — otherwise outcomes sit in the local store and the next hazard's triage learns
    nothing from this one, which was true of every run until this was wired up.
    """
    import app.agents.runner as runner_mod
    from app import reminders

    ep1, _ = setup()
    synced = []

    def fake_sync(episode_id, member_id=""):
        synced.append((episode_id, member_id))
        return {"written": 1}

    import app.agents.tools_memory as tm
    real = tm.sync_to_agentcore
    tm.sync_to_agentcore = fake_sync
    try:
        # a run finishing records the whole episode
        runner_mod.runner._remember(ep1.id)
        assert (ep1.id, "") in synced, f"a finished run must record its outcomes: {synced}"

        # and a neighbour answering records theirs, as soon as they answer
        synced.clear()
        c = next(c for c in store.checkins(ep1.id))
        store.mutate_checkin(c.token, lambda x: (setattr(x, "status", "sent"),
                                                 setattr(x, "responded_at", "")))
        ep = store.episode(ep1.id)
        store.mutate_episode(ep.id, lambda e: setattr(e, "status", "monitoring"))
        reminders.resolve_all_for(c.member_id, "ok", "said: im fine")
        assert any(m == c.member_id for _, m in synced), f"a reply must be remembered: {synced}"
    finally:
        tm.sync_to_agentcore = real


def test_remembering_never_breaks_the_thing_it_is_recording():
    """AgentCore being unreachable must cost the memory, not the response."""
    import app.agents.runner as runner_mod
    import app.agents.tools_memory as tm

    ep1, _ = setup()
    real = tm.sync_to_agentcore
    tm.sync_to_agentcore = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("agentcore down"))
    try:
        runner_mod.runner._remember(ep1.id)   # must not raise
    finally:
        tm.sync_to_agentcore = real


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL MEMORY TESTS PASSED")
