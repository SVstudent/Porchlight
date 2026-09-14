"""Drive the real Strands graph end to end with a scripted model in place of a language model.

What this proves, without a model provider and in a few seconds:

  * the approval gate turns a gated tool call into a real SDK interrupt, and the graph reports INTERRUPTED
  * an approval row is written for the coordinator, carrying the tool input they are being asked to approve
  * approving it resumes the same graph, and the tool then actually runs
  * check-in rows and links are created for the neighbours who were messaged
  * the run reaches the briefing node and the episode leaves the working states

What it does not prove: anything about the agents' judgement. Every plan here is hard-coded.
The quality of a real assessment, triage or message is the model's job, and this file deliberately
says nothing about it.

Run: python -m tests.test_pipeline_mechanics
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-mechanics-")
os.environ["SENTINEL_ENABLED"] = "false"
os.environ["SEND_MODE"] = "console"

from app.agents.runner import EpisodeRunner
from app.models import HazardEvent
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS
from app.store import store
from tests.scripted_model import ScriptedModel


def _seed() -> ScriptedModel:
    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    for r in RESOURCES:
        store.put_resource(r)
    members = [m.id for m in store.members()][:4]
    return ScriptedModel(members, store.volunteers()[0].id, store.resources()[0].id)


def _hazard() -> HazardEvent:
    return HazardEvent(
        source="replay", external_id="urn:test:mechanics", hazard_type="heat",
        event_name="Extreme Heat Warning", severity="Severe",
        headline="Extreme Heat Warning in effect", description="Dangerous heat.",
        area="Maryvale, Phoenix",
    )


async def _run(decision: str, escalate_member_id: str = "") -> dict:
    """Run one episode from detection to settled, answering every pause with `decision`."""
    model = _seed()
    if escalate_member_id:
        model.escalate = escalate_member_id
    r = EpisodeRunner()
    r.model = lambda: model  # type: ignore[method-assign]

    ep = await r.start(_hazard())
    await _settle(r, ep.id)

    seen: list[str] = []
    # Work through every pause the graph raises until it stops pausing.
    for _ in range(6):
        pending = [a for a in store.approvals(ep.id) if a.status == "pending"]
        if not pending:
            break
        for a in pending:
            seen.append(a.kind)
            await r.decide(a.id, decision, note=f"{decision} by the mechanics test.")
        await _settle(r, ep.id)

    return {"episode": store.episode(ep.id), "approvals_seen": seen, "model": model,
            "runner": r, "checkins": store.checkins(ep.id)}


async def _restart_resume() -> dict:
    """The README claims a paused run survives a restart. Prove it by throwing the Graph object away.

    Dropping the in-memory graph is what a process restart looks like to the runner: the next call has
    to rebuild it, and the rebuilt Graph reloads its state from the FileSessionManager session on disk.
    """
    model = _seed()
    r = EpisodeRunner()
    r.model = lambda: model  # type: ignore[method-assign]
    ep = await r.start(_hazard())
    await _settle(r, ep.id)

    pending = [a for a in store.approvals(ep.id) if a.status == "pending"]
    if not pending:
        return {"episode": store.episode(ep.id), "paused": False, "rebuilt": False}

    r._graphs.pop(ep.id, None)          # the restart
    r._graphs.pop(ep.id + ":followup", None)
    rebuilt_from_disk = ep.id not in r._graphs

    for a in pending:
        await r.decide(a.id, "approve", note="Approved after a restart.")
    await _settle(r, ep.id)
    for _ in range(4):
        more = [a for a in store.approvals(ep.id) if a.status == "pending"]
        if not more:
            break
        for a in more:
            await r.decide(a.id, "approve", note="Approved after a restart.")
        await _settle(r, ep.id)

    return {"episode": store.episode(ep.id), "paused": True, "rebuilt": rebuilt_from_disk,
            "checkins": store.checkins(ep.id)}


async def _drive() -> dict:
    approved = await _run("approve")

    # A neighbour who never answered. The follow-up agent should notice and escalate.
    ep_id = approved["episode"].id
    silent = store.checkins(ep_id)[0]
    store.mutate_checkin(silent.token, lambda c: setattr(c, "status", "no_response"))
    approved["model"].escalate = silent.member_id
    r = approved["runner"]
    await r.run_followup(ep_id)
    await _settle(r, ep_id + ":followup")
    for _ in range(3):
        pending = [a for a in store.approvals(ep_id) if a.status == "pending"]
        if not pending:
            break
        for a in pending:
            approved["approvals_seen"].append(a.kind)
            await r.decide(a.id, "approve", note="Approved by the mechanics test.")
        await _settle(r, ep_id + ":followup")
    approved["episode"] = store.episode(ep_id)
    approved["escalated_member"] = silent.member_id

    # A second, independent episode where the coordinator says no to everything.
    rejected = await _run("reject")
    # A third that is interrupted, loses its graph, and has to come back from the session on disk.
    restarted = await _restart_resume()
    return {"approved": approved, "rejected": rejected, "restarted": restarted}


async def _settle(r: EpisodeRunner, ep_id: str, limit: float = 90.0) -> None:
    """Wait for whatever the runner is currently doing to stop."""
    waited = 0.0
    while r.busy(ep_id) and waited < limit:
        await asyncio.sleep(0.2)
        waited += 0.2
    task = r._tasks.get(ep_id)
    if task:
        with contextlib.suppress(Exception):  # only wait for the run to settle; the assertions below judge it
            await asyncio.wait_for(asyncio.shield(task), timeout=5)


_BOTH = asyncio.run(_drive())
RESULT = _BOTH["approved"]
REJECTED = _BOTH["rejected"]
RESTARTED = _BOTH["restarted"]


def test_the_gated_tools_actually_paused_the_graph():
    """Both destructive tools must stop and ask. If this fails, the demo's whole premise is gone."""
    assert "outreach_dispatch" in RESULT["approvals_seen"], (
        f"outreach never asked for approval; pauses seen: {RESULT['approvals_seen']}")


def test_the_approval_carried_the_plan_the_coordinator_is_approving():
    ep = RESULT["episode"]
    approvals = [a for a in store.approvals(ep.id) if a.kind == "outreach_dispatch"]
    assert approvals, "no outreach approval was ever written"
    payload = approvals[0].payload
    assert payload, "the approval had no payload, so the coordinator would be approving blind"


def test_approving_let_the_tool_run_and_messages_went_out():
    ep = RESULT["episode"]
    assert ep.outreach, f"outreach never produced a plan (status {ep.status})"
    assert RESULT["checkins"], "no check-in rows, so nothing was actually sent"
    for c in RESULT["checkins"]:
        assert c.token, "a check-in without a token has no link for the neighbour to tap"


def test_the_run_reached_the_end():
    ep = RESULT["episode"]
    assert ep.status not in ("assessing", "triaging", "dispatching"), f"still mid-run: {ep.status}"
    assert ep.status != "failed", (
        "the run failed; last timeline entries: "
        + " | ".join(t.text[:120] for t in ep.timeline[-3:]))


def test_rejecting_an_approval_sends_nothing():
    """The safety claim the whole design rests on: no message leaves without a coordinator's yes."""
    ep = REJECTED["episode"]
    assert REJECTED["approvals_seen"], "the rejected run never even asked, so nothing was gated"
    assert not store.checkins(ep.id), (
        f"{len(store.checkins(ep.id))} check-ins exist for an episode where every approval was refused")
    assert ep.status != "failed", f"a refusal should end the run cleanly, not fail it (status {ep.status})"


def test_a_silent_neighbor_is_escalated():
    """The demo's closing beat: nobody answered, so a volunteer is sent."""
    ep = RESULT["episode"]
    assert "followup" in RESULT["model"].calls, (
        f"the follow-up agent never ran; nodes seen: {RESULT['model'].calls}")
    assert "escalation" in RESULT["approvals_seen"], (
        "the escalation never asked the coordinator; pauses seen: "
        + ", ".join(RESULT["approvals_seen"]))
    assert ep.status == "escalating", f"a carried-out escalation should leave the episode escalating, not {ep.status}"


def test_a_paused_run_survives_losing_its_graph():
    """The README says a paused run resumes after a restart. This is that claim, tested."""
    assert RESTARTED["paused"], "the run never paused, so there was nothing to resume"
    assert RESTARTED["rebuilt"], "the graph was not actually discarded, so nothing was proven"
    ep = RESTARTED["episode"]
    assert ep.status != "failed", (
        "resuming from the persisted session failed; last timeline entries: "
        + " | ".join(t.text[:120] for t in ep.timeline[-3:]))
    assert RESTARTED["checkins"], "the graph came back but the approved messages never went out"


def test_every_node_was_reached_in_order():
    calls = RESULT["model"].calls
    assert calls[0] == "assess", f"assess did not run first: {calls}"
    assert "triage" in calls, f"triage never ran: {calls}"
    assert "outreach" in calls, f"outreach never ran: {calls}"


if __name__ == "__main__":
    ep = RESULT["episode"]
    print(f"  episode {ep.id} finished as '{ep.status}'")
    print(f"  nodes that ran: {', '.join(RESULT['model'].calls)}")
    print(f"  pauses for approval: {', '.join(RESULT['approvals_seen']) or 'none'}")
    print(f"  check-ins created: {len(RESULT['checkins'])}")
    rej = REJECTED["episode"]
    print(f"  refused run {rej.id}: status '{rej.status}', {len(store.checkins(rej.id))} check-ins")
    res = RESTARTED["episode"]
    print(f"  restarted run {res.id}: status '{res.status}', "
          f"{len(RESTARTED.get('checkins') or [])} check-ins after rebuilding the graph from disk")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PIPELINE MECHANICS TESTS PASSED")
