"""Proposing who should go to whom, once a neighbour's need is established.

A deployment is only ever raised on evidence, never on suspicion. Two things count:

* **They asked.** A check-in came back `needs_help`, or the responder agent read their message and
  judged that it did.
* **They stopped answering.** The reminders ran out and the check-in went `critical`. Silence from
  someone who is 78 and lives alone in a heat wave is the finding, not an absence of one.

Everything here is a proposal. The coordinator approves before anyone is contacted, in the same way
every other outbound action in this system works.
"""
from __future__ import annotations

import itertools
import logging
from typing import Any

from .events import bus
from .models import Deployment, TimelineEntry, now_iso
from .routing import haversine_m, route
from .store import store

log = logging.getLogger("porchlight.deployments")

# A check-in in one of these states is evidence that someone should go round.
TRIGGERS = {"needs_help": "needs_help", "critical": "critical", "escalated": "needs_help"}

# A cooling centre is only worth suggesting if they could plausibly get to it.
MAX_RESOURCE_M = 4000


def _busy(volunteer_id: str) -> int:
    """How many live deployments this volunteer already has."""
    return sum(1 for d in store.deployments()
               if d.responder_id == volunteer_id and d.status in ("proposed", "approved"))


def best_volunteer(member, task: str = "wellness_visit") -> Any:
    """The closest available volunteer who can actually do this job.

    Ranked on fitness before distance, because the nearest person is the wrong answer when the job needs
    a driver and they do not drive, or needs a nurse and they are not one. Among equally suitable people,
    the closest wins.
    """
    needs_medical = "powered_medical_device" in (member.risk_factors or [])
    needs_driving = task == "ride_to_cooling_center"
    ranked = []
    for v in store.volunteers():
        if not v.available or _busy(v.id) >= max(1, v.max_assignments):
            continue
        if needs_driving and "drive" not in v.skills:
            continue  # cannot give someone a lift without a car
        metres = haversine_m(v.lat, v.lon, member.lat, member.lon)
        medical = 0 if (needs_medical and "medical" in v.skills) else 1
        speaks = 0 if (member.language == "es" and "spanish" in v.skills) else 1
        ranked.append((medical, speaks, metres, v))
    ranked.sort(key=lambda r: r[:3])
    return ranked[0][3] if ranked else None


def choose_task(member, checkin, hazard_type: str) -> tuple[str, Any, str]:
    """What kind of help this particular neighbour needs, and where they are going if anywhere.

    Returns (task, resource_or_None, why). The point is that the suggestion matches the person: a
    neighbour on an oxygen concentrator during an outage needs someone medical, not a lift; a neighbour
    with no air conditioning in a heat wave needs a ride to somewhere cooled, not a doorstep chat.
    """
    risks = set(member.risk_factors or [])
    said = (checkin.note or "").lower()

    if "powered_medical_device" in risks or "oxygen" in said or "dialysis" in said:
        return ("wellness_visit", None,
                "on powered medical equipment, so someone should lay eyes on them")

    cooled = _nearest_cooled(member, hazard_type)
    wants_cool = hazard_type in ("heat", "outage") and (
        "no_air_conditioning" in risks or "ac" in said or "air conditioning" in said or "hot" in said)
    if wants_cool and cooled is not None:
        resource, metres = cooled
        if "no_transport" in risks or "mobility_limited" in risks:
            return ("ride_to_cooling_center", resource,
                    f"no way to get there alone, and {resource.name} is {metres / 1000:.1f} km away")
        return ("ride_to_cooling_center", resource,
                f"their home is not keeping cool and {resource.name} is {metres / 1000:.1f} km away")

    if "mobility_limited" in risks or "no_transport" in risks:
        return ("deliver_supplies", None, "limited mobility, so bring what they need to them")
    return ("wellness_visit", None, "check on them in person")


def _nearest_cooled(member, hazard_type: str):
    """The closest public building that helps with this hazard, if one is near enough to be useful."""
    kinds = {"heat": ("cooling_center", "clean_air", "shelter"),
             "outage": ("cooling_center", "shelter"),
             "cold": ("warming_center", "shelter"),
             "winter": ("warming_center", "shelter"),
             "air_quality": ("clean_air", "cooling_center")}.get(hazard_type, ("shelter", "cooling_center"))
    best = None
    for r in store.resources():
        if r.kind not in kinds:
            continue
        metres = haversine_m(member.lat, member.lon, r.lat, r.lon)
        if metres <= MAX_RESOURCE_M and (best is None or metres < best[1]):
            best = (r, metres)
    return best


def _reason(member, checkin, volunteer) -> str:
    risks = ", ".join(member.risk_factors[:3]) or "no recorded risk factors"
    if checkin.status == "critical":
        return (f"{member.name} has not answered {checkin.reminders_sent} messages. "
                f"On file: {risks}. {volunteer.name} is the closest available volunteer.")
    said = (checkin.note or "").replace("said: ", "").strip()
    return (f"{member.name} asked for help{': ' + said[:90] if said else ''}. "
            f"On file: {risks}. {volunteer.name} is the closest available volunteer.")


def propose_for(checkin) -> Deployment | None:
    """Raise a deployment for one established need, if there is not already one open."""
    trigger = TRIGGERS.get(checkin.status)
    if trigger is None:
        return None
    ep = store.episode(checkin.episode_id)
    member = store.member(checkin.member_id)
    if ep is None or member is None or ep.status in ("closed", "stood_down"):
        return None
    for d in store.deployments(ep.id):
        if d.member_id == member.id and d.status in ("proposed", "approved"):
            return None  # somebody is already going

    # What the job is comes first: it decides who is suitable for it.
    task, resource, why = choose_task(member, checkin, ep.hazard.hazard_type)
    volunteer = best_volunteer(member, task)
    if volunteer is None and task == "ride_to_cooling_center":
        # Nobody free can drive. A visit from someone who can walk over is better than nothing.
        task, resource = "wellness_visit", None
        why = "nobody free can drive them, so someone should at least check on them"
        volunteer = best_volunteer(member, task)
    if volunteer is None:
        bus.emit("gap", f"No volunteer is free to reach {member.name}", episode_id=ep.id,
                 member_id=member.id, agent="deployments")
        return None
    r = route(volunteer.lat, volunteer.lon, member.lat, member.lon)
    dep = Deployment(
        episode_id=ep.id, member_id=member.id, responder_id=volunteer.id,
        responder_kind="volunteer", task=task, trigger=trigger,
        destination_id=resource.id if resource else "",
        destination_name=resource.name if resource else "",
        reason=_reason(member, checkin, volunteer) + f" Suggested because they are {why}.",
        route=r["points"], route_source=r["source"],
        distance_m=r["metres"], duration_s=r["seconds"], steps=r["steps"],
    )
    store.put_deployment(dep)
    store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(
        kind="deployment",
        text=f"Suggested: {volunteer.name} to {member.name} "
             f"({r['metres'] / 1000:.1f} km, about {round(r['seconds'] / 60)} min)")))
    bus.emit("deployment", f"Suggested: {volunteer.name} to {member.name}",
             episode_id=ep.id, member_id=member.id, agent="deployments", deployment_id=dep.id)
    log.info("proposed %s -> %s (%s)", volunteer.name, member.name, trigger)
    return dep


def sweep(episode_id: str | None = None) -> list[Deployment]:
    """Look over the open check-ins and propose for any established need without one."""
    made = []
    for c in store.checkins(episode_id):
        if c.status in TRIGGERS:
            d = propose_for(c)
            if d:
                made.append(d)
    return made


def decide(dep_id: str, approve: bool, note: str = "") -> Deployment | None:
    """The coordinator's call. Approving is what starts the trip and puts it on the map."""
    dep = store.deployment(dep_id)
    if dep is None or dep.status != "proposed":
        return dep

    def _apply(d):
        d.status = "approved" if approve else "declined"
        d.decision_note = note
        if approve:
            d.approved_at = now_iso()

    store.mutate_deployment(dep_id, _apply)
    dep = store.deployment(dep_id)
    member = store.member(dep.member_id)
    volunteer = store.volunteer(dep.responder_id)
    who = volunteer.name if volunteer else dep.responder_id
    to = member.name if member else dep.member_id

    store.mutate_episode(dep.episode_id, lambda e: e.timeline.append(TimelineEntry(
        kind="deployment",
        text=(f"{who} is on the way to {to}" if approve else f"Declined sending {who} to {to}")
             + (f" — {note}" if note else ""))))
    bus.emit("deployment", f"{who} is on the way to {to}" if approve else f"Declined: {who} to {to}",
             episode_id=dep.episode_id, member_id=dep.member_id, agent="deployments",
             deployment_id=dep.id, status=dep.status)
    return dep


def progress(dep: Deployment, now_s: float) -> dict[str, Any]:
    """Where along the route the responder is expected to be, given how long ago they set off.

    This is an estimate derived from the routing service's own travel time, not a position report. It
    is what the coordinator can reasonably expect, and the interface labels it that way rather than
    implying the volunteer's phone is being tracked.
    """
    if dep.status != "approved" or not dep.route or dep.duration_s <= 0:
        return {"fraction": 0.0, "point": dep.route[0] if dep.route else None, "eta_s": dep.duration_s}
    elapsed = max(0.0, now_s)
    fraction = min(1.0, elapsed / dep.duration_s)

    # Walk the polyline by distance so the marker follows the road at a steady speed.
    total = 0.0
    spans = []
    for a, b in itertools.pairwise(dep.route):
        d = haversine_m(a[0], a[1], b[0], b[1])
        spans.append((a, b, d))
        total += d
    if total <= 0:
        return {"fraction": fraction, "point": dep.route[-1], "eta_s": 0}

    want = total * fraction
    run = 0.0
    for a, b, d in spans:
        if run + d >= want:
            t = 0 if d == 0 else (want - run) / d
            return {"fraction": fraction,
                    "point": [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
                    "eta_s": max(0.0, dep.duration_s - elapsed)}
        run += d
    return {"fraction": 1.0, "point": dep.route[-1], "eta_s": 0.0}
