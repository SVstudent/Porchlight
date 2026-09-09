"""Optional long-term neighbor memory in Amazon Bedrock AgentCore Memory.

Enabled only when AGENTCORE_MEMORY_ID and AWS_REGION are set (backend/.env). Every call is wrapped so a missing
SDK, missing credentials, or any AWS error is logged once and otherwise ignored: the deterministic local history
in tools_memory.py always works on its own.

Data model: one AgentCore *actor* per neighbor (actor_id = member id) and one *session* per episode
(session_id = episode id). Each check-in outcome and each coordinator lesson is written with
MemoryClient.create_event; the memory resource's semantic + summary strategies distil those into long-term
records that get_neighbor_history retrieves with MemoryClient.retrieve_memories.

Signatures used (verified in bedrock_agentcore 1.22.0, bedrock_agentcore/memory/client.py):
  MemoryClient(region_name=...)
  .create_event(memory_id, actor_id, session_id, messages=[(text, role), ...], event_timestamp=None, ...)
  .retrieve_memories(memory_id, namespace=None, query=..., top_k=3, namespace_path=None, ...)
  .get_memory_strategies(memory_id) -> [{"strategyId", "namespaces"/"namespaceTemplates", ...}]
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from ..config import settings  # noqa: F401  (loads backend/.env before we read the environment)
from ..models import Episode, Member, now_iso
from ..store import store

log = logging.getLogger("porchlight.agentcore_memory")

MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "").strip()
REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")).strip()
# Namespace template the memory's strategies write to; scripts/create_agentcore_memory.py sets exactly this.
NAMESPACE_TEMPLATE = os.getenv("AGENTCORE_MEMORY_NAMESPACE", "/porchlight/neighbors/{actorId}/").strip()

_client: Any = None
_lock = threading.Lock()
_warned = False
_strategy_paths: list[str] | None = None


def enabled() -> bool:
    return bool(MEMORY_ID and REGION)


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "memory_id": MEMORY_ID[:12] + "…" if len(MEMORY_ID) > 12 else MEMORY_ID, "region": REGION if enabled() else ""}


def _get_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            from bedrock_agentcore.memory import MemoryClient  # imported lazily: optional dependency at runtime
            _client = MemoryClient(region_name=REGION)
        return _client


def _log_failure(what: str, e: Exception) -> None:
    global _warned
    level = logging.WARNING if not _warned else logging.INFO
    log.log(level, "AgentCore Memory %s skipped: %s", what, e)
    _warned = True


def _actor_path(template: str, member_id: str) -> str:
    """'/porchlight/neighbors/{actorId}/episodes/{sessionId}/' -> '/porchlight/neighbors/mem_x/' (prefix path)."""
    p = template.replace("{actorId}", member_id)
    if "{sessionId}" in p:
        p = p.split("{sessionId}")[0]
    return p


def _outcome_sentence(m: Member, rec: dict[str, Any]) -> str:
    first = m.name.split()[0]
    o = rec["outcome"]
    if o == "ok":
        s = f"{first} replied \"I'm OK\"" + (f" after {rec['minutes_to_reply']} minutes" if rec.get("minutes_to_reply") is not None else "")
    elif o == "needs_help":
        s = f"{first} replied \"I need help\"" + (f" after {rec['minutes_to_reply']} minutes" if rec.get("minutes_to_reply") is not None else "")
        if rec.get("note"):
            s += f' and said: "{rec["note"]}"'
    elif o == "no_reply":
        s = f"{first} did not reply to the {rec.get('channel') or 'message'} check-in"
    elif o == "not_reached":
        s = f"{first} could not be reached ({rec.get('note') or 'delivery failed'})"
    else:
        s = f"{first} was not contacted"
    if rec.get("escalations"):
        s += "; escalations: " + ", ".join(f"{e['action'].replace('_', ' ')} ({e['detail']})" if e.get("detail") else e["action"].replace("_", " ") for e in rec["escalations"])
    if rec.get("needs_visit"):
        s += "; an in-person visit was needed"
    return s + "."


def record_member_outcome(ep: Episode, m: Member, rec: dict[str, Any]) -> bool:
    """One event per member per episode. Returns True only when a new event was written."""
    if not enabled():
        return False
    if m.id in (ep.stats.get("agentcore_events") or {}):
        return False
    tier = f"tier {rec['tier']}" if rec.get("tier") is not None else "untriaged"
    observation = (
        f"Porchlight check-in log. During the {rec['hazard_type'].replace('_', ' ')} event \"{rec['event_name']}\" on {rec['date']}, "
        f"neighbor {m.name} (member {m.id}, preferred channel {m.preferred_channel}, emergency contact "
        f"{m.emergency_contact_name or 'none'}) was {tier} and contacted by {rec.get('channel') or 'no channel'}. "
        f"Outcome: {_outcome_sentence(m, rec)}"
    )
    ack = f"Noted for future check-ins with {m.name}: {_outcome_sentence(m, rec)}"
    try:
        _get_client().create_event(memory_id=MEMORY_ID, actor_id=m.id, session_id=ep.id,
                                   messages=[(observation, "USER"), (ack, "ASSISTANT")])
    except Exception as e:  # noqa: BLE001
        _log_failure(f"create_event for {m.id}/{ep.id}", e)
        return False
    store.mutate_episode(ep.id, lambda e: e.stats.setdefault("agentcore_events", {}).__setitem__(m.id, now_iso()))
    log.info("AgentCore Memory: recorded %s outcome for %s in %s", rec["outcome"], m.name, ep.id)
    return True


def record_lesson(ep: Episode, member_id: str, text: str) -> bool:
    """A coordinator lesson becomes an event for that neighbor (or the community actor when no member is given)."""
    if not enabled():
        return False
    m = store.member(member_id) if member_id else None
    actor = m.id if m else "community"
    who = f"about neighbor {m.name} (member {m.id})" if m else "about the community"
    try:
        _get_client().create_event(memory_id=MEMORY_ID, actor_id=actor, session_id=ep.id, messages=[
            (f"Coordinator lesson {who} after the {ep.hazard.hazard_type.replace('_', ' ')} event \"{ep.hazard.event_name}\": {text}", "USER"),
            (f"Noted for next time: {text}", "ASSISTANT"),
        ])
    except Exception as e:  # noqa: BLE001
        _log_failure(f"create_event (lesson) for {actor}", e)
        return False
    return True


def _candidate_paths(member_id: str) -> list[str]:
    """Configured namespace first; if the resource was created elsewhere with default namespaces, derive them
    once from its strategies (/strategies/<id>/actors/<member>/)."""
    global _strategy_paths
    paths = [_actor_path(NAMESPACE_TEMPLATE, member_id)]
    if os.getenv("AGENTCORE_MEMORY_NAMESPACE"):
        return paths
    if _strategy_paths is None:
        try:
            tmpl: list[str] = []
            for s in _get_client().get_memory_strategies(MEMORY_ID):
                sid = s.get("strategyId") or s.get("memoryStrategyId") or ""
                for ns in (s.get("namespaces") or s.get("namespaceTemplates") or []):
                    tmpl.append(str(ns).replace("{memoryStrategyId}", sid))
            _strategy_paths = tmpl
        except Exception as e:  # noqa: BLE001
            _log_failure("get_memory_strategies", e)
            _strategy_paths = []
    for t in _strategy_paths:
        p = _actor_path(t, member_id)
        if p not in paths:
            paths.append(p)
    return paths


def retrieve_member_memories(member_id: str, query: str, top_k: int = 6) -> list[dict[str, Any]]:
    """Long-term memories AgentCore has distilled for this neighbor; [] when disabled or on any error."""
    if not enabled():
        return []
    out: list[dict[str, Any]] = []
    try:
        client = _get_client()
        for path in _candidate_paths(member_id):
            for r in client.retrieve_memories(memory_id=MEMORY_ID, namespace_path=path, query=query, top_k=top_k) or []:
                content = r.get("content") or {}
                text = content.get("text") if isinstance(content, dict) else str(content)
                if text:
                    out.append({"text": str(text)[:600], "namespaces": r.get("namespaces", []), "created_at": str(r.get("createdAt", ""))})
            if out:
                break
    except Exception as e:  # noqa: BLE001
        _log_failure(f"retrieve_memories for {member_id}", e)
    return out
