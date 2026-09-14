"""Power-outage routes: who depends on electricity, and reporting an outage as a hazard (compound-aware)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .agents.runner import runner
from .agents.tools_outage import electricity_dependent_members
from .config import settings
from .models import Episode, HazardEvent, now_iso
from .store import store

log = logging.getLogger("porchlight.outage")
router = APIRouter()

COMPOUND_TYPES = ("heat", "cold", "winter")
ACTIVE_EXCLUDED = ("closed", "stood_down", "failed")


def active_compound_episode() -> Episode | None:
    """Most recent heat/cold/winter episode that is still open, if any."""
    for ep in store.episodes():  # newest first
        if ep.hazard.hazard_type in COMPOUND_TYPES and ep.status not in ACTIVE_EXCLUDED:
            return ep
    return None


@router.get("/api/outage/electricity-dependent")
def electricity_dependent() -> dict[str, Any]:
    members = electricity_dependent_members()
    return {"members": members, "count": len(members), "under_4h": sum(1 for m in members if m["backup_power_hours"] < 4)}


class OutageReportIn(BaseModel):
    utility: str = "APS"
    area: str = ""
    description: str = ""
    estimated_restoration_iso: str = ""


def build_outage_hazard(body: OutageReportIn, compound: Episode | None) -> HazardEvent:
    utility = (body.utility or "the utility").strip()
    area = body.area.strip() or settings.COMMUNITY_NAME
    dependents = electricity_dependent_members()
    urgent = [m for m in dependents if m["backup_power_hours"] < 4]
    lines = [body.description.strip() or f"{utility} reports a power outage affecting {area}."]
    if body.estimated_restoration_iso:
        lines.append(f"Estimated restoration: {body.estimated_restoration_iso}.")
    lines.append(f"{len(dependents)} neighbor(s) on the roster depend on electricity for a medical device; "
                 f"{len(urgent)} of them have under 4 hours of backup power.")
    metrics: dict[str, Any] = {"utility": utility, "electricity_dependent": len(dependents), "under_4h_backup": len(urgent)}
    if compound is not None:
        ctype = compound.hazard.hazard_type
        metrics["compound_with"] = compound.id
        metrics["compound_hazard"] = ctype
        lines.insert(0, f"COMPOUND HAZARD: this outage is happening during an active {ctype} event "
                        f"({compound.hazard.event_name}{' — ' + compound.hazard.headline if compound.hazard.headline else ''}, episode {compound.id}). "
                        f"Loss of power during {ctype} removes cooling/heating and stops medical devices at the same time; treat every "
                        f"member with a powered medical device as life-threatening priority.")
    return HazardEvent(
        source="manual",
        external_id=f"manual-outage-{now_iso()}",
        hazard_type="outage",
        event_name=f"Power outage — {utility}",
        severity="Extreme" if compound is not None else "Severe",
        headline=f"{utility} outage in {area}" + (f" during {compound.hazard.event_name}" if compound is not None else ""),
        description="\n".join(lines),
        instruction="Check on every neighbor with a powered medical device first. Anyone with under 4 hours of backup needs a visit "
                    "or a ride to a place with power. Do not wait for the utility's restoration estimate to be confirmed.",
        area=area,
        onset=now_iso(),
        expires=body.estimated_restoration_iso,
        metrics=metrics,
    )


@router.post("/api/outage/report")
async def report_outage(body: OutageReportIn) -> dict[str, Any]:
    compound = active_compound_episode()
    h = build_outage_hazard(body, compound)
    ep = await runner.start(h)
    if compound is not None:
        log.info("outage %s reported during active %s episode %s", ep.id, compound.hazard.hazard_type, compound.id)
    return {"episode": ep.model_dump(), "compound_with": compound.id if compound else None}
