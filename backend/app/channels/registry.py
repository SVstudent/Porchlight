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

log = logging.getLogger("porchlight.channels")

_PROVIDERS = {
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


def deliver(member: Member, body: str, preferred: str | None = None, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
    """Try the preferred channel, then any other configured channel the member has an address for."""
    order = [preferred or member.preferred_channel] + [c for c in ("sms", "telegram", "email") if c != (preferred or member.preferred_channel)]
    order = ["sms" if c == "voice" else c for c in order]  # voice is delivered as SMS text with the call script in dev
    tried: list[str] = []
    for ch in order:
        provider = _PROVIDERS.get(ch)
        addr = _address(member, ch)
        if not provider or not addr:
            continue
        if settings.SEND_MODE == "live" and provider.configured():
            res = provider.send(addr, body, subject=subject, meta=meta)
            tried.append(f"{ch}:{'ok' if res.ok else 'fail'}")
            if res.ok:
                return res
            log.warning("delivery via %s failed for %s: %s", ch, member.name, res.detail)
    if settings.SEND_MODE != "live":
        addr = _address(member, order[0]) or member.name
        res = _CONSOLE.send(addr, body, subject=subject, meta=meta)
        res.extra["requested_channel"] = order[0]
        return res
    return DeliveryResult(ok=False, channel=order[0], detail=f"no configured channel could reach {member.name} (tried {tried or 'none'})")
