"""After-action metrics for one episode. Pure and deterministic: no model, no store, no network.

Everything a partner has to report to a funder or emergency manager after a check-in event is already in the
episode record, the check-ins, and the approvals. This module turns those into numbers; the optional narrative
(agents/report_agent.py) only ever paraphrases what is computed here.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime
from typing import Any, Iterable, Optional

from .models import Approval, Checkin, Episode, Member, Volunteer

REPLIED_STATUSES = {"ok", "needs_help"}
NEEDED_HELP_STATUSES = {"needs_help", "escalated"}
_ESCALATION_RE = re.compile(r"escalated \(([a-z_0-9]+)\)")


def _dt(s: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string from the models; '' / None / garbage -> None."""
    if not s or not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:  # treat naive stamps as UTC so they compare with now_iso() values
        from datetime import timezone

        d = d.replace(tzinfo=timezone.utc)
    return d


def _minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


def _median(xs: Iterable[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    return round(statistics.median(vals), 1) if vals else None


def _pct(num: int, den: int) -> Optional[float]:
    return round(100.0 * num / den, 1) if den else None


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in items:
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def compute_metrics(episode: Episode, checkins: list[Checkin], approvals: list[Approval],
                    members: list[Member], volunteers: list[Volunteer]) -> dict[str, Any]:
    """Aggregate one episode into funder/EM-ready numbers. Safe on partial episodes (assessing, stood down)."""
    ep = episode
    m_by_id = {m.id: m for m in members}
    v_by_id = {v.id: v for v in volunteers}
    tier_of: dict[str, int] = {d.member_id: d.tier for d in (ep.triage.decisions if ep.triage else [])}
    checkins = sorted(checkins, key=lambda c: c.sent_at or "")

    # ---- timeline-derived moments
    detected = _dt(ep.hazard.detected_at) or _dt(ep.created_at)
    tl = ep.timeline or []
    assessed_at = next((_dt(t.ts) for t in tl if t.kind == "assessment"), None)
    closed_at = next((_dt(t.ts) for t in reversed(tl) if t.kind == "closed"), None)

    # ---- outreach
    contacted = [c for c in checkins if c.status != "failed"]
    failed = [c for c in checkins if c.status == "failed"]
    replied = [c for c in contacted if c.responded_at]
    first_sent = min((_dt(c.sent_at) for c in contacted if _dt(c.sent_at)), default=None)
    last_sent = max((_dt(c.sent_at) for c in contacted if _dt(c.sent_at)), default=None)
    first_reply = min((_dt(c.responded_at) for c in replied if _dt(c.responded_at)), default=None)
    reply_minutes = [_minutes(_dt(c.sent_at), _dt(c.responded_at)) for c in replied]

    tier1 = [c for c in contacted if tier_of.get(c.member_id) == 1]
    tier1_replied = [c for c in tier1 if c.responded_at]

    planned_by_tier = _count(f"tier_{t}" for t in tier_of.values())
    contacted_by_tier = _count(f"tier_{tier_of.get(c.member_id, 'untriaged')}" for c in contacted)
    sent_by_channel = _count(c.channel or "unknown" for c in contacted)
    failed_by_channel = _count(c.channel or "unknown" for c in failed)
    # Failures for unknown members never create a Checkin; the dispatch tool still counted them.
    failed_total = max(len(failed), int(ep.stats.get("messages_failed", 0) or 0))

    status_counts = _count(c.status for c in checkins)
    needed_help = [c for c in contacted if c.status in NEEDED_HELP_STATUSES]
    no_reply = [c for c in contacted if not c.responded_at and c.status in ("sent", "delivered", "no_response")]

    # ---- escalations: approval rows are the structured source; policy-approved ones only leave timeline entries
    esc_actions: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for a in approvals:
        if a.kind != "escalation":
            continue
        inp = (a.payload or {}).get("input", {}) or {}
        mid = str(inp.get("member_id", ""))
        action = str(inp.get("action", "")) or "unknown"
        seen_keys.add((mid, action))
        esc_actions.append({
            "member_id": mid, "member_name": m_by_id[mid].name if mid in m_by_id else mid,
            "action": action, "reason": str(inp.get("reason", "")), "decision": _decision(a.status),
            "requested_at": a.created_at, "resolved_at": a.resolved_at,
            "decision_minutes": _minutes(_dt(a.created_at), _dt(a.resolved_at)),
            "outcome": _escalation_outcome(mid, action, tl, a.status),
        })
    name_to_id = {m.name: m.id for m in members}
    for t in tl:
        if t.kind != "escalation":
            continue
        mt = _ESCALATION_RE.search(t.text or "")
        action = mt.group(1) if mt else "unknown"
        name = (t.text or "").split(" escalated", 1)[0].strip()
        mid = name_to_id.get(name, "")
        if (mid, action) in seen_keys:
            continue
        seen_keys.add((mid, action))
        esc_actions.append({
            "member_id": mid, "member_name": name or mid, "action": action,
            "reason": (t.text or "").split(": ", 1)[1] if ": " in (t.text or "") else "",
            "decision": "policy", "requested_at": t.ts, "resolved_at": t.ts, "decision_minutes": 0.0,
            "outcome": str((t.data or {}).get("detail", "")),
        })
    esc_actions.sort(key=lambda e: e.get("requested_at") or "")

    # ---- approvals (coordinator decisions)
    apr_rows = []
    for a in sorted(approvals, key=lambda a: a.created_at):
        apr_rows.append({
            "id": a.id, "kind": a.kind, "title": a.title, "agent": a.agent_name, "decision": _decision(a.status),
            "edited": bool(a.edits), "note": a.decision_note, "created_at": a.created_at, "resolved_at": a.resolved_at,
            "decision_minutes": _minutes(_dt(a.created_at), _dt(a.resolved_at)),
        })
    decided = [r for r in apr_rows if r["decision"] != "pending"]
    outreach_approved_at = min((_dt(a.resolved_at) for a in approvals if a.kind == "outreach_dispatch" and a.status == "approved" and _dt(a.resolved_at)), default=None)

    # ---- volunteers
    assignments = ep.logistics.assignments if ep.logistics else []
    asg_rows = [{
        "volunteer_id": x.volunteer_id, "volunteer_name": v_by_id[x.volunteer_id].name if x.volunteer_id in v_by_id else x.volunteer_id,
        "member_id": x.member_id, "member_name": m_by_id[x.member_id].name if x.member_id in m_by_id else x.member_id,
        "task": x.task, "reason": x.reason, "priority": x.priority,
    } for x in assignments]
    gaps = list(ep.logistics.gaps) if ep.logistics else []

    # ---- per-member table (everyone contacted; triaged-but-not-contacted members are listed too)
    esc_by_member: dict[str, str] = {}
    for e in esc_actions:
        if e["decision"] in ("approved", "policy"):  # a declined escalation never happened
            esc_by_member[e["member_id"]] = e["action"]  # last real escalation wins
    rows = []
    for c in checkins:
        m = m_by_id.get(c.member_id)
        rows.append({
            "member_id": c.member_id, "name": m.name if m else c.member_id, "tier": tier_of.get(c.member_id),
            "language": m.language if m else "", "channel": c.channel, "sent_at": c.sent_at, "status": c.status,
            "replied_at": c.responded_at or None, "reply_minutes": _minutes(_dt(c.sent_at), _dt(c.responded_at)),
            "escalation": esc_by_member.get(c.member_id) or (c.note.split(":", 1)[0] if c.status == "escalated" and ":" in c.note else None),
            "note": c.note,
        })
    contacted_ids = {c.member_id for c in checkins}
    for mid, tier in tier_of.items():
        if mid in contacted_ids or tier == 0:
            continue
        m = m_by_id.get(mid)
        rows.append({"member_id": mid, "name": m.name if m else mid, "tier": tier, "language": m.language if m else "",
                     "channel": "", "sent_at": "", "status": "not_contacted", "replied_at": None, "reply_minutes": None,
                     "escalation": esc_by_member.get(mid), "note": ""})
    rows.sort(key=lambda r: ((r["tier"] if r["tier"] is not None else 9), r["name"]))

    return {
        "episode_id": ep.id,
        "status": ep.status,
        "activated": bool(ep.assessment and ep.assessment.activate),
        "timing": {
            "detected_at": ep.hazard.detected_at or ep.created_at,
            "assessed_at": assessed_at.isoformat(timespec="seconds") if assessed_at else None,
            "first_message_at": first_sent.isoformat(timespec="seconds") if first_sent else None,
            "last_message_at": last_sent.isoformat(timespec="seconds") if last_sent else None,
            "first_reply_at": first_reply.isoformat(timespec="seconds") if first_reply else None,
            "closed_at": closed_at.isoformat(timespec="seconds") if closed_at else None,
            "minutes_detection_to_assessment": _minutes(detected, assessed_at),
            "minutes_detection_to_first_message": _minutes(detected, first_sent),
            "minutes_approval_to_first_message": _minutes(outreach_approved_at, first_sent),
            "minutes_detection_to_first_reply": _minutes(detected, first_reply),
            "median_minutes_to_reply": _median(reply_minutes),
            "max_minutes_to_reply": max([x for x in reply_minutes if x is not None], default=None),
            "median_coordinator_decision_minutes": _median(r["decision_minutes"] for r in decided),
            "duration_minutes": _minutes(detected, closed_at or _dt(ep.updated_at)),
        },
        "roster": {
            "members_total": len(members),
            "members_opted_in": sum(1 for m in members if m.opted_in),
            "triaged": len(tier_of),
            "planned_by_tier": planned_by_tier,
        },
        "outreach": {
            "messages_attempted": len(checkins) + max(0, failed_total - len(failed)),
            "contacted": len(contacted),
            "failed": failed_total,
            "sent_by_channel": sent_by_channel,
            "failed_by_channel": failed_by_channel,
            "contacted_by_tier": contacted_by_tier,
            "status_counts": status_counts,
            "replied": len(replied),
            "replied_ok": sum(1 for c in contacted if c.status == "ok"),
            "needed_help": len(needed_help),
            "no_reply": len(no_reply),
            "response_rate_pct": _pct(len(replied), len(contacted)),
            "tier1_contacted": len(tier1),
            "tier1_replied": len(tier1_replied),
            "tier1_response_rate_pct": _pct(len(tier1_replied), len(tier1)),
        },
        "escalations": {
            "count": len(esc_actions),
            "by_action": _count(e["action"] for e in esc_actions),
            "by_decision": _count(e["decision"] for e in esc_actions),
            "members_escalated": len({e["member_id"] for e in esc_actions}),
            "items": esc_actions,
        },
        "approvals": {
            "total": len(apr_rows),
            "approved": sum(1 for r in apr_rows if r["decision"] == "approved"),
            "declined": sum(1 for r in apr_rows if r["decision"] == "declined"),
            "pending": sum(1 for r in apr_rows if r["decision"] == "pending"),
            "edited": sum(1 for r in apr_rows if r["edited"]),
            "by_kind": _count(r["kind"] for r in apr_rows),
            "median_decision_minutes": _median(r["decision_minutes"] for r in decided),
            "max_decision_minutes": max([r["decision_minutes"] for r in decided if r["decision_minutes"] is not None], default=None),
            "items": apr_rows,
        },
        "volunteers": {
            "assignments": len(asg_rows),
            "by_task": _count(r["task"] for r in asg_rows),
            "by_volunteer": _count(r["volunteer_name"] for r in asg_rows),
            "volunteers_used": len({r["volunteer_id"] for r in asg_rows}),
            "volunteers_available": sum(1 for v in volunteers if v.available),
            "items": asg_rows,
        },
        "gaps": gaps,
        "unresolved": {
            "no_reply": [r["name"] for r in rows if r["status"] in ("sent", "delivered", "no_response")],
            "failed_delivery": [r["name"] for r in rows if r["status"] == "failed"],
            "not_contacted": [r["name"] for r in rows if r["status"] == "not_contacted"],
            "pending_approvals": [r["title"] for r in apr_rows if r["decision"] == "pending"],
            "gaps": gaps,
        },
        "brief": str(ep.stats.get("brief", "") or ""),
        "per_member": rows,
    }


def _decision(status: str) -> str:
    return {"approved": "approved", "rejected": "declined", "pending": "pending"}.get(status, status)


def _escalation_outcome(member_id: str, action: str, timeline: list, status: str) -> str:
    if status == "rejected":
        return "declined by coordinator"
    if status == "pending":
        return "awaiting coordinator"
    for t in timeline:
        if t.kind == "escalation" and f"({action})" in (t.text or ""):
            detail = str((t.data or {}).get("detail", ""))
            if detail:
                return detail
    return "approved"
