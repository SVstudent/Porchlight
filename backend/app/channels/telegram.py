"""Telegram Bot API. Two-way: members can reply OK / HELP and the poller records it as a check-in."""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .base import ChannelProvider, DeliveryResult


def _base() -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


class TelegramProvider(ChannelProvider):
    name = "telegram"

    def configured(self) -> bool:
        return bool(settings.TELEGRAM_BOT_TOKEN)

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
        try:
            with httpx.Client(timeout=20.0) as c:
                r = c.post(f"{_base()}/sendMessage", json={"chat_id": to, "text": body, "disable_web_page_preview": True})
            j = r.json()
            if not j.get("ok"):
                return DeliveryResult(ok=False, channel="telegram", detail=f"telegram: {j.get('description')}")
            return DeliveryResult(ok=True, channel="telegram", detail=f"sent to chat {to}", provider_id=str(j["result"]["message_id"]))
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(ok=False, channel="telegram", detail=f"telegram error: {e}")


def get_updates(offset: int | None = None) -> list[dict[str, Any]]:
    """Long-poll new messages (used by the check-in poller to capture replies)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return []
    params: dict[str, Any] = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{_base()}/getUpdates", params=params)
        j = r.json()
    return j.get("result", []) if j.get("ok") else []
