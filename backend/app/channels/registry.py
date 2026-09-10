"""Pick a transport for a member. Falls back through channels the member can actually receive."""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings
from ..models import Member
from .base import DeliveryResult
from .console import ConsoleProvider
from .ses_email import SESEmailProvider
from .telegram import TelegramProvider
from .twilio_sms import TwilioSMSProvider
from .twilio_voice import TwilioVoiceProvider, spoken_text, voice_for

log = logging.getLogger("porchlight.channels")

_PROVIDERS = {
    "voice": TwilioVoiceProvider(),
    "sms": TwilioSMSProvider(),
    "telegram": TelegramProvider(),
    "email": SESEmailProvider(),
}
_CONSOLE = ConsoleProvider()


def available_channels() -> dict[str, bool]:
    return {name: p.configured() for name, p in _PROVIDERS.items()} | {"console": settings.SEND_MODE != "live"}


def _address(member: Member, channel: str) -> str:
    if channel == "sms" or channel == "voice":
        return settings.DEMO_OVERRIDE_PHONE or member.phone
    if channel == "telegram":
        return settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID or member.telegram_chat_id
    if channel == "email":
        return settings.DEMO_OVERRIDE_EMAIL or member.email
    return ""


def live_for(member: Member) -> bool:
    """Whether this member's messages should really be sent right now.

    DEMO_LIVE_MEMBER_ID exists because a demo has one phone and the roster has a dozen neighbours. When it
    names a member, only that member is contacted for real and the rest are logged, so the coordinator's
    own phone shows one neighbour's conversation rather than the whole roster's.
    """
    if settings.SEND_MODE != "live":
        return False
    only = settings.DEMO_LIVE_MEMBER_ID
    return not only or member.id == only


def deliver(member: Member, body: str, preferred: str | None = None, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
    """Try the preferred channel, then any other configured channel the member has an address for."""
    first = preferred or member.preferred_channel
    order = [first] + [c for c in ("sms", "telegram", "email") if c != first]
    sending = live_for(member)
    live_voice = sending and _PROVIDERS["voice"].configured()
    if not live_voice:  # no voice line configured: the call script goes out as a text instead
        order = ["sms" if c == "voice" else c for c in order]
    order = list(dict.fromkeys(order))
    tried: list[str] = []
    for ch in order:
        provider = _PROVIDERS.get(ch)
        addr = _address(member, ch)
        if not provider or not addr:
            continue
        if sending and provider.configured():
            res = provider.send(addr, body, subject=subject, meta=meta)
            tried.append(f"{ch}:{'ok' if res.ok else 'fail'}")
            if res.ok:
                return res
            log.warning("delivery via %s failed for %s: %s", ch, member.name, res.detail)
    if not sending:
        addr = _address(member, order[0]) or member.name
        if first == "voice":
            m = meta or {}
            script = spoken_text(body, str(m.get("call_script") or ""))
            log.info("[console] VOICE CALL to %s (%s) would say: %s", addr, voice_for(m.get("language") or member.language), script)
            res = DeliveryResult(ok=True, channel="console", detail=f"voice call logged (not placed) to {addr}; would say: \u201c{script[:160]}\u201d",
                                 extra={"script": script})
        else:
            res = _CONSOLE.send(addr, body, subject=subject, meta=meta)
        res.extra["requested_channel"] = first
        return res
    return DeliveryResult(ok=False, channel=order[0], detail=f"no configured channel could reach {member.name} (tried {tried or 'none'})")
