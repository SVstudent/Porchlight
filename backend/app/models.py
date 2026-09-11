"""Domain models shared by the API, the store, and the Strands agents (structured outputs)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


RiskFactor = Literal[
    "lives_alone",
    "age_75_plus",
    "no_air_conditioning",
    "powered_medical_device",
    "mobility_limited",
    "cognitive_impairment",
    "infant_or_young_child",
    "outdoor_worker",
    "pregnant",
    "chronic_illness",
    "no_transport",
    "limited_english",
    "unhoused",
]

Channel = Literal["sms", "telegram", "email", "voice"]
HazardType = Literal["heat", "cold", "air_quality", "storm", "flood", "winter", "outage", "other"]


class Member(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    name: str
    phone: str = ""
    email: str = ""
    telegram_chat_id: str = ""
    preferred_channel: Channel = "sms"
    language: str = "en"
    address: str = ""
    lat: float
    lon: float
    risk_factors: list[RiskFactor] = []
    notes: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    opted_in: bool = True
    # Power-outage fields (optional): powered medical devices this neighbor depends on, how long their battery
    # or backup lasts, which utility serves them, and what they plan to do when the power fails.
    devices: list[str] = []  # oxygen_concentrator, ventilator, cpap, home_dialysis, powered_wheelchair, refrigerated_medication, nebulizer
    backup_power_hours: float = 0
    utility: str = ""  # e.g. APS, SRP
    backup_plan: str = ""


class Volunteer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("vol"))
    name: str
    phone: str = ""
    lat: float
    lon: float
    skills: list[str] = []  # drive, wellness_visit, spanish, medical, deliver
    available: bool = True
    max_assignments: int = 2


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: new_id("res"))
    name: str
    kind: str  # cooling_center, warming_center, shelter, clean_air, hydration, pharmacy, other
    address: str = ""
    lat: float
    lon: float
    hours: str = ""
    phone: str = ""
    source: str = "coordinator"
    notes: str = ""


class HazardEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("haz"))
    source: str  # nws | open-meteo | replay | manual
    external_id: str = ""
    hazard_type: HazardType = "other"
    event_name: str
    severity: str = ""
    headline: str = ""
    description: str = ""
    instruction: str = ""
    area: str = ""
    onset: str = ""
    expires: str = ""
    metrics: dict[str, Any] = {}
    detected_at: str = Field(default_factory=now_iso)


# ---------- Structured outputs produced by Strands agents ----------

class HazardAssessment(BaseModel):
    """Sentinel agent output: should the community activate, and why."""
    activate: bool = Field(description="True if this hazard warrants proactive member outreach")
    hazard_type: HazardType
    severity_score: int = Field(ge=1, le=5, description="1 = minor, 5 = life-threatening")
    plain_summary: str = Field(description="Two sentences a neighbor with no weather knowledge would understand")
    elevated_risk_factors: list[RiskFactor] = Field(description="Which member risk factors this hazard makes dangerous")
    recommended_actions: list[str] = Field(description="Concrete protective actions for affected members")
    reasoning: str


class TriageDecision(BaseModel):
    member_id: str
    tier: int = Field(ge=0, le=3, description="1 = contact now + likely visit, 2 = contact today, 3 = informational, 0 = no action")
    reason: str
    channel: Channel
    needs_visit: bool = False


class TriagePlan(BaseModel):
    decisions: list[TriageDecision]
    summary: str


class OutreachMessage(BaseModel):
    member_id: str
    channel: Channel
    language: str
    body: str = Field(description="Plain-language message under 320 characters; must include the check-in link placeholder {checkin_link}")
    call_script: str = ""


class OutreachPlan(BaseModel):
    messages: list[OutreachMessage]
    coordinator_note: str


class VolunteerAssignment(BaseModel):
    volunteer_id: str
    member_id: str
    task: Literal["wellness_visit", "ride_to_cooling_center", "phone_call", "deliver_supplies"]
    reason: str
    priority: int = Field(ge=1, le=3)


class LogisticsPlan(BaseModel):
    assignments: list[VolunteerAssignment]
    recommended_resource_ids: list[str]
    gaps: list[str] = Field(description="Needs that no volunteer or resource can currently cover")


# ---------- Runtime records ----------

class Approval(BaseModel):
    id: str = Field(default_factory=lambda: new_id("apr"))
    episode_id: str
    kind: str  # outreach_dispatch | volunteer_dispatch | escalation
    title: str
    summary: str
    payload: dict[str, Any]
    interrupt_id: str = ""
    agent_name: str = ""
    scope: str = "graph"  # graph | followup  (which runnable to resume)
    batch_id: str = ""  # interrupts raised in the same pause share a batch and are resumed together
    edits: dict[str, Any] = {}  # coordinator edits applied to the tool input on approval
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str = Field(default_factory=now_iso)
    resolved_at: str = ""
    decision_note: str = ""


class Checkin(BaseModel):
    token: str
    episode_id: str
    member_id: str
    # "critical" means the reminders ran out with no word at all, which is the state a coordinator must
    # look at first: silence from someone at risk is not the same as being told they are fine.
    status: Literal["sent", "delivered", "failed", "ok", "needs_help",
                    "no_response", "escalated", "critical"] = "sent"
    channel: str = ""
    sent_at: str = Field(default_factory=now_iso)
    responded_at: str = ""
    note: str = ""
    reminders_sent: int = 0
    last_contact_at: str = ""  # when we last said anything to them; reminders are paced from this


class TimelineEntry(BaseModel):
    ts: str = Field(default_factory=now_iso)
    kind: str
    text: str
    data: dict[str, Any] = {}


class Episode(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ep"))
    hazard: HazardEvent
    status: str = "assessing"  # assessing | stood_down | triaging | awaiting_approval | dispatching | monitoring | escalating | closed | failed
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    assessment: Optional[HazardAssessment] = None
    triage: Optional[TriagePlan] = None
    outreach: Optional[OutreachPlan] = None
    logistics: Optional[LogisticsPlan] = None
    timeline: list[TimelineEntry] = []
    session_id: str = ""
    stats: dict[str, Any] = {}


class AgentEvent(BaseModel):
    """Live telemetry pushed to the dashboard over SSE."""
    id: str = Field(default_factory=lambda: new_id("evt"))
    ts: str = Field(default_factory=now_iso)
    episode_id: str = ""
    agent: str = ""
    type: str  # status | text | reasoning | tool_call | tool_result | interrupt | node_start | node_stop | error | checkin | dispatch
    text: str = ""
    data: dict[str, Any] = {}
