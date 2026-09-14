# Porchlight

**A neighbor check-in agent for community groups, built with the Strands Agents SDK.**

When an Extreme Heat Warning, a smoke event, a freeze or an outage threatens a neighborhood, Porchlight works in the background: it reads the official alert, works out which neighbors are actually in danger, writes each of them a personal message in their language, lines up volunteers and cooling centers, and then **stops and waits** for the block captain to approve. After the messages go out it reads the replies people actually write, reminds the ones who go quiet — three times, three minutes apart, then stops and flags them rather than texting a fourth time — and routes a real volunteer to whoever needs one.

*Agents for Humans Hackathon · **Good Neighbor Agents** track · MIT licensed*

![Architecture](docs/architecture.png)

---

## Try it in three minutes

No AWS account needed for this path — console mode logs every message instead of sending it, so the whole product is testable with no credentials and no accounts.

```bash
git clone https://github.com/SVstudent/Porchlight.git && cd Porchlight

# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # works as-is for the console-mode walkthrough
python run.py                   # http://localhost:8000

# frontend (second terminal, from the repo root)
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Open **http://localhost:5173**. The board starts empty on purpose — twelve grey neighbor cards, nobody contacted.

1. Press **`ingestion`**. Nothing is pre-seeded; this is the system starting from nothing.
2. Watch the agents work in the live feed. Every model call and tool call is streamed as it happens.
3. **The run stops.** Two approval cards appear. Read one of the messages, edit the wording, approve it. The graph resumes *inside the paused tool call*, with your edit.
4. Open a check-in link from the activity feed and write back something in your own words — *"my ac stopped working and i feel dizzy"*. An agent reads what you actually wrote, answers you by name, and flags you on the board.
5. Approve the suggested deployment. A route is drawn along real roads with a real travel time.

To run the agents against a model you'll need Bedrock credentials (see [Run it locally](#run-it-locally)). To send real messages, see [Real messages](#real-messages).

---

## The problem

Heat is the leading cause of weather-related deaths in the United States ([NWS](https://www.weather.gov/wrn/summer-heat-sm)). On the National Weather Service's 30-year average, heat kills 180 people a year, more than floods (94), tornadoes (73) or hurricanes (50), and the 10-year average is 279 ([NWS hazard statistics](https://www.weather.gov/media/hazstat/81year_2025.pdf)). Maricopa County (Phoenix), where our demo roster lives, confirmed 645 heat-related deaths in 2023 and 608 in 2024 ([county report](https://www.maricopa.gov/ArchiveCenter/ViewFile/Item/5934)).

The people who die at home are the ones nobody reached in time:

| Event | What the official review found | Source |
|---|---|---|
| Multnomah County (Portland), June 2021 heat dome | 69 deaths from the event. 78% were 60 or older. 71% lived alone. Almost none had working air conditioning. | [Multnomah County](https://www.multco.us/help-when-its-hot/news/2021-heat-killed-72-people-multnomah-county-most-were-older-lived-alone-had) |
| Oregon statewide, same event | "Most lived alone in homes with no working air conditioning or fans." The state's after-action review concluded that "neighbors checking on neighbors saved lives." | [Oregon OEM after-action review](https://www.oregon.gov/oem/Documents/2021_June_Excessive_Heat_Event_AAR.pdf) |
| Texas, February 2021 winter storm | 246 deaths across 77 counties. 161 from cold exposure, 107 of them people 60 or older. 25 from loss of dialysis, oxygen, or power to life-sustaining equipment. 19 from carbon monoxide. | [Texas DSHS final report](https://www.dshs.texas.gov/sites/default/files/news/updates/SMOC_FebWinterStorm_MortalitySurvReport_12-30-21.pdf) |
| Chicago, July 1995 | 739 excess deaths in one week. People 65 and older were overrepresented; most died at home, alone. | [Whitman et al., AJPH 1997](https://pmc.ncbi.nlm.nih.gov/articles/PMC1380980/), [Klinenberg, Heat Wave](https://press.uchicago.edu/ucp/books/book/chicago/H/bo20809880.html) |

Every agency says the same sentence. CDC: "Check on your family, friends, and neighbors, especially if they have chronic medical problems or live alone." ([CDC](https://www.cdc.gov/heat-health/about/index.html)). Ready.gov: "Check on family members, older adults and neighbors." ([Ready.gov](https://www.ready.gov/heat)). Maricopa County's own chief medical officer: "checking on vulnerable neighbors" ([Maricopa County](https://www.maricopa.gov/CivicAlerts.aspx?AID=3222)).

The scale of "who to check on" is public. HHS emPOWER counts Medicare beneficiaries whose medical equipment needs electricity, by ZIP code. In Maricopa County alone that is 28,833 people, 6,535 of them on home oxygen ([HHS emPOWER](https://empowerprogram.hhs.gov/empowermap), county data as of Aug 2026; see [docs/sources.md](docs/sources.md)).

Checking on them falls to volunteers: block captains, church phone trees, senior-building managers, mutual-aid groups. Their "system" is a spreadsheet and a group text. During an event they do the same thing over and over: read a weather alert, guess who is at risk, type individual texts in two languages, call around for someone with a car, and try to remember who never wrote back.

## Who it is for

The one volunteer who holds a community's contact list together: a block captain, a parish coordinator, a senior-building resident manager, a mutual-aid dispatcher, a "Be a Buddy" site lead. Porchlight gives them an agent that does the repetitive part and surfaces only when a human should decide.

## How this compares to what exists today

The manual version of Porchlight already exists and works. New York City's [Be a Buddy](https://www.nyc.gov/content/climate/pages/initiatives/be-a-buddy) program, launched in 2017 in the South Bronx (Hunts Point), pairs community organizations and volunteers with at-risk residents and, during heat or cold emergencies, has them "conduct telephone and, if necessary, door-to-door and building level checks on vulnerable individuals" ([Cool Neighborhoods NYC, 2017](https://www.nyc.gov/assets/orr/pdf/Cool_Neighborhoods_NYC_Report.pdf)). Relaunched in 2025, it conducted 1,942 wellness checks during extreme heat events between February and September 2025 ([NYC Health, 2026](https://www.nyc.gov/assets/doh/downloads/pdf/about/climate-health-strategy.pdf)). County heat relief networks, 2-1-1 lines, and church phone trees do the same job with the same tools: a list, a phone, and a volunteer's evening.

Porchlight is the automation layer for those programs, not a replacement for them and not a replacement for 911:

| Today | With Porchlight |
|---|---|
| A coordinator notices the heat warning | The sentinel notices it within 15 minutes, from the official NWS feed |
| The coordinator guesses who is most at risk | The triage agent ranks every neighbor from their recorded risk factors and the conditions at their own home |
| The coordinator types texts one by one, in two languages | The outreach agent drafts one personal message per neighbor; the coordinator edits and approves them in one card |
| The coordinator calls around for a driver | The logistics agent proposes volunteer matches by skill, distance and load; the coordinator approves |
| The coordinator re-texts whoever they remember, or forgets | Reminders are paced and finite: three, three minutes apart, per person. One reply closes all of them |
| Someone who never answers is simply lost | After the last reminder the texting stops and the person is marked **critical** — silence from someone at risk becomes a finding, not an unanswered thread |
| "Can somebody drive Rosa?" in a group chat | A deployment matched to the need — a driver for a lift, a nurse for a medical device — with a real road route and travel time |
| Nothing is written down afterwards | The brief and the timeline are the after-action record, and the outcomes are remembered for next time |

The list stays the community's list. The decisions stay with the coordinator. The check-in page tells neighbors in distress to call 911.

## Multi-hazard

The loop is the same for every hazard: official alert in, triage, personal outreach, volunteers, follow-up. The sentinel maps National Weather Service event names deterministically to hazard types (heat, air quality including smoke and dust, cold, winter, flood, storm) in `backend/app/feeds/nws.py`, and threshold checks on live Open-Meteo conditions (feels-like at or above 105 F, US AQI at or above 151, air at or below 15 F) cover places without an active alert. For hazards no feed reports (a power outage, a water main break, a building evacuation) the sentinel panel has a manual report form; a coordinator-reported outage runs the same loop with hazard type `outage`. The prompts ask the agents to reason about the hazard they are given, so a freeze warning raises the oxygen-concentrator and no-heat neighbors while a smoke event raises the COPD and asthma neighbors. Five real archived NWS alerts ship as replay fixtures: an Extreme Heat Warning (Phoenix), an Air Quality Alert from the 2023 Canadian wildfire smoke (northern New Jersey), the February 2021 Winter Storm Warning (Dallas-Fort Worth), a Flash Flood Warning (Orlando) and a Tornado Warning (North Dakota). Each carries its source URL, and the Compare view shows how the same roster is triaged differently across them.

## What the agent does

| Step | Agent | What happens |
|---|---|---|
| Watch | Sentinel scan — **deterministic, no model** | Polls National Weather Service alerts for the roster's location and live feels-like temperature and air quality from Open-Meteo every 15 minutes. Opens an episode when a relevant alert or threshold appears, de-duplicated so one hazard opens one episode. |
| Assess | `assess` node | Reads the alert text and live conditions, returns a typed `HazardAssessment` (activate or stand down, severity, which risk factors are elevated, plain-language summary). A mild advisory stops here and nobody is disturbed. |
| Triage | `triage` node | Ranks every neighbor into tiers from their recorded risk factors (lives alone, no AC, oxygen concentrator, dialysis, memory issues, young kids, works outdoors) against the conditions measured at their own address. |
| Outreach | `outreach` node | Drafts a personal message per neighbor in English or Spanish with one concrete action and a one-tap check-in link. Calls `dispatch_outreach`, which **pauses for the coordinator**. |
| Logistics | `logistics` node | Matches volunteers to tier-1 neighbors by skill (Spanish, driver, nurse), proximity and load; finds the nearest real cooling center. Calls `assign_volunteers`, which **pauses for the coordinator**. |
| Brief | `brief` node | Writes a plain-language brief: who was contacted, who is visiting whom, what gaps remain, what the coordinator should do next. |
| Reply | `responder` agent | Reads what a neighbor actually wrote back — not a button press — answers them by name with the nearest cooled building, and flags them on the coordinator's board. |

Outreach and logistics are **parallel branches** that join at `brief`. The coordinator sees all of it on one screen: neighbors on the left ordered worst-first, the live map on the right, agent activity streaming, and a decision card whenever a human is needed.

## After the messages go out

This is the part a spreadsheet cannot do, and most of it is deliberately **not** left to a model.

**Reminders are paced and finite.** A neighbor who does not reply is reminded three times, three minutes apart. The count is kept **per person across every open episode**, not per row in a table — the difference between one reminder and six arriving at once. Any reply, in any channel, closes every open thread for that person immediately. (`backend/app/reminders.py`, `backend/tests/test_reminders.py`)

**Then it stops and says so.** Out of reminders with no word back, Porchlight stops texting and marks the person **critical** for the coordinator. Silence from someone on a home oxygen concentrator is the finding; sending a fourth message is not a plan.

**People write back in sentences, not buttons.** The `responder` agent reads free text in either language and works out what was actually said. Symptoms that mean *call 911 now* — chest pain, trouble breathing, confusion — are matched **before any model call** and answered with 911 advice, because that decision should not depend on a language model being available or in a good mood. (`backend/app/agents/responder.py`)

**Deployments are raised on evidence and matched to the need.** Not "somebody go check on Rosa" — a lift needs someone who drives, a powered medical device needs someone medical, and if no driver is free the lift degrades to a visit rather than silently vanishing. Each carries a road route and travel time from Valhalla, falling back to OSRM and then to a straight line, all keyless and cached. A deployment is a **suggestion** until the coordinator approves it. (`backend/app/deployments.py`, `backend/app/routing.py`)

**The moving marker is an estimate, and the interface says so.** Progress along a deployment is computed from the route and the elapsed time. Nobody is GPS-tracked, and the product never implies otherwise.

## How it uses Strands Agents

- **`GraphBuilder` multi-agent pipeline** (`backend/app/agents/pipeline.py`): five agents with distinct system prompts and tool sets, a conditional edge (`assess -> triage` only when the assessment says activate), and parallel branches (`outreach` and `logistics`) that join at `brief`.
- **Human-in-the-loop with interrupts** (`backend/app/agents/hooks.py`): `ApprovalGateHook` registers on `BeforeToolCallEvent` and calls `event.interrupt()` for every world-changing tool. The graph stops with `Status.INTERRUPTED` **inside the tool call**; the API turns each interrupt into an approval card; the coordinator's decision is fed back as an `interruptResponse` and the graph resumes exactly where it paused. A declined action sets `event.cancel_tool` with a message the agent can reason about. Edited messages are written back into `tool_use["input"]`.
- **An action is never asked twice.** Approvals are fingerprinted on the *material* content of the tool input, with model-rewritten wording (reasons, notes, summaries) stripped out, so an agent that re-proposes the same decision in different words is told it was already answered instead of re-prompting the coordinator forever. (`backend/tests/test_duplicate_approvals.py`)
- **Session persistence**: every graph uses `FileSessionManager`. A paused graph is rebuilt from its session and resumed when an approval arrives after a restart (covered by `tests/smoke_resume.py`).
- **Structured output**: the sentinel agent returns a Pydantic `HazardAssessment` via `structured_output_model`; the graph edge condition reads it.
- **Tools with context**: `@tool(context=True)` tools read the episode id from `invocation_state`, so one tool module serves every agent in every episode.
- **Hooks for observability**: `AuditHook` mirrors `BeforeModelCallEvent`, `BeforeToolCallEvent`, `AfterToolCallEvent` and `MessageAddedEvent` into a server-sent event stream and the episode timeline, which is what the dashboard's live feed shows.
- **Streaming**: `graph.stream_async()` node events drive the pipeline stepper; `agent.stream_async()` text deltas are forwarded live.
- **`ModelRouter` with fallback**: Amazon Bedrock (Nova Pro) first, with a configured fallback taking over if Bedrock fails, so a provider outage does not end an episode mid-run.
- **AgentCore Runtime entrypoint** (`backend/agentcore_app.py`): `BedrockAgentCoreApp` with a streaming `@app.entrypoint` that runs the identical graph and resumes on interrupt responses.
- **AgentCore Memory** (`backend/app/agents/agentcore_memory.py`): outcomes are written on every reply and at the end of every run; distilled lessons are read back at triage. See below.
- **Deterministic guardrails outside the model**: thresholds, alert filtering and de-duplication live in `sentinel.py`; reminder pacing lives in `reminders.py`; 911 symptom matching runs before the model. The model never decides *whether* to poll or *when* to stop reminding — only what to do once a real hazard exists.

## Memory across episodes

Heat comes back to the same street every summer, and what a coordinator learns the first time is exactly what a spreadsheet forgets.

Neighbor history always works locally in SQLite, with no AWS account. When `AGENTCORE_MEMORY_ID` is set, Porchlight additionally writes every outcome to **Amazon Bedrock AgentCore Memory** — automatically, on each reply and again when a run finishes; nothing asks a human to press a button. Two strategies are configured: a **semantic** strategy that keeps durable facts about a person, and a **summary** strategy that keeps what happened in one episode.

AgentCore then distils those raw events into its own records — *"Contact Lesson: Rosa Alvarez — answers in Spanish, by phone"* — and the `triage` agent **retrieves them at the start of the next hazard**. That closes the loop: a hazard happens, outcomes are recorded, and the next hazard starts better informed than the last.

```bash
cd backend
python scripts/create_agentcore_memory.py --region us-east-1   # prints the memory id
# put it in backend/.env as AGENTCORE_MEMORY_ID=...
```

## What is real and what is simulated

A project that claims nothing is faked should say plainly where the line is.

**Real:** the NWS alerts and forecast-zone polygons, the Open-Meteo conditions at each address, the OpenStreetMap cooling centers and their published phone numbers, the road routes and travel times, the Bedrock model calls, the AgentCore Memory resource, and the Telegram/SMS/email delivery.

**Not real:** the twelve neighbors. The roster is fictional — names, risk factors and phone numbers in the reserved `555-01xx` range — placed at real Maryvale, Phoenix coordinates, because NWS Phoenix issues real Extreme Heat Warnings the agent can act on live. Real people's medical details do not belong in a public demo repo.

**An estimate, not a measurement:** the marker moving along a deployment route. It is computed from the route and elapsed time. Nobody is tracked.

Three read-only reviewers were pointed at this codebase and told to find what was wrong with it rather than confirm that it worked. Their reports are published unedited in [`docs/audit/`](docs/audit/), including the one that found three of four phone numbers for real Phoenix institutions were wrong — one belonged to a hotel.

## Repository layout

```
backend/                  Python 3.11+ · FastAPI · Strands Agents SDK
  app/agents/             pipeline.py (the graph), tools.py, hooks.py (approval gate),
                          runner.py, sentinel.py, responder.py, agentcore_memory.py,
                          model_factory.py, playbooks.py
  app/feeds/              nws.py, open_meteo.py, places.py, footprint.py (warning-zone
                          polygons), field.py (conditions grid) — public APIs, no keys
  app/channels/           twilio_sms.py, telegram.py, ses_email.py, twilio_voice.py,
                          console.py, registry.py
  app/reminders.py        the paced, finite reminder ladder and the critical state
  app/deployments.py      who goes, matched to the need
  app/routing.py          Valhalla -> OSRM -> straight line, cached
  app/data/fixtures/      real archived NWS alerts for reproducible replays
  app/main.py             REST + SSE API
  agentcore_app.py        Amazon Bedrock AgentCore Runtime entrypoint
  tests/                  15 suites; see Testing below
  .env.example            all configuration; copy to backend/.env (never committed)
frontend/                 React 18 · Vite · Leaflet on OpenStreetMap
  src/pages/              Watch (the coordinator desk), Neighbor (a case page),
                          Checkin (what a neighbor sees), Compare, Report, Roster, Demo
  src/components/         MapView, ApprovalCard, PipelineStrip, DeploymentCards,
                          ActivityFeed, VoiceCallSim, ...
docs/                     architecture diagram, pitch one-pager, sources for every number,
                          demo script, go-live guide, and the three self-critique audits
docker-compose.yml        backend + nginx-served frontend
```

## Run it locally

Prerequisites: Python 3.11+, Node 20+, and — to run the agents against a model — AWS credentials with Amazon Bedrock model access.

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit: model provider, channels, PUBLIC_BASE_URL
python run.py                   # http://localhost:8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173  (proxies /api to the backend)
```

Open the desk and press **`ingestion`** to run the whole loop from an empty board. To replay a specific archived hazard instead, use the Compare view or the sentinel panel's replay control; five real NWS alerts ship in `backend/app/data/fixtures/`.

Or point the roster somewhere with weather right now: edit `backend/app/seed.py` coordinates, reset the database, and press **Scan now**.

### Bedrock preflight

Model access is the most common blocker. Before the first run, confirm your account can invoke the configured model:

```bash
aws bedrock list-foundation-models --region us-east-1 --by-provider amazon --query 'modelSummaries[].modelId'
python -c "from strands import Agent; print(Agent(model='amazon.nova-pro-v1:0', callback_handler=None)('Say ready.'))"
```

`python scripts/aws_preflight.py` runs the same checks from inside the server's own process and environment, which is the only version of the question that matters. If the model id is not enabled for your account, request access in the Bedrock console (Model access) or set `BEDROCK_MODEL_ID` to one that is.

### Model configuration (`backend/.env`)

| Setting | Purpose |
|---|---|
| `MODEL_PROVIDER=auto` | Bedrock first, then a configured fallback, through `strands.models.ModelRouter` |
| `BEDROCK_MODEL_ID`, `AWS_REGION` | Bedrock model; credentials come from the standard AWS chain or `AWS_BEARER_TOKEN_BEDROCK` |
| `ANTHROPIC_API_KEY` | optional fallback |

Amazon Nova Pro is the default because it is a Bedrock first-party model that needs no per-account use-case form, so a fresh AWS account can run Porchlight immediately. Anthropic models are a one-line swap once that form is approved.

### Real messages

`SEND_MODE=console` (the default) logs every message instead of sending it. Set `SEND_MODE=live` and configure any of: Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`), Telegram (`TELEGRAM_BOT_TOKEN` — the fastest live channel to set up, and replies come back automatically), or Amazon SES (`SES_FROM_EMAIL`).

**Before sending anything live, set `DEMO_LIVE_MEMBER_ID`.** With a demo override configured, that setting limits real delivery to one neighbor — yours — and logs everyone else. Without it, a twelve-person roster sends twelve messages to the same device at once. The demo video was recorded this way: one neighbor contacted for real, the rest logged, and the video says so out loud.

### Docker

```bash
cp backend/.env.example backend/.env   # edit
docker compose up --build              # http://localhost:5173
```

## Amazon Bedrock AgentCore

**Memory** is live and in use — see [Memory across episodes](#memory-across-episodes) above.

**Runtime**: `backend/agentcore_app.py` is a `BedrockAgentCoreApp` entrypoint that runs the identical graph and streams its events, with interrupts returned as payloads and resumed by invoking again with `interrupt_responses`. To deploy it:

```bash
npm install -g @aws/agentcore
cd backend
agentcore create          # framework: Strands · entrypoint: agentcore_app.py · model: Bedrock
agentcore deploy
agentcore invoke '{"action": "replay", "fixture_id": "nws_phoenix_extreme_heat_warning_2026-09-08"}'
# resume after the coordinator decides:
agentcore invoke '{"action": "resume", "episode_id": "<id>", "interrupt_responses": [{"interruptId": "<id>", "response": {"decision": "approve"}}]}'
```

The FastAPI service can be pointed at the deployed runtime instead of running the graph in-process. Observability: install `strands-agents[otel]` (already in requirements) and set `OTEL_EXPORTER_OTLP_ENDPOINT`, or enable CloudWatch GenAI Observability on the runtime.

## Taking it live

Console mode logs every message instead of sending it, so the whole product is testable with no accounts. To make the agent send real texts, calls, or emails, see [docs/go-live.md](docs/go-live.md) for the exact environment variables, tiered by what each one unlocks.

## Testing

`backend/scripts/verify.sh` runs every suite below and builds the frontend. Individually:

```bash
cd backend
python -m tests.test_deterministic        # alert classification, fixture parsing, atomic store updates
python -m tests.test_pipeline_mechanics   # the whole graph, both approval pauses, with no model provider
python -m tests.test_reminders            # pacing, per-person counting, one reply closing everything
python -m tests.test_duplicate_approvals  # the same decision is never asked twice
python -m tests.test_deployments          # skill matching, and degrading a lift when no driver is free
python -m tests.test_map_layers           # warning-zone polygons and the conditions grid
python -m tests.test_telegram_replies     # free-text replies, and 911 symptoms matched before the model
python -m tests.test_memory               # neighbor history and AgentCore Memory round-trip
python -m tests.test_recovery             # what happens after a run has already gone wrong
python -m tests.test_actions              # ...plus multi_hazard, outage, report, voice
python -m tests.smoke_strands             # needs a model provider
python -m tests.smoke_resume              # resume a paused graph from a new Graph object
```

`test_pipeline_mechanics` is the one worth reading. It runs the real `Graph`, the real approval hook and
the real tools, with `tests/scripted_model.py` — a `Model` subclass that emits a fixed sequence of tool
calls — in place of a language model. In a few seconds it shows the graph pausing twice for coordinator
approval, resuming after each decision, sending the messages, and producing the check-in links.

**That file is a test double, and the distinction matters.** It is imported only by tests and never runs
in the product; nothing a user or a judge sees comes from it. It proves the machinery around the agents
is real. It deliberately proves nothing about the agents' judgement — every plan it emits is hard-coded,
so the quality of an assessment, a triage or a message is left entirely to the model, where it belongs.

The smoke tests exercise the same path on a real model provider: a `BeforeToolCallEvent` interrupt, resume
from a `FileSessionManager` session in a fresh `Agent`, tool execution after approval, `structured_output_model`,
and a `Graph` whose node interrupts and then resumes to completion.

## Safety and privacy

- No message, volunteer dispatch or escalation leaves the system without a coordinator decision, unless the coordinator has explicitly enabled the one standing policy (auto-dispatch a volunteer to a tier-1 neighbor who has not replied).
- Reminders are capped. Porchlight will not keep texting someone who is not answering; it stops and escalates to a human.
- Symptoms that mean *call 911* are matched deterministically, before any model call, so that answer never depends on a model being reachable.
- Nobody is GPS-tracked. The marker moving along a route is an estimate computed from the route, and the interface says so.
- The roster in this repo is fictional; the coordinates and cooling centers are real Maryvale, Phoenix locations.
- Porchlight is a coordination aid for volunteers, not an emergency service. The check-in page tells neighbors to call 911 for symptoms of heat stroke.
- `backend/.env` holds every secret and is git-ignored. No credential, token or key is committed anywhere in this repository or its history.

## Built with

Strands Agents SDK 1.55 (Python) · Amazon Bedrock (Nova Pro) · Amazon Bedrock AgentCore Runtime · Amazon Bedrock AgentCore Memory · Amazon Polly · Amazon SES · FastAPI · React + Vite · Leaflet/OpenStreetMap · National Weather Service API · Open-Meteo · Valhalla / OSRM · Twilio · Telegram

AI coding assistants were used for boilerplate, tests and debugging, as permitted by the hackathon rules. All code was written during the submission period.

## License

MIT, see [LICENSE](LICENSE).
