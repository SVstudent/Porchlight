"""A Strands Model that emits a fixed sequence of tool calls instead of asking a language model.

This exists so the mechanics of the pipeline — the approval gate raising an interrupt, the graph
reporting INTERRUPTED, the coordinator's decision being handed back, the run resuming and finishing —
can be exercised in seconds and asserted on. It is a test double: it is imported only by tests, never
by app code, and it never runs in the product.

It is not a stand-in for the agents' judgement. Every plan it emits is hard-coded, which is exactly
why it is useless for anything except proving that the plumbing around the agents works.
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, AsyncIterable

from strands.models.model import Model

from app.models import HazardAssessment


# Every tool the app registers on a node. Anything else in a node's tool list was put there by the SDK.
APP_TOOLS = {
    "get_area_conditions", "get_episode_context", "get_community_history", "get_roster",
    "get_member_conditions", "get_electricity_dependent_members", "get_neighbor_history",
    "submit_triage_plan", "find_nearby_cooled_places", "dispatch_outreach", "list_volunteers",
    "list_community_resources", "assign_volunteers", "get_checkin_status", "record_coordinator_brief",
}

ASSESSMENT = {
    "activate": True,
    "hazard_type": "heat",
    "severity_score": 5,
    "plain_summary": "It will be dangerously hot today and tonight. People without working cooling are at "
                     "real risk of heat illness.",
    "elevated_risk_factors": ["age_75_plus", "powered_medical_device", "no_air_conditioning", "lives_alone"],
    "recommended_actions": ["Drink water before you are thirsty",
                            "Spend the afternoon somewhere cooled",
                            "Check on a neighbour"],
    "reasoning": "Scripted test double: a fixed assessment, so the graph mechanics can be exercised.",
}


def _tool_use(name: str, args: dict[str, Any], use_id: str) -> list[dict[str, Any]]:
    """The Bedrock-shaped event sequence for one tool call."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": use_id, "name": name}}, "contentBlockIndex": 0}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}, "contentBlockIndex": 0}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                      "metrics": {"latencyMs": 0}}},
    ]


def _text(body: str) -> list[dict[str, Any]]:
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": body}, "contentBlockIndex": 0}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                      "metrics": {"latencyMs": 0}}},
    ]


class ScriptedModel(Model):
    """Picks its reply from which node is calling, identified by that node's own submit tool."""

    def __init__(self, member_ids: list[str], volunteer_id: str, resource_id: str) -> None:
        self.members = member_ids
        self.volunteer = volunteer_id
        self.resource = resource_id
        self.calls: list[str] = []  # node names, in the order they asked for a completion
        self._n = 0

    # -- Model interface ------------------------------------------------------------------
    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> Any:
        return {"model_id": "scripted-test-double"}

    async def structured_output(
        self, output_model: type, prompt: Any = None, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Required by the interface. Agents configured with structured_output_model do not call this —
        the SDK registers a tool for the output model and forces a normal tool call through stream()."""
        yield {"output": output_model(**ASSESSMENT) if output_model is HazardAssessment else output_model()}

    async def stream(self, messages: Any, tool_specs: list[dict[str, Any]] | None = None,
                     system_prompt: str | None = None, **kwargs: Any) -> AsyncIterable[dict[str, Any]]:
        names = {t["name"] for t in (tool_specs or [])}
        self._n += 1
        use_id = f"tooluse_scripted_{self._n}"

        # An agent given structured_output_model gets a tool named after that model registered for it.
        # It is the only tool offered that the app did not write, which is how we recognise it.
        injected = names - APP_TOOLS
        if injected and (not self._done("assess") or names == injected):
            if not self._done("assess"):
                self.calls.append("assess")
            for ev in _tool_use(sorted(injected)[0], ASSESSMENT, use_id):
                yield ev
            return

        if "submit_triage_plan" in names and not self._done("triage"):
            self.calls.append("triage")
            for ev in _tool_use("submit_triage_plan", {
                "decisions": [
                    {"member_id": m, "tier": 1 if i < 3 else 2,
                     "reason": "Scripted test double.", "channel": "sms", "needs_visit": i == 0}
                    for i, m in enumerate(self.members)
                ],
                "summary": "Scripted test double: every neighbour triaged so the graph can continue.",
            }, use_id):
                yield ev
            return

        if "dispatch_outreach" in names and not self._done("outreach"):
            self.calls.append("outreach")
            for ev in _tool_use("dispatch_outreach", {
                "messages": [
                    {"member_id": m, "channel": "sms", "language": "en",
                     "body": "It will be dangerously hot today. Are you doing OK? {checkin_link}"}
                    for m in self.members
                ],
                "coordinator_note": "Scripted test double: contacting the whole roster.",
            }, use_id):
                yield ev
            return

        if "assign_volunteers" in names and not self._done("logistics"):
            self.calls.append("logistics")
            for ev in _tool_use("assign_volunteers", {
                "assignments": [{"volunteer_id": self.volunteer, "member_id": self.members[0],
                                 "task": "wellness_visit", "reason": "Scripted test double.", "priority": 1}],
                "recommended_resource_ids": [self.resource],
                "gaps": [],
            }, use_id):
                yield ev
            return

        if "record_coordinator_brief" in names and not self._done("brief"):
            self.calls.append("brief")
            for ev in _tool_use("record_coordinator_brief", {
                "brief": "Scripted test double.\nEveryone on the roster was contacted.\nOne wellness visit assigned.",
            }, use_id):
                yield ev
            return

        for ev in _text("Done."):
            yield ev

    def _done(self, node: str) -> bool:
        """Each node submits once; after that it should wrap up rather than loop."""
        return node in self.calls
