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
from ..models import Approval, Episode, HazardAssessment, HazardEvent, TimelineEntry, new_id, now_iso
from ..store import store
from .context import current_episode_id
from .hooks import APPROVAL_INTERRUPT
from .model_factory import build_model
from .pipeline import build_followup_agent, build_graph, graph_session_id, graph_task

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

    def _reset_session(self, ep_id: str) -> None:
        """Delete the persisted graph session so the next run starts clean."""
        import shutil

        ep = store.episode(ep_id)
        stored = ep.session_id if ep and ep.session_id else ""
        names = {f"session_{stored}", stored} if stored else set()
        names |= {f"session_graph-{ep_id}", f"graph-{ep_id}"}
        for name in names:
            path = settings.SESSION_DIR / name
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def busy(self, ep_id: str) -> bool:
        t = self._tasks.get(ep_id)
        return bool(t and not t.done())

    # ------------------------------------------------------------ start
    async def start(self, hazard: HazardEvent) -> Episode:
        store.put_hazard(hazard)
        ep = Episode(hazard=hazard)
        ep.session_id = graph_session_id(ep)  # the id is generated at construction, so name the session after it
        ep.timeline.append(TimelineEntry(kind="detected", text=f"{hazard.event_name} detected via {hazard.source}", data={"headline": hazard.headline}))
        store.put_episode(ep)
        bus.emit("status", f"Episode opened for {hazard.event_name}", episode_id=ep.id, agent="sentinel", status=ep.status)
        self._tasks[ep.id] = asyncio.create_task(self._run_graph(ep.id, graph_task(ep)))
        return ep

    # ------------------------------------------------------------ graph execution
    def _stored_interrupt_responses(self, ep_id: str) -> list[dict[str, Any]]:
        """The decisions a paused graph is still waiting for, in the shape the SDK expects."""
        decided = [a for a in store.approvals(ep_id)
                   if a.scope == "graph" and a.status != "pending" and a.interrupt_id]
        return [
            {"interruptResponse": {"interruptId": a.interrupt_id, "response": {
                "decision": "approve" if a.status == "approved" else "reject",
                "note": a.decision_note, "edits": a.edits or {}}}}
            for a in decided
        ]

    async def _run_graph(self, ep_id: str, task_input: Any, allow_recovery: bool = False) -> None:
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
            try:
                final = await self._stream(ep_id, graph, task_input)
            except TypeError as e:
                # The saved graph is still paused on an approval, so it will only accept interrupt responses.
                if not allow_recovery or "interrupt" not in str(e).lower():
                    raise
                responses = self._stored_interrupt_responses(ep_id)
                if not responses:
                    raise
                log.info("graph for %s is still paused; resuming with %d stored decision(s)", ep_id, len(responses))
                try:
                    final = await self._stream(ep_id, graph, responses)
                except KeyError as stale:
                    # One of the ids belongs to an interrupt the restored state no longer knows about.
                    log.warning("stale interrupt for %s (%s); starting the graph over", ep_id, stale)
                    bus.emit("status", "Could not resume the paused run; starting it over.", episode_id=ep_id)
                    final = await self._stream(ep_id, self._rebuild_clean(ep_id), task_input)
            except KeyError as e:
                # A stale interrupt id the restored state does not know. Start this episode's graph clean.
                if not allow_recovery:
                    raise
                log.warning("resume mismatch for %s (%s); starting the graph over", ep_id, e)
                bus.emit("status", "Could not resume the paused run; starting it over.", episode_id=ep_id)
                graph = self._rebuild_clean(ep_id)
                final = await self._stream(ep_id, graph, task_input)
            await self._finish_graph(ep_id, final)
        except Exception as e:  # noqa: BLE001
            log.error("graph failed for %s: %s\n%s", ep_id, e, traceback.format_exc())
            reason = str(e)

            def _fail(ep):
                ep.status = "failed"
                ep.timeline.append(TimelineEntry(kind="error", text=f"Agent run failed: {reason}"))

            store.mutate_episode(ep_id, _fail)
            self._graphs.pop(ep_id, None)
            # Let the sentinel find this alert again on the next scan instead of suppressing it forever.
            ep = store.episode(ep_id)
            if ep and ep.hazard.external_id:
                store.unmark_alert_seen(ep.hazard.external_id)
            bus.emit("error", f"Agent run failed: {e}", episode_id=ep_id)
        finally:
            self._tasks.pop(ep_id, None)
            current_episode_id.reset(token)

    async def _stream(self, ep_id: str, graph: Any, task: Any) -> Any:
        """Consume the graph's events, pausing between agents when asked to.

        The pause is for a person watching, not for the system: the agents are fast enough that five of
        them finish inside half a minute, and a recording of that is a wall of text nobody can follow.
        Holding briefly after each agent finishes lets each step be described as it lands. It is zero
        unless a pause has been configured.
        """
        from .pipeline import step_pause_s

        final: Any = None
        pause = step_pause_s()
        async for ev in graph.stream_async(task, invocation_state={"episode_id": ep_id}):
            final = self._handle_graph_event(ep_id, ev) or final
            if pause and ev.get("type") == "multiagent_node_stop":
                bus.emit("status", f"{ev.get('node_id')} finished", episode_id=ep_id,
                         agent=str(ev.get("node_id") or ""))
                await asyncio.sleep(pause)
        return final

    def _rebuild_clean(self, ep_id: str) -> Any:
        """Throw away the persisted session and build a fresh graph for this episode."""
        self._reset_session(ep_id)
        self._graphs.pop(ep_id, None)
        graph = build_graph(store.episode(ep_id), self.model())
        self._graphs[ep_id] = graph
        return graph

    def _handle_graph_event(self, ep_id: str, ev: dict[str, Any]) -> Any:
        t = ev.get("type")
        if t == "multiagent_node_start":
            bus.emit("node_start", f"{ev.get('node_id')} started", episode_id=ep_id, agent=ev.get("node_id", ""))
            if ev.get("node_id") == "assess":
                store.mutate_episode(ep_id, lambda ep: setattr(ep, "status", "assessing"))
        elif t == "multiagent_node_stream":
            pass  # per-token deltas are not published; AuditHook surfaces final assistant text and every tool call
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
        elif t == "multiagent_result" or ("result" in ev and t is None):
            return ev.get("result")
        return None

    def _persist_node_result(self, ep_id: str, node_id: str, nr: Any) -> None:
        if nr is None or node_id != "assess":
            return
        res = getattr(nr, "result", None)
        so = getattr(res, "structured_output", None)
        if isinstance(so, HazardAssessment):
            def _apply(ep):
                ep.assessment = so
                ep.status = "triaging" if so.activate else "stood_down"
                ep.timeline.append(TimelineEntry(kind="assessment", text=("ACTIVATE: " if so.activate else "Stand down: ") + so.plain_summary, data=so.model_dump()))

            store.mutate_episode(ep_id, _apply)
            bus.emit("assessment", so.plain_summary, episode_id=ep_id, agent="sentinel", activate=so.activate, severity=so.severity_score)
        else:
            text = str(getattr(res, "message", "") or res)
            store.mutate_episode(ep_id, lambda ep: ep.timeline.append(TimelineEntry(kind="assessment", text=text[:500])))

    async def _finish_graph(self, ep_id: str, result: Any) -> None:
        ep = store.episode(ep_id)
        if ep is None:
            return
        status = getattr(result, "status", None)
        if status == Status.INTERRUPTED:
            self._register_approvals(ep, getattr(result, "interrupts", []) or [], scope="graph")
            store.mutate_episode(ep_id, lambda e: setattr(e, "status", "awaiting_approval"))
            bus.emit("status", "Waiting for coordinator approval", episode_id=ep.id, status="awaiting_approval")
            return
        if status == Status.FAILED:
            store.mutate_episode(ep_id, lambda e: setattr(e, "status", "failed"))
            bus.emit("error", "Graph reported failure", episode_id=ep.id)
            return

        def _complete(e):
            if e.assessment and not e.assessment.activate:
                e.status = "stood_down"
            elif e.outreach or e.logistics:
                # Anything that reached a real person needs follow-up, even if only volunteers were dispatched.
                e.status = "monitoring"
            else:
                e.status = "closed"

        ep = store.mutate_episode(ep_id, _complete) or ep
        self._graphs.pop(ep_id, None)
        bus.emit("status", f"Pipeline complete: {ep.status}", episode_id=ep.id, status=ep.status)
        self._remember(ep_id)

    def _remember(self, ep_id: str) -> None:
        """Push what happened in this episode into long-term memory.

        Without this the integration is a function nobody calls: outcomes sit in the local store and the
        next hazard's triage learns nothing from this one.
        """
        try:
            from .tools_memory import sync_to_agentcore

            result = sync_to_agentcore(ep_id)
            if result.get("written"):
                log.info("recorded %s outcome(s) in AgentCore Memory for %s", result["written"], ep_id)
        except Exception as e:  # noqa: BLE001 — memory is an enhancement, never a dependency
            log.debug("could not record %s in long-term memory: %s", ep_id, e)

    def _register_approvals(self, ep: Episode, interrupts: list[Any], scope: str) -> None:
        batch_id = new_id("batch")
        for itp in interrupts:
            if getattr(itp, "name", "") != APPROVAL_INTERRUPT:
                continue
            reason = getattr(itp, "reason", {}) or {}
            existing = [a for a in store.approvals(ep.id) if a.interrupt_id == itp.id]
            if existing:
                # A re-raised interrupt belongs to this pause, so move it onto the current batch.
                if existing[0].status == "pending" and existing[0].batch_id != batch_id:
                    existing[0].batch_id = batch_id
                    store.put_approval(existing[0])
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
                batch_id=batch_id,
            )
            store.put_approval(a)
            store.mutate_episode(ep.id, lambda e, a=a: e.timeline.append(TimelineEntry(kind="approval_requested", text=a.title, data={"approval_id": a.id})))
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
        if ep.status in ("closed", "stood_down"):
            a.status = "rejected"
            a.resolved_at = now_iso()
            a.decision_note = "This episode was closed before the decision was made, so nothing was sent."
            store.put_approval(a)
            bus.emit("decision", f"{a.title} was not carried out: the episode is closed.", episode_id=ep.id)
            return a
        a.status = "approved" if decision.lower().startswith("appr") else "rejected"
        a.resolved_at = now_iso()
        a.decision_note = note
        a.edits = edits or {}
        store.put_approval(a)
        store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(kind="approval_" + a.status, text=f"{a.title}: {a.status}" + (f" — {note}" if note else ""))))

        # Resume only when every interrupt raised in the same pause has a decision.
        if a.batch_id:
            batch = [p for p in store.approvals(ep.id) if p.batch_id == a.batch_id]
        else:  # legacy rows without a batch id: everything unresolved in the same scope was raised together
            batch = [p for p in store.approvals(ep.id) if p.scope == a.scope and (p.status == "pending" or p.id == a.id)]
        if any(p.status == "pending" for p in batch):
            bus.emit("status", f"{a.title}: {a.status}. Waiting on {sum(1 for p in batch if p.status == 'pending')} more decision(s) before resuming.", episode_id=ep.id)
            return a
        responses = [
            {"interruptResponse": {"interruptId": p.interrupt_id, "response": {"decision": "approve" if p.status == "approved" else "reject", "note": p.decision_note, "edits": p.edits or {}}}}
            for p in batch
        ]
        if a.scope == "graph":
            store.mutate_episode(ep.id, lambda e: setattr(e, "status", "dispatching"))
            self._tasks[ep.id] = asyncio.create_task(self._run_graph(ep.id, responses))
        else:
            self._tasks[ep.id + ":followup"] = asyncio.create_task(self._run_followup(ep.id, responses))
        return a

    # ------------------------------------------------------------ follow-up agent
    async def retry(self, ep_id: str) -> None:
        """Re-run a failed episode.

        The graph is rebuilt from its persisted session so completed nodes are kept. If the run died while the
        graph was paused on an approval, it must be resumed with interrupt responses rather than a fresh task
        string, or the SDK rejects the input.
        """
        ep = store.episode(ep_id)
        if ep is None or self.busy(ep_id):
            return
        self._graphs.pop(ep_id, None)  # force a rebuild from the session on disk
        self._model = None  # the usual cause is an unreachable provider; re-resolve it

        # A retried run makes fresh model calls, so any interrupt it raises gets a new id. Old pending rows could
        # never be answered and would block follow-up forever.
        for stale in store.approvals(ep_id, status="pending"):
            stale.status = "rejected"
            stale.resolved_at = now_iso()
            stale.decision_note = "Superseded by a retry of the agent run."
            store.put_approval(stale)

        # Start from the ordinary task. If the persisted graph turns out to still be paused on an approval, the
        # SDK rejects a plain string and _run_graph retries with the decisions we already have.
        self._tasks[ep_id] = asyncio.create_task(self._run_graph(ep_id, graph_task(ep), allow_recovery=True))

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
            store.mutate_episode(ep_id, lambda e: e.timeline.append(TimelineEntry(kind="followup", text=text[:800])))
            bus.emit("node_stop", "follow-up finished", episode_id=ep_id, agent="followup")
        except Exception as e:  # noqa: BLE001
            log.error("follow-up failed for %s: %s\n%s", ep_id, e, traceback.format_exc())
            bus.emit("error", f"Follow-up failed: {e}", episode_id=ep_id, agent="followup")
        finally:
            current_episode_id.reset(token)


runner = EpisodeRunner()
