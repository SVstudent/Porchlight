"""Twilio Programmable Voice: a real phone call read by an Amazon Polly voice, with a keypad check-in.

For neighbors who only have a landline (no apps, no texts). The call speaks the outreach script, then asks
them to press 1 (I'm OK) or 2 (I need help). Keypresses and call outcomes come back through the webhooks in
app/routes_voice.py. The initial TwiML is passed inline in the REST call (Twilio's `Twiml` parameter), so the
only URLs Twilio must reach are the keypress action and the status callback under PUBLIC_BASE_URL.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx

from ..config import settings
from .base import ChannelProvider, DeliveryResult

log = logging.getLogger("porchlight.channels.voice")

# Amazon Polly voices as exposed by Twilio <Say voice="Polly.*">
POLLY_VOICE = {"en": "Polly.Joanna", "es": "Polly.Lupe"}

PROMPTS = {
    "en": {
        "gather": "Press 1 if you are okay. Press 2 if you need help.",
        "goodbye": "We will call again soon. Goodbye.",
        "thanks_ok": "Thank you. We are glad you are okay. Stay cool and drink water. Goodbye.",
        "thanks_help": "Thank you. A neighbor will contact you very soon. If this is an emergency, call 9 1 1. Goodbye.",
        "retry": "Sorry, I did not get that.",
        "unknown": "Sorry, this check-in link is no longer active. Goodbye.",
    },
    "es": {
        "gather": "Presione 1 si está bien. Presione 2 si necesita ayuda.",
        "goodbye": "Le llamaremos de nuevo pronto. Adiós.",
        "thanks_ok": "Gracias. Nos alegra que esté bien. Manténgase fresco y tome agua. Adiós.",
        "thanks_help": "Gracias. Un vecino le contactará muy pronto. Si es una emergencia, llame al 9 1 1. Adiós.",
        "retry": "Perdón, no le entendí.",
        "unknown": "Lo sentimos, este enlace ya no está activo. Adiós.",
    },
}

MAX_SCRIPT_CHARS = 900  # Twilio's inline Twiml parameter is capped at 4000 chars
_CHECKIN_LINE = re.compile(r"(check in|regístrese|registrese|responda aquí)\s*:?\s*https?://\S+", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")


def lang(language: str | None) -> str:
    return "es" if (language or "").lower().startswith("es") else "en"


def voice_for(language: str | None) -> str:
    return POLLY_VOICE[lang(language)]


def spoken_text(body: str, call_script: str = "") -> str:
    """What the call says: the agent's call script if it wrote one, else the message with links removed.
    A URL is never read aloud - the keypad is the check-in."""
    text = (call_script or "").strip() or body
    text = text.replace("{checkin_link}", "")
    text = _CHECKIN_LINE.sub("", text)
    text = _URL.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    return text[:MAX_SCRIPT_CHARS]


def _say(text: str, voice: str) -> str:
    return f"<Say voice={quoteattr(voice)}>{escape(text)}</Say>"


def keypress_url(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/voice/keypress/{token}"


def status_url(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/voice/status/{token}"


def build_twiml(script: str, language: str = "en", token: str = "", *, preface: str = "") -> str:
    """Outbound call script: speak, then gather one digit. Without a token there is nothing to record, so the
    call just delivers the message."""
    lg = lang(language)
    voice = POLLY_VOICE[lg]
    p = PROMPTS[lg]
    parts = ["<Response>"]
    if preface:
        parts.append(_say(preface, voice))
    if script:
        parts.append(_say(script, voice))
    if token:
        parts.append(
            f'<Gather input="dtmf" numDigits="1" timeout="8" action={quoteattr(keypress_url(token))} method="POST">'
            + _say(p["gather"], voice)
            + "</Gather>"
        )
    parts.append(_say(p["goodbye"], voice))
    parts.append("</Response>")
    return '<?xml version="1.0" encoding="UTF-8"?>' + "".join(parts)


def build_reply_twiml(kind: str, language: str = "en") -> str:
    """Short reply after a keypress (thanks) or when the call cannot be matched (unknown)."""
    lg = lang(language)
    p = PROMPTS[lg]
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + _say(p[kind], POLLY_VOICE[lg]) + "</Response>"


class TwilioVoiceProvider(ChannelProvider):
    name = "voice"

    def configured(self) -> bool:
        return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER)

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
        meta = meta or {}
        token = str(meta.get("token") or "")
        language = lang(meta.get("language"))
        script = spoken_text(body, str(meta.get("call_script") or ""))
        if not script:
            return DeliveryResult(ok=False, channel="voice", detail="nothing to say")
        twiml = build_twiml(script, language, token)
        data = {"From": settings.TWILIO_FROM_NUMBER, "To": to, "Twiml": twiml}
        if token:
            data["StatusCallback"] = status_url(token)
            data["StatusCallbackMethod"] = "POST"
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json"
        try:
            with httpx.Client(timeout=20.0, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)) as c:
                r = c.post(url, data=data)
            if r.status_code >= 300:
                return DeliveryResult(ok=False, channel="voice", detail=f"twilio voice {r.status_code}: {r.text[:200]}")
            j = r.json()
            return DeliveryResult(ok=True, channel="voice", detail=f"calling {to} ({POLLY_VOICE[language]})",
                                  provider_id=j.get("sid", ""), extra={"script": script})
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(ok=False, channel="voice", detail=f"twilio voice error: {e}")
