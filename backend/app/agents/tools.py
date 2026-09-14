"""Strands tools available to the Porchlight agents.

Read tools pull live data (roster, weather, air quality, nearby cooled buildings).
Action tools (dispatch_outreach, assign_volunteers, escalate_member) are the only way the agents can affect the
world, and every one of them is gated by the ApprovalGateHook interrupt unless policy pre-authorises it.
"""
from __future__ import annotations

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..channels import deliver
from ..config import settings
from ..events import bus
from ..feeds import open_meteo, places
from ..feeds.places import haversine_km
from ..models import (
    Checkin,
    LogisticsPlan,
    Member,
    OutreachMessage,
    OutreachPlan,
    TimelineEntry,
    VolunteerAssignment,
    now_iso,
)
from ..store import store
from .context import episode_id_from

log = logging.getLogger("porchlight.tools")

GATED_TOOLS = {"dispatch_outreach", "assign_volunteers", "escalate_member"}


def _episode(tool_context: ToolContext):
    ep_id = episode_id_from(tool_context.invocation_state)
    ep = store.episode(ep_id) if ep_id else None
    return ep_id, ep


def _timeline(ep, kind: str, text: str, **data: Any) -> None:
    if ep is None:
        return
    store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(kind=kind, text=text, data=data)))


def _community_centroid() -> tuple[float, float]:
    ms = store.members()
    if not ms:
        return 33.4942, -112.1770
    return sum(m.lat for m in ms) / len(ms), sum(m.lon for m in ms) / len(ms)


# ---------------------------------------------------------------- read tools

@tool(context=True)
def get_episode_context(tool_context: ToolContext) -> dict:
    """Get the current hazard, the sentinel assessment, and any triage already completed for this episode.
    Call this first so your work builds on what earlier agents decided."""
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    return {
        "episode_id": ep.id,
        "community": settings.COMMUNITY_NAME,
        "coordinator": settings.COORDINATOR_NAME,
        "now_utc": now_iso(),
        "hazard": ep.hazard.model_dump(exclude={"description", "instruction"}) | {
            "description": ep.hazard.description[:1500],
            "instruction": ep.hazard.instruction[:800],
        },
        "assessment": ep.assessment.model_dump() if ep.assessment else None,
        "triage": ep.triage.model_dump() if ep.triage else None,
        "policy": {"auto_approve_escalations": store.get_setting("auto_approve_escalations", settings.AUTO_APPROVE_ESCALATIONS)},
    }


@tool
def get_roster() -> list[dict]:
    """List every opted-in community member with their risk factors, language, preferred channel, and notes.
    Risk factors: lives_alone, age_75_plus, no_air_conditioning, powered_medical_device, mobility_limited,
    cognitive_impairment, infant_or_young_child, outdoor_worker, pregnant, chronic_illness, no_transport,
    limited_english, unhoused."""
    out = []
    for m in store.members():
        if not m.opted_in:
            continue
        out.append({
            "member_id": m.id,
            "name": m.name,
            "language": m.language,
            "preferred_channel": m.preferred_channel,
            "risk_factors": m.risk_factors,
            "notes": m.notes,
            "address": m.address,
            "has_emergency_contact": bool(m.emergency_contact_phone),
        })
    return out


@tool
def get_area_conditions() -> dict:
    """Current weather and air quality at the centre of the community (live Open-Meteo data)."""
    lat, lon = _community_centroid()
    try:
        wx = open_meteo.current_conditions(lat, lon)
    except Exception as e:  # noqa: BLE001
        wx = {"error": str(e)}
    try:
        aq = open_meteo.air_quality(lat, lon)
        aq["label"] = open_meteo.aqi_label(aq.get("us_aqi"))
    except Exception as e:  # noqa: BLE001
        aq = {"error": str(e)}
    return {"lat": lat, "lon": lon, "weather": wx, "air_quality": aq}


@tool
def get_member_conditions(member_ids: list[str]) -> dict:
    """Live weather and air quality at each member's home, plus the distance to the nearest cooled place.
    Ask for every member you care about in one call rather than one at a time.
    Args:
        member_ids: ids from get_roster
    """
    if isinstance(member_ids, str):  # a model that sends one bare id instead of a list
        member_ids = [member_ids]
    if not member_ids:
        return {"error": "give at least one member_id"}

    cooled = [r for r in store.resources()
              if r.kind in ("cooling_center", "warming_center", "shelter", "clean_air")]
    # Open-Meteo resolves to a grid cell several kilometres across, so neighbours within about a kilometre
    # of each other get the identical forecast anyway. Group them and fetch once per group rather than once
    # per person: same numbers, a fraction of the requests.
    wanted: list[tuple[str, Any]] = []
    out: dict[str, Any] = {}
    for member_id in member_ids[:50]:
        m = store.member(member_id)
        if not m:
            out[member_id] = {"error": f"unknown member {member_id}"}
        else:
            wanted.append((member_id, m))

    def _fetch(key: tuple[float, float]) -> dict:
        lat, lon = key
        try:
            wx = open_meteo.current_conditions(lat, lon)
        except Exception as e:  # noqa: BLE001
            wx = {"error": str(e)}
        try:
            aq = open_meteo.air_quality(lat, lon)
            aq["label"] = open_meteo.aqi_label(aq.get("us_aqi"))
        except Exception as e:  # noqa: BLE001
            aq = {"error": str(e)}
        return {"weather": wx, "air_quality": aq}

    keys = {(round(m.lat, 2), round(m.lon, 2)) for _, m in wanted}
    # Serially this is a minute of waiting in the middle of a live demo; the calls are independent.
    with ThreadPoolExecutor(max_workers=8) as pool:
        by_place = dict(zip(keys, pool.map(_fetch, keys), strict=True))

    for _, m in wanted:
        key = (round(m.lat, 2), round(m.lon, 2))
        nearest = None
        for r in cooled:
            d = haversine_km(m.lat, m.lon, r.lat, r.lon)
            if nearest is None or d < nearest["distance_km"]:
                nearest = {"resource_id": r.id, "name": r.name, "distance_km": round(d, 2)}
        out[m.id] = {"name": m.name, "nearest_resource": nearest, **by_place[key]}
    return out


@tool
def find_nearby_cooled_places(member_id: str, radius_m: int = 3000) -> dict:
    """Find public cooled/heated buildings near a member: the community's known cooling centres plus
    libraries and community centres from OpenStreetMap.
    Args:
        member_id: id from get_roster
        radius_m: search radius in metres (default 3000)
    """
    m = store.member(member_id)
    if not m:
        return {"error": f"unknown member {member_id}"}
    known = []
    for r in store.resources():
        d = haversine_km(m.lat, m.lon, r.lat, r.lon)
        if d * 1000 <= radius_m or r.kind == "hydration":
            known.append({"resource_id": r.id, "name": r.name, "kind": r.kind, "address": r.address,
                          "hours": r.hours, "phone": r.phone, "distance_km": round(d, 2)})
    known.sort(key=lambda x: x["distance_km"])
    try:
        osm = places.nearby_public_buildings(m.lat, m.lon, radius_m=radius_m)
    except Exception as e:  # noqa: BLE001
        osm = [{"error": f"openstreetmap lookup failed: {e}"}]
    return {"member": m.name, "known_resources": known, "openstreetmap_places": osm}


@tool
def list_community_resources() -> list[dict]:
    """Cooling/warming centres, shelters, hotlines and other resources the coordinator has registered."""
    return [r.model_dump() for r in store.resources()]


@tool
def list_volunteers() -> list[dict]:
    """Available volunteers with their skills (drive, wellness_visit, spanish, medical, deliver, phone_call)
    and current assignment load."""
    load: dict[str, int] = {}
    for ep in store.episodes():
        if ep.status in ("closed", "stood_down", "failed") or not ep.logistics:
            continue
        for a in ep.logistics.assignments:
            load[a.volunteer_id] = load.get(a.volunteer_id, 0) + 1
    return [
        v.model_dump() | {"current_assignments": load.get(v.id, 0)}
        for v in store.volunteers()
        if v.available
    ]


@tool(context=True)
def get_checkin_status(tool_context: ToolContext) -> dict:
    """Per-member check-in status for this episode: ok, needs_help, sent (no reply yet), or escalated,
    with minutes elapsed since the message went out."""
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    from datetime import datetime

    out = []
    for c in store.checkins(ep.id):
        m = store.member(c.member_id)
        sent = datetime.fromisoformat(c.sent_at)
        mins = int((datetime.now(sent.tzinfo) - sent).total_seconds() // 60)
        tier = next((d.tier for d in (ep.triage.decisions if ep.triage else []) if d.member_id == c.member_id), None)
        out.append({
            "member_id": c.member_id, "name": m.name if m else c.member_id, "tier": tier,
            "status": c.status, "minutes_since_sent": mins, "note": c.note,
            "has_emergency_contact": bool(m and m.emergency_contact_phone),
        })
    grace = store.get_setting("followup_grace_minutes", settings.FOLLOWUP_GRACE_MINUTES)
    return {"episode_id": ep.id, "grace_minutes": grace, "members": out}


# ---------------------------------------------------------------- action tools (gated)

def _checkin_link(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/checkin/{token}"


@tool(context=True)
def dispatch_outreach(tool_context: ToolContext, messages: list[dict], coordinator_note: str) -> dict:
    """Send personalised check-in messages to members. REQUIRES coordinator approval (the call pauses until a
    human approves). Each message body must contain the literal placeholder {checkin_link}; it is replaced with a
    one-tap link the member uses to answer "I'm OK" or "I need help".
    Args:
        messages: list of objects, one per member: {"member_id": str, "channel": "sms"|"telegram"|"email"|"voice",
                  "language": "en"|"es", "body": str (<320 chars, includes {checkin_link}), "call_script": str (optional)}
        coordinator_note: 2-3 sentences for the coordinator explaining who is being contacted and why
    """
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    return dispatch_outreach_impl(ep.id, messages, coordinator_note)


def dispatch_outreach_impl(episode_id: str, messages: list[dict], coordinator_note: str) -> dict:
    ep = store.episode(episode_id)
    if ep is None:
        return {"error": "no active episode"}
    try:
        plan = OutreachPlan(messages=[OutreachMessage(**m) for m in messages], coordinator_note=coordinator_note)
    except Exception as e:  # noqa: BLE001
        return {"error": f"invalid messages: {e}"}
    messages = plan.messages

    def _start(e):
        e.outreach = plan
        e.status = "dispatching"

    store.mutate_episode(ep.id, _start)
    report = []
    for msg in messages:
        m = store.member(msg.member_id)
        if not m:
            report.append({"member_id": msg.member_id, "ok": False, "detail": "unknown member"})
            continue
        token = secrets.token_urlsafe(8)
        body = msg.body.replace("{checkin_link}", _checkin_link(token))
        if "{checkin_link}" not in msg.body:
            body = f"{body}\nCheck in: {_checkin_link(token)}"
        res = deliver(m, body, preferred=msg.channel, subject=f"{settings.COMMUNITY_NAME}: please check in",
                      meta={"token": token, "language": msg.language, "call_script": msg.call_script})
        store.put_checkin(Checkin(token=token, episode_id=ep.id, member_id=m.id, channel=res.channel,
                                  status="sent" if res.ok else "failed", note="" if res.ok else res.detail))
        bus.emit("dispatch", f"{'Sent' if res.ok else 'FAILED'} {res.channel} to {m.name}: {res.detail}",
                 episode_id=ep.id, agent="outreach", member_id=m.id, ok=res.ok, channel=res.channel, body=body, token=token)
        report.append({"member_id": m.id, "name": m.name, "ok": res.ok, "channel": res.channel, "detail": res.detail, "checkin_link": _checkin_link(token)})
    sent = sum(1 for r in report if r["ok"])

    def _done(e):
        e.status = "monitoring"
        e.stats["messages_sent"] = sent
        e.stats["messages_failed"] = len(report) - sent

    store.mutate_episode(ep.id, _done)
    _timeline(ep, "dispatch", f"Outreach dispatched: {sent} sent, {len(report) - sent} failed", report=report)
    return {"sent": sent, "failed": len(report) - sent, "deliveries": report}


@tool(context=True)
def assign_volunteers(tool_context: ToolContext, assignments: list[dict], recommended_resource_ids: list[str], gaps: list[str]) -> dict:
    """Assign volunteers to members (wellness visit, ride to cooling centre, phone call, deliver supplies) and
    notify each volunteer. REQUIRES coordinator approval.
    Args:
        assignments: list of objects: {"volunteer_id": str, "member_id": str,
                     "task": "wellness_visit"|"ride_to_cooling_center"|"phone_call"|"deliver_supplies",
                     "reason": str, "priority": 1|2|3}
        recommended_resource_ids: resource ids members should be pointed to
        gaps: needs that no volunteer or resource can cover, for the coordinator to solve
    """
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    return assign_volunteers_impl(ep.id, assignments, recommended_resource_ids, gaps)


def assign_volunteers_impl(episode_id: str, assignments: list[dict], recommended_resource_ids: list[str], gaps: list[str]) -> dict:
    ep = store.episode(episode_id)
    if ep is None:
        return {"error": "no active episode"}
    try:
        plan = LogisticsPlan(assignments=[VolunteerAssignment(**a) for a in assignments], recommended_resource_ids=recommended_resource_ids, gaps=gaps)
    except Exception as e:  # noqa: BLE001
        return {"error": f"invalid assignments: {e}"}
    assignments = plan.assignments
    store.mutate_episode(ep.id, lambda e: setattr(e, "logistics", plan))
    report = []
    for a in assignments:
        v = store.volunteer(a.volunteer_id)
        m = store.member(a.member_id)
        if not v or not m:
            report.append({"assignment": a.model_dump(), "ok": False, "detail": "unknown volunteer or member"})
            continue
        body = (f"{settings.COMMUNITY_NAME}: {v.name}, can you do a {a.task.replace('_', ' ')} for {m.name} "
                f"at {m.address}? Reason: {a.reason}. Reply to {settings.COORDINATOR_NAME} if you can't.")
        pseudo = Member(id=v.id, name=v.name, phone=v.phone, lat=v.lat, lon=v.lon, preferred_channel="sms")
        res = deliver(pseudo, body, preferred="sms", subject=f"{settings.COMMUNITY_NAME}: volunteer request")
        bus.emit("dispatch", f"Volunteer {v.name} -> {m.name} ({a.task}): {res.detail}", episode_id=ep.id, agent="logistics",
                 volunteer_id=v.id, member_id=m.id, ok=res.ok, task=a.task)
        report.append({"volunteer": v.name, "member": m.name, "task": a.task, "ok": res.ok, "detail": res.detail})
    store.mutate_episode(ep.id, lambda e: e.stats.__setitem__("volunteer_assignments", len(assignments)))
    _timeline(ep, "logistics", f"{len(assignments)} volunteer assignment(s) made; {len(gaps)} gap(s) flagged", report=report, gaps=gaps)
    return {"assigned": len(assignments), "notifications": report, "gaps": gaps}


@tool(context=True)
def escalate_member(tool_context: ToolContext, member_id: str, action: str, reason: str, volunteer_id: str = "") -> dict:
    """Escalate a member who reported needing help or who has not responded past the grace period.
    Actions: "volunteer_visit" (send a volunteer now; give volunteer_id), "notify_emergency_contact",
    "recommend_911" (coordinator should call emergency services). REQUIRES coordinator approval unless policy
    pre-authorises volunteer visits.
    Args:
        member_id: id from get_checkin_status
        action: volunteer_visit | notify_emergency_contact | recommend_911
        reason: why, in one sentence
        volunteer_id: required for volunteer_visit
    """
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    return escalate_member_impl(ep.id, member_id, action, reason, volunteer_id)


def escalate_member_impl(episode_id: str, member_id: str, action: str, reason: str, volunteer_id: str = "") -> dict:
    ep = store.episode(episode_id)
    if ep is None:
        return {"error": "no active episode"}
    m = store.member(member_id)
    if not m:
        return {"error": f"unknown member {member_id}"}
    detail = ""
    if action == "volunteer_visit":
        v = store.volunteer(volunteer_id)
        if not v:
            return {"error": f"unknown volunteer {volunteer_id}"}
        body = (f"{settings.COMMUNITY_NAME} URGENT: {v.name}, please check on {m.name} at {m.address} now. "
                f"{reason} Call {settings.COORDINATOR_NAME} when you arrive.")
        pseudo = Member(id=v.id, name=v.name, phone=v.phone, lat=v.lat, lon=v.lon, preferred_channel="sms")
        res = deliver(pseudo, body, preferred="sms")
        detail = f"volunteer {v.name} dispatched: {res.detail}"
    elif action == "notify_emergency_contact":
        if not m.emergency_contact_phone:
            return {"error": f"{m.name} has no emergency contact on file"}
        body = (f"{settings.COMMUNITY_NAME}: this is {m.name}'s neighbourhood check-in network. {reason} "
                f"We could not reach {m.name}. Can you call them or stop by? Contact {settings.COORDINATOR_NAME}.")
        pseudo = Member(id=f"ec_{m.id}", name=m.emergency_contact_name, phone=m.emergency_contact_phone, lat=m.lat, lon=m.lon, preferred_channel="sms")
        res = deliver(pseudo, body, preferred="sms")
        detail = f"emergency contact {m.emergency_contact_name} notified: {res.detail}"
    elif action == "recommend_911":
        detail = f"Coordinator advised to call emergency services for {m.name}: {reason}"
    else:
        return {"error": f"unknown action {action}"}
    for c in store.checkins(ep.id):
        if c.member_id == m.id:
            def _esc(x, _a=action, _r=reason):
                x.status = "escalated"
                x.note = f"{_a}: {_r}"

            store.mutate_checkin(c.token, _esc)
    def _esc(e):
        e.status = "escalating"
        e.stats["escalations"] = e.stats.get("escalations", 0) + 1

    store.mutate_episode(ep.id, _esc)
    bus.emit("escalation", f"{m.name}: {detail}", episode_id=ep.id, agent="followup", member_id=m.id, action=action)
    _timeline(ep, "escalation", f"{m.name} escalated ({action}): {reason}", detail=detail)
    return {"member": m.name, "action": action, "detail": detail}


@tool(context=True)
def record_coordinator_brief(tool_context: ToolContext, brief: str) -> dict:
    """Save the final plain-language briefing for the coordinator (what was done, who to watch, open gaps).
    Args:
        brief: 4-8 short lines, no jargon
    """
    _, ep = _episode(tool_context)
    if ep is None:
        return {"error": "no active episode"}
    return record_coordinator_brief_impl(ep.id, brief)


def record_coordinator_brief_impl(episode_id: str, brief: str) -> dict:
    ep = store.episode(episode_id)
    if ep is None:
        return {"error": "no active episode"}
    store.mutate_episode(ep.id, lambda e: e.stats.__setitem__("brief", brief))
    _timeline(ep, "brief", brief)
    bus.emit("brief", brief, episode_id=ep.id, agent="briefing")
    return {"saved": True}

