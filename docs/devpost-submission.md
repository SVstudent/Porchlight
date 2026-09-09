# Devpost submission text (paste into the form)

**Project name:** Porchlight
**Tagline:** A neighbor check-in agent that turns a weather alert into personal outreach, volunteer dispatch and follow-up, and only asks the block captain to press Approve.
**Track:** Good Neighbor Agents
**Built with:** Strands Agents SDK (Python), Amazon Bedrock (Claude), Amazon Bedrock AgentCore Runtime, FastAPI, React, Vite, Leaflet, National Weather Service API, Open-Meteo, OpenStreetMap, Twilio, Telegram Bot API, Amazon SES, SQLite, Docker

## Inspiration

Extreme heat is the deadliest weather in the United States, and the people it kills are mostly older adults who live alone, have no working air conditioning, and were never checked on. Maricopa County confirmed 645 heat-associated deaths in 2023. After every event the advice is the same: check on your neighbors. In practice that job belongs to one volunteer with a spreadsheet and a group text: a block captain, a parish coordinator, a senior-building manager. During an alert they read the warning, guess who is at risk, type the same texts in two languages, hunt for a driver, and try to remember who never answered. Porchlight is the agent that does that repetitive work for them.

## What it does

Porchlight runs in the background for a community group. A deterministic sentinel polls National Weather Service alerts and live Open-Meteo conditions for the roster's location. When a relevant hazard appears (Extreme Heat Warning, smoke, freeze, or a coordinator-reported outage), a Strands multi-agent graph takes over:

- **Assess**: reads the alert and live feels-like temperature and air quality, and returns a typed decision to activate or stand down, with the risk factors it endangers.
- **Triage**: ranks every neighbor into tiers from their risk factors (lives alone, no AC, oxygen concentrator, dialysis, memory issues, young kids, outdoor work) and the conditions at their home.
- **Outreach**: writes each neighbor a personal message in English or Spanish with one concrete action and a one-tap check-in link, then pauses for the coordinator.
- **Logistics**: matches volunteers by skill, proximity and load, finds the nearest real cooling center, and pauses for the coordinator.
- **Brief**: writes a plain-language summary and what the coordinator should do next.
- **Follow-up**: every two minutes it reads the replies and escalates "I need help" and tier-1 non-responders to a volunteer visit or emergency contact, pausing for approval unless the coordinator has set a standing policy.

The coordinator's desk shows the live agent activity, a decision card with editable messages, neighbor status tiles, a map, and the brief. Neighbors get a page with two very large buttons: I'm OK, I need help.

## How we built it

Every agent is a Strands `Agent` with its own system prompt and tool set, wired into a `GraphBuilder` graph with a conditional edge and parallel branches. Human approval is a Strands interrupt raised from a `BeforeToolCallEvent` hook on the three world-changing tools; the graph stops with `Status.INTERRUPTED`, the API turns interrupts into approval cards, and the coordinator's decision resumes the graph through `interruptResponse` content. `FileSessionManager` persists graph and interrupt state so approvals survive restarts. The sentinel returns a Pydantic model through `structured_output_model`. An `AuditHook` mirrors model and tool events into a server-sent event stream. `ModelRouter` falls back from Bedrock to the Anthropic API to a local Ollama model, which is how the Strands primitives were tested before AWS credentials were available. A `BedrockAgentCoreApp` entrypoint runs the identical graph on AgentCore Runtime.

## Challenges

Keeping the LLM out of decisions that should be deterministic (when to poll, what counts as a hazard, de-duplicating alerts), designing the approval gate so it works uniformly across every agent in the graph, and making check-in links and Telegram replies close the loop back into the follow-up agent.

## What we learned

Interrupts plus session persistence are the difference between a demo and something a volunteer could trust: the agent can be stopped mid-action and picked up hours later on the same decision.

## What's next

Voice check-ins for landline-only neighbors, Open311 and utility outage feeds, and multi-community deployments on AgentCore with Memory for long-term neighbor context.
