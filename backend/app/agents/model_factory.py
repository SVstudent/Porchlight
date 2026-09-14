"""Build the Strands model for every agent.

Primary: Amazon Bedrock. Fallbacks (via strands ModelRouter) let the same code run on the Anthropic API or
on TokenRouter, an OpenAI-compatible gateway, when Bedrock is not reachable.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger("porchlight.models")

# Transport failures are the single most common way a run dies on a laptop or a flaky network. Strands retries
# throttling out of the box but re-raises connection errors on the first attempt, which kills the whole episode.
_TRANSIENT = ("connection", "timed out", "timeout", "temporarily unavailable", "connection reset",
              "server error", "503", "502", "429")


def transient_retry_strategy():
    """A retry strategy that also survives a dropped connection. Falls back to the SDK default if unavailable."""
    try:
        from strands.event_loop._retry import ModelRetryStrategy
    except Exception:  # noqa: BLE001 — never let a private-module move break startup
        return None

    class TransientRetryStrategy(ModelRetryStrategy):
        def is_retryable(self, exception: Exception) -> bool:
            if super().is_retryable(exception):
                return True
            msg = str(exception).lower()
            return any(marker in msg for marker in _TRANSIENT)

    return TransientRetryStrategy(max_attempts=4, initial_delay=2, max_delay=30)


def _bedrock():
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=settings.BEDROCK_MODEL_ID,
        region_name=settings.AWS_REGION,
        temperature=settings.MODEL_TEMPERATURE,
    )


def _anthropic():
    from strands.models.anthropic import AnthropicModel

    return AnthropicModel(
        client_args={"api_key": settings.ANTHROPIC_API_KEY},
        model_id=settings.ANTHROPIC_MODEL_ID,
        max_tokens=4096,
        params={"temperature": settings.MODEL_TEMPERATURE},
    )


def _tokenrouter():
    """TokenRouter speaks the OpenAI wire format, so the OpenAI adapter drives it with a different base URL."""
    from strands.models.openai import OpenAIModel

    params: dict[str, Any] = {"temperature": settings.MODEL_TEMPERATURE, "max_tokens": 2048}
    if settings.TOKENROUTER_REASONING_EFFORT:
        params["reasoning_effort"] = settings.TOKENROUTER_REASONING_EFFORT
    return OpenAIModel(
        client_args={"api_key": settings.TOKENROUTER_API_KEY, "base_url": settings.TOKENROUTER_BASE_URL},
        model_id=settings.TOKENROUTER_MODEL_ID,
        params=params,
    )


def candidate_names() -> list[str]:
    names: list[str] = []
    p = settings.MODEL_PROVIDER
    if p in ("bedrock", "auto"):
        names.append(f"bedrock:{settings.BEDROCK_MODEL_ID}")
    if p in ("anthropic", "auto") and settings.ANTHROPIC_API_KEY:
        names.append(f"anthropic:{settings.ANTHROPIC_MODEL_ID}")
    if p in ("tokenrouter", "auto") and settings.TOKENROUTER_API_KEY:
        names.append(f"tokenrouter:{settings.TOKENROUTER_MODEL_ID}")
    return names


def build_model() -> Any:
    p = settings.MODEL_PROVIDER
    candidates = []
    if p in ("bedrock", "auto"):
        candidates.append(_bedrock())
    if p in ("anthropic", "auto") and settings.ANTHROPIC_API_KEY:
        candidates.append(_anthropic())
    if p in ("tokenrouter", "auto") and settings.TOKENROUTER_API_KEY:
        candidates.append(_tokenrouter())
    if not candidates:
        raise RuntimeError("No model provider configured. Set AWS credentials for Bedrock, or "
                           "ANTHROPIC_API_KEY, or TOKENROUTER_API_KEY, in backend/.env")
    if len(candidates) == 1:
        log.info("model provider: %s", candidate_names()[0])
        return candidates[0]
    from strands.models import ModelRouter

    log.info("model router with fallback order: %s", candidate_names())
    return ModelRouter(models=candidates, max_switches=len(candidates) - 1)
