"""Twilio Programmable Voice webhooks: keypad check-ins and call outcomes.

POST /api/voice/keypress/{token}  <Gather> action: Digits=1 -> ok, Digits=2 -> needs_help (same effect as /api/checkin)
POST /api/voice/status/{token}    StatusCallback: no-answer/busy/failed/canceled -> no_response, completed -> noted

Requests are verified with Twilio's X-Twilio-Signature (HMAC-SHA1 over the URL + sorted POST params) unless
VOICE_SKIP_SIGNATURE=true is set for local testing.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import voice_sim
from .agents.runner import runner
from .channels.twilio_voice import PROMPTS, build_reply_twiml, build_twiml, lang
from .config import settings
from .events import bus
from .models import Checkin, TimelineEntry, now_iso
from .store import store

log = logging.getLogger("porchlight.voice")
router = APIRouter()

FAILED_CALL = {"no-answer", "busy", "failed", "canceled"}


# ------------------------------------------------------------------ simulated call recording (not a Twilio webhook)

class VoiceSimRequest(BaseModel):
    member_id: str
    episode_id: str | None = None
    outcome: str = "auto"  # auto | ok | needs_help
    call_script: str = ""


@router.post("/api/voice/sim")
def create_voice_sim(req: VoiceSimRequest) -> dict[str, Any]:
    """Render the check-in call for one neighbour as audio, voiced by Amazon Polly. Dials nobody."""
    member = store.member(req.member_id)
    if member is None:
        raise HTTPException(404, "unknown neighbour")
    episode = store.episode(req.episode_id) if req.episode_id else voice_sim.current_episode()
    try:
        return voice_sim.simulate(member, episode, req.outcome, req.call_script)
    except Exception as e:
        log.warning("voice simulation failed for %s: %s", member.id, e)
        raise HTTPException(503, f"Amazon Polly could not record the call: {e}") from e


@router.get("/api/voice/sim/{sim_id}.wav")
def get_voice_sim(sim_id: str) -> FileResponse:
    path = voice_sim.audio_path(sim_id)
    if path is None:
        raise HTTPException(404, "no such recording")
    return FileResponse(path, media_type="audio/wav")


# ------------------------------------------------------------------ signature validation

def compute_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(auth_token, url + concat(sorted key+value)))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(url: str, params: dict[str, str], signature: str, auth_token: str) -> bool:
    if not signature or not auth_token:
        return False
    return hmac.compare_digest(compute_signature(url, params, auth_token), signature.strip())


def _candidate_urls(request: Request) -> list[str]:
    """Twilio signs the URL it dialled. Behind a tunnel that is PUBLIC_BASE_URL + path, not the local socket."""
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    cands = [f"{settings.PUBLIC_BASE_URL}{path}{query}", str(request.url)]
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if proto and host:
        cands.append(f"{proto}://{host}{path}{query}")
    return list(dict.fromkeys(cands))


async def _twilio_params(request: Request) -> dict[str, str]:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if settings.VOICE_SKIP_SIGNATURE:
        return params
    sig = request.headers.get("x-twilio-signature", "")
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(503, "voice webhooks need TWILIO_AUTH_TOKEN (or VOICE_SKIP_SIGNATURE=true for local tests)")
    if not any(verify_signature(u, params, sig, settings.TWILIO_AUTH_TOKEN) for u in _candidate_urls(request)):
        log.warning("rejected voice webhook with bad signature for %s", request.url.path)
        raise HTTPException(403, "invalid Twilio signature")
    return params


def _twiml(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


# ------------------------------------------------------------------ recording (mirrors POST /api/checkin)

async def record_checkin(c: Checkin, status: str, note: str) -> None:
    c.status = status  # type: ignore[assignment]
    c.responded_at = now_iso()
    c.note = note[:300]
    store.put_checkin(c)
    m = store.member(c.member_id)
    ep = store.episode(c.episode_id)
    name = m.name if m else c.member_id
    bus.emit("checkin", f"{name} checked in: {'OK' if status == 'ok' else 'NEEDS HELP'}" + (f" — {note[:120]}" if note else ""),
             episode_id=c.episode_id, member_id=c.member_id, status=status, note=note[:300], channel="voice")
    if ep:
        def _rec(e):
            e.timeline.append(TimelineEntry(kind="checkin", text=f"{name}: {status}", data={"note": note[:300], "channel": "voice"}))
            e.stats["responses"] = e.stats.get("responses", 0) + 1

        store.mutate_episode(ep.id, _rec)
        if status == "needs_help":
            await runner.run_followup(ep.id)


# ------------------------------------------------------------------ webhooks

@router.post("/api/voice/keypress/{token}")
async def voice_keypress(token: str, request: Request) -> Response:
    params = await _twilio_params(request)
    c = store.checkin(token)
    if not c:
        return _twiml(build_reply_twiml("unknown", "en"))
    m = store.member(c.member_id)
    language = lang(m.language if m else "en")
    digits = params.get("Digits", "").strip()
    if c.status in ("ok", "needs_help", "escalated"):  # already answered (second keypress or a web check-in)
        return _twiml(build_reply_twiml("thanks_ok" if c.status == "ok" else "thanks_help", language))
    if digits not in ("1", "2"):
        return _twiml(build_twiml("", language, token, preface=PROMPTS[language]["retry"]))
    status = "ok" if digits == "1" else "needs_help"
    await record_checkin(c, status, f"pressed {digits} on the phone")
    return _twiml(build_reply_twiml("thanks_ok" if status == "ok" else "thanks_help", language))


@router.post("/api/voice/status/{token}")
async def voice_status(token: str, request: Request) -> dict[str, Any]:
    params = await _twilio_params(request)
    call_status = params.get("CallStatus", "").strip().lower()
    c = store.checkin(token)
    if not c:
        return {"recorded": False, "detail": "unknown check-in"}
    m = store.member(c.member_id)
    name = m.name if m else c.member_id
    ep = store.episode(c.episode_id)
    changed = False
    if call_status in FAILED_CALL and c.status in ("sent", "delivered", "failed"):
        c.status = "no_response"
        c.note = f"phone call: {call_status}"
        changed = True
        text = f"{name}: phone call {call_status} — no answer yet; the follow-up agent will retry"
    elif call_status == "completed" and c.status in ("sent", "delivered"):
        c.note = "phone call answered, no key pressed"
        changed = True
        text = f"{name}: phone call answered but no key was pressed"
    if changed:
        store.put_checkin(c)
        bus.emit("status", text, episode_id=c.episode_id, member_id=c.member_id, call_status=call_status, channel="voice", status=c.status)
        if ep:
            store.mutate_episode(ep.id, lambda e: e.timeline.append(TimelineEntry(kind="voice", text=text, data={"call_status": call_status})))
    return {"recorded": changed, "status": c.status, "call_status": call_status}
