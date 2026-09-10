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


def get_updates(offset: int | None = None, wait_s: int = 0) -> list[dict[str, Any]]:
    """Fetch new messages.

    With wait_s > 0 this is a long poll: Telegram holds the connection open until something arrives, so a
    neighbour's reply is picked up in about a second instead of waiting for the next scheduled tick. That
    is as close to a push as the Bot API offers without exposing a public webhook URL.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return []
    params: dict[str, Any] = {"timeout": wait_s}
    if offset is not None:
        params["offset"] = offset
    with httpx.Client(timeout=wait_s + 15.0) as c:
        r = c.get(f"{_base()}/getUpdates", params=params)
        j = r.json()
    return j.get("result", []) if j.get("ok") else []
