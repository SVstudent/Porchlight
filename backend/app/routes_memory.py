"""Neighbor memory routes: per-member history, coordinator lessons, and the AgentCore Memory writer.

The writer subscribes to the in-process event bus so check-ins and episode closes are mirrored to AgentCore
Memory without touching the existing routes; it starts only when AGENTCORE_MEMORY_ID is configured.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .agents import agentcore_memory
from .agents.tools_memory import community_history, compact_history, neighbor_history, sync_to_agentcore
from .events import bus
from .models import TimelineEntry, now_iso
from .store import store

log = logging.getLogger("porchlight.memory")
router = APIRouter()


# ------------------------------------------------------------------ history

@router.get("/api/roster/history")
def roster_history(exclude: str = "") -> dict[str, Any]:
    """Compact per-member history for dashboard tiles. `exclude` = the episode currently on screen."""
    members: dict[str, Any] = {}
    for m in store.members():
        h = compact_history(m.id, exclude_episode_id=exclude)
        if h:
            members[m.id] = h
    return {"members": members, "agentcore": agentcore_memory.status()}


@router.get("/api/roster/{member_id}/history")
def member_history(member_id: str, exclude: str = "") -> dict[str, Any]:
    """Same summary the triage/follow-up agents get from get_neighbor_history."""
    h = neighbor_history(member_id, exclude_episode_id=exclude)
    if "error" in h:
        raise HTTPException(404, h["error"])
    h["agentcore_memories"] = agentcore_memory.retrieve_member_memories(
        member_id, query=f"{h['name']} check-in reply behaviour, emergency contact, visits, what helped")
    h["agentcore"] = agentcore_memory.status()
    return h


@router.get("/api/community/history")
def community_history_route(limit: int = 5, exclude: str = "") -> dict[str, Any]:
    return community_history(limit=max(1, min(limit, 20)), exclude_episode_id=exclude)


# ------------------------------------------------------------------ lessons

class LessonIn(BaseModel):
    member_id: str = ""
    text: str


@router.post("/api/episodes/{episode_id}/lessons")
def add_lesson(episode_id: str, body: LessonIn) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    text = body.text.strip()[:500]
    if not text:
        raise HTTPException(400, "lesson text is required")
    m = store.member(body.member_id) if body.member_id else None
    if body.member_id and not m:
        raise HTTPException(404, "unknown member")
    entry = {"member_id": m.id if m else "", "text": text, "ts": now_iso()}

    def _apply(e):
        lessons = e.stats.get("lessons")
        if not isinstance(lessons, list):
            lessons = []
        lessons.append(entry)
        e.stats["lessons"] = lessons
        e.timeline.append(TimelineEntry(kind="lesson", text=f"Lesson recorded{' for ' + m.name if m else ''}: {text}", data=entry))

    ep = store.mutate_episode(episode_id, _apply)
    bus.emit("lesson", f"Lesson recorded{' for ' + m.name if m else ''}: {text}", episode_id=episode_id, member_id=entry["member_id"])
    agentcore_memory.record_lesson(ep, entry["member_id"], text)
    return {"lessons": ep.stats["lessons"]}


@router.get("/api/episodes/{episode_id}/lessons")
def list_lessons(episode_id: str) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    return {"lessons": [l for l in ep.stats.get("lessons", []) if isinstance(l, dict)]}


# ------------------------------------------------------------------ AgentCore writer (bus subscriber)

async def _pump(q: asyncio.Queue) -> None:
    while True:
        ev = await q.get()
        try:
            if ev.type == "checkin" and ev.episode_id and ev.data.get("member_id"):
                await asyncio.to_thread(sync_to_agentcore, ev.episode_id, str(ev.data["member_id"]))
            elif ev.type == "status" and ev.episode_id and ev.data.get("status") == "closed":
                await asyncio.to_thread(sync_to_agentcore, ev.episode_id)
        except Exception as e:  # noqa: BLE001
            log.info("AgentCore Memory writer skipped an event: %s", e)


@router.on_event("startup")
async def _start_memory_writer() -> None:
    if not agentcore_memory.enabled():
        log.info("AgentCore Memory not configured (set AGENTCORE_MEMORY_ID and AWS_REGION); using local history only")
        return
    asyncio.create_task(_pump(bus.subscribe()))
    log.info("AgentCore Memory writer started for memory %s in %s", agentcore_memory.status()["memory_id"], agentcore_memory.REGION)
