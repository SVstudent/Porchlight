from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeliveryResult:
    ok: bool
    channel: str
    detail: str = ""
    provider_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ChannelProvider:
    name: str = "base"

    def configured(self) -> bool:  # pragma: no cover
        return False

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:  # pragma: no cover
        raise NotImplementedError
