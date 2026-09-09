"""After-action report routes: deterministic metrics plus an optional model-written narrative."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .agents import report_agent
from .config import settings
from .models import TimelineEntry, now_iso
from .report import compute_metrics
from .store import store

router = APIRouter()


def _episode_summary(ep) -> dict[str, Any]:
    return {
        "id": ep.id, "status": ep.status, "created_at": ep.created_at, "updated_at": ep.updated_at,
        "community": settings.COMMUNITY_NAME, "coordinator": settings.COORDINATOR_NAME,
        "activated": bool(ep.assessment and ep.assessment.activate),
        "assessment": ep.assessment.model_dump() if ep.assessment else None,
        "triage_summary": ep.triage.summary if ep.triage else "",
        "coordinator_note": ep.outreach.coordinator_note if ep.outreach else "",
    }


def _report(ep) -> dict[str, Any]:
    metrics = compute_metrics(ep, store.checkins(ep.id), store.approvals(ep.id), store.members(), store.volunteers())
    cached = ep.stats.get("report") or {}
    return {
        "episode": _episode_summary(ep),
        "hazard": ep.hazard.model_dump(exclude={"description", "instruction"}) | {"description": ep.hazard.description[:1200]},
        "metrics": metrics,
        "narrative": cached.get("narrative"),
        "narrative_generated_at": cached.get("generated_at"),
        "narrative_reason": cached.get("reason", "") or ("" if cached.get("narrative") else "not_generated"),
        "generated_at": now_iso(),
    }


@router.get("/api/episodes/{episode_id}/report")
def episode_report(episode_id: str) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    return _report(ep)


@router.post("/api/episodes/{episode_id}/report/narrative")
def episode_report_narrative(episode_id: str) -> dict[str, Any]:
    """Generate (or regenerate) the narrative with the reporter agent and cache it on the episode."""
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    metrics = compute_metrics(ep, store.checkins(ep.id), store.approvals(ep.id), store.members(), store.volunteers())
    narrative, reason = report_agent.generate_narrative(metrics, _episode_summary(ep) | {"hazard": ep.hazard.model_dump(exclude={"description", "instruction"})})

    def _cache(e):
        if narrative is not None:
            e.stats["report"] = {"narrative": narrative.model_dump(), "generated_at": now_iso(), "reason": ""}
            e.timeline.append(TimelineEntry(kind="report", text="After-action narrative generated"))
        else:
            prev = e.stats.get("report") or {}
            e.stats["report"] = prev | {"reason": reason}

    ep = store.mutate_episode(ep.id, _cache) or ep
    return _report(ep)
