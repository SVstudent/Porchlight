"""Amazon SES email (works in the SES sandbox for verified addresses)."""
from __future__ import annotations

from typing import Any

from ..config import settings
from .base import ChannelProvider, DeliveryResult


class SESEmailProvider(ChannelProvider):
    name = "email"

    def configured(self) -> bool:
        return bool(settings.SES_FROM_EMAIL)

    def send(self, to: str, body: str, *, subject: str = "", meta: dict[str, Any] | None = None) -> DeliveryResult:
        try:
            import boto3  # local import keeps boto optional for non-AWS dev

            ses = boto3.client("ses", region_name=settings.AWS_REGION)
            r = ses.send_email(
                Source=settings.SES_FROM_EMAIL,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject or f"{settings.COMMUNITY_NAME}: please check in"},
                    "Body": {"Text": {"Data": body}},
                },
            )
            return DeliveryResult(ok=True, channel="email", detail=f"sent to {to}", provider_id=r.get("MessageId", ""))
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(ok=False, channel="email", detail=f"ses error: {e}")
