"""Strands hooks: a full audit trail of every model call and tool call, and the human approval gate.

The approval gate is the product's core promise: the agents work in the background, but no message leaves the
system and no volunteer is dispatched until a human coordinator approves (or policy pre-authorises it).
It is implemented with Strands interrupts raised from a BeforeToolCallEvent hook, so it applies uniformly to
every agent in the graph and survives process restarts through session persistence.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)

from ..config import settings
from ..events import bus
from ..models import TimelineEntry
from ..store import store
from .context import episode_id_from
from .tools import GATED_TOOLS

log = logging.getLogger("porchlight.hooks")

APPROVAL_INTERRUPT = "porchlight-approval"
# structured_output_model is implemented by Strands as a synthetic tool call; keep it out of the audit feed
STRUCTURED_OUTPUT_NAMES = {"HazardAssessment"}


def _short(obj: Any, n: int = 600) -> str:
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s if len(s) <= n else s[:n] + "…"


def _agent_name(agent: Any) -> str:
    return getattr(agent, "name", None) or "agent"


class AuditHook(HookProvider):
    """Streams reasoning/tool telemetry to the dashboard and writes tool calls to the episode timeline."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)
        registry.add_callback(MessageAddedEvent, self.message_added)

    def before_model(self, event: BeforeModelCallEvent) -> None:
        bus.emit("reasoning", "thinking…", episode_id=episode_id_from(event.invocation_state), agent=_agent_name(event.agent))

    def after_model(self, event: AfterModelCallEvent) -> None:
        if event.exception:
            bus.emit("error", f"model call failed: {event.exception}", episode_id=episode_id_from(event.invocation_state), agent=_agent_name(event.agent))

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "?")
        if name in STRUCTURED_OUTPUT_NAMES:
            return
        ep_id = episode_id_from(event.invocation_state)
        bus.emit("tool_call", f"calling {name}", episode_id=ep_id, agent=_agent_name(event.agent), tool=name, input=event.tool_use.get("input", {}))

    def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get("name", "?")
        if name in STRUCTURED_OUTPUT_NAMES:
            return
        ep_id = episode_id_from(event.invocation_state)
        result = event.result or {}
        content = result.get("content", []) if isinstance(result, dict) else []
        text = " ".join(str(c.get("text") or c.get("json") or "") for c in content if isinstance(c, dict))
        status = result.get("status", "success") if isinstance(result, dict) else "success"
        bus.emit("tool_result", _short(text, 400), episode_id=ep_id, agent=_agent_name(event.agent), tool=name, status=status)
        if ep_id:
            entry = TimelineEntry(kind="tool", text=f"{_agent_name(event.agent)} used {name}", data={"status": status, "input": _short(event.tool_use.get('input', {}), 300)})
            store.mutate_episode(ep_id, lambda e: e.timeline.append(entry))

    def message_added(self, event: MessageAddedEvent) -> None:
        msg = event.message
        if msg.get("role") != "assistant":
            return
        texts = [c["text"] for c in msg.get("content", []) if isinstance(c, dict) and c.get("text")]
        if texts:
            bus.emit("text", " ".join(texts).strip()[:1200], agent=_agent_name(event.agent))


def _describe(name: str, inp: dict[str, Any]) -> tuple[str, str, str]:
    """(kind, title, summary) for the approval card."""
    if name == "dispatch_outreach":
        msgs = inp.get("messages", []) or []
        names = []
        for m in msgs:
            mid = m.get("member_id") if isinstance(m, dict) else getattr(m, "member_id", "")
            mem = store.member(mid)
            names.append(mem.name if mem else mid)
        return ("outreach_dispatch", f"Send check-in messages to {len(msgs)} neighbor{'s' if len(msgs) != 1 else ''}",
                inp.get("coordinator_note", "") or ", ".join(names))
    if name == "assign_volunteers":
        asg = inp.get("assignments", []) or []
        return ("volunteer_dispatch", f"Dispatch {len(asg)} volunteer assignment{'s' if len(asg) != 1 else ''}",
                "; ".join(f"{a.get('task', '?').replace('_', ' ')} for {(store.member(a.get('member_id', '')) or type('x', (), {'name': a.get('member_id')})).name}" for a in asg if isinstance(a, dict)))
    if name == "escalate_member":
        mem = store.member(inp.get("member_id", ""))
        who = mem.name if mem else inp.get("member_id")
        return ("escalation", f"Escalate {who}: {str(inp.get('action', '')).replace('_', ' ')}", inp.get("reason", ""))
    return ("action", name, _short(inp, 200))


class ApprovalGateHook(HookProvider):
    """Pause before any world-changing tool call and wait for the coordinator's decision."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.gate)

    def gate(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        if name not in GATED_TOOLS:
            return
        inp: dict[str, Any] = event.tool_use.get("input", {}) or {}
        ep_id = episode_id_from(event.invocation_state)

        # Policy: the coordinator can pre-authorise volunteer visits for non-responders.
        auto = store.get_setting("auto_approve_escalations", settings.AUTO_APPROVE_ESCALATIONS)
        if name == "escalate_member" and auto and inp.get("action") == "volunteer_visit":
            bus.emit("policy", f"Volunteer visit auto-approved by standing policy for {inp.get('member_id')}", episode_id=ep_id, agent=_agent_name(event.agent))
            return

        kind, title, summary = _describe(name, inp)
        reason = {"kind": kind, "title": title, "summary": summary, "tool": name, "payload": inp,
                  "episode_id": ep_id, "agent": _agent_name(event.agent)}
        response = event.interrupt(APPROVAL_INTERRUPT, reason=reason)

        # --- resumed with the coordinator's decision ---
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except Exception:  # noqa: BLE001
                response = {"decision": response}
        response = response or {}
        decision = str(response.get("decision", "reject")).lower()
        note = response.get("note", "")
        if decision not in ("approve", "approved", "yes", "y"):
            event.cancel_tool = f"The coordinator declined this action{': ' + note if note else ''}. Do not retry it; explain what you would have done and finish."
            bus.emit("decision", f"Coordinator declined {title}", episode_id=ep_id, agent=_agent_name(event.agent), note=note)
            return
        edits = response.get("edits") or {}
        if isinstance(edits, dict) and edits:
            inp.update(edits)
            event.tool_use["input"] = inp
        bus.emit("decision", f"Coordinator approved {title}", episode_id=ep_id, agent=_agent_name(event.agent), note=note, edited=bool(edits))
