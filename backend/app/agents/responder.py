"""The agent that answers a neighbour who replies in their own words.

The check-in page gives a neighbour two buttons, and most will use them. But some will write back
instead — "the ac died last night and i feel a bit dizzy" — and a keyword match on "ok" and "help"
either misreads that or drops it. This agent reads the reply, works out whether the neighbour is fine
or needs help, answers them in plain language on the same channel, and records the outcome so the
coordinator's dashboard and the follow-up agent both see it.

Two things are deliberately not left to the model:

* **Emergencies.** A reply that mentions chest pain, trouble breathing, fainting or similar is answered
  with "call 911" immediately, before any model call, and recorded as needing help. A model that is
  slow, throttled or simply wrong must never sit between a person and that sentence.
* **Actions.** This agent can talk. It cannot dispatch a volunteer, notify an emergency contact or
  escalate; those stay behind the coordinator's approval gate, where the rest of the system puts them.
  Answering a neighbour who just wrote to you is a reply, not a new outbound campaign.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from strands import Agent

from ..config import settings
from ..events import bus
from ..models import TimelineEntry, now_iso
from ..store import store
from .model_factory import build_model

log = logging.getLogger("porchlight.responder")

# Words that mean "stop reading and tell them to call 911". Deliberately blunt and deliberately first.
EMERGENCY = re.compile(
    r"\b(chest pain|can'?t breathe|cannot breathe|trouble breathing|breathing problem|passed out|"
    r"fainted|unconscious|collapsed|heat ?stroke|seizure|stroke|heart attack|bleeding|"
    r"no puedo respirar|dolor de pecho|desmay)\w*", re.I)

EMERGENCY_REPLY = (
    "This sounds like an emergency. Please call 911 now, or ask someone near you to call for you. "
    "Stay somewhere cool and keep sipping water until help arrives. Your coordinator has been alerted."
)

PROMPT = """You are Porchlight, replying by text message to a neighbour during a weather emergency.

You are talking to the neighbour themselves, not to the coordinator. Write to them directly, warmly, and
in very plain language. Two or three short sentences, under 45 words. No jargon, no lists, no emoji.
If they say they are struggling in any way, tell them help is being arranged. Always suggest calling 911
if they feel worse. Reply in this language: {language}.

What is happening: {hazard}
Nearest cooled public building to them: {resource}
What we already know about them: {risks}

Answer with the message to send, then a final line that is exactly "STATUS: ok" or "STATUS: needs_help".
Choose needs_help if there is any doubt at all. Write nothing after that line."""


def _emergency(text: str) -> bool:
    return bool(EMERGENCY.search(text or ""))


def _context(ep: Any, member: Any) -> dict[str, str]:
    """Everything the reply needs, gathered directly rather than discovered through tool calls.

    A neighbour waiting on a text is the one place in this system where latency is felt by a person, and
    every tool call is another full round trip to the model. The graph is where the agents explore; here
    the answer is short and the context is small, so it is handed over up front.
    """
    from ..feeds.places import haversine_km

    h = ep.hazard
    hazard = f"{h.event_name}. {h.headline or ''}".strip()
    if ep.assessment and ep.assessment.plain_summary:
        hazard = ep.assessment.plain_summary

    nearest, best = "none on file", None
    for r in store.resources():
        if r.kind in ("cooling_center", "warming_center", "shelter", "clean_air"):
            d = haversine_km(member.lat, member.lon, r.lat, r.lon)
            if best is None or d < best:
                best, nearest = d, f"{r.name}, {r.address} ({d:.1f} km away)" + (f", phone {r.phone}" if r.phone else "")
    risks = ", ".join(member.risk_factors) or "none recorded"
    return {"hazard": hazard[:400], "resource": nearest, "risks": risks}


def build_responder(ep: Any, member: Any) -> Agent:
    """A single-turn agent: no tools, so one round trip rather than three."""
    ctx = _context(ep, member)
    return Agent(
        name="responder",
        model=build_model(),
        system_prompt=PROMPT.format(language=getattr(member, "language", "en") or "en", **ctx),
        callback_handler=None,
    )


STATUS_LINE = re.compile(r"^\s*STATUS\s*:\s*(ok|needs[_ ]?help)\s*$", re.I | re.M)


def parse(raw: str) -> dict[str, Any] | None:
    """Split the model's answer into the message for the neighbour and the status for the dashboard."""
    if not raw or not raw.strip():
        return None
    m = STATUS_LINE.search(raw)
    status = "needs_help"
    if m:
        status = "ok" if m.group(1).lower() == "ok" else "needs_help"
        raw = raw[:m.start()]
    reply = raw.strip().strip('"').strip()
    return {"reply": reply, "status": status} if reply else None


async def respond(ep: Any, member: Any, text: str) -> dict[str, Any]:
    """Work out how to answer one free-text reply. Returns {'reply', 'status', 'source'}."""
    # 1. Emergencies never wait for a model.
    if _emergency(text):
        bus.emit("escalation", f"{member.name} reported an emergency; told to call 911 immediately",
                 episode_id=ep.id, member_id=member.id, agent="responder")
        return {"reply": EMERGENCY_REPLY, "status": "needs_help", "source": "safety_rule"}

    # 2. Otherwise let the agent read it.
    try:
        agent = build_responder(ep, member)
        result = await agent.invoke_async(
            f"{member.name} replied to the check-in message: \"{text}\"",
            invocation_state={"episode_id": ep.id},
        )
        parsed = parse(str(result))
        if parsed:
            return {**parsed, "source": "agent"}
    except Exception as e:  # noqa: BLE001
        log.warning("responder failed for %s: %s", member.name, e)

    # 3. The model was unavailable or said nothing usable. A neighbour who wrote in still gets an answer.
    return {
        "reply": ("Thank you for letting us know. Your coordinator has seen this and will follow up. "
                  "Please call 911 if you feel unwell."),
        "status": "needs_help",
        "source": "fallback",
    }


def record(ep: Any, member: Any, checkin_token: str, text: str, outcome: dict[str, Any]) -> None:
    """Write the neighbour's own words and the agent's answer where the coordinator will see them.

    Answering closes every conversation open with this neighbour, not only the one they happened to
    reply to. Someone who has told us how they are should not still be chased by another episode.
    """
    from ..reminders import resolve_all_for

    status = outcome["status"]
    closed = resolve_all_for(member.id, status, f"said: {text[:120]}")
    if not closed:  # nothing was open (already answered); still record against the one we were given
        def _apply(c):
            c.status = status
            c.responded_at = c.responded_at or now_iso()
            c.note = f"said: {text[:120]}"

        store.mutate_checkin(checkin_token, _apply)
    store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(
        kind="checkin",
        text=f"{member.name} wrote: “{text[:160]}” — Porchlight replied: “{outcome['reply'][:160]}”",
    )))
    bus.emit("checkin", f"{member.name} replied: {status.replace('_', ' ')}",
             episode_id=ep.id, member_id=member.id, status=status,
             said=text[:200], answered=outcome["reply"][:200], source=outcome["source"], agent="responder")

    # Someone who has just said they need help is the clearest evidence there is.
    if status == "needs_help":
        try:
            from .. import deployments

            for c in store.checkins(ep.id):
                if c.member_id == member.id and c.status == "needs_help":
                    deployments.propose_for(c)
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("could not propose a visit for %s: %s", member.name, e)
