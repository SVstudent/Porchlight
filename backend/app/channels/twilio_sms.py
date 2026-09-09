"""Twilio SMS via the REST API (no SDK dependency)."""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .base import ChannelProvider, DeliveryResult


class TwilioSMSProvider(ChannelProvider):
    name = "sms"

    def configured(self) -> bool:
        return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER)

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        try:
            with httpx.Client(timeout=20.0, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)) as c:
                r = c.post(url, data={"From": settings.TWILIO_FROM_NUMBER, "To": to, "Body": body})
            if r.status_code >= 300:
                return DeliveryResult(ok=False, channel="sms", detail=f"twilio {r.status_code}: {r.text[:200]}")
            j = r.json()
            return DeliveryResult(ok=True, channel="sms", detail=f"sent to {to}", provider_id=j.get("sid", ""))
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(ok=False, channel="sms", detail=f"twilio error: {e}")
