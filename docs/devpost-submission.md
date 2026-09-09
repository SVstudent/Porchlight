# Devpost submission text (paste into the form)

**Project name:** Porchlight
**Tagline:** A neighbor check-in agent that turns a weather alert into personal outreach, volunteer dispatch and follow-up, and only asks the block captain to press Approve.
**Track:** Good Neighbor Agents
**Built with:** Strands Agents SDK (Python), Amazon Bedrock (Claude), Amazon Bedrock AgentCore Runtime, FastAPI, React, Vite, Leaflet, National Weather Service API, Open-Meteo, OpenStreetMap, Twilio, Telegram Bot API, Amazon SES, SQLite, Docker

## Inspiration

New York City runs a program called Be a Buddy. Community organizations keep a list of neighbors who are older, live alone, depend on medical equipment, or have no air conditioning, and when a heat or cold emergency hits, volunteers call and knock on doors. Between February and September 2025 it made 1,942 wellness checks during extreme heat events. It works. It also runs on a spreadsheet, a phone, and one coordinator's evening.

The reason it matters is in every after-action report. In the June 2021 Pacific Northwest heat dome, 69 people died in Multnomah County; 78% were 60 or older and 71% lived alone. Oregon's after-action review concluded that "neighbors checking on neighbors saved lives." In the February 2021 Texas winter storm, 246 people died; 161 from cold exposure, most of them 60 or older, and 25 because dialysis, oxygen, or power to life-sustaining equipment stopped. Heat is the leading weather-related killer in the United States on the National Weather Service's 30-year average. Maricopa County, where our demo roster lives, confirmed 645 heat-related deaths in 2023 and 608 in 2024.

The CDC's advice is one sentence: "Check on your family, friends, and neighbors, especially if they have chronic medical problems or live alone." Porchlight is Be a Buddy with an agent. It reads the alert, ranks the list, drafts the messages, lines up the volunteers, watches the replies, and asks the coordinator before anything goes out.

## What it does

Porchlight runs in the background for a community group. A deterministic sentinel polls National Weather Service alerts and live Open-Meteo conditions for the roster's location. When a relevant hazard appears (Extreme Heat Warning, smoke, freeze, winter storm, flood, or an outage the coordinator reports by hand), a Strands multi-agent graph takes over:

- **Assess**: reads the alert and live feels-like temperature and air quality, and returns a typed decision to activate or stand down, with the risk factors it endangers.
- **Triage**: ranks every neighbor into tiers from their risk factors (lives alone, no AC, oxygen concentrator, dialysis, memory issues, young kids, outdoor work) and the conditions at their home.
- **Outreach**: writes each neighbor a personal message in English or Spanish with one concrete action and a one-tap check-in link, then pauses for the coordinator.
- **Logistics**: matches volunteers by skill, proximity and load, finds the nearest real cooling center, and pauses for the coordinator.
- **Brief**: writes a plain-language summary and what the coordinator should do next.
- **Follow-up**: every two minutes it reads the replies and escalates "I need help" and tier-1 non-responders to a volunteer visit or emergency contact, pausing for approval unless the coordinator has set a standing policy.

The coordinator's desk shows the live agent activity, a decision card with editable messages, neighbor status tiles, a map, and the brief. Neighbors get a page with two very large buttons: I'm OK, I need help.

The same loop runs for heat, smoke, freeze, winter storm, flood and outage. The sentinel maps NWS event names to hazard types in plain Python; the agents reason about whichever hazard they are handed.

## Why it matters

Porchlight is the automation layer for programs that already exist (NYC Be a Buddy, county heat relief networks, 2-1-1, church phone trees). It is not an emergency service; the check-in page tells neighbors in distress to call 911. Every number below is sourced in `docs/sources.md`.

| Number | What it is | Source |
|---|---|---|
| 180 | Average US heat deaths per year, NWS 30-year average (floods 94, tornadoes 73, hurricanes 50) | [NWS](https://www.weather.gov/media/hazstat/81year_2025.pdf) |
| 645 and 608 | Heat-related deaths in Maricopa County, AZ in 2023 and 2024 | [Maricopa County](https://www.maricopa.gov/ArchiveCenter/ViewFile/Item/5934) |
| 69 | Deaths in Multnomah County, OR from the June 2021 heat dome; 78% were 60 or older, 71% lived alone | [Multnomah County](https://www.multco.us/help-when-its-hot/news/2021-heat-killed-72-people-multnomah-county-most-were-older-lived-alone-had) |
| 246 | Deaths in the February 2021 Texas winter storm; 161 from cold exposure, 25 from loss of dialysis, oxygen, or powered medical equipment, 19 from carbon monoxide | [Texas DSHS](https://www.dshs.texas.gov/sites/default/files/news/updates/SMOC_FebWinterStorm_MortalitySurvReport_12-30-21.pdf) |
| 739 | Excess deaths in Chicago, July 14 to 20, 1995; people 65 and older overrepresented | [Whitman et al., AJPH](https://pmc.ncbi.nlm.nih.gov/articles/PMC1380980/) |
| 28,833 | Medicare beneficiaries in Maricopa County whose medical equipment needs electricity (6,535 on home oxygen) | [HHS emPOWER](https://empowerprogram.hhs.gov/empowermap) |
| 1,942 | Wellness checks NYC Be a Buddy made during extreme heat events, Feb to Sep 2025, by hand | [NYC Health](https://www.nyc.gov/assets/doh/downloads/pdf/about/climate-health-strategy.pdf) |

A county with 28,833 electricity-dependent residents cannot check on them with phone trees. A block with twelve can, if the coordinator is not the bottleneck. Porchlight removes the bottleneck and keeps the person.

## How we built it

Every agent is a Strands `Agent` with its own system prompt and tool set, wired into a `GraphBuilder` graph with a conditional edge and parallel branches. Human approval is a Strands interrupt raised from a `BeforeToolCallEvent` hook on the three world-changing tools: the graph stops with `Status.INTERRUPTED`, the API turns each interrupt into an approval card, and the coordinator's decision resumes the graph through `interruptResponse` content. `FileSessionManager` persists graph and interrupt state so approvals survive restarts. The sentinel returns a Pydantic model through `structured_output_model`. An `AuditHook` mirrors model and tool events into a server-sent event stream. `ModelRouter` falls back from Bedrock to the Anthropic API, so a provider outage does not end an episode mid-run. A `BedrockAgentCoreApp` entrypoint runs the identical graph on AgentCore Runtime.

## Challenges

Keeping the LLM out of decisions that should be deterministic (when to poll, what counts as a hazard, de-duplicating alerts), designing the approval gate so it works uniformly across every agent in the graph, and making check-in links and Telegram replies close the loop back into the follow-up agent.

## What we learned

Interrupts plus session persistence are the difference between a demo and something a volunteer could trust: the agent can be stopped mid-action and picked up hours later on the same decision.

## What's next

Voice check-ins for landline-only neighbors, Open311 and utility outage feeds, and multi-community deployments on AgentCore with Memory for long-term neighbor context.
