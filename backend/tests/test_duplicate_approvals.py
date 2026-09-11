"""An agent that proposes the same action twice must not ask the coordinator twice.

Seen in a real Bedrock run: the logistics agent called assign_volunteers, then called it again with the
identical plan, and two approval cards appeared for the same four assignments. Approving both would have
dispatched them twice. Run: python -m tests.test_duplicate_approvals
"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-dup-")
os.environ["SENTINEL_ENABLED"] = "false"

from app.agents.hooks import _already_decided, _fingerprint  # noqa: E402
from app.models import Approval, Episode, HazardEvent  # noqa: E402
from app.store import store  # noqa: E402

PLAN = {"assignments": [{"volunteer_id": "vol_marisol", "member_id": "mem_rosa",
                         "task": "wellness_visit", "reason": "Spanish speaker", "priority": 1}],
        "recommended_resource_ids": ["res_paloverde"], "gaps": []}


def episode() -> Episode:
    ep = Episode(hazard=HazardEvent(source="test", hazard_type="heat", event_name="Heat"))
    ep.status = "monitoring"
    store.put_episode(ep)
    return ep


def approve(ep, name, payload, title="Dispatch 1 volunteer assignment"):
    store.put_approval(Approval(
        episode_id=ep.id, kind="volunteer_dispatch", title=title, summary="s",
        payload={**payload, "_fingerprint": _fingerprint(name, payload)},
        status="approved", scope="graph", interrupt_id="int_x",
    ))


def test_the_same_plan_twice_only_asks_once():
    ep = episode()
    assert _already_decided(ep.id, "assign_volunteers", PLAN) is None, "nothing approved yet"
    approve(ep, "assign_volunteers", PLAN)
    assert _already_decided(ep.id, "assign_volunteers", PLAN) == "Dispatch 1 volunteer assignment"


def test_a_different_plan_still_asks():
    """Suppression must be exact: a changed plan is a new decision the coordinator has not made."""
    ep = episode()
    approve(ep, "assign_volunteers", PLAN)
    changed = {**PLAN, "assignments": [{**PLAN["assignments"][0], "member_id": "mem_walter"}]}
    assert _already_decided(ep.id, "assign_volunteers", changed) is None


def test_a_different_tool_with_the_same_arguments_still_asks():
    ep = episode()
    approve(ep, "assign_volunteers", PLAN)
    assert _already_decided(ep.id, "dispatch_outreach", PLAN) is None


def test_a_declined_action_can_be_proposed_again():
    """A refusal is not a decision to suppress; the agent may legitimately come back with the same ask."""
    ep = episode()
    store.put_approval(Approval(
        episode_id=ep.id, kind="volunteer_dispatch", title="Dispatch", summary="s",
        payload={**PLAN, "_fingerprint": _fingerprint("assign_volunteers", PLAN)},
        status="rejected", scope="graph", interrupt_id="int_y",
    ))
    assert _already_decided(ep.id, "assign_volunteers", PLAN) is None


def test_approval_in_another_episode_does_not_suppress():
    a, b = episode(), episode()
    approve(a, "assign_volunteers", PLAN)
    assert _already_decided(b.id, "assign_volunteers", PLAN) is None, "episodes are independent"


def test_argument_order_does_not_matter():
    ep = episode()
    approve(ep, "assign_volunteers", PLAN)
    reordered = {"gaps": [], "recommended_resource_ids": ["res_paloverde"],
                 "assignments": PLAN["assignments"]}
    assert _already_decided(ep.id, "assign_volunteers", reordered) is not None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL DUPLICATE-APPROVAL TESTS PASSED")
