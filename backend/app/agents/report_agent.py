"""Optional narrative for the after-action report: a Strands agent that paraphrases computed metrics.

The numbers come from app/report.py and are never produced by the model. If no model provider is configured
(or the call fails) the report still works; only the prose is missing.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ..config import settings
from .model_factory import build_model

log = logging.getLogger("porchlight.report")


class AfterActionNarrative(BaseModel):
    executive_summary: str = Field(description="3-5 plain sentences: what the hazard was, who was contacted, how they responded, what needed escalation")
    what_worked: list[str] = Field(description="Short bullet points, each grounded in a number from the metrics")
    what_to_fix: list[str] = Field(description="Short bullet points on delivery failures, slow replies, uncovered gaps, slow decisions")
    recommendations: list[str] = Field(description="Concrete things to change before the next event (roster data, channels, volunteers, policy)")
    funder_paragraph: str = Field(description="One paragraph a nonprofit could paste into a grant or funder report, past tense, numbers included")


REPORTER_PROMPT = f"""
You write after-action reports for "{settings.COMMUNITY_NAME}", a neighbor check-in network coordinated by
{settings.COORDINATOR_NAME}. You are given a JSON object of metrics computed from the event record.
Rules:
- Use ONLY numbers, names, channels and outcomes that appear in the metrics JSON. Never invent or round up.
- If a value is null, say it was not measured; do not guess.
- Plain language for volunteers, funders and county emergency managers. Short sentences. No jargon, no acronyms.
- "what_worked" and "what_to_fix" are each 2-5 bullets. "recommendations" are 2-5 concrete actions.
- The funder paragraph is past tense, 4-6 sentences, and includes: neighbors contacted, response rate,
  time from hazard detection to first message, escalations and their outcomes, volunteer assignments.
"""


def generate_narrative(metrics: dict[str, Any], episode_summary: dict[str, Any]) -> tuple[AfterActionNarrative | None, str]:
    """Return (narrative, reason). narrative is None and reason is set when no model is available or the call fails."""
    try:
        model = build_model()
    except Exception as e:  # noqa: BLE001
        log.info("narrative unavailable: %s", e)
        return None, f"narrative_unavailable: {e}"
    try:
        from strands import Agent

        agent = Agent(name="reporter", model=model, system_prompt=REPORTER_PROMPT, tools=[],
                      structured_output_model=AfterActionNarrative, callback_handler=None,
                      trace_attributes={"porchlight.agent": "reporter", "porchlight.community": settings.COMMUNITY_NAME})
        prompt = ("Write the after-action report for this event.\n\nEpisode:\n"
                  + json.dumps(episode_summary, indent=1, default=str)
                  + "\n\nMetrics (the only source of truth):\n" + json.dumps(metrics, indent=1, default=str))
        result = agent(prompt)
        so = getattr(result, "structured_output", None)
        if isinstance(so, AfterActionNarrative):
            return so, ""
        return None, "narrative_unavailable: model did not return a structured narrative"
    except Exception as e:  # noqa: BLE001
        log.warning("narrative generation failed: %s", e)
        return None, f"narrative_unavailable: {e}"
