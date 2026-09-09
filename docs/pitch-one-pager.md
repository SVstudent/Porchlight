# Porchlight, in one page

A neighbor check-in agent for community groups. Built with the Strands Agents SDK on Amazon Bedrock. Every number below is sourced in [sources.md](sources.md).

## The problem

Heat is the leading weather-related killer in the US: 180 deaths a year on the NWS 30-year average, more than floods, tornadoes or hurricanes. Maricopa County alone confirmed 645 heat-related deaths in 2023 and 608 in 2024.

The people who die at home are older, alone, and unreached. Multnomah County, June 2021: 69 deaths, 78% were 60 or older, 71% lived alone. Texas, February 2021: 246 deaths, 25 of them because power to oxygen, dialysis or medical equipment stopped.

Every agency's advice is one sentence: check on your neighbors. Oregon's after-action review found that "neighbors checking on neighbors saved lives."

## Who it is for

The one volunteer who holds a community's list: a block captain, a parish coordinator, a senior-building manager, a mutual-aid dispatcher, a Be a Buddy site lead. NYC's Be a Buddy program does this by hand today (1,942 wellness checks during heat events, Feb to Sep 2025). Porchlight is Be a Buddy with an agent.

## What the agent does

- Watches official National Weather Service alerts and live conditions for the roster's location every 15 minutes, in plain Python. No model decides when to wake up.
- Reads the alert and returns a typed decision: activate or stand down, and which risk factors it endangers.
- Ranks every neighbor into tiers from recorded risk factors (lives alone, no AC, powered medical device, dialysis, memory issues, young kids, outdoor work) and the conditions at their home.
- Drafts one personal message per neighbor in English or Spanish with one concrete action and a one-tap check-in link, then pauses for the coordinator to edit and approve.
- Matches volunteers by skill, distance and load, finds the nearest real cooling center, and pauses for approval.
- Watches replies, escalates "I need help" and tier-1 non-responders, and writes the after-action brief.

## Why Strands

- `GraphBuilder` multi-agent graph: five agents with distinct prompts and tools, a conditional edge (triage only if the assessment activates) and parallel outreach and logistics branches that join at the brief.
- Human in the loop with interrupts: a `BeforeToolCallEvent` hook calls `event.interrupt()` on every world-changing tool; the graph stops with `Status.INTERRUPTED` and resumes on `interruptResponse`. Coordinator edits are written into the tool input.
- `FileSessionManager` persistence: a paused graph is rebuilt and resumed after a restart, so a decision can wait hours.
- `structured_output_model` for the hazard assessment, so a Pydantic object drives the graph edge, not free text.
- `ModelRouter` fallback (Bedrock, then Anthropic, then Ollama) and a `BedrockAgentCoreApp` entrypoint: the same graph runs on a laptop and on AgentCore Runtime.

## Impact model

HHS emPOWER publishes, by ZIP code, how many Medicare beneficiaries rely on electricity-dependent medical equipment. In Maricopa County that is 28,833 people (6,535 on home oxygen); in Arizona, 64,386.

| Scale | Neighbors on the list | Volunteers | What Porchlight does |
|---|---|---|---|
| One block (demo roster) | 12 | 4 | One coordinator approves two cards; every neighbor gets a personal message within minutes of the alert |
| One Be a Buddy site or parish | a few hundred | 10 to 30 | Same two cards; triage decides who gets a visit versus a text; volunteers are matched by language and distance |
| A county heat relief network | thousands (emPOWER gives the ceiling) | hundreds across many groups | Each group runs its own roster and coordinator; the county gets consistent after-action briefs instead of phone-tree memory |

The coordinator is the only approver at every scale. Nothing leaves the system without a decision, unless the coordinator has switched on the one standing policy (auto-dispatch a volunteer to a tier-1 neighbor who has not replied).

## What is real and what is demo

| Real | Demo |
|---|---|
| NWS alerts and Open-Meteo conditions are live public feeds, no keys | The roster is fictional; the coordinates and cooling centers are real Maryvale, Phoenix locations |
| "Replay this alert" uses an archived, real NWS Phoenix Extreme Heat Warning, labeled as a replay | Other-hazard replays are archived NWS alerts, labeled the same way |
| Messages go out over Twilio, Telegram or Amazon SES when `SEND_MODE=live` | The demo video routes every message to one phone we control (`DEMO_OVERRIDE_PHONE`) |
| Interrupts, resume, sessions, structured output and the graph are exercised by `tests/smoke_strands.py` on the configured model | Timings in the video are sped up 4x where marked |
| Porchlight is a coordination aid for volunteers | It is not an emergency service; the check-in page tells neighbors to call 911 |
