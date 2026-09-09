"""Neighbor memory across episodes.

Everything here is deterministic and computed from the store (episodes, check-ins, timeline, coordinator
lessons), so it works without a model or AWS. When Amazon Bedrock AgentCore Memory is configured
(see agentcore_memory.py) the neighbor tool additionally appends long-term memories retrieved for that member.
"""
from __future__ import annotations

import logging
import re
import statistics
from datetime import datetime
from typing import Any, Optional

from strands import tool
from strands.types.tools import ToolContext

from ..models import Episode, Member
from ..store import store
from . import agentcore_memory
from .context import episode_id_from

log = logging.getLogger("porchlight.memory")

# escalate_member writes timeline text "<full name> escalated (<action>): <reason>"
_ESC_RE = re.compile(r"^(?P<name>.+?) escalated \((?P<action>\w+)\)")

OUTCOME_LABEL = {
    "ok": "replied OK",
    "needs_help": "asked for help",
    "no_reply": "no reply",
    "not_reached": "could not be reached",
    "not_contacted": "not contacted",
}


def _minutes_between(a: str, b: str) -> Optional[int]:
    try:
        return max(0, int(round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60)))
    except Exception:  # noqa: BLE001
        return None


def _member_escalations(ep: Episode, m: Member) -> list[dict[str, Any]]:
    """Escalations for this member only. Matched on the exact leading name (never a substring: a volunteer or
    emergency contact named in the detail must not be credited with the escalation)."""
    out = []
    for t in ep.timeline:
        if t.kind != "escalation":
            continue
        mm = _ESC_RE.match(t.text or "")
        if not mm:
            continue
        if mm.group("name") != m.name and (t.data or {}).get("member_id") != m.id:
            continue
        out.append({"ts": t.ts, "action": mm.group("action"), "detail": str((t.data or {}).get("detail", ""))[:200]})
    return out


def episode_record(ep: Episode, m: Member) -> Optional[dict[str, Any]]:
    """What happened to one member in one episode, or None if they played no part in it."""
    decision = next((d for d in (ep.triage.decisions if ep.triage else []) if d.member_id == m.id), None)
    cks = sorted((c for c in store.checkins(ep.id) if c.member_id == m.id), key=lambda c: c.sent_at)
    esc = _member_escalations(ep, m)
    lessons = [l for l in ep.stats.get("lessons", []) if isinstance(l, dict) and l.get("member_id") == m.id]
    tasks = [a.task for a in (ep.logistics.assignments if ep.logistics else []) if a.member_id == m.id]
    if decision is None and not cks and not esc and not lessons and not tasks:
        return None

    ck = cks[0] if cks else None
    outcome, minutes, note = "not_contacted", None, ""
    # "console" is the development stand-in for a real send; report the channel triage chose instead
    channel = (ck.channel if ck and ck.channel and ck.channel != "console" else (decision.channel if decision else "")) or ""
    if ck:
        if ck.status == "failed":
            outcome = "not_reached"
        elif ck.status in ("ok", "needs_help"):
            outcome = ck.status
        elif ck.status == "escalated":
            outcome = "needs_help" if ck.responded_at else "no_reply"
        else:  # sent / delivered / no_response
            outcome = "no_reply"
        if ck.responded_at:
            minutes = _minutes_between(ck.sent_at, ck.responded_at)
        note = ck.note or ""
    needs_visit = bool(decision and decision.needs_visit) or any(e["action"] == "volunteer_visit" for e in esc) \
        or any(t in ("wellness_visit", "ride_to_cooling_center") for t in tasks)
    return {
        "episode_id": ep.id,
        "date": (ep.created_at or "")[:10],
        "hazard_type": ep.hazard.hazard_type,
        "event_name": ep.hazard.event_name,
        "episode_status": ep.status,
        "tier": decision.tier if decision else None,
        "channel": channel,
        "needs_visit": needs_visit,
        "outcome": outcome,
        "outcome_label": OUTCOME_LABEL.get(outcome, outcome),
        "minutes_to_reply": minutes,
        "note": note[:300],
        "escalations": esc,
        "volunteer_tasks": tasks,
        "lessons": [str(l.get("text", ""))[:300] for l in lessons],
    }


def _reliability(m: Member, recs: list[dict[str, Any]]) -> dict[str, Any]:
    contacted = [r for r in recs if r["outcome"] in ("ok", "needs_help", "no_reply")]
    replied = [r for r in contacted if r["outcome"] in ("ok", "needs_help")]
    minutes = [r["minutes_to_reply"] for r in replied if r["minutes_to_reply"] is not None]
    channels: dict[str, dict[str, int]] = {}
    for r in contacted:
        ch = channels.setdefault(r["channel"] or "unknown", {"contacted": 0, "replied": 0})
        ch["contacted"] += 1
        if r in replied:
            ch["replied"] += 1
    return {
        "episodes": len(recs),
        "contacted": len(contacted),
        "replied": len(replied),
        "reply_rate": round(len(replied) / len(contacted), 2) if contacted else None,
        "median_minutes_to_reply": int(statistics.median(minutes)) if minutes else None,
        "needs_help_count": sum(1 for r in recs if r["outcome"] == "needs_help"),
        "escalations": sum(len(r["escalations"]) for r in recs),
        "emergency_contact_notified": sum(1 for r in recs for e in r["escalations"] if e["action"] == "notify_emergency_contact"),
        "visits_needed": sum(1 for r in recs if r["needs_visit"]),
        "channels": channels,
        "has_emergency_contact": bool(m.emergency_contact_phone),
    }


def _insight(m: Member, recs: list[dict[str, Any]], rel: dict[str, Any]) -> str:
    first = m.name.split()[0]
    n = rel["episodes"]
    if n == 0:
        return f"No past episodes on record for {first}."
    contacted, replied, median = rel["contacted"], rel["replied"], rel["median_minutes_to_reply"]
    parts: list[str] = []
    if contacted == 0:
        parts.append(f"{first} was on the roster for {n} past episode{'s' if n != 1 else ''} but was never contacted.")
    elif replied == 0:
        chans = sorted(ch for ch, s in rel["channels"].items() if s["contacted"] and not s["replied"])
        parts.append(f"{first} has never replied to {', '.join(chans) if chans else 'messages'} ({contacted} of {contacted} unanswered).")
    else:
        head = f"{first} replied every time ({replied} of {contacted})" if replied == contacted else f"{first} replied {replied} of {contacted} times"
        if median is not None:
            head += f", usually within {median} minute{'s' if median != 1 else ''}"
        good = sorted(ch for ch, s in rel["channels"].items() if s["replied"])
        if len(good) == 1:
            head += f" via {good[0]}"
        parts.append(head + ".")
    if rel["emergency_contact_notified"]:
        who = m.emergency_contact_name or "The emergency contact"
        parts.append(f"Emergency contact {who} was notified {rel['emergency_contact_notified']} time{'s' if rel['emergency_contact_notified'] != 1 else ''}.")
    if rel["visits_needed"]:
        kinds = {r["hazard_type"] for r in recs if r["needs_visit"]}
        what = f"{kinds.pop().replace('_', ' ')} events" if len(kinds) == 1 else "events"
        parts.append(f"Needed a visit in {rel['visits_needed']} of {n} past {what}.")
    if rel["needs_help_count"]:
        parts.append(f"Asked for help {rel['needs_help_count']} time{'s' if rel['needs_help_count'] != 1 else ''}.")
    latest_lesson = next((l for r in recs for l in r["lessons"]), "")
    if latest_lesson:
        parts.append(f'Coordinator note: "{latest_lesson}"')
    return " ".join(parts)


def neighbor_history(member_id: str, exclude_episode_id: str = "") -> dict[str, Any]:
    """Deterministic per-member history: past episodes (newest first), a reliability summary, and an insight line."""
    m = store.member(member_id)
    if not m:
        return {"error": f"unknown member {member_id}"}
    recs = []
    for ep in store.episodes():  # newest first
        if ep.id == exclude_episode_id:
            continue
        r = episode_record(ep, m)
        if r:
            recs.append(r)
    rel = _reliability(m, recs)
    return {
        "member_id": m.id,
        "name": m.name,
        "preferred_channel": m.preferred_channel,
        "emergency_contact": m.emergency_contact_name,
        "episodes": recs,
        "reliability": rel,
        "insight": _insight(m, recs, rel),
    }


def compact_history(member_id: str, exclude_episode_id: str = "") -> Optional[dict[str, Any]]:
    """Tiny per-member summary for dashboard tiles; None when there is nothing to show."""
    h = neighbor_history(member_id, exclude_episode_id)
    if "error" in h or not h["episodes"]:
        return None
    last = h["episodes"][0]
    return {
        "episodes": len(h["episodes"]),
        "reply_rate": h["reliability"]["reply_rate"],
        "median_minutes_to_reply": h["reliability"]["median_minutes_to_reply"],
        "insight": h["insight"],
        "last": {k: last[k] for k in ("date", "hazard_type", "event_name", "outcome", "outcome_label", "minutes_to_reply", "channel", "needs_visit")}
        | {"escalated": bool(last["escalations"])},
    }


def community_history(limit: int = 5, exclude_episode_id: str = "") -> dict[str, Any]:
    """The last few episodes at community level: how many were contacted, replied, escalated, and lessons."""
    out = []
    for ep in store.episodes():
        if ep.id == exclude_episode_id:
            continue
        if len(out) >= limit:
            break
        cks = store.checkins(ep.id)
        contacted = sum(1 for c in cks if c.status != "failed")
        replied = sum(1 for c in cks if c.responded_at or c.status in ("ok", "needs_help"))
        lessons = [l for l in ep.stats.get("lessons", []) if isinstance(l, dict)]
        out.append({
            "episode_id": ep.id,
            "date": (ep.created_at or "")[:10],
            "hazard_type": ep.hazard.hazard_type,
            "event_name": ep.hazard.event_name,
            "status": ep.status,
            "activated": bool(ep.assessment and ep.assessment.activate) if ep.assessment else ep.status not in ("stood_down",),
            "contacted": contacted,
            "replied": replied,
            "needs_help": sum(1 for c in cks if c.status == "needs_help" or (c.status == "escalated" and c.responded_at)),
            "escalated": sum(1 for t in ep.timeline if t.kind == "escalation"),
            "volunteer_assignments": len(ep.logistics.assignments) if ep.logistics else 0,
            "lessons": [{"member_id": l.get("member_id", ""), "text": str(l.get("text", ""))[:300]} for l in lessons],
            "brief": str(ep.stats.get("brief", ""))[:400],
        })
    return {
        "episodes": out,
        "totals": {
            "episodes": len(out),
            "contacted": sum(e["contacted"] for e in out),
            "replied": sum(e["replied"] for e in out),
            "escalated": sum(e["escalated"] for e in out),
            "lessons": sum(len(e["lessons"]) for e in out),
        },
    }


# ---------------------------------------------------------------- Strands tools

@tool(context=True)
def get_neighbor_history(tool_context: ToolContext, member_id: str) -> dict:
    """What happened with this neighbor in past episodes: for each earlier hazard the tier, channel used, whether
    they replied (ok / needs_help / no reply) and how many minutes it took, any escalations (volunteer visit,
    emergency contact notified), and coordinator notes. Includes a reliability summary and an "insight" line.
    Use it to pick the channel that has worked before, decide whether a visit is likely needed, and whether to go
    to the emergency contact first.
    Args:
        member_id: id from get_roster or get_checkin_status
    """
    out = neighbor_history(member_id, exclude_episode_id=episode_id_from(tool_context.invocation_state))
    if "error" in out:
        return out
    out["agentcore_memories"] = agentcore_memory.retrieve_member_memories(
        member_id, query=f"{out['name']} check-in reply behaviour, emergency contact, visits, what helped")
    return out


@tool(context=True)
def get_community_history(tool_context: ToolContext) -> dict:
    """The last five episodes for this community: hazard, how many neighbors were contacted, replied, and
    escalated, volunteer assignments, and lessons the coordinator recorded. Use it to calibrate the response."""
    return community_history(limit=5, exclude_episode_id=episode_id_from(tool_context.invocation_state))


# ---------------------------------------------------------------- AgentCore sync (no-op unless configured)

def sync_to_agentcore(episode_id: str, member_id: str = "") -> dict[str, Any]:
    """Write one outcome event per member for this episode to AgentCore Memory (idempotent per member/episode)."""
    if not agentcore_memory.enabled():
        return {"skipped": "not configured"}
    ep = store.episode(episode_id)
    if ep is None:
        return {"error": "unknown episode"}
    members = [store.member(member_id)] if member_id else store.members()
    written = 0
    for m in members:
        if m is None:
            continue
        rec = episode_record(ep, m)
        if rec and agentcore_memory.record_member_outcome(ep, m, rec):
            written += 1
    return {"written": written}
