"""The Porchlight multi-agent pipeline, built with the Strands Agents SDK.

    assess ──(activate?)──> triage ──┬──> outreach ──┐
                                     └──> logistics ─┴──> brief

Each node is a Strands Agent with its own system prompt and tool set. Deterministic thresholds decide when the
graph runs (see sentinel.py); the LLM agents decide who is at risk, what to say, and who should go where.
Every world-changing tool is gated by ApprovalGateHook (a Strands interrupt) so a human signs off first.
"""
from __future__ import annotations

import os
from typing import Any

from strands import Agent, tool
from strands.multiagent import GraphBuilder
from strands.types.tools import ToolContext
from strands.multiagent.graph import GraphState
from strands.session import FileSessionManager

from ..config import settings
from ..models import Episode, HazardAssessment, TriageDecision, TriagePlan
from ..store import store
from .context import episode_id_from
from .hooks import ApprovalGateHook, AuditHook
from .model_factory import build_model, transient_retry_strategy
from .playbooks import playbook_text
from .tools import (
    assign_volunteers,
    dispatch_outreach,
    escalate_member,
    find_nearby_cooled_places,
    get_area_conditions,
    get_checkin_status,
    get_episode_context,
    get_member_conditions,
    get_roster,
    list_community_resources,
    list_volunteers,
    record_coordinator_brief,
)
from .tools_memory import get_community_history, get_neighbor_history
from .tools_outage import get_electricity_dependent_members


@tool(context=True)
def submit_triage_plan(tool_context: ToolContext, decisions: list[dict], summary: str) -> dict:
    """Submit the final triage plan (one decision per member, tier 0-3). Call exactly once when done.
    Args:
        decisions: list of objects: {"member_id": str, "tier": 0|1|2|3, "reason": str,
                   "channel": "sms"|"telegram"|"email"|"voice", "needs_visit": bool}
        summary: two sentences on who is most at risk and why
    """
    ep = store.episode(episode_id_from(tool_context.invocation_state))
    if ep is None:
        return {"error": "no active episode"}
    try:
        plan = TriagePlan(decisions=[TriageDecision(**d) for d in decisions], summary=summary)
    except Exception as e:  # noqa: BLE001
        return {"error": f"invalid decisions: {e}"}
    def _apply(e):
        e.triage = plan
        e.status = "triaging"

    store.mutate_episode(ep.id, _apply)
    tiers = {t: sum(1 for d in plan.decisions if d.tier == t) for t in (1, 2, 3, 0)}
    return {"saved": True, "counts_by_tier": tiers}


COMMON_RULES = f"""
You are part of Porchlight, a neighbor check-in agent for "{settings.COMMUNITY_NAME}", coordinated by {settings.COORDINATOR_NAME}.
Rules for every agent:
- Use tools to get facts; never invent members, volunteers, phone numbers, hours, or weather values.
- Write for neighbors and volunteers, not for meteorologists: short sentences, no jargon, no acronyms.
- Be decisive. Do not ask the coordinator questions; make the safe call and explain it.
- Never contact anyone without going through the gated tools. If a gated tool is declined, do not retry it.
- Keep your final response under 150 words; details belong in tool calls.
"""

SENTINEL_PROMPT = COMMON_RULES + """
Role: SENTINEL. A weather/environment alert has been detected for the community. Decide whether it warrants
proactive neighbor outreach. Call get_area_conditions to confirm what people are actually experiencing right now.
Consider: severity, timing (is the dangerous period now or days away?), which risk factors it endangers
(for heat: no_air_conditioning, age_75_plus, lives_alone, chronic_illness, pregnant, infant_or_young_child,
outdoor_worker, powered_medical_device, cognitive_impairment; for air quality: chronic_illness, infant,
pregnant, outdoor_worker; for cold/winter/outage: powered_medical_device, age_75_plus, no heat, unhoused).
Activate for Extreme Heat Warnings, Excessive Heat Warnings, Heat Advisories when the feels-like temperature
is at or above 105 F, Air Quality alerts at AQI 151+, Freeze/Wind Chill/Winter Storm warnings, Flash Flood
Warnings, Tornado/Hurricane warnings, and power outages in extreme temperatures. Do not activate for routine
advisories with no vulnerable-population impact.
The task includes the playbook for this hazard: take elevated_risk_factors and recommended_actions from it
(adjusted to the actual alert and live conditions), not from heat habits.
"""

TRIAGE_PROMPT = COMMON_RULES + """
Role: TRIAGE. Call get_episode_context, then get_roster. For members whose risk factors match the hazard, call
get_member_conditions for the highest-risk ones (you do not need to check everyone). Which risk factors count
as "elevated" comes from the assessment and the playbook for this hazard (a flood endangers different people
than a heat wave). Assign every opted-in member a tier:
  1 = contact within the hour and probably needs an in-person visit or a ride (multiple elevated risk factors,
      no air conditioning or powered medical device, lives alone, cognitive impairment)
  2 = contact today (one or two elevated risk factors)
  3 = informational message only (low risk but part of the community)
  0 = no action (not affected; e.g. healthy and offered to help)
Pick each member's channel: their preferred channel, but use "sms" instead of "voice" if the message is short,
and "email" only if they have no phone. Set needs_visit for tier 1 members who cannot get themselves to safety.
For an outage or a compound hazard (an outage during heat or cold), call get_electricity_dependent_members: every
member with a powered medical device is tier 1, and needs_visit when their backup runtime is under 4 hours.
For tier 1 candidates, call get_neighbor_history and use past reply behaviour to pick the channel and whether a visit is needed.
Then call submit_triage_plan exactly once with every decision, and finish with a two-sentence summary.
"""

OUTREACH_PROMPT = COMMON_RULES + """
Role: OUTREACH. Call get_episode_context to read the assessment and triage. Write one message for every member
with tier 1, 2, or 3 (skip tier 0). Requirements for each message:
- In the member's language ("es" = Spanish, "en" = English). Warm, plain, personal; use their first name.
- Under 320 characters. Say what the danger is, one concrete action for their situation (from the assessment,
  the playbook for this hazard and their notes, e.g. no AC -> nearest cooling center by name; smoke -> windows
  closed, N95 if going out; flood -> higher ground; oxygen device -> what to do if power fails),
  and end with the literal placeholder {checkin_link} so they can tap "I'm OK" or "I need help".
- The playbook's Spanish phrases show the right terms (e.g. "centro de enfriamiento"); do not translate literally.
- For members whose channel is voice, also fill call_script (what a volunteer should say on the phone).
Then call dispatch_outreach ONCE with all messages and a coordinator_note that lists who is being contacted
and why in 2-3 sentences. The coordinator will approve or edit before anything is sent.
"""

LOGISTICS_PROMPT = COMMON_RULES + """
Role: LOGISTICS. Call get_episode_context, list_volunteers, list_community_resources. For each tier 1 member
(especially needs_visit), call find_nearby_cooled_places to identify the closest real option. The playbook for
this hazard says what "safe place" means (cooling center, warming center, clean-air space, higher ground, storm
shelter) and which volunteer tasks matter; assign those tasks, not heat-specific ones. Match volunteers
to members by skill (Spanish speakers to Spanish-speaking members, drivers for rides, medical for members with
devices or illness), proximity, and load (respect max_assignments). Do not assign a member to themselves.
Then call assign_volunteers ONCE with the assignments, the resource ids you recommend, and any gaps (needs
nobody can cover, e.g. a member with no transport and no available driver). The coordinator will approve first.
"""

BRIEF_PROMPT = COMMON_RULES + """
Role: BRIEFING. Call get_episode_context and get_checkin_status. Write a 4-8 line plain-language brief for the
coordinator: what hazard, how many neighbors were contacted and how, who volunteers are visiting, what gaps
remain, and what the coordinator should personally do next. Save it with record_coordinator_brief.
"""

FOLLOWUP_PROMPT = COMMON_RULES + """
Role: FOLLOW-UP. Outreach already went out. Call get_episode_context and get_checkin_status.
- Members with status needs_help: escalate immediately (volunteer_visit with the best available volunteer from
  list_volunteers; if none available, notify_emergency_contact; if the note suggests a medical emergency,
  recommend_911).
- Tier 1 members with status "sent" and minutes_since_sent past the grace period: escalate with volunteer_visit,
  or notify_emergency_contact if no volunteer is available.
- Tier 2 members past twice the grace period: notify_emergency_contact if they have one, otherwise leave as is.
- Everyone else: no action.
Use get_neighbor_history before escalating: if a member has never replied to messages but their emergency contact has, notify the emergency contact first.
Call escalate_member once per member that needs it, most urgent first, at most two per cycle (each call pauses
for approval unless policy allows it); the next cycle handles the rest.
Finish with one or two sentences summarising what you did and who is still unaccounted for.
"""


def _agent(name: str, prompt: str, tools: list[Any], model: Any, session_id: str | None = None, **kw: Any) -> Agent:
    kwargs: dict[str, Any] = dict(
        name=name,
        model=model,
        system_prompt=prompt,
        tools=tools,
        hooks=[AuditHook(), ApprovalGateHook()],
        callback_handler=None,
        trace_attributes={"porchlight.agent": name, "porchlight.community": settings.COMMUNITY_NAME},
    )
    retry = transient_retry_strategy()
    if retry is not None:
        kwargs["retry_strategy"] = retry
    if session_id:
        kwargs["session_manager"] = FileSessionManager(session_id=session_id, storage_dir=str(settings.SESSION_DIR))
    kwargs.update(kw)
    return Agent(**kwargs)


def build_graph(ep: Episode, model: Any | None = None):
    """Build the per-episode Strands Graph. Session-managed so an interrupted run can resume after a restart."""
    model = model or build_model()
    sentinel = _agent("sentinel", SENTINEL_PROMPT, [get_area_conditions, get_episode_context, get_community_history], model,
                      structured_output_model=HazardAssessment)
    triage = _agent("triage", TRIAGE_PROMPT, [get_episode_context, get_roster, get_member_conditions, get_electricity_dependent_members, get_neighbor_history, submit_triage_plan], model)
    outreach = _agent("outreach", OUTREACH_PROMPT, [get_episode_context, get_roster, find_nearby_cooled_places, dispatch_outreach], model)
    logistics = _agent("logistics", LOGISTICS_PROMPT, [get_episode_context, list_volunteers, list_community_resources, find_nearby_cooled_places, get_electricity_dependent_members, assign_volunteers], model)
    brief = _agent("briefing", BRIEF_PROMPT, [get_episode_context, get_checkin_status, get_community_history, record_coordinator_brief], model)

    def activated(state: GraphState) -> bool:
        node = state.results.get("assess")
        res = getattr(node, "result", None)
        so = getattr(res, "structured_output", None)
        if isinstance(so, HazardAssessment):
            return so.activate
        # Fallback: the runner persists the assessment; trust the store.
        cur = store.episode(ep.id)
        return bool(cur and cur.assessment and cur.assessment.activate)

    b = GraphBuilder()
    b.add_node(sentinel, "assess")
    b.add_node(triage, "triage")
    b.add_node(outreach, "outreach")
    b.add_node(logistics, "logistics")
    b.add_node(brief, "brief")
    b.add_edge("assess", "triage", condition=activated)
    b.add_edge("triage", "outreach")
    b.add_edge("triage", "logistics")
    b.add_edge("outreach", "brief")
    b.add_edge("logistics", "brief")
    b.set_entry_point("assess")
    b.set_execution_timeout(int(os.getenv("GRAPH_TIMEOUT_S", "1800")))
    b.set_node_timeout(int(os.getenv("NODE_TIMEOUT_S", "900")))
    b.set_session_manager(FileSessionManager(session_id=f"graph-{ep.id}", storage_dir=str(settings.SESSION_DIR)))
    return b.build()


def build_followup_agent(ep: Episode, model: Any | None = None) -> Agent:
    model = model or build_model()
    return _agent("followup", FOLLOWUP_PROMPT,
                  [get_episode_context, get_checkin_status, list_volunteers, get_electricity_dependent_members, get_neighbor_history, escalate_member], model,
                  session_id=f"followup-{ep.id}")


def graph_task(ep: Episode) -> str:
    h = ep.hazard
    return (
        f"Hazard detected for {settings.COMMUNITY_NAME} (episode {ep.id}).\n"
        f"Source: {h.source}. Event: {h.event_name}. Severity: {h.severity}. Area: {h.area}.\n"
        f"Headline: {h.headline}\nOnset: {h.onset}  Expires: {h.expires}\n"
        f"Description:\n{h.description[:2500]}\n\nInstruction:\n{h.instruction[:1200]}\n\n"
        f"Metrics: {h.metrics}\n\n"
        f"{playbook_text(h.hazard_type)}\n\n"
        "Assess whether to activate neighbor outreach; if so, triage the roster, draft outreach, arrange logistics, and brief the coordinator."
    )
