"""Demo and operations controls.

Nothing here fabricates output. Every endpoint drives the same code paths the product uses in production:
it only makes them convenient to trigger and to watch, which is what a five-minute demo needs.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .agents.runner import runner
from .agents.sentinel import list_fixtures
from .channels import available_channels
from .config import settings
from .events import bus
from .models import TimelineEntry, now_iso
from .store import store

log = logging.getLogger("porchlight.demo")
router = APIRouter()


# --------------------------------------------------------------- pacing controls

class PacingIn(BaseModel):
    """Follow-up timings. Real deployments use 20+ minute grace; a demo needs a shorter one to show escalation."""
    followup_grace_minutes: Optional[int] = None
    followup_interval_minutes: Optional[int] = None


@router.get("/api/demo/pacing")
def get_pacing() -> dict[str, Any]:
    return {
        "followup_grace_minutes": store.get_setting("followup_grace_minutes", settings.FOLLOWUP_GRACE_MINUTES),
        "followup_interval_minutes": store.get_setting("followup_interval_minutes", settings.FOLLOWUP_INTERVAL_MINUTES),
        "defaults": {
            "followup_grace_minutes": settings.FOLLOWUP_GRACE_MINUTES,
            "followup_interval_minutes": settings.FOLLOWUP_INTERVAL_MINUTES,
        },
    }


@router.post("/api/demo/pacing")
def set_pacing(body: PacingIn) -> dict[str, Any]:
    if body.followup_grace_minutes is not None:
        store.set_setting("followup_grace_minutes", max(0, int(body.followup_grace_minutes)))
    if body.followup_interval_minutes is not None:
        mins = max(1, int(body.followup_interval_minutes))
        store.set_setting("followup_interval_minutes", mins)
        try:
            from . import scheduler as sched

            job = sched.scheduler.get_job("followup")
            if job is not None:
                job.reschedule(trigger="interval", minutes=mins)
        except Exception as e:  # noqa: BLE001
            log.warning("could not reschedule follow-up job: %s", e)
    bus.emit("policy", "Coordinator changed follow-up pacing", **get_pacing())
    return get_pacing()


# --------------------------------------------------------------- retry a failed episode

@router.post("/api/episodes/{episode_id}/retry")
async def retry_episode(episode_id: str) -> dict[str, Any]:
    """Re-run an episode whose agent run failed (usually the model was unreachable).

    The graph is rebuilt from its persisted session, so a run that failed after the assessment resumes with
    that work intact rather than starting from nothing.
    """
    ep = store.episode(episode_id)
    if ep is None:
        raise HTTPException(404, "unknown episode")
    if runner.busy(episode_id):
        raise HTTPException(409, "this episode is already running")
    if ep.status not in ("failed", "stood_down", "assessing", "triaging"):
        raise HTTPException(409, f"nothing to retry from status '{ep.status}'")

    def _reset(e):
        e.status = "assessing"
        e.timeline.append(TimelineEntry(kind="retry", text="Coordinator retried the agent run"))

    store.mutate_episode(episode_id, _reset)
    bus.emit("status", "Retrying the agent run", episode_id=episode_id, status="assessing")
    await runner.retry(episode_id)
    return {"retrying": True, "episode_id": episode_id}


# --------------------------------------------------------------- readiness for recording

# A check-in link is only as good as PUBLIC_BASE_URL. Probing it catches the case that quietly ruins a take:
# the URL resolves, but to a different app on that port. Cached because readiness is polled every 20 seconds.
_base_probe: dict[str, Any] = {"at": 0.0, "ok": False, "detail": "not checked yet"}


_model_probe: dict[str, Any] = {"at": 0.0, "ok": False, "detail": "not checked yet"}


def probe_model() -> tuple[bool, str]:
    """Ask the configured provider for one short completion, from inside the server process.

    Whether a model answers from a developer's shell says nothing about whether it answers from the
    process that actually runs the agents, which is the one that matters. This checks the latter.
    """
    import time

    now = time.time()
    if now - _model_probe["at"] < 120:
        return _model_probe["ok"], _model_probe["detail"]

    from .agents.model_factory import build_model, candidate_names

    names = ", ".join(candidate_names()) or "none configured"
    try:
        from strands import Agent

        t0 = time.time()
        reply = str(Agent(model=build_model(), callback_handler=None)("Reply with the single word: ready"))
        ok = bool(reply.strip())
        detail = (f"{names} answered in {time.time() - t0:.0f}s" if ok
                  else f"{names} returned an empty reply")
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{names} could not be reached: {str(e)[:120]}"

    _model_probe.update({"at": now, "ok": ok, "detail": detail})
    return ok, detail


def probe_public_base() -> tuple[bool, str]:
    """Fetch PUBLIC_BASE_URL and report whether Porchlight is what answers."""
    import time
    import urllib.error
    import urllib.request

    now = time.time()
    if now - _base_probe["at"] < 30:
        return _base_probe["ok"], _base_probe["detail"]

    url = settings.PUBLIC_BASE_URL
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            body = r.read(4096).decode("utf-8", "replace")
        if "Porchlight" in body:
            ok, detail = True, f"{url} is serving Porchlight"
        else:
            ok, detail = False, f"{url} answered, but it is not Porchlight — a check-in link would open the wrong app"
    except urllib.error.URLError as e:
        ok, detail = False, f"{url} is not answering ({getattr(e, 'reason', e)}). Start the frontend, or fix PUBLIC_BASE_URL."
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{url} could not be checked: {e}"

    _base_probe.update({"at": now, "ok": ok, "detail": detail})
    return ok, detail


@router.get("/api/demo/readiness")
def readiness() -> dict[str, Any]:
    """Everything a person needs to confirm before hitting record, in one call."""
    from .agents.model_factory import candidate_names

    members = store.members()
    episodes = store.episodes()
    completed = [e for e in episodes if e.status in ("monitoring", "escalating", "closed")]
    hazards_shown = sorted({e.hazard.hazard_type for e in completed})
    channels = available_channels()
    live_channels = [k for k, v in channels.items() if v and k != "console"]

    base_ok, base_detail = probe_public_base()
    model_ok, model_detail = probe_model()
    local_base = settings.PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1"))

    checks = [
        {
            "id": "model",
            "label": "A model provider is configured",
            "ok": bool(candidate_names()),
            "detail": ", ".join(candidate_names()) or "none — set MODEL_PROVIDER and credentials in backend/.env",
        },
        {
            "id": "model_reachable",
            "label": "The agents can actually reach the model",
            "ok": model_ok,
            "detail": model_detail,
        },
        {
            "id": "roster",
            "label": "Roster has neighbors with risk factors",
            "ok": any(m.risk_factors for m in members),
            "detail": f"{len(members)} neighbors, {sum(1 for m in members if m.risk_factors)} with risk factors",
        },
        {
            "id": "volunteers",
            "label": "Volunteers available to assign",
            "ok": any(v.available for v in store.volunteers()),
            "detail": f"{sum(1 for v in store.volunteers() if v.available)} available",
        },
        {
            "id": "sending",
            "label": "Outbound channel ready",
            "ok": settings.SEND_MODE == "live" and bool(live_channels),
            "detail": (f"live via {', '.join(live_channels)}" if settings.SEND_MODE == "live" and live_channels
                       else "console mode — messages are logged, not sent. Set SEND_MODE=live and configure a channel."),
        },
        {
            "id": "public_url_serves",
            "label": "Check-in links open Porchlight",
            "ok": base_ok,
            "detail": base_detail,
        },
        {
            "id": "public_url",
            "label": "Check-in links reachable from a phone",
            "ok": not local_base,
            "detail": settings.PUBLIC_BASE_URL + (
                "  — localhost cannot be opened on a phone; run a tunnel and set PUBLIC_BASE_URL"
                if local_base else ""),
        },
        {
            "id": "override",
            "label": "Demo override protects the roster",
            "ok": bool(settings.DEMO_OVERRIDE_PHONE or settings.DEMO_OVERRIDE_EMAIL or settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID),
            "detail": ("all outbound routed to your own contact"
                       if (settings.DEMO_OVERRIDE_PHONE or settings.DEMO_OVERRIDE_EMAIL or settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID)
                       else "not set — in live mode messages would go to the roster's real numbers"),
        },
        {
            "id": "hazards",
            "label": "More than one hazard type has been run",
            "ok": len(hazards_shown) >= 2,
            "detail": (", ".join(hazards_shown) if hazards_shown else "none completed yet")
                      + f" ({len(list_fixtures())} archived alerts available to replay)",
        },
    ]
    blocking = [c for c in checks if not c["ok"] and c["id"] in ("model", "roster")]
    return {
        "ready": not blocking,
        "checks": checks,
        "episodes_total": len(episodes),
        "episodes_completed": len(completed),
        "hazard_types_shown": hazards_shown,
        "generated_at": now_iso(),
    }


# --------------------------------------------------------------- hazard comparison

@router.get("/api/demo/compare")
def compare() -> dict[str, Any]:
    """The same roster across every completed episode, so one screen proves 'one loop, any hazard'.

    Built only from episodes that actually ran. Nothing is synthesized.
    """
    members = {m.id: m for m in store.members()}
    episodes = [e for e in store.episodes() if e.triage and e.triage.decisions]
    episodes.sort(key=lambda e: e.created_at)
    cols = []
    for e in episodes:
        by_member = {d.member_id: d for d in e.triage.decisions}
        checkins = {c.member_id: c.status for c in store.checkins(e.id)}
        cols.append({
            "episode_id": e.id,
            "hazard_type": e.hazard.hazard_type,
            "event_name": e.hazard.event_name,
            "area": e.hazard.area,
            "created_at": e.created_at,
            "status": e.status,
            "activated": bool(e.assessment and e.assessment.activate),
            "severity_score": e.assessment.severity_score if e.assessment else None,
            "summary": e.assessment.plain_summary if e.assessment else "",
            "tier1": sum(1 for d in e.triage.decisions if d.tier == 1),
            "contacted": sum(1 for d in e.triage.decisions if d.tier in (1, 2, 3)),
            "decisions": {mid: {"tier": d.tier, "reason": d.reason, "needs_visit": d.needs_visit,
                                "checkin": checkins.get(mid)} for mid, d in by_member.items()},
        })
    rows = [{"member_id": m.id, "name": m.name, "risk_factors": m.risk_factors,
             "devices": getattr(m, "devices", [])} for m in members.values()]
    rows.sort(key=lambda r: r["name"])
    return {"members": rows, "episodes": cols,
            "hazard_types": sorted({c["hazard_type"] for c in cols})}


# --------------------------------------------------------------- latest check-in link

@router.get("/api/demo/latest-checkin")
def latest_checkin(episode_id: str | None = None) -> dict[str, Any]:
    """The most recent check-in link, so the demo can open the real neighbor page without hunting the log."""
    cks = store.checkins(episode_id) if episode_id else store.checkins()
    cks = [c for c in cks if c.status in ("sent", "delivered")]
    if not cks:
        return {"token": None, "url": None, "member": None}
    cks.sort(key=lambda c: c.sent_at, reverse=True)
    c = cks[0]
    m = store.member(c.member_id)
    return {
        "token": c.token,
        "url": f"{settings.PUBLIC_BASE_URL}/checkin/{c.token}",
        "path": f"/checkin/{c.token}",
        "member": m.name if m else c.member_id,
        "channel": c.channel,
        "episode_id": c.episode_id,
        "pending": [{"token": x.token, "path": f"/checkin/{x.token}",
                     "member": (store.member(x.member_id).name if store.member(x.member_id) else x.member_id)}
                    for x in cks[:8]],
    }
