"""Porchlight API — FastAPI front door for the Strands agent pipeline and the coordinator dashboard."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import routes_outage
from . import scheduler as sched
from .agents.model_factory import candidate_names
from .agents.runner import runner
from .agents.sentinel import _clusters, list_fixtures, replay_fixture, scan_nws, scan_thresholds
from .channels import available_channels
from .config import settings
from .events import bus
from .feeds import open_meteo
from .models import Checkin, HazardEvent, Member, Resource, TimelineEntry, Volunteer, now_iso
from .seed import MEMBERS, RESOURCES, VOLUNTEERS
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("porchlight")

app = FastAPI(title="Porchlight", description="Neighbor check-in agent built with the Strands Agents SDK", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def _startup() -> None:
    bus.bind_loop(asyncio.get_running_loop())
    if store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES):
        log.info("seeded demo roster for %s", settings.COMMUNITY_NAME)
    sched.start()
    log.info("Porchlight ready. Model candidates: %s. Channels: %s", candidate_names(), available_channels())


@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        sched.scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ health / settings

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "community": settings.COMMUNITY_NAME,
        "coordinator": settings.COORDINATOR_NAME,
        "models": candidate_names(),
        "channels": available_channels(),
        "send_mode": settings.SEND_MODE,
        "sentinel_enabled": store.get_setting("sentinel_enabled", settings.SENTINEL_ENABLED),
        "sentinel_interval_minutes": settings.SENTINEL_INTERVAL_MINUTES,
        "last_scan_at": store.get_setting("last_scan_at"),
        "auto_approve_escalations": store.get_setting("auto_approve_escalations", settings.AUTO_APPROVE_ESCALATIONS),
        "public_base_url": settings.PUBLIC_BASE_URL,
        "time": now_iso(),
    }


class SettingsIn(BaseModel):
    auto_approve_escalations: Optional[bool] = None
    sentinel_enabled: Optional[bool] = None


@app.post("/api/settings")
def update_settings(body: SettingsIn) -> dict[str, Any]:
    if body.auto_approve_escalations is not None:
        store.set_setting("auto_approve_escalations", body.auto_approve_escalations)
    if body.sentinel_enabled is not None:
        store.set_setting("sentinel_enabled", body.sentinel_enabled)
    return health()


# ------------------------------------------------------------------ events (SSE)

@app.get("/api/events")
def events(episode_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    return {"events": [e.model_dump() for e in bus.history(episode_id, limit)]}


@app.get("/api/events/stream")
async def events_stream(request: Request):
    q = bus.subscribe()

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'time': now_iso()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {ev.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ roster / volunteers / resources

@app.get("/api/roster")
def roster() -> dict[str, Any]:
    return {"members": [m.model_dump() for m in store.members()]}


@app.post("/api/roster")
def upsert_member(m: Member) -> dict[str, Any]:
    return store.put_member(m).model_dump()


@app.delete("/api/roster/{member_id}")
def delete_member(member_id: str) -> dict[str, Any]:
    store.delete_member(member_id)
    return {"deleted": member_id}


@app.post("/api/roster/import")
async def import_roster(file: UploadFile) -> dict[str, Any]:
    """CSV columns: name,phone,email,language,preferred_channel,address,lat,lon,risk_factors(;-separated),notes,emergency_contact_name,emergency_contact_phone"""
    text = (await file.read()).decode("utf-8", errors="ignore")
    n = 0
    for row in csv.DictReader(io.StringIO(text)):
        try:
            m = Member(
                name=row["name"].strip(), phone=row.get("phone", "").strip(), email=row.get("email", "").strip(),
                language=row.get("language", "en").strip() or "en", preferred_channel=(row.get("preferred_channel") or "sms").strip(),  # type: ignore[arg-type]
                address=row.get("address", ""), lat=float(row["lat"]), lon=float(row["lon"]),
                risk_factors=[r.strip() for r in row.get("risk_factors", "").split(";") if r.strip()],  # type: ignore[list-item]
                notes=row.get("notes", ""), emergency_contact_name=row.get("emergency_contact_name", ""), emergency_contact_phone=row.get("emergency_contact_phone", ""),
            )
            store.put_member(m)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("skipping roster row %s: %s", row, e)
    return {"imported": n}


@app.get("/api/volunteers")
def volunteers() -> dict[str, Any]:
    return {"volunteers": [v.model_dump() for v in store.volunteers()]}


@app.post("/api/volunteers")
def upsert_volunteer(v: Volunteer) -> dict[str, Any]:
    return store.put_volunteer(v).model_dump()


@app.get("/api/resources")
def resources() -> dict[str, Any]:
    return {"resources": [r.model_dump() for r in store.resources()]}


@app.post("/api/resources")
def upsert_resource(r: Resource) -> dict[str, Any]:
    return store.put_resource(r).model_dump()


# ------------------------------------------------------------------ hazards

@app.get("/api/hazards/live")
def hazards_live() -> dict[str, Any]:
    """What the sentinel sees right now: official alerts for the roster's area plus live conditions."""
    lat, lon = _clusters(1)[0]
    try:
        alerts = [h.model_dump(exclude={"description", "instruction"}) | {"seen": store.alert_seen(h.external_id)} for h in scan_nws()]
    except Exception as e:  # noqa: BLE001
        alerts = [{"error": str(e)}]
    try:
        wx = open_meteo.current_conditions(lat, lon)
    except Exception as e:  # noqa: BLE001
        wx = {"error": str(e)}
    try:
        aq = open_meteo.air_quality(lat, lon)
        aq["label"] = open_meteo.aqi_label(aq.get("us_aqi"))
    except Exception as e:  # noqa: BLE001
        aq = {"error": str(e)}
    thresholds = [h.model_dump(exclude={"description"}) for h in scan_thresholds()]
    return {"lat": lat, "lon": lon, "alerts": alerts, "weather": wx, "air_quality": aq, "threshold_hazards": thresholds,
            "thresholds": {"heat_index_f": settings.HEAT_INDEX_ACTIVATE_F, "aqi": settings.AQI_ACTIVATE, "cold_f": settings.COLD_ACTIVATE_F}}


@app.post("/api/hazards/scan")
async def hazards_scan() -> dict[str, Any]:
    before = {e.id for e in store.episodes()}
    await sched.sentinel_job()
    after = [e.model_dump(exclude={"timeline"}) for e in store.episodes() if e.id not in before]
    return {"new_episodes": after, "scanned_at": now_iso()}


@app.get("/api/hazards/fixtures")
def hazards_fixtures() -> dict[str, Any]:
    return {"fixtures": list_fixtures()}


class ReplayIn(BaseModel):
    fixture_id: str


@app.post("/api/hazards/replay")
async def hazards_replay(body: ReplayIn) -> dict[str, Any]:
    try:
        h = replay_fixture(body.fixture_id)
    except FileNotFoundError:
        raise HTTPException(404, "unknown fixture")
    ep = await runner.start(h)
    return {"episode": ep.model_dump()}


class ManualHazardIn(BaseModel):
    event_name: str
    hazard_type: str = "other"
    severity: str = "Severe"
    headline: str = ""
    description: str = ""
    area: str = ""


@app.post("/api/hazards/manual")
async def hazards_manual(body: ManualHazardIn) -> dict[str, Any]:
    h = HazardEvent(source="manual", external_id=f"manual-{now_iso()}", hazard_type=body.hazard_type,  # type: ignore[arg-type]
                    event_name=body.event_name, severity=body.severity, headline=body.headline or body.event_name,
                    description=body.description, area=body.area or settings.COMMUNITY_NAME)
    ep = await runner.start(h)
    return {"episode": ep.model_dump()}


# ------------------------------------------------------------------ episodes / approvals

def _episode_view(ep) -> dict[str, Any]:
    members = {m.id: m for m in store.members()}
    checkins = []
    for c in store.checkins(ep.id):
        m = members.get(c.member_id)
        checkins.append(c.model_dump() | {"member_name": m.name if m else c.member_id, "lat": m.lat if m else None, "lon": m.lon if m else None})
    return ep.model_dump() | {
        "approvals": [a.model_dump() for a in store.approvals(ep.id)],
        "checkins": checkins,
        "busy": runner.busy(ep.id) or runner.busy(ep.id + ":followup"),
    }


@app.get("/api/episodes")
def episodes() -> dict[str, Any]:
    return {"episodes": [ep.model_dump(exclude={"timeline"}) | {"pending_approvals": len(store.approvals(ep.id, status="pending")), "checkins": len(store.checkins(ep.id))} for ep in store.episodes()]}


@app.get("/api/episodes/{episode_id}")
def episode(episode_id: str) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    return _episode_view(ep)


@app.post("/api/episodes/{episode_id}/followup")
async def episode_followup(episode_id: str) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    await runner.run_followup(episode_id)
    return {"started": True}


@app.post("/api/episodes/{episode_id}/close")
def episode_close(episode_id: str) -> dict[str, Any]:
    ep = store.episode(episode_id)
    if not ep:
        raise HTTPException(404, "unknown episode")
    def _close(e):
        e.status = "closed"
        e.timeline.append(TimelineEntry(kind="closed", text="Closed by coordinator"))

    ep = store.mutate_episode(episode_id, _close)
    bus.emit("status", "Episode closed by coordinator", episode_id=ep.id, status="closed")
    return _episode_view(ep)


@app.get("/api/approvals")
def approvals(status: str | None = "pending") -> dict[str, Any]:
    return {"approvals": [a.model_dump() for a in store.approvals(status=status)]}


class DecisionIn(BaseModel):
    decision: str  # approve | reject
    note: str = ""
    edits: dict[str, Any] = {}


@app.post("/api/approvals/{approval_id}/decide")
async def decide(approval_id: str, body: DecisionIn) -> dict[str, Any]:
    try:
        a = await runner.decide(approval_id, body.decision, body.note, body.edits)
    except KeyError:
        raise HTTPException(404, "unknown approval")
    return a.model_dump()


# ------------------------------------------------------------------ member check-in

@app.get("/api/checkin/{token}")
def checkin_get(token: str) -> dict[str, Any]:
    c = store.checkin(token)
    if not c:
        raise HTTPException(404, "unknown check-in link")
    m = store.member(c.member_id)
    ep = store.episode(c.episode_id)
    return {
        "token": token, "status": c.status, "member_first_name": (m.name.split()[0] if m else "neighbor"),
        "language": m.language if m else "en", "community": settings.COMMUNITY_NAME,
        "hazard": ep.hazard.event_name if ep else "", "summary": (ep.assessment.plain_summary if ep and ep.assessment else ""),
        "actions": (ep.assessment.recommended_actions[:3] if ep and ep.assessment else []),
    }


class CheckinIn(BaseModel):
    status: str  # ok | needs_help
    note: str = ""


@app.post("/api/checkin/{token}")
async def checkin_post(token: str, body: CheckinIn) -> dict[str, Any]:
    c = store.checkin(token)
    if not c:
        raise HTTPException(404, "unknown check-in link")
    if body.status not in ("ok", "needs_help"):
        raise HTTPException(400, "status must be ok or needs_help")
    c.status = body.status  # type: ignore[assignment]
    c.responded_at = now_iso()
    c.note = body.note[:300]
    store.put_checkin(c)
    m = store.member(c.member_id)
    ep = store.episode(c.episode_id)
    name = m.name if m else c.member_id
    bus.emit("checkin", f"{name} checked in: {'OK' if body.status == 'ok' else 'NEEDS HELP'}" + (f" — {body.note[:120]}" if body.note else ""),
             episode_id=c.episode_id, member_id=c.member_id, status=body.status, note=body.note[:300])
    if ep:
        def _rec(e):
            e.timeline.append(TimelineEntry(kind="checkin", text=f"{name}: {body.status}", data={"note": body.note[:300]}))
            e.stats["responses"] = e.stats.get("responses", 0) + 1

        store.mutate_episode(ep.id, _rec)
        if body.status == "needs_help":
            await runner.run_followup(ep.id)
    return {"recorded": True, "status": c.status}


# ------------------------------------------------------------------ admin

@app.post("/api/admin/reset")
def admin_reset() -> dict[str, Any]:
    store.reset_runtime()
    bus.emit("status", "Runtime data reset by coordinator")
    return {"reset": True}


app.include_router(routes_outage.router)


# ------------------------------------------------------------------ static frontend (production build)

_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
