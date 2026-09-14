# Porchlight

**A neighbor check-in agent for community groups, built with the Strands Agents SDK.**
When an Extreme Heat Warning, smoke event, freeze, or outage threatens a neighborhood, Porchlight works in the background: it reads the official alert, figures out which neighbors are actually in danger, writes each of them a personal message in their language, lines up volunteers and cooling centers, and then pauses so the block captain can approve with one click. After the messages go out it keeps watching the replies and escalates the people who never answer.

*Agents for Humans Hackathon · Good Neighbor Agents track · MIT licensed*

![Architecture](docs/architecture.svg)

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
| The coordinator guesses who is most at risk | The triage agent ranks every neighbor from their recorded risk factors and the conditions at their home |
| The coordinator types texts one by one, in two languages | The outreach agent drafts one personal message per neighbor; the coordinator edits and approves them in one card |
| The coordinator calls around for a driver | The logistics agent proposes volunteer matches by skill, distance and load; the coordinator approves |
| The coordinator tries to remember who never answered | The follow-up agent tracks replies and escalates non-responders, with approval |
| Nothing is written down afterwards | The brief and the timeline are the after-action record |

The list stays the community's list. The decisions stay with the coordinator. The check-in page tells neighbors in distress to call 911.

## Multi-hazard

The loop is the same for every hazard: official alert in, triage, personal outreach, volunteers, follow-up. The sentinel maps National Weather Service event names deterministically to hazard types (heat, air quality including smoke and dust, cold, winter, flood, storm) in `backend/app/feeds/nws.py`, and threshold checks on live Open-Meteo conditions (feels-like at or above 105 F, US AQI at or above 151, air at or below 15 F) cover places without an active alert. For hazards no feed reports (a power outage, a water main break, a building evacuation) the sentinel panel has a manual report form; a coordinator-reported outage runs the same loop with hazard type `outage`. The prompts ask the agents to reason about the hazard they are given, so a freeze warning raises the oxygen-concentrator and no-heat neighbors while a smoke event raises the COPD and asthma neighbors. Five real archived NWS alerts ship as replay fixtures: an Extreme Heat Warning (Phoenix), an Air Quality Alert from the 2023 Canadian wildfire smoke (northern New Jersey), the February 2021 Winter Storm Warning (Dallas-Fort Worth), a Flash Flood Warning (Orlando) and a Tornado Warning (North Dakota). Each carries its source URL, and the Compare view shows how the same roster is triaged differently across them.

## What the agent does

| Step | Strands agent | What happens |
|---|---|---|
| Watch | Sentinel scan (deterministic, no LLM) | Polls National Weather Service alerts for the roster's location and live feels-like temperature and air quality from Open-Meteo every 15 minutes. Opens an episode when a relevant alert or threshold appears. |
| Assess | `assess` node | Reads the alert text and live conditions, returns a typed `HazardAssessment` (activate or stand down, severity, which risk factors are elevated, plain-language summary). |
| Triage | `triage` node | Ranks every neighbor into tiers from their risk factors (lives alone, no AC, oxygen concentrator, dialysis, memory issues, young kids, works outdoors) and live conditions at their home. |
| Outreach | `outreach` node | Drafts a personal message per neighbor in English or Spanish with one concrete action and a one-tap check-in link. Calls `dispatch_outreach`, which **pauses for the coordinator**. |
| Logistics | `logistics` node | Matches volunteers to tier-1 neighbors by skill (Spanish, driver, nurse), proximity and load; finds the nearest real cooling center. Calls `assign_volunteers`, which **pauses for the coordinator**. |
| Brief | `brief` node | Writes a plain-language brief: who was contacted, who is visiting whom, what gaps remain, what the coordinator should do next. |
| Follow up | `followup` agent | Every two minutes while monitoring: reads check-in replies, escalates "I need help" and tier-1 non-responders (volunteer visit, emergency contact, 911 advice). Each escalation pauses for approval unless the coordinator's standing policy pre-authorises it. |

The coordinator sees all of it on one screen: live agent activity, a decision card with editable messages, neighbor status tiles, a map, and the brief. Neighbors see a single page with two very large buttons.

## How it uses Strands Agents

- **`GraphBuilder` multi-agent pipeline** (`backend/app/agents/pipeline.py`): five agents with distinct system prompts and tool sets, a conditional edge (`assess -> triage` only when the assessment says activate), and parallel branches (`outreach` and `logistics`) that join at `brief`.
- **Human-in-the-loop with interrupts** (`backend/app/agents/hooks.py`): `ApprovalGateHook` registers on `BeforeToolCallEvent` and calls `event.interrupt()` for every world-changing tool. The graph stops with `Status.INTERRUPTED`; the API turns each interrupt into an approval card; the coordinator's decision is fed back as an `interruptResponse` and the graph resumes exactly where it paused. A declined action sets `event.cancel_tool` with a message the agent can reason about. Edited messages are written back into `tool_use["input"]`.
- **Session persistence**: every graph and the follow-up agent use `FileSessionManager`. A paused graph is rebuilt from its session and resumed when an approval arrives after a restart (covered by `tests/smoke_resume.py`).
- **Structured output**: the sentinel agent returns a Pydantic `HazardAssessment` via `structured_output_model`; the graph edge condition reads it.
- **Tools with context**: `@tool(context=True)` tools read the episode id from `invocation_state`, so one tool module serves every agent in every episode.
- **Hooks for observability**: `AuditHook` mirrors `BeforeModelCallEvent`, `BeforeToolCallEvent`, `AfterToolCallEvent` and `MessageAddedEvent` into a server-sent event stream and the episode timeline, which is what the dashboard's live feed shows.
- **Streaming**: `graph.stream_async()` node events drive the pipeline stepper; `agent.stream_async()` text deltas are forwarded live.
- **`ModelRouter` with fallback**: Amazon Bedrock (Nova Pro) first; with `MODEL_PROVIDER=auto`, TokenRouter or the Anthropic API take over if Bedrock fails, so a provider outage does not end an episode mid-run.
- **AgentCore Runtime entrypoint** (`backend/agentcore_app.py`): `BedrockAgentCoreApp` with a streaming `@app.entrypoint` that runs the identical graph and resumes on interrupt responses.
- **Deterministic guardrails outside the LLM**: thresholds, alert filtering and de-duplication live in `sentinel.py`; the model never decides whether to poll, only what to do once a real hazard exists.

## Repository layout

```
backend/                  Python 3.11+ · FastAPI · Strands Agents SDK
  app/agents/             pipeline.py (graph), tools.py, hooks.py, runner.py, sentinel.py, model_factory.py
  app/feeds/              nws.py, open_meteo.py, places.py (public APIs, no keys)
  app/channels/           twilio_sms.py, telegram.py, ses_email.py, console.py, registry.py
  app/data/fixtures/      real archived NWS alerts for reproducible replays
  app/main.py             REST + SSE API
  agentcore_app.py        Amazon Bedrock AgentCore Runtime entrypoint
  tests/smoke_strands.py  verifies interrupts, resume, sessions, structured output, graph
  .env.example            all configuration; copy to backend/.env (never committed)
frontend/                 React 18 · Vite · Leaflet
  src/pages/              Dashboard (coordinator desk), Checkin (neighbor page), Roster
docs/                     architecture diagram, pitch one-pager, sources for every number, demo script, Devpost text, builder.aws.com post drafts
docker-compose.yml        backend + nginx-served frontend
```

## Run it locally

Prerequisites: Python 3.11+, Node 20+, and AWS credentials with Amazon Bedrock model access (an Anthropic API key also works as a fallback).

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit: model provider, channels, PUBLIC_BASE_URL
python run.py                   # http://localhost:8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173  (proxies /api to the backend)
```

Open the desk, press **Replay this alert** (a real Extreme Heat Warning from NWS Phoenix, archived in `backend/app/data/fixtures/`), and watch the agents work. When the decision card appears, edit a message if you like and press **Approve & send**. Open one of the check-in links printed in the activity feed (or the SMS if a channel is configured) and tap **I need help**; the follow-up agent escalates.

Or point the roster somewhere with weather right now: edit `backend/app/seed.py` coordinates, reset the database, and press **Scan now**.

### Bedrock preflight

Model access is the most common blocker. Before the first run, confirm your account can invoke the configured model:

```bash
aws bedrock list-foundation-models --region us-east-1 --by-provider amazon --query 'modelSummaries[].modelId'
python -c "from strands import Agent; print(Agent(model='amazon.nova-pro-v1:0', callback_handler=None)('Say ready.'))"
```
If the model id is not enabled for your account, request access in the Bedrock console (Model access) or set `BEDROCK_MODEL_ID` to one that is.

### Model configuration (`backend/.env`)

| Setting | Purpose |
|---|---|
| `MODEL_PROVIDER=auto` | Bedrock, then Anthropic, through `strands.models.ModelRouter` |
| `BEDROCK_MODEL_ID`, `AWS_REGION` | Bedrock model; credentials come from the standard AWS chain or `AWS_BEARER_TOKEN_BEDROCK` |
| `ANTHROPIC_API_KEY` | optional fallback |

### Real messages

`SEND_MODE=console` (default) logs every message instead of sending. Set `SEND_MODE=live` and configure any of: Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`), Telegram (`TELEGRAM_BOT_TOKEN`, members need a `telegram_chat_id`; replies of "OK" or "HELP" are captured automatically), or Amazon SES (`SES_FROM_EMAIL`). `DEMO_OVERRIDE_PHONE` / `DEMO_OVERRIDE_EMAIL` route every outbound message to one address you control, which is how the demo video was recorded without texting fictional neighbors.

### Docker

```bash
cp backend/.env.example backend/.env   # edit
docker compose up --build              # http://localhost:5173
```

## Deploy the agent to Amazon Bedrock AgentCore Runtime

```bash
npm install -g @aws/agentcore
cd backend
agentcore create          # framework: Strands · entrypoint: agentcore_app.py · model: Bedrock
agentcore deploy
agentcore invoke '{"action": "replay", "fixture_id": "nws_phoenix_extreme_heat_warning_2026-09-08"}'
# resume after the coordinator decides:
agentcore invoke '{"action": "resume", "episode_id": "<id>", "interrupt_responses": [{"interruptId": "<id>", "response": {"decision": "approve"}}]}'
```

The runtime entrypoint streams graph events and interrupt payloads; the FastAPI service can be pointed at it instead of running the graph in-process. Observability: install `strands-agents[otel]` (already in requirements) and set `OTEL_EXPORTER_OTLP_ENDPOINT`, or enable CloudWatch GenAI Observability on the runtime.

## Taking it live

Console mode logs every message instead of sending it, so the whole product is testable with no accounts. To make the agent send real texts, calls, or emails, see [docs/go-live.md](docs/go-live.md) for the exact environment variables, tiered by what each one unlocks.

## Testing

`backend/scripts/verify.sh` runs every test below and builds the frontend. Individually:

```bash
cd backend
python -m tests.test_deterministic       # alert classification, fixture parsing, atomic store updates
python -m tests.test_pipeline_mechanics  # the whole graph, both approval pauses, with no model provider
python -m tests.test_recovery            # what happens after a run has already gone wrong
python -m tests.smoke_strands            # needs a model provider
python -m tests.smoke_resume             # resume a paused graph from a new Graph object
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
- The roster in this repo is fictional; the coordinates and cooling centers are real Maryvale, Phoenix locations chosen because NWS Phoenix issues real Extreme Heat Warnings the agent can act on live.
- Porchlight is a coordination aid for volunteers, not an emergency service. The check-in page tells neighbors to call 911 for symptoms of heat stroke.
- `backend/.env` holds every secret and is git-ignored. Scan the repo before publishing.

## Built with

Strands Agents SDK 1.55 (Python) · Amazon Bedrock (Nova Pro) · Amazon Bedrock AgentCore Runtime · FastAPI · React + Vite · Leaflet/OpenStreetMap · National Weather Service API · Open-Meteo · Twilio / Telegram / Amazon SES

AI coding assistants were used for boilerplate, tests and debugging, as permitted by the hackathon rules. All code was written during the submission period.

## License

MIT, see [LICENSE](LICENSE).
