"""Development transport: prints the message and reports success. Never used when SEND_MODE=live."""
from __future__ import annotations

import logging
from typing import Any

from .base import ChannelProvider, DeliveryResult

log = logging.getLogger("porchlight.channels.console")


class ConsoleProvider(ChannelProvider):
    name = "console"

    def configured(self) -> bool:
        return True

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
        log.info("[console] -> %s | %s | %s", to, subject, body)
        return DeliveryResult(ok=True, channel="console", detail=f"logged (not sent) to {to}")
