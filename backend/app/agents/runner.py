"""Runs the Strands graph for an episode, streams its events to the dashboard, and handles approvals.

An interrupted graph (waiting on a coordinator decision) is kept in memory and, thanks to the graph's session
manager, can also be rebuilt and resumed after a process restart.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

from strands.multiagent.base import Status

from ..config import settings
from ..events import bus
from ..models import Approval, Episode, HazardAssessment, HazardEvent, TimelineEntry, now_iso
from ..store import store
from .context import current_episode_id
from .hooks import APPROVAL_INTERRUPT
from .model_factory import build_model
from .pipeline import build_followup_agent, build_graph, graph_task

log = logging.getLogger("porchlight.runner")


class EpisodeRunner:
    def __init__(self) -> None:
        self._graphs: dict[str, Any] = {}
        self._followups: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ model
    def model(self) -> Any:
        if self._model is None:
            self._model = build_model()
        return self._model

    def busy(self, ep_id: str) -> bool:
        t = self._tasks.get(ep_id)
        return bool(t and not t.done())

    # ------------------------------------------------------------ start
    async def start(self, hazard: HazardEvent) -> Episode:
        store.put_hazard(hazard)
        ep = Episode(hazard=hazard, session_id=f"graph-{hazard.id}")
        ep.timeline.append(TimelineEntry(kind="detected", text=f"{hazard.event_name} detected via {hazard.source}", data={"headline": hazard.headline}))
        store.put_episode(ep)
        bus.emit("status", f"Episode opened for {hazard.event_name}", episode_id=ep.id, agent="sentinel", status=ep.status)
        self._tasks[ep.id] = asyncio.create_task(self._run_graph(ep.id, graph_task(ep)))
        return ep

    # ------------------------------------------------------------ graph execution
    async def _run_graph(self, ep_id: str, task_input: Any) -> None:
        token = current_episode_id.set(ep_id)
        try:
            ep = store.episode(ep_id)
            if ep is None:
                return
            graph = self._graphs.get(ep_id)
            if graph is None:
                graph = build_graph(ep, self.model())
                self._graphs[ep_id] = graph
            final: Any = None
            async for ev in graph.stream_async(task_input, invocation_state={"episode_id": ep_id}):
                final = self._handle_graph_event(ep_id, ev) or final
            await self._finish_graph(ep_id, final)
        except Exception as e:  # noqa: BLE001
            log.error("graph failed for %s: %s\n%s", ep_id, e, traceback.format_exc())
            ep = store.episode(ep_id)
            if ep:
                ep.status = "failed"
                ep.timeline.append(TimelineEntry(kind="error", text=f"Agent run failed: {e}"))
                store.put_episode(ep)
            bus.emit("error", f"Agent run failed: {e}", episode_id=ep_id)
        finally:
            current_episode_id.reset(token)

    def _handle_graph_event(self, ep_id: str, ev: dict[str, Any]) -> Any:
        t = ev.get("type")
        if t == "multiagent_node_start":
            bus.emit("node_start", f"{ev.get('node_id')} started", episode_id=ep_id, agent=ev.get("node_id", ""))
            ep = store.episode(ep_id)
            if ep and ev.get("node_id") == "assess":
                ep.status = "assessing"
                store.put_episode(ep)
        elif t == "multiagent_node_stream":
            inner = ev.get("event", {})
            if "data" in inner and inner["data"]:
                bus.emit("delta", inner["data"], episode_id=ep_id, agent=ev.get("node_id", ""))
        elif t == "multiagent_node_stop":
            node_id = ev.get("node_id", "")
            nr = ev.get("node_result")
            self._persist_node_result(ep_id, node_id, nr)
            secs = getattr(nr, "execution_time", 0)
            secs = round(secs / 1000, 1) if isinstance(secs, (int, float)) and secs > 1000 else secs
            bus.emit("node_stop", f"{node_id} finished ({secs}s)", episode_id=ep_id, agent=node_id, status=str(getattr(nr, 'status', '')))
        elif t == "multiagent_node_interrupt":
            for itp in ev.get("interrupts", []) or []:
                bus.emit("interrupt", f"{ev.get('node_id')} is waiting for the coordinator", episode_id=ep_id, agent=ev.get("node_id", ""), interrupt_id=getattr(itp, "id", ""))
        elif t == "multiagent_result":
            return ev.get("result")
        elif "result" in ev and t is None:
            return ev.get("result")
        return None

    def _persist_node_result(self, ep_id: str, node_id: str, nr: Any) -> None:
        ep = store.episode(ep_id)
        if ep is None or nr is None:
            return
        res = getattr(nr, "result", None)
        so = getattr(res, "structured_output", None)
        if node_id == "assess" and isinstance(so, HazardAssessment):
            ep.assessment = so
            ep.status = "triaging" if so.activate else "stood_down"
            ep.timeline.append(TimelineEntry(kind="assessment", text=("ACTIVATE: " if so.activate else "Stand down: ") + so.plain_summary, data=so.model_dump()))
            bus.emit("assessment", so.plain_summary, episode_id=ep_id, agent="sentinel", activate=so.activate, severity=so.severity_score)
        elif node_id == "assess":
            # structured output missing: try to parse the text as a last resort
            text = str(getattr(res, "message", "") or res)
            ep.timeline.append(TimelineEntry(kind="assessment", text=text[:500]))
        store.put_episode(ep)

    async def _finish_graph(self, ep_id: str, result: Any) -> None:
        ep = store.episode(ep_id)
        if ep is None:
            return
        status = getattr(result, "status", None)
        if status == Status.INTERRUPTED:
            self._register_approvals(ep, getattr(result, "interrupts", []) or [], scope="graph")
            ep.status = "awaiting_approval"
            store.put_episode(ep)
            bus.emit("status", "Waiting for coordinator approval", episode_id=ep.id, status=ep.status)
            return
        if status == Status.FAILED:
            ep.status = "failed"
            store.put_episode(ep)
            bus.emit("error", "Graph reported failure", episode_id=ep.id)
            return
        # completed
        if ep.assessment and not ep.assessment.activate:
            ep.status = "stood_down"
        elif ep.outreach:
            ep.status = "monitoring"
        else:
            ep.status = "closed"
        store.put_episode(ep)
        self._graphs.pop(ep_id, None)
        bus.emit("status", f"Pipeline complete: {ep.status}", episode_id=ep.id, status=ep.status)

    def _register_approvals(self, ep: Episode, interrupts: list[Any], scope: str) -> None:
        for itp in interrupts:
            if getattr(itp, "name", "") != APPROVAL_INTERRUPT:
                continue
            reason = getattr(itp, "reason", {}) or {}
            existing = [a for a in store.approvals(ep.id) if a.interrupt_id == itp.id]
            if existing:
                continue
            a = Approval(
                episode_id=ep.id,
                kind=reason.get("kind", "action"),
                title=reason.get("title", "Approval needed"),
                summary=reason.get("summary", ""),
                payload={"tool": reason.get("tool"), "input": reason.get("payload", {})},
                interrupt_id=itp.id,
                agent_name=reason.get("agent", ""),
                scope=scope,
            )
            store.put_approval(a)
            ep.timeline.append(TimelineEntry(kind="approval_requested", text=a.title, data={"approval_id": a.id}))
            store.put_episode(ep)
            bus.emit("approval", a.title, episode_id=ep.id, agent=a.agent_name, approval_id=a.id, kind=a.kind)

    # ------------------------------------------------------------ decisions
    async def decide(self, approval_id: str, decision: str, note: str = "", edits: dict[str, Any] | None = None) -> Approval:
        a = store.approval(approval_id)
        if a is None:
            raise KeyError(approval_id)
        if a.status != "pending":
            return a
        ep = store.episode(a.episode_id)
        if ep is None:
            raise KeyError(a.episode_id)
        a.status = "approved" if decision.lower().startswith("appr") else "rejected"
        a.resolved_at = now_iso()
        a.decision_note = note
        store.put_approval(a)
        ep.timeline.append(TimelineEntry(kind="approval_" + a.status, text=f"{a.title}: {a.status}" + (f" — {note}" if note else "")))
        store.put_episode(ep)
        response = {"decision": "approve" if a.status == "approved" else "reject", "note": note, "edits": edits or {}}
        responses = [{"interruptResponse": {"interruptId": a.interrupt_id, "response": response}}]

        # Resume only when every pending approval for this runnable has a decision.
        pending = [p for p in store.approvals(ep.id, status="pending") if p.scope == a.scope]
        if pending:
            return a
        siblings = [p for p in store.approvals(ep.id) if p.scope == a.scope and p.resolved_at and p.status != "pending"]
        # include decisions for sibling interrupts raised in the same pause (same batch)
        batch = [p for p in siblings if p.created_at == a.created_at and p.id != a.id]
        for p in batch:
            responses.append({"interruptResponse": {"interruptId": p.interrupt_id, "response": {"decision": "approve" if p.status == "approved" else "reject", "note": p.decision_note, "edits": {}}}})

        if a.scope == "graph":
            ep.status = "dispatching"
            store.put_episode(ep)
            self._tasks[ep.id] = asyncio.create_task(self._run_graph(ep.id, responses))
        else:
            self._tasks[ep.id + ":followup"] = asyncio.create_task(self._run_followup(ep.id, responses))
        return a

    # ------------------------------------------------------------ follow-up agent
    async def run_followup(self, ep_id: str) -> None:
        if self.busy(ep_id) or self.busy(ep_id + ":followup"):
            return
        if store.approvals(ep_id, status="pending"):
            return
        self._tasks[ep_id + ":followup"] = asyncio.create_task(self._run_followup(ep_id, "Run the follow-up check now."))

    async def _run_followup(self, ep_id: str, task_input: Any) -> None:
        token = current_episode_id.set(ep_id)
        try:
            ep = store.episode(ep_id)
            if ep is None:
                return
            agent = self._followups.get(ep_id)
            if agent is None:
                agent = build_followup_agent(ep, self.model())
                self._followups[ep_id] = agent
            bus.emit("node_start", "follow-up started", episode_id=ep_id, agent="followup")
            result = await agent.invoke_async(task_input, invocation_state={"episode_id": ep_id})
            if result.stop_reason == "interrupt":
                self._register_approvals(ep, result.interrupts, scope="followup")
                bus.emit("status", "Follow-up is waiting for coordinator approval", episode_id=ep_id, agent="followup")
                return
            text = str(result)
            ep = store.episode(ep_id) or ep
            ep.timeline.append(TimelineEntry(kind="followup", text=text[:800]))
            if ep.status == "escalating":
                pass
            store.put_episode(ep)
            bus.emit("node_stop", "follow-up finished", episode_id=ep_id, agent="followup")
        except Exception as e:  # noqa: BLE001
            log.error("follow-up failed for %s: %s\n%s", ep_id, e, traceback.format_exc())
            bus.emit("error", f"Follow-up failed: {e}", episode_id=ep_id, agent="followup")
        finally:
            current_episode_id.reset(token)


runner = EpisodeRunner()
