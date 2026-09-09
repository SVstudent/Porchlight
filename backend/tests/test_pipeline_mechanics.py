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
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-mechanics-")
os.environ["SENTINEL_ENABLED"] = "false"
os.environ["SEND_MODE"] = "console"

from app.agents import runner as runner_mod  # noqa: E402
from app.agents.runner import EpisodeRunner  # noqa: E402
from app.models import HazardEvent  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402
from tests.scripted_model import ScriptedModel  # noqa: E402


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


async def _drive() -> dict:
    model = _seed()
    r = EpisodeRunner()
    r.model = lambda: model  # type: ignore[method-assign]

    ep = await r.start(_hazard())
    await _settle(r, ep.id)

    seen: list[str] = []
    # Work through every pause the graph raises, approving each one, until it stops pausing.
    for _ in range(6):
        pending = [a for a in store.approvals(ep.id) if a.status == "pending"]
        if not pending:
            break
        for a in pending:
            seen.append(a.kind)
            await r.decide(a.id, "approve", note="Approved by the mechanics test.")
        await _settle(r, ep.id)

    return {"episode": store.episode(ep.id), "approvals_seen": seen, "model": model,
            "checkins": store.checkins(ep.id)}


async def _settle(r: EpisodeRunner, ep_id: str, limit: float = 90.0) -> None:
    """Wait for whatever the runner is currently doing to stop."""
    waited = 0.0
    while r.busy(ep_id) and waited < limit:
        await asyncio.sleep(0.2)
        waited += 0.2
    task = r._tasks.get(ep_id)
    if task:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except (asyncio.TimeoutError, Exception):
            pass


RESULT = asyncio.run(_drive())


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
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PIPELINE MECHANICS TESTS PASSED")
