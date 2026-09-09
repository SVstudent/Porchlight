"""Build the Strands model for every agent.

Primary: Amazon Bedrock. Fallbacks (via strands ModelRouter) let the same code run on the Anthropic API or a
local Ollama model for development without AWS credentials.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger("porchlight.models")


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

    return OllamaModel(host=settings.OLLAMA_HOST, model_id=settings.OLLAMA_MODEL, temperature=settings.MODEL_TEMPERATURE)


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
