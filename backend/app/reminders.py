"""Chasing a neighbour who has not answered, without becoming the thing that harasses them.

The rules are deliberately simple, deterministic and outside the model's control, because "how often do
we text an anxious 78-year-old" is a policy decision, not something to re-derive from a prompt each time:

* **One word back ends it.** A reply resolves every open check-in that neighbour has, across every
  episode. Answering "I'm fine" once should not leave three other conversations still nagging them.
* **Reminders are paced, and counted per person.** At most one every REMINDER_GAP_MINUTES, counted from
  the last time we said anything to them. A neighbour can be in several episodes at once — a heat wave
  and an outage, or a coordinator testing — and they are one person who has been texted N times, not
  three rows that have each been texted once.
* **Silence runs out.** After MAX_REMINDERS with no word, the check-in becomes `critical` and stops.
  Nobody is texted a fifth time; instead the coordinator is told that this person has gone quiet, which
  is the thing that actually needs a human.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from .config import settings
from .events import bus
from .models import TimelineEntry, now_iso
from .store import store

log = logging.getLogger("porchlight.reminders")

OPEN = ("sent", "delivered")


def _age_minutes(ts: str) -> float:
    """Minutes since an ISO timestamp. Unparseable or missing means "long ago"."""
    if not ts:
        return 1e9
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (datetime.now(UTC) - t).total_seconds() / 60.0


def open_checkins_for(member_id: str) -> list:
    """Every check-in still waiting on this neighbour, in any episode that is still running."""
    out = []
    for c in store.checkins():
        if c.member_id != member_id or c.status not in OPEN:
            continue
        ep = store.episode(c.episode_id)
        if ep and ep.status in ("monitoring", "escalating", "dispatching"):
            out.append(c)
    return out


def remember(member_id: str) -> None:
    """Write this neighbour's outcome to long-term memory, if AgentCore Memory is configured.

    What is worth keeping is not that a message was sent but how they responded: which channel reached
    them, how long they took, whether it took a visit. The next hazard's triage reads it back.
    """
    try:
        from .agents.tools_memory import sync_to_agentcore

        for c in store.checkins():
            if c.member_id == member_id and c.responded_at:
                sync_to_agentcore(c.episode_id, member_id)
                return
    except Exception as e:  # noqa: BLE001 — never let remembering break responding
        log.debug("could not record %s in long-term memory: %s", member_id, e)


def resolve_all_for(member_id: str, status: str, note: str) -> list[str]:
    """A neighbour answered. Close every conversation we have open with them, not just the newest.

    Without this, a roster that has been through several episodes keeps chasing someone who has already
    said they are fine, which is precisely the behaviour that makes people stop reading the messages.
    """
    closed: list[str] = []
    for c in open_checkins_for(member_id):
        def _apply(x, _s=status, _n=note):
            x.status = _s
            x.responded_at = now_iso()
            x.note = _n

        store.mutate_checkin(c.token, _apply)
        closed.append(c.episode_id)
    if closed:
        remember(member_id)
    return closed


def gap_minutes() -> float:
    """The wait between reminders. A stored value set from the app wins over backend/.env, the same
    way the follow-up grace period does, so pacing can be changed without a restart."""
    try:
        stored = store.get_setting("reminder_gap_minutes", None)
        if stored is not None:
            return max(0.0, float(stored))
    except (TypeError, ValueError):
        pass
    return float(settings.REMINDER_GAP_MINUTES)


def due_for_reminder(c) -> bool:
    """Is this check-in owed another nudge yet?"""
    if c.status not in OPEN:
        return False
    if c.reminders_sent >= settings.MAX_REMINDERS:
        return False
    since = _age_minutes(c.last_contact_at or c.sent_at)
    return since >= gap_minutes()


def exhausted(c) -> bool:
    """Reminders used up and still nothing back."""
    return (c.status in OPEN
            and c.reminders_sent >= settings.MAX_REMINDERS
            and _age_minutes(c.last_contact_at or c.sent_at) >= gap_minutes())


def reminder_text(member, episode, attempt: int) -> str:
    """Escalating in seriousness but never in volume. Short, and always easy to answer."""
    event = episode.hazard.event_name
    if attempt == 1:
        return (f"Hi {member.name.split()[0]}, checking again about the {event}. "
                f"Are you doing okay? Just reply OK, or tell me how you're doing.")
    if attempt == 2:
        return (f"{member.name.split()[0]}, we still haven't heard from you about the {event} and we'd "
                f"like to know you're alright. Reply OK if you're fine, or HELP if you need anything.")
    return (f"{member.name.split()[0]}, this is our last message. If we don't hear back we'll ask someone "
            f"to come check on you. Reply OK if you're safe. Call 911 if this is an emergency.")


def mark_critical(c, member) -> None:
    """Out of reminders and still silent. Stop texting; make it the coordinator's problem."""
    def _apply(x):
        x.status = "critical"
        x.note = (f"No reply after {settings.MAX_REMINDERS} attempts over "
                  f"{settings.MAX_REMINDERS * gap_minutes():.0f} minutes")

    store.mutate_checkin(c.token, _apply)
    ep = store.episode(c.episode_id)
    if ep:
        store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(
            kind="critical",
            text=(f"{member.name} has not answered {settings.MAX_REMINDERS} messages. "
                  f"Marked critical — someone should go round."))))
        bus.emit("critical", f"{member.name} has not answered {settings.MAX_REMINDERS} messages",
                 episode_id=ep.id, member_id=member.id, status="critical", agent="reminders")
    log.info("marked %s critical on %s", member.name, c.episode_id)
    _propose_a_visit(c)


def _propose_a_visit(c) -> None:
    """Silence that has run out of reminders is evidence enough to suggest someone goes round."""
    try:
        from . import deployments

        deployments.propose_for(store.checkin(c.token))
    except Exception as e:  # noqa: BLE001 — a routing outage must not stop the escalation itself
        log.warning("could not propose a visit for %s: %s", c.member_id, e)


def record_reminder(c) -> None:
    def _apply(x):
        x.reminders_sent = x.reminders_sent + 1
        x.last_contact_at = now_iso()

    store.mutate_checkin(c.token, _apply)


# --------------------------------------------------------------------------- per-person view
# The unit of pacing is a person, not a check-in row. Everything below reads and writes across every
# open row a neighbour has, so a second episode cannot double their messages.


def members_awaiting() -> list[str]:
    """Every neighbour with at least one conversation still open, each listed once."""
    seen: list[str] = []
    for c in store.checkins():
        if c.status in OPEN and c.member_id not in seen:
            ep = store.episode(c.episode_id)
            if ep and ep.status in ("monitoring", "escalating"):
                seen.append(c.member_id)
    return seen


def oldest_open_for(member_id: str):
    """The conversation that has been waiting longest; its hazard is what a reminder should mention."""
    rows = open_checkins_for(member_id)
    return min(rows, key=lambda c: c.sent_at) if rows else None


def attempts_for(member_id: str) -> int:
    """How many reminders this person has had, across every episode."""
    rows = open_checkins_for(member_id)
    return max((c.reminders_sent for c in rows), default=0)


def record_reminder_for(member_id: str) -> None:
    """Count one reminder against every open row, so the tally follows the person."""
    stamp = now_iso()
    for c in open_checkins_for(member_id):
        def _apply(x, _s=stamp):
            x.reminders_sent = x.reminders_sent + 1
            x.last_contact_at = _s

        store.mutate_checkin(c.token, _apply)


def mark_critical_for(member) -> None:
    """Out of reminders. Close every open conversation as critical, not just the one we looked at."""
    for c in open_checkins_for(member.id):
        mark_critical(c, member)
