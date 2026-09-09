"""Build the Strands model for every agent.

Primary: Amazon Bedrock. Fallbacks (via strands ModelRouter) let the same code run on the Anthropic API or a
local Ollama model for development without AWS credentials.
"""
from __future__ import annotations

import logging
import os
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


def _ollama():
    from strands.models.ollama import OllamaModel

    # Ollama defaults to a 4k context; the triage prompt alone (roster + alert) is ~4k tokens.
    return OllamaModel(host=settings.OLLAMA_HOST, model_id=settings.OLLAMA_MODEL, temperature=settings.MODEL_TEMPERATURE,
                       options={"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "16384"))})


def candidate_names() -> list[str]:
    names: list[str] = []
    p = settings.MODEL_PROVIDER
    if p in ("bedrock", "auto"):
        names.append(f"bedrock:{settings.BEDROCK_MODEL_ID}")
    if p in ("anthropic", "auto") and settings.ANTHROPIC_API_KEY:
        names.append(f"anthropic:{settings.ANTHROPIC_MODEL_ID}")
    if p in ("ollama", "auto") and settings.OLLAMA_HOST:
        names.append(f"ollama:{settings.OLLAMA_MODEL}")
    return names


def build_model() -> Any:
    p = settings.MODEL_PROVIDER
    candidates = []
    if p in ("bedrock", "auto"):
        candidates.append(_bedrock())
    if p in ("anthropic", "auto") and settings.ANTHROPIC_API_KEY:
        candidates.append(_anthropic())
    if p in ("ollama", "auto") and settings.OLLAMA_HOST:
        candidates.append(_ollama())
    if not candidates:
        raise RuntimeError("No model provider configured. Set AWS credentials, ANTHROPIC_API_KEY, or OLLAMA_HOST in backend/.env")
    if len(candidates) == 1:
        log.info("model provider: %s", candidate_names()[0])
        return candidates[0]
    from strands.models import ModelRouter

    log.info("model router with fallback order: %s", candidate_names())
    return ModelRouter(models=candidates, max_switches=len(candidates) - 1)
