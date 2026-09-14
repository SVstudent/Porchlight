"""Porchlight API — FastAPI front door for the Strands agent pipeline and the coordinator dashboard."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import logging
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import routes_demo, routes_memory, routes_outage, routes_report, routes_voice
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
    # Community resources are reference data maintained in seed.py, not coordinator input. Refresh them on every
    # start so a corrected phone number or address reaches an existing database.
    for r in RESOURCES:
        store.put_resource(r)
    _setup_telemetry()
    sched.start()
    _warn_about_stored_overrides()
    log.info("Porchlight ready. Model candidates: %s. Channels: %s", candidate_names(), available_channels())


def _setup_telemetry() -> None:
    """Turn the per-agent trace_attributes into real spans when an OTLP endpoint or console tracing is configured."""
    import os

    try:
        from strands.telemetry import StrandsTelemetry
    except Exception as e:  # noqa: BLE001
        log.debug("telemetry unavailable: %s", e)
        return
    try:
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            StrandsTelemetry().setup_otlp_exporter()
            log.info("tracing to %s", os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])
        elif os.getenv("TRACE_CONSOLE", "").lower() in {"1", "true", "yes"}:
            StrandsTelemetry().setup_console_exporter()
            log.info("tracing to the console")
    except Exception as e:  # noqa: BLE001
        log.warning("could not start tracing: %s", e)


@app.on_event("shutdown")
async def _shutdown() -> None:
    with contextlib.suppress(Exception):  # stopping an already-stopped scheduler is harmless
        sched.stop()


# Settings the presenter view can change at runtime. Once changed they live in the database and win over
# backend/.env, which is correct — a coordinator adjusting pacing mid-event should not be overruled by a
# file — but it is invisible, and an edit to .env that silently does nothing costs an hour to work out.
_OVERRIDABLE = ("followup_grace_minutes", "followup_interval_minutes", "sentinel_enabled",
                "auto_approve_escalations")


def _warn_about_stored_overrides() -> None:
    for key in _OVERRIDABLE:
        stored = store.get_setting(key, None)
        if stored is None:
            continue
        env_value = getattr(settings, key.upper(), None)
        if env_value is not None and str(stored) != str(env_value):
            log.warning(
                "%s is %s, set from the presenter view and stored in the database. It overrides "
                "%s=%s in backend/.env; change it in the app, or clear the stored value.",
                key, stored, key.upper(), env_value)


def _begin_shutdown(*_a) -> None:
    """Stop scheduled work the instant a stop is requested.

    FastAPI's shutdown handler runs only after connections have drained, which is too late: the
    dashboard holds an event stream open, so the scheduler went on sending messages for the nine
    minutes between asking the server to stop and it actually stopping.
    """
    with contextlib.suppress(Exception):  # stopping an already-stopped scheduler is harmless
        sched.stop()


@app.on_event("startup")
async def _install_signal_handlers() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous = signal.getsignal(sig)
            loop.add_signal_handler(sig, _on_signal, sig, previous)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform dependent
            pass


def _on_signal(sig, previous) -> None:
    _begin_shutdown()
    if callable(previous):
        previous(sig, None)


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
        # Which process answered. A restart hands the port over gradually, so without this a probe can
        # read the configuration of the process that is on its way out and conclude a change did nothing.
        "pid": os.getpid(),
        "time": now_iso(),
    }


class SettingsIn(BaseModel):
    auto_approve_escalations: bool | None = None
    sentinel_enabled: bool | None = None


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


def _neighbour_state(member, episode, checkins, deployments) -> dict[str, Any]:
    """One neighbour, as they stand right now: their risk, where the check-in got to, who is going."""
    tier = None
    if episode and episode.triage:
        for d in episode.triage.decisions:
            if d.member_id == member.id:
                tier = d.tier
                break
    mine = [c for c in checkins if c.member_id == member.id]
    checkin = max(mine, key=lambda c: c.sent_at) if mine else None
    trip = next((d for d in deployments
                 if d.member_id == member.id and d.status in ("proposed", "approved")), None)

    # One word for the whole situation, which is what the card leads with and what it sorts on.
    if checkin is None:
        state = "not_contacted"
    elif checkin.status == "critical":
        state = "critical"
    elif checkin.status in ("needs_help", "escalated"):
        state = "needs_help"
    elif checkin.status == "ok":
        state = "ok"
    else:
        state = "waiting"

    return {
        "id": member.id, "name": member.name, "address": member.address,
        "lat": member.lat, "lon": member.lon, "language": member.language,
        "risk_factors": member.risk_factors, "notes": member.notes,
        "devices": member.devices, "preferred_channel": member.preferred_channel,
        "emergency_contact_name": member.emergency_contact_name,
        "tier": tier,
        "state": state,
        "checkin": checkin.model_dump() if checkin else None,
        "reminders_sent": checkin.reminders_sent if checkin else 0,
        "deployment": ({"id": trip.id, "status": trip.status, "task": trip.task,
                        "responder_id": trip.responder_id,
                        "responder_name": (store.volunteer(trip.responder_id).name
                                           if store.volunteer(trip.responder_id) else trip.responder_id),
                        "eta_minutes": round(trip.duration_s / 60)} if trip else None),
    }


# The order a coordinator should work down the list in: loudest problem first, people who are fine last.
_STATE_ORDER = {"critical": 0, "needs_help": 1, "waiting": 2, "not_contacted": 3, "ok": 4}


@app.get("/api/map/layers")
def map_layers(episode_id: str | None = None) -> dict[str, Any]:
    """What the map should draw besides the roster: the hazard's footprint and the conditions field.

    These are the two scales of the same event. The footprint is the National Weather Service's own
    geometry — the forecaster's polygon, or the outlines of the forecast zones the alert named. The
    field is measured conditions sampled across the neighbourhood, which is where a warning stops being
    a county-wide statement and starts being about one person's street.
    """
    from .feeds import field as field_mod
    from .feeds import footprint as fp_mod

    episode = store.episode(episode_id) if episode_id else _current_episode()
    members = [m for m in store.members() if m.opted_in]
    points = [(m.lat, m.lon) for m in members]

    layers: dict[str, Any] = {"episode_id": episode.id if episode else None}
    if episode:
        fp = fp_mod.for_hazard(episode.hazard)
        layers["footprint"] = {
            **fp,
            "event_name": episode.hazard.event_name,
            "area": episode.hazard.area,
            "severity": episode.hazard.severity,
            "hazard_type": episode.hazard.hazard_type,
        }
    else:
        layers["footprint"] = {"kind": "none", "parts": [], "points": 0}

    hazard_type = episode.hazard.hazard_type if episode else "heat"
    layers["field"] = field_mod.sample(points, hazard_type)
    return layers


@app.get("/api/neighbors")
def neighbors(episode_id: str | None = None) -> dict[str, Any]:
    """Every neighbour and how they are doing, for the watch list."""
    episode = store.episode(episode_id) if episode_id else _current_episode()
    checkins = store.checkins(episode.id) if episode else []
    deployments = store.deployments(episode.id) if episode else []
    rows = [_neighbour_state(m, episode, checkins, deployments) for m in store.members() if m.opted_in]
    rows.sort(key=lambda r: (_STATE_ORDER.get(r["state"], 9), r["tier"] if r["tier"] else 9, r["name"]))
    return {"episode_id": episode.id if episode else None,
            "episode": episode.model_dump() if episode else None,
            "neighbors": rows}


@app.get("/api/neighbors/{member_id}")
def neighbor(member_id: str, episode_id: str | None = None) -> dict[str, Any]:
    """One neighbour's case: their state now, their history, and the trips involving them."""
    member = store.member(member_id)
    if member is None:
        raise HTTPException(404, "unknown neighbour")
    episode = store.episode(episode_id) if episode_id else _current_episode()
    checkins = store.checkins(episode.id) if episode else []
    deployments = store.deployments(episode.id) if episode else []
    state = _neighbour_state(member, episode, checkins, deployments)
    from .agents.tools_memory import neighbor_history

    return {
        **state,
        "episode": episode.model_dump() if episode else None,
        "phone": member.phone, "email": member.email,
        "emergency_contact_phone": member.emergency_contact_phone,
        "history": neighbor_history(member_id, exclude_episode_id=episode.id if episode else None),
        "deployments": [_deployment_view(d) for d in deployments if d.member_id == member_id],
    }


def _deployment_view(d) -> dict[str, Any]:
    """One trip, with where the responder should be by now.

    The map needs more than the stored record: it needs the point along the route that corresponds to
    how long ago the coordinator approved it. Shared by the watch and by a neighbour's own page so both
    draw the same thing.
    """
    from . import deployments as dep_mod

    member = store.member(d.member_id)
    responder = store.volunteer(d.responder_id)
    elapsed = 0.0
    if d.approved_at:
        elapsed = max(0.0, (datetime.now(UTC)
                            - datetime.fromisoformat(d.approved_at.replace("Z", "+00:00"))).total_seconds())
    p = dep_mod.progress(d, elapsed)
    return {
        **d.model_dump(),
        "member_name": member.name if member else d.member_id,
        "member_point": [member.lat, member.lon] if member else None,
        "responder_name": responder.name if responder else d.responder_id,
        "responder_skills": responder.skills if responder else [],
        "origin": d.route[0] if d.route else None,
        "progress": p["fraction"],
        "position": p["point"],
        "eta_seconds": p["eta_s"],
        "elapsed_seconds": elapsed,
    }


@app.post("/api/neighbors/{member_id}/checkup")
async def run_checkup(member_id: str) -> dict[str, Any]:
    """Send this one neighbour a check-in now, and start the reminder ladder for them.

    The coordinator's own version of what the outreach agent does for the whole roster: aimed at one
    person, because sometimes you are worried about one person.
    """
    import secrets

    from .channels.registry import deliver

    member = store.member(member_id)
    episode = _current_episode()
    if member is None:
        raise HTTPException(404, "unknown neighbour")
    if episode is None:
        raise HTTPException(400, "no episode is running; start one first")

    open_already = [c for c in store.checkins(episode.id)
                    if c.member_id == member_id and c.status in ("sent", "delivered")]
    if open_already:
        return {"already_waiting": True, "token": open_already[0].token}

    token = secrets.token_urlsafe(8)
    link = f"{settings.PUBLIC_BASE_URL}/checkin/{token}"
    body = (f"Hi {member.name.split()[0]}, this is Porchlight from {settings.COMMUNITY_NAME}. "
            f"{episode.hazard.event_name} — are you doing okay?\n\n{link}\n\nOr just reply here.")
    store.put_checkin(Checkin(token=token, episode_id=episode.id, member_id=member_id,
                              channel=member.preferred_channel, status="sent"))
    res = await asyncio.to_thread(deliver, member, body, member.preferred_channel,
                                  meta={"token": token, "language": member.language})
    store.mutate_episode(episode.id, lambda e: e.timeline.append(TimelineEntry(
        kind="checkin", text=f"Check-in sent to {member.name} by the coordinator")))
    bus.emit("checkin", f"Check-in sent to {member.name}", episode_id=episode.id,
             member_id=member_id, agent="coordinator")
    from .channels.registry import live_for

    really_sent = live_for(member) and res.channel != "console"
    return {
        "sent": really_sent,
        "logged_only": not really_sent,
        "channel": res.channel,
        "detail": res.detail,
        "token": token,
        "why": ("" if really_sent
                else f"SEND_MODE is '{settings.SEND_MODE}'" if settings.SEND_MODE != "live"
                else f"only {settings.DEMO_LIVE_MEMBER_ID} is contacted for real right now"),
    }


@app.post("/api/neighbors/{member_id}/escalate")
def run_escalate(member_id: str) -> dict[str, Any]:
    """Treat this neighbour as needing help now, and propose who should go to them."""
    from . import deployments as dep_mod

    member = store.member(member_id)
    episode = _current_episode()
    if member is None:
        raise HTTPException(404, "unknown neighbour")
    if episode is None:
        raise HTTPException(400, "no episode is running; start one first")

    mine = [c for c in store.checkins(episode.id) if c.member_id == member_id]
    if not mine:
        raise HTTPException(400, "nothing has been sent to this neighbour yet; run a check-in first")
    checkin = max(mine, key=lambda c: c.sent_at)
    store.mutate_checkin(checkin.token, lambda c: (setattr(c, "status", "needs_help"),
                                                   setattr(c, "note", "escalated by the coordinator")))
    dep = dep_mod.propose_for(store.checkin(checkin.token))
    if dep is None:
        return {"proposed": False, "reason": "no volunteer is free, or someone is already going"}
    return {"proposed": True, "deployment": dep.model_dump()}


def _current_episode():
    """The episode a coordinator is working right now: the newest one that has not been closed."""
    live = [e for e in store.episodes() if e.status not in ("closed", "stood_down")]
    return max(live, key=lambda e: e.created_at) if live else None


@app.get("/api/episodes/{episode_id}/deployments")
def list_deployments(episode_id: str) -> dict[str, Any]:
    """Suggested and approved trips, each with its road route and where the responder should be by now."""

    return {"deployments": [_deployment_view(d) for d in store.deployments(episode_id)]}


@app.post("/api/deployments/{deployment_id}/decide")
def decide_deployment(deployment_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from . import deployments as dep_mod

    d = dep_mod.decide(deployment_id, str(body.get("decision", "")).lower().startswith("appr"),
                       str(body.get("note", "")))
    if d is None:
        raise HTTPException(404, "unknown deployment")
    return {"deployment": d.model_dump()}


@app.post("/api/episodes/{episode_id}/deployments/sweep")
def sweep_deployments(episode_id: str) -> dict[str, Any]:
    """Propose a trip for every established need in this episode that does not already have one."""
    from . import deployments as dep_mod

    made = dep_mod.sweep(episode_id)
    return {"proposed": [d.model_dump() for d in made]}


@app.get("/api/events/stream")
async def events_stream(request: Request):
    q = bus.subscribe()

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'time': now_iso()})}\n\n"
            while True:
                # A server-sent event stream never ends on its own, so uvicorn's graceful shutdown waits
                # for it forever while background jobs keep running. Leaving when the server is stopping
                # is what lets "stop" actually mean stop.
                if sched.stopping.is_set() or await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {ev.model_dump_json()}\n\n"
                except TimeoutError:
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
        raise HTTPException(404, "unknown fixture") from None
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
    # Stop any work in flight, then void decisions that can no longer be carried out.
    for key in (episode_id, episode_id + ":followup"):
        task = runner._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
    runner._graphs.pop(episode_id, None)
    runner._followups.pop(episode_id, None)
    voided = 0
    for a in store.approvals(episode_id, status="pending"):
        a.status = "rejected"
        a.resolved_at = now_iso()
        a.decision_note = "The coordinator closed this episode before deciding."
        store.put_approval(a)
        voided += 1

    def _close(e):
        e.status = "closed"
        e.timeline.append(TimelineEntry(
            kind="closed",
            text="Closed by coordinator" + (f"; {voided} pending decision(s) cancelled" if voided else ""),
        ))

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
        raise HTTPException(404, "unknown approval") from None
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
    def _record(x):
        x.status = body.status  # type: ignore[assignment]
        x.responded_at = now_iso()
        x.note = body.note[:300]

    c = store.mutate_checkin(token, _record) or c
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


app.include_router(routes_demo.router)
app.include_router(routes_memory.router)
app.include_router(routes_outage.router)
app.include_router(routes_report.router)
app.include_router(routes_voice.router)


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
