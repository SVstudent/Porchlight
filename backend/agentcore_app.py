"""Amazon Bedrock AgentCore Runtime entrypoint for Porchlight.

Deploy with the AgentCore CLI (npm install -g @aws/agentcore):
    agentcore create   # choose "existing entrypoint" -> backend/agentcore_app.py
    agentcore deploy
    agentcore invoke '{"action": "assess", "hazard": {...}}'

The same Strands graph that powers the local API runs here. The runtime streams graph events back to the
caller; approvals arrive as interrupt payloads and are resumed by invoking again with `interrupt_responses`.
"""
from __future__ import annotations

import json
from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp

from app.agents.context import current_episode_id
from app.agents.pipeline import build_graph, graph_task
from app.agents.sentinel import new_hazards, replay_fixture
from app.models import Episode, HazardEvent
from app.store import store

app = BedrockAgentCoreApp()
_graphs: dict[str, Any] = {}


def _serialisable(ev: dict[str, Any]) -> dict[str, Any] | None:
    t = ev.get("type")
    if t in ("multiagent_node_start", "multiagent_node_stop", "multiagent_node_interrupt", "multiagent_handoff"):
        out = {"type": t, "node_id": ev.get("node_id")}
        if t == "multiagent_node_interrupt":
            out["interrupts"] = [{"id": i.id, "name": i.name, "reason": i.reason} for i in ev.get("interrupts", [])]
        return out
    if t == "multiagent_node_stream":
        inner = ev.get("event", {})
        if inner.get("data"):
            return {"type": "delta", "node_id": ev.get("node_id"), "text": inner["data"]}
        if inner.get("current_tool_use", {}).get("name"):
            return {"type": "tool", "node_id": ev.get("node_id"), "tool": inner["current_tool_use"]["name"]}
    return None


@app.entrypoint
async def invoke(payload: dict[str, Any]):
    """Payload shapes:
    {"action": "scan"}                                   -> detect new hazards for the roster (no LLM)
    {"action": "assess", "hazard": {...HazardEvent}}     -> run the full graph for a hazard
    {"action": "replay", "fixture_id": "..."}            -> run the graph on an archived real alert
    {"action": "resume", "episode_id": "...", "interrupt_responses": [{"interruptId": "...", "response": {"decision": "approve"}}]}
    """
    action = payload.get("action", "assess")
    if action == "scan":
        yield {"type": "hazards", "hazards": [h.model_dump() for h in new_hazards()]}
        return

    if action == "resume":
        ep_id = payload["episode_id"]
        ep = store.episode(ep_id)
        if ep is None:
            yield {"type": "error", "message": f"unknown episode {ep_id}"}
            return
        graph = _graphs.get(ep_id) or build_graph(ep)
        _graphs[ep_id] = graph
        task: Any = [{"interruptResponse": r} for r in payload.get("interrupt_responses", [])]
    else:
        hazard = replay_fixture(payload["fixture_id"]) if action == "replay" else HazardEvent(**payload["hazard"])
        store.put_hazard(hazard)
        ep = Episode(hazard=hazard)
        store.put_episode(ep)
        ep_id = ep.id
        graph = build_graph(ep)
        _graphs[ep_id] = graph
        task = graph_task(ep)
        yield {"type": "episode", "episode_id": ep_id}

    token = current_episode_id.set(ep_id)
    try:
        async for ev in graph.stream_async(task, invocation_state={"episode_id": ep_id}):
            s = _serialisable(ev)
            if s:
                yield s
            if ev.get("type") == "multiagent_result":
                res = ev["result"]
                yield {
                    "type": "result",
                    "status": str(res.status),
                    "interrupts": [{"id": i.id, "name": i.name, "reason": i.reason} for i in (res.interrupts or [])],
                    "episode": json.loads(store.episode(ep_id).model_dump_json()) if store.episode(ep_id) else None,
                }
    finally:
        current_episode_id.reset(token)


if __name__ == "__main__":
    app.run()
