# Authenticity audit — "Nothing is faked."

> **Point-in-time report.** This is the audit as it was written, unedited, against the tree of that
> date. Findings listed here as missing or broken may have been fixed since — the repository's
> current state is what `README.md` and the test suite describe. The reports are kept because a
> project claiming nothing is faked should be willing to publish what its own critics found.

> **Status:** this is the original report, kept unedited. Everything it marks BLOCKER has been fixed;
> see [README.md](README.md) for what changed and what is still open. Line numbers below refer to the
> tree on 2026-09-08 and have since drifted.

**Scope:** fabricated real-world facts, fixture integrity, claims vs implementation, simulation smells, unverified
SDK usage, dead code.
**Audited:** 2026-09-08, the **working tree** (not `HEAD`).
At audit time `git status` showed 11 modified tracked files and 6 untracked new files (see G1); another agent
appears to have been editing concurrently, so line numbers may drift. Every `file:line` below was confirmed with
`grep -n` at the moment of writing.

**Headline:** the code is remarkably clean. I found **zero** runtime fakery — no `random`, no `time.sleep`
theatre, no canned data, no hardcoded numeric metrics in JSX, no function that returns a pre-baked answer
instead of computing it. The after-action metrics are genuinely computed, the fixtures are verified property-by-
property against the National Weather Service, every AgentCore SDK call is real, and all seven no-model test
suites pass. The problems are concentrated in three places: **hardcoded contact data for real institutions that
is largely wrong**, **AWS claims the repo has no evidence for**, and — the one I did not expect —
**every persisted graph run in this repo failed; the five-agent pipeline has never completed once.**

---

## A. Fabricated real-world facts

### A1. Three of four hardcoded phone numbers for real Phoenix institutions are wrong; one is fabricated and reused for two different facilities

- **Severity:** blocker
- **File:** `backend/app/seed.py:66-74` (the `RESOURCES` list; comment at `:64`)
- **What:** `seed.py` hardcodes name, address, phone and hours for four real, named public institutions. Three
  of the four phone numbers do not belong to the facility they are attached to. `+16024955760` is attached to
  **both** Maryvale Community Center and Desert West Community Center — two facilities that genuinely have
  different numbers — and could not be attributed to any City of Phoenix facility on any reachable source.
  `+16022622500` (claimed for Palo Verde Library) is the Sheraton Phoenix Downtown hotel. The 2-1-1 entry
  (`:73`) attributes a statewide Solari service to Maricopa County and invents a heat-season-only schedule.
  All three lat/lon pairs are 385–650 m north of the actual buildings.
- **Evidence:** verified against phoenixpubliclibrary.org, phoenix.gov Parks & Recreation facility pages,
  211arizona.org and OSM/Nominatim:

  | Field | In `seed.py` | Verdict | Correct value | Source |
  |---|---|---|---|---|
  | Palo Verde Library name | `Palo Verde Library` | correct | — | phoenixpubliclibrary.org/locations |
  | Palo Verde Library address | `4402 N 51st Ave, ... 85031` | correct | — | same |
  | Palo Verde Library **phone** | `+16022622500` | **WRONG** | `602-262-4636` (Phoenix Public Library Call Center; no branch-direct line is published). `602-262-2500` is the Sheraton Phoenix Downtown. | phoenixpubliclibrary.org/locations/palo-verde |
  | Palo Verde Library lat/lon | `33.5039, -112.1692` | **WRONG (~385 m N)** | `33.5005, -112.1698` | Nominatim |
  | Maryvale CC name / address | `Maryvale Community Center` / `4420 N 51st Ave` | correct | — | phoenix.gov |
  | Maryvale CC **phone** | `+16024955760` | **WRONG** | `602-262-5030` | phoenix.gov facility page; corroborated on the Palo Verde library page |
  | Maryvale CC lat/lon | `33.5043, -112.1690` | **WRONG (~385 m N)** | `33.5009, -112.1697` | Nominatim |
  | Desert West CC name / address | `Desert West Community Center` / `6501 W Virginia Ave` | correct — and correctly *not* confused with the separate Desert West Park & Sports Complex at 6602 W Encanto Blvd | — | phoenix.gov |
  | Desert West CC **phone** | `+16024955760` | **WRONG** | `602-495-3700` | phoenix.gov facility page |
  | Desert West CC lat/lon | `33.4816, -112.1990` | **WRONG (~650 m N)** | `33.4760, -112.2012` | Nominatim |
  | 2-1-1 **name** | `Maricopa County 2-1-1 Heat Relief line` | **WRONG** | `2-1-1 Arizona` — a statewide program of **Solari Crisis & Human Services**, not a Maricopa County agency and not a heat-specific line. The regional **Heat Relief Network** is run by **MAG** (hrn.azmag.gov), also not the county. | 211arizona.org/about-us |
  | 2-1-1 phone | `211` | correct | also `877-211-8661` | 211arizona.org |
  | 2-1-1 **hours** | `9am-7pm daily during heat season` | **PARTLY WRONG** | 9am–7pm seven days a week, **year-round**, not heat-season-only | 211arizona.org/about-us; phoenix.gov |
  | 2-1-1 notes ("cooling centers, water, transportation") | — | correct | — | phoenix.gov heat-relief newsroom |

  This is not cosmetic. `find_nearby_cooled_places` puts `r.phone`, `r.address` and `r.hours` straight into the
  outreach agent's context, which writes them into a neighbor's message:

  ```python
  # backend/app/agents/tools.py:163-164
  known.append({"resource_id": r.id, "name": r.name, "kind": r.kind, "address": r.address,
                "hours": r.hours, "phone": r.phone, "distance_km": round(d, 2)})
  ```

  And the agents' own system prompt forbids exactly this:

  ```python
  # backend/app/agents/pipeline.py:73
  - Use tools to get facts; never invent members, volunteers, phone numbers, hours, or weather values.
  ```

  The rule is enforced on the model and broken by the seed data the model is handed. Two facilities sharing one
  phone number is the visible tell a judge would spot without leaving the file.
- **Fix:** correct the four rows. `Resource.phone` is `str = ""` (`backend/app/models.py:82`) and `hours` is
  `str = ""` (`:81`), so both are safely blankable:
  ```python
  Resource(id="res_paloverde", name="Palo Verde Library", ..., lat=33.5005, lon=-112.1698,
           phone="+16022624636",  # Phoenix Public Library Call Center; no branch-direct line is published
           ...),
  Resource(id="res_maryvalecc", name="Maryvale Community Center", ..., lat=33.5009, lon=-112.1697,
           phone="+16022625030", ...),
  Resource(id="res_desertwest", name="Desert West Community Center", ..., lat=33.4760, lon=-112.2012,
           phone="+16024953700", ...),
  Resource(id="res_211", name="2-1-1 Arizona (Solari)", ..., hours="9am-7pm daily, year-round", ...),
  ```
  If any value cannot be re-verified before submission, **blank the field** rather than guess — the `hours`
  fields already use the honest `"Confirm current hours"` pattern, which is the right instinct and should be
  extended to `phone`.

### A2. The seed comment overclaims Heat Relief Network membership and misattributes the network

- **Severity:** minor
- **File:** `backend/app/seed.py:64`
- **What:** the comment reads "Real public buildings in Maryvale that **Maricopa County's Heat Relief Network**
  has used as cooling sites." Palo Verde Library is verifiably a City of Phoenix cooling center (one of 17
  library sites). The two community centers appear on **no** reachable published cooling-center or heat-relief
  list — neither their own phoenix.gov pages nor the city's heat-relief newsroom list mentions cooling or
  respite. Separately, the Heat Relief Network is operated by **MAG** (Maricopa Association of Governments,
  hrn.azmag.gov), not by Maricopa County.
- **Caveat, stated so it is not overread:** hrn.azmag.gov's interactive map is a JS application that returns
  403 to scrapers, so the community centers' *absence* from the network could not be positively established —
  only their absence from every text list reachable. The MAG-vs-county attribution is established.
- **Fix:** reword to what is verifiable, e.g. *"Real public buildings near the demo roster. Palo Verde Library
  is a City of Phoenix cooling center; the community centers are plausible sites the coordinator should confirm
  against the MAG Heat Relief Network map (hrn.azmag.gov) each season."*

### A3. Fictional roster data is handled correctly — verified clean

- **Severity:** — (verified correct)
- **File:** `backend/app/seed.py:11-58`
- **What:** every member/volunteer phone is in the `+1602555xxxx` reserved-fiction range, the one email is
  `@example.com`, and both the module docstring (`:1`) and the README say the roster is fictional. Coordinates
  are real Maryvale street locations, which is exactly what the README claims. No issue.

---

## B. Fixture integrity

### B1. All five fixtures are genuine NWS products — three verified property-by-property against the live API, two verbatim against the raw text archive

- **Severity:** — (verified correct)
- **Files:** `backend/app/data/fixtures/*.json`
- **What:** I did not stop at "reads like a real product." I re-fetched every source and diffed.
- **Evidence:**
  - The three `api.weather.gov` fixtures (`mclean_county_nd_tornado`, `orlando_flash_flood`,
    `phoenix_extreme_heat`) were re-fetched live from the `@id` / `source_url` in each file and every key in
    `properties` compared. Result for all three: **`NONE — identical to live api.weather.gov`**. Not one field
    was edited, trimmed or added.
  - `nws_northern_new_jersey_air_quality_alert_2023-06-07.json`: re-fetched the AFOS `AQAOKX` archive
    (`retrieve.py?pil=AQAOKX&sdate=2023-06-06&edate=2023-06-09`, 53 KB). `headline` and `description` are
    **verbatim substrings** of the raw product (whitespace-normalised match). `instruction` is empty and the
    provenance block correctly explains why ("no instruction section exists in the product").
  - `nws_fort_worth_winter_storm_warning_2021-02-12.json`: re-fetched `WSWFWD`. All six paragraphs of
    `description`, plus `headline` and `instruction`, are **verbatim** slices. **All 46 counties** in
    `areaDesc` appear in the product (checked exhaustively, none missing). `onset`/`expires` match the P-VTEC
    line `/O.NEW.KFWD.WS.W.0003.210213T1200Z-210216T0000Z/` exactly. **The fixture also carries the complete
    `parameters.rawText`** — the whole raw product — so a judge can audit the conversion themselves. Nothing was
    invented.
  - Honest handling of absent CAP fields: FWD leaves `severity`/`certainty`/`urgency` as `""` and says so in its
    provenance note; NJ uses `"Unknown"`, which is what the NWS API genuinely returns for Air Quality Alerts.
    Neither file guessed a severity.
  - `backend/tests/test_multi_hazard.py::test_fixture_text_is_real_alert_text` already guards this and passes.
- **Conclusion:** this is the strongest part of the project. Say so in the README.

### B2. The Phoenix fixture is the only one with no `porchlight` provenance block

- **Severity:** nit
- **File:** `backend/app/data/fixtures/nws_phoenix_extreme_heat_warning_2026-09-08.json` (top level)
- **What:** the other four carry a `porchlight` block with `retrieved`, `source`, `source_url`, `place` and a
  conversion note. The Phoenix file is the raw, unmodified API `FeatureCollection` with `@context`/`title`/
  `updated` and no block. It is arguably the *most* authentic of the five, but the inconsistency invites the
  question "why does the flagship demo alert have no provenance?" — and `sentinel.list_fixtures()` falls back to
  `senderName.removeprefix("NWS ")` for `place`, so the UI shows "Phoenix AZ" instead of a curated label.
- **Fix:** add the same block (the `@id` already in the file is the `source_url`):
  ```json
  "porchlight": {
    "retrieved": "2026-09-09T04:34:31Z",
    "source": "api.weather.gov alerts archive",
    "source_url": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.584fd59be8737281b62d15bc75eb473ffaec99d0.003.1",
    "place": "Phoenix metro, AZ",
    "note": "Unmodified api.weather.gov response."
  }
  ```

---

## C. Claims vs implementation

Claims I traced and can confirm are **honest**:

| Claim | Where implemented | Verdict |
|---|---|---|
| `GraphBuilder` graph, 5 agents, conditional edge, parallel branches joining at `brief` | `pipeline.py:196-211` | verified |
| Interrupt-based approval on exactly `dispatch_outreach`, `assign_volunteers`, `escalate_member` | `hooks.py:126-166`, `tools.py:36` | verified |
| Declined action sets `event.cancel_tool`; edits written into `tool_use["input"]` | `hooks.py:160`, `hooks.py:165-166` | verified |
| Structured output drives the graph edge | `pipeline.py:179-180` (`structured_output_model=HazardAssessment`), edge condition `pipeline.py:188-196` | verified |
| `ModelRouter` Bedrock → Anthropic → Ollama | `model_factory.py:63-75`; `ModelRouter(models, *, strategy=None, max_switches=None)` signature confirmed in strands-agents 1.55.0 | verified |
| Deterministic sentinel, no LLM decides when to poll | `sentinel.py`, `scheduler.py` | verified |
| **Two-way Telegram**, "OK"/"HELP" replies captured automatically | `telegram.get_updates` → `scheduler.telegram_job` (`scheduler.py:48-79`, 8 s poll, matches `telegram_chat_id`, writes a `Checkin`, emits to the bus) | verified |
| Multi-hazard: NWS event → hazard type, playbooks per hazard | `nws._EVENT_MAP`, `playbooks.py`; `test_multi_hazard` passes 5/5 | verified |
| After-action report metrics | `report.py` — pure and deterministic, no model/store/network; every number derived from the episode, check-ins and approvals. Narrative explicitly "paraphrases those numbers." `test_report` passes 3/3 | verified |
| Memory across episodes | `tools_memory.py` computes history from the store; `get_neighbor_history`/`get_community_history` are wired into the sentinel, triage, brief and follow-up agents (`pipeline.py:179, 181, 184, 217`); the AgentCore writer is a live bus subscriber (`routes_memory.py:96-117`); `test_memory` passes 5/5 | verified |
| Session persistence survives restart | genuinely implemented: approvals persist to SQLite with `interrupt_id`; `runner._run_graph` rebuilds via `build_graph(ep)` when `self._graphs` is empty (`runner.py:62-64`) and `build_graph` attaches `FileSessionManager(session_id=f"graph-{ep.id}")` (`pipeline.py:210`); `runner.decide` reconstructs `interruptResponse` payloads from the persisted rows (`runner.py:199`) | verified (but see C2) |

### C1. Every persisted graph run in this repo failed; the five-agent pipeline has never completed once

- **Severity:** blocker
- **Files:** `backend/data/sessions/*/multi_agents/multi_agent_default_graph/multi_agent.json` (6 files);
  `backend/.env`; `docs/builder-aws-posts.md:32,54`
- **What:** I read all six persisted graph session states. **Every one has `"status": "failed"`.** Five failed
  at the very first node; the best run got one node further and then timed out:

  ```
  ep_095e1d1150  failed  completed=[]        failed=['assess']  assess: "All connection attempts failed"
  ep_19f205b0b2  failed  completed=[]        failed=['assess']  assess: "Node 'assess' execution timed out after 900s"
  ep_3062b8b853  failed  completed=[]        failed=['assess']  assess: "Server disconnected without sending a response."
  ep_82dc21927f  failed  completed=[]        failed=['assess']  assess: "All connection attempts failed"
  ep_9189bd9e2a  failed  completed=['assess'] failed=['triage']  triage: "Node 'triage' execution timed out after 900s"
  ep_ac479f33f5  failed  completed=[]        failed=['assess']  assess: "All connection attempts failed"
  ```

  `backend/data/porchlight.db` holds 2 episodes, neither with an assessment, triage or outreach record.
  This exactly corroborates `docs/builder-aws-posts.md:54` ("the 3B model on a laptop CPU timed out on triage").
  So: `assess` has succeeded **once**, on Ollama/`qwen2.5:3b`; `triage`, `outreach`, `logistics`, `brief` and
  the approval card have **never** run to completion on any provider.
  Nothing in the code is faked because of this — but the demo everything else describes has not yet been
  observed to work, which means there is no approval-card screenshot, no completed after-action report, and no
  demo video footage yet. This is the single highest-risk item for the submission, and it is a *capacity*
  problem, not a code problem: the machine has no model that can run the pipeline.
- **Fix:** get one full pipeline run on a real model (Bedrock or the Anthropic API — anything but a 3 B model on
  a 2017 CPU) before anything else. Everything in this audit is cheap; this one is the gate. Note that
  `POST /api/episodes/{id}/retry` (`routes_demo.py:67`) already rebuilds a failed graph from its session and
  resumes with completed nodes intact, so `ep_9189bd9e2a` — which has `assess` completed — can be resumed rather
  than restarted once a working model is configured.

### C2. "Amazon Bedrock" and "Amazon Bedrock AgentCore Runtime" are presented as things the project uses; the repo contains no evidence either has ever run

- **Severity:** major
- **Files:** `README.md:188` ("Built with"), `docs/devpost-submission.md:7` ("Built with"),
  `docs/pitch-one-pager.md:3` ("Built with the Strands Agents SDK **on Amazon Bedrock**"),
  `docs/builder-aws-posts.md:32,54`
- **What:** three of four public-facing docs list Amazon Bedrock and AgentCore Runtime as part of the stack.
  The repo's own evidence says neither has been exercised:
  - `backend/.env`: `MODEL_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:3b`. No AWS credentials configured.
  - `docs/builder-aws-posts.md` still contains `[FINALIZE AFTER FIRST BEDROCK RUN.]` (`:32`),
    `[FINALIZE AFTER FIRST BEDROCK RUN: add timings and a screenshot of the decision card.]` (`:54`), and a
    literal `Repo: <link>` placeholder (`:32`) — the drafts state outright that the first Bedrock run has not
    happened.
  - Every persisted session failed on a local Ollama connection (C1).
  - `agentcore_app.py` is real, imports cleanly (`BedrockAgentCoreApp` confirmed present in
    bedrock-agentcore 1.22.0) and reuses the same graph — but it has never been deployed, and it holds `_graphs`
    in process memory with SQLite and `FileSessionManager` on local disk, so cross-invocation resume on
    AgentCore Runtime depends on container/session affinity that nothing here tests.
  This is the claim an AWS judge is most likely to probe.
- **Fix:** either (a) run it once — one Bedrock pipeline run plus one `agentcore deploy` + `agentcore invoke` —
  then delete the two `FINALIZE` markers and the `<link>` placeholder; or (b) reword to what is true:
  "**deployable to** Amazon Bedrock AgentCore Runtime (`backend/agentcore_app.py`); developed against Ollama and
  the Anthropic API via `ModelRouter`." Never ship `docs/builder-aws-posts.md` with the bracketed markers in it.

### C3. `tests/smoke_resume.py` does not test what the README says it covers

- **Severity:** minor
- **Files:** `README.md:72`; `backend/tests/smoke_resume.py:65`
- **What:** the README says "A paused graph is rebuilt from its session and resumed when an approval arrives
  **after a restart** (covered by `tests/smoke_resume.py`)." The test does `del g1  # simulate process restart:
  nothing in memory` and then builds a second `Graph` from the same session directory **in the same process** —
  module state, the `SENT` list, the session manager's caches and the model object all survive. It is a good
  test of "resume in a fresh `Graph` object from the session on disk"; it is not a process-restart test. The
  interrupt ids it feeds back also come from the in-memory `r1.interrupts` rather than from persisted rows.
- **Evidence:** the *production* path is stronger than the test — `Approval.interrupt_id` is persisted in
  SQLite and `runner.decide` (`runner.py:174-201`) reconstructs `interruptResponse` payloads from those rows —
  so the claim is probably true; it just is not the thing that is tested.
- **Fix:** either restate `README.md:72` as "resumed in a fresh `Graph` rebuilt from the session on disk
  (covered by `tests/smoke_resume.py`)", or make the test genuinely two-process (`subprocess` run 1, then run 2
  reading the interrupt id from disk).

### C4. Two shipped features are listed as "What's next"

- **Severity:** minor
- **File:** `docs/devpost-submission.md:59-61`
- **What:** "Voice check-ins for landline-only neighbors ... and multi-community deployments on AgentCore with
  Memory for long-term neighbor context." Both are implemented: `channels/twilio_voice.py` (real Twilio
  Programmable Voice with Polly voices, inline TwiML, DTMF check-in) plus `routes_voice.py` webhooks with
  signature validation — `test_voice` passes 5/5; and `agents/agentcore_memory.py` +
  `scripts/create_agentcore_memory.py` + the bus-subscriber writer at `routes_memory.py:96-117`. Under-claiming
  costs the submission real credit.
- **Fix:** move both into "What it does", and replace "What's next" with things actually not built (Open311 and
  utility outage feeds, multi-tenant rosters).

### C5. Stale README passages

- **Severity:** nit
- **File:** `README.md:52`, `:81-100` (Repository layout), `:142`, `:169-179` (Testing)
- **What:**
  - `:52` "Archived NWS alerts for other hazards **are being added** as replay fixtures alongside the Phoenix
    Extreme Heat Warning." — four already exist and all five are verified genuine (B1). Present tense
    understates finished, high-credibility work.
  - `:142` "...which is **how the demo video was recorded** without texting fictional neighbors." Past tense
    asserts a recording exists; there is no video artifact in the repo, no pipeline run has completed (C1), and
    `docs/builder-aws-posts.md:54` still asks for a screenshot "after the first Bedrock run." As written this is
    an unsupported claim. Reword to "which is how the demo is recorded" until footage exists.
  - Repository layout (`:81-100`) omits `report.py`, `playbooks.py`, `routes_report.py`, `routes_memory.py`,
    `routes_outage.py`, `routes_voice.py`, `routes_demo.py`, `agents/agentcore_memory.py`,
    `agents/tools_memory.py`, `agents/tools_outage.py` and `channels/twilio_voice.py` — roughly half the newer
    work is invisible.
  - Testing (`:169-179`) lists only `test_deterministic`, `smoke_strands`, `smoke_resume`. Six more no-model
    suites exist and **all pass** (C6) — free credibility being left on the floor.
- **Fix:** update the four passages.

### C6. Every no-model test suite passes — verified

- **Severity:** — (verified correct)
- **Evidence:** run against the audit venv, no network calls to a model, no AWS:
  ```
  test_deterministic  4/4 ok    test_actions  3/3 ok    test_memory  5/5 ok
  test_multi_hazard   5/5 ok    test_outage   5/5 ok    test_report  3/3 ok
  test_voice          5/5 ok
  ```
- **Fix:** list them at `README.md:169-179` (C5).

### C7. The after-action report does not say that console-mode messages were never sent

- **Severity:** minor
- **Files:** `backend/app/report.py:74` (`contacted = [c for c in checkins if c.status != "failed"]`);
  `frontend/src/pages/Report.jsx:78` (the "neighbors contacted" KPI)
- **What:** `ConsoleProvider.send` honestly returns `detail="logged (not sent) to ..."`, but the `Checkin` row it
  produces has `status="sent"` and `channel="console"`, so a demo run in the default `SEND_MODE=console` prints
  an after-action report whose headline KPI reads "12 neighbors contacted". The channel breakdown at
  `Report.jsx:89` does render "console 12" further down, so it is not hidden — but the number a judge
  screenshots is the KPI.
- **Fix:** one line in the report header, driven by `channel == "console"` in `sent_by_channel`:
  ```jsx
  {m.outreach.sent_by_channel?.console ? <span className="pill warn">Console mode — messages were logged, not delivered</span> : null}
  ```

---

## D. Simulation smells in code

### D1. No runtime fakery anywhere — verified clean

- **Severity:** — (verified correct)
- **What:** a repo-wide grep for `random`, `time.sleep`, `asyncio.sleep`, `fake`, `mock`, `dummy`, `placeholder`,
  `TODO`, `FIXME`, `lorem`, `stub`, `simulat`, `pretend`, `hardcod`, `for demo`, `demo only` across `*.py`,
  `*.js`, `*.jsx`, `*.json`, `*.md`, `*.yml` (excluding `node_modules`, `frontend/dist`, `.claude/worktrees`)
  returns **only legitimate hits**:
  - every `placeholder` is a real JSX `<input placeholder=...>` attribute, or the deliberate `{checkin_link}`
    token documented at `backend/app/models.py:134` and `backend/app/agents/tools.py:229`;
  - `stub` appears only in `backend/tests/test_memory.py:159-193`, a test double for the AgentCore client (fine);
  - `simulate` appears only in the two smoke tests' comments;
  - `for demos` appears once, at `backend/app/config.py:61`, describing `DEMO_OVERRIDE_*` — a real, documented,
    README-explained feature.
  There is **no** `random`, **no** `time.sleep`, **no** `fake`/`mock`/`dummy`/`lorem`, and **no** `TODO`/`FIXME`
  anywhere in the tracked codebase.
- **Hardcoded numeric fallbacks in JSX:** two hits, both the same benign pattern —
  `frontend/src/components/SentinelPanel.jsx:114` and `frontend/src/pages/Dashboard.jsx:70`, each
  `health?.sentinel_interval_minutes || 15`, a UI default matching `config.py`'s own default of 15. Not a faked
  metric. Nothing of the `|| 19370` shape exists.
- **Canned-data functions:** none. `report.py`, `tools_memory.py`, `routes_demo.py` and `routes_outage.py` all
  compute from the store. `routes_demo.py:1-4` even opens with "Nothing here fabricates output" and I traced
  each of its five endpoints to confirm it: `/api/demo/compare` is built only from episodes that have real
  triage decisions, `/api/demo/readiness` reads live config and store state, `/api/demo/latest-checkin` returns
  real tokens.

### D2. The demo pacing control is honest but should be visible in the video

- **Severity:** nit
- **Files:** `backend/app/routes_demo.py:28-29`, `backend/.env` (`FOLLOWUP_GRACE_MINUTES=3` vs the default of 20
  at `backend/app/config.py:45`)
- **What:** `/api/demo/pacing` lets the coordinator shorten the follow-up grace period so escalation is
  demonstrable in five minutes. The docstring at `:29` says exactly that ("Real deployments use 20+ minute
  grace"), the endpoint returns `defaults` alongside the current value, and the code default is 20. This is the
  right design. The risk is purely presentational: if the video shows an escalation 3 minutes after dispatch
  without saying the grace period was shortened, it *looks* like a faked timeline.
- **Fix:** say it out loud in the demo narration, or render `defaults` next to the current value in the UI.

---

## E. Unverified SDK usage (bedrock-agentcore 1.22.0)

### E1. Every AgentCore Memory call is real — verified against the installed package

- **Severity:** — (verified correct)
- **Files:** `backend/app/agents/agentcore_memory.py`, `backend/scripts/create_agentcore_memory.py`
- **What:** both files carry "verified in bedrock_agentcore 1.22.0" comments. I checked them against the
  installed source rather than trusting the comment. **All of them are accurate.** Nothing here would fail at
  runtime on a signature error.
- **Evidence:** `inspect.signature` on the installed `bedrock_agentcore.memory.MemoryClient`:
  ```
  __init__(self, region_name=None, integration_source=None, boto3_session=None)
  create_event(self, memory_id, actor_id, session_id, messages: List[Tuple[str,str]],
               event_timestamp=None, branch=None, metadata=None, extraction_mode=None)
  retrieve_memories(self, memory_id, namespace=None, query=None, actor_id=None,
                    top_k=3, namespace_path=None, metadata_filters=None)
  get_memory_strategies(self, memory_id) -> List[Dict[str, Any]]
  create_memory_and_wait(self, name, strategies, description=None, event_expiry_days=90,
                         memory_execution_role_arn=None, stream_delivery_resources=None,
                         max_wait=300, poll_interval=10, indexed_keys=None)
  ```
  Point by point:
  - `MemoryClient(region_name=REGION)` — correct; `self.region_name` is assigned at `memory/client.py:91`, so
    `create_agentcore_memory.py`'s use of `client.region_name` in its output message resolves.
  - `create_event(memory_id=, actor_id=, session_id=, messages=[(text, "USER"), (text, "ASSISTANT")])` —
    correct. The SDK validates each message is a 2-tuple `(text, role)` and coerces the role through
    `MessageRole(role.upper())`; `USER` and `ASSISTANT` are both members of that enum
    (`memory/constants.py:64-70`).
  - `retrieve_memories(memory_id=, namespace_path=, query=, top_k=)` — correct. The method requires *exactly
    one* of `namespace`/`namespace_path` and the code passes only `namespace_path`; `query` is required and is
    passed. Return items are `memoryRecordSummaries`, whose `content.text`, `namespaces` and `createdAt` are
    the exact keys `retrieve_member_memories` reads.
  - `get_memory_strategies(MEMORY_ID)` — correct, positional. The SDK normalises each strategy to carry **both**
    `strategyId` and `memoryStrategyId`, which is precisely the pair `_candidate_paths` probes.
  - `create_memory_and_wait(name=, strategies=, description=, event_expiry_days=, memory_execution_role_arn=,
    max_wait=)` — correct. The strategy dict keys `"semanticMemoryStrategy"` and `"summaryMemoryStrategy"` match
    `StrategyType.SEMANTIC.value` / `StrategyType.SUMMARY.value`, and `"namespaceTemplates"` is the current
    (non-deprecated) key — `_add_default_namespaces` respects a caller-supplied `namespaceTemplates` and only
    injects defaults when it is absent. The return is read as `memory.get("memoryId") or memory.get("id")`,
    the same both-field-names pattern the SDK itself uses internally.
  - `from bedrock_agentcore.memory import MemoryClient` and `from bedrock_agentcore import BedrockAgentCoreApp`
    both import successfully in the installed environment.
  - Every call site is wrapped in `try/except` with a downgrade-to-local-history fallback (`_log_failure`,
    `enabled()` guards), so even an API-shape change degrades rather than crashes.
- **Fix:** none. Consider changing the comment from "Signatures used (verified in ...)" to name the package
  version *and the date checked*, so the claim stays falsifiable — then leave it alone.

### E2. Also verified: strands-agents 1.55.0 imports

- **Severity:** — (verified correct)
- **Evidence:** `ModelRouter`, `BedrockModel`, `AnthropicModel`, `OllamaModel`, `GraphBuilder` and
  `FileSessionManager` all import from the paths the code uses.
  `ModelRouter.__init__(models, *, strategy=None, max_switches=None)` matches `model_factory.py:75`.
  `OllamaModel(host, **model_config)` accepts the `options={"num_ctx": ...}` passthrough at
  `model_factory.py:37-38`.

---

## F. Dead or unreachable code

### F1. `READ_TOOLS` is defined and never used

- **Severity:** nit
- **File:** `backend/app/agents/tools.py:416-417`
- **What:** `READ_TOOLS = [get_episode_context, get_roster, ...]` is the last statement in the file and has zero
  references anywhere (`grep -rn "READ_TOOLS" backend` returns only the definition). `pipeline.py` builds each
  agent's tool list explicitly instead. Leftover from an earlier design.
- **Fix:** delete the two lines.

### F2. Three `api.js` methods are never called

- **Severity:** nit
- **File:** `frontend/src/lib/api.js`
- **What:** diffing the 37 exported keys against every `api.<name>` reference in `components/`, `pages/` and
  `main.jsx`: **`approvals`**, **`retryEpisode`** and **`saveVolunteer`** have no caller. (`events` is called
  internally by `useEventStream`, so it is fine.) Notably `retryEpisode` is dead even though
  `POST /api/episodes/{id}/retry` (`routes_demo.py:67`) exists and is exactly the recovery path C1 needs, and
  `saveVolunteer` means the Roster page can add members but not volunteers.
- **Fix:** wire `retryEpisode` to a "Retry" button on a failed episode — cheap, and given C1 it is the single
  most useful missing control in the UI — and `saveVolunteer` into the Roster page; or delete the three entries.

### F3. `GET /api/community/history` has no frontend caller

- **Severity:** nit
- **File:** `backend/app/routes_memory.py:50`
- **What:** the only reference outside the route is `backend/tests/test_memory.py:148`. The frontend calls
  `rosterHistory` and `memberHistory` but never the community endpoint. The underlying `community_history()`
  function *is* used — it backs the `get_community_history` tool wired into three agents — so only the HTTP
  route is orphaned.
- **Fix:** harmless. Either surface it on the dashboard (it is the "what did we learn last time" panel this
  project would want) or drop the route.

### F4. The outage branches in `new_hazards()` are unreachable

- **Severity:** nit
- **File:** `backend/app/agents/sentinel.py:83-87`
- **What:** two conditions at `:86` and `:87` special-case `h.hazard_type == "outage"` to bypass de-duplication,
  with a three-line comment (`:83-85`) explaining why. But the only producer feeding them is
  `scan_thresholds()`, which emits exactly three hazard types — `heat`, `cold`, `air_quality` — and never
  `outage`. Coordinator-reported outages enter through `POST /api/outage/report` → `runner.start(h)`
  (`routes_outage.py:84`), bypassing `new_hazards()` entirely. The code and its comment describe behaviour that
  cannot execute. (`backend/tests/test_outage.py::test_sentinel_never_filters_outage` passes because it exercises
  the filter logic with a synthesised outage hazard, not through `scan_thresholds`.)
- **Fix:** keep the branches as future-proofing but shorten the comment to say the path is currently only
  reachable via a manual report, or remove them and rely on the scheduler's active-episode check.

### F5. `("flash flood", "flood")` in `_EVENT_MAP` is unreachable

- **Severity:** nit
- **File:** `backend/app/feeds/nws.py:28`
- **What:** `classify_event` returns on the first substring match and `("flood", "flood")` is at `:27`, so
  `"flash flood"` at `:28` can never be reached. Behaviour is unaffected (both map to `flood`), but a reader
  will pause on it.
- **Fix:** delete line 28.

### F6. `Episode.session_id` stores a value that does not match the actual session

- **Severity:** nit
- **Files:** `backend/app/agents/runner.py:48`, `backend/app/agents/pipeline.py:210`,
  `backend/app/models.py:206`
- **What:** `runner.start` sets `Episode(hazard=hazard, session_id=f"graph-{hazard.id}")` — keyed on the
  **hazard** id — but `build_graph` creates `FileSessionManager(session_id=f"graph-{ep.id}")`, keyed on the
  **episode** id. The on-disk directories confirm the latter
  (`backend/data/sessions/session_graph-ep_19f205b0b2/`). The persisted `Episode.session_id` field is read
  nowhere and points at a session that does not exist; anyone debugging a resume failure would follow it to the
  wrong place.
- **Fix:** `Episode(hazard=hazard)` then `ep.session_id = f"graph-{ep.id}"`, or drop the field.

### F7. Ignored build artifacts and the stale agent worktree — verified clean

- **Severity:** — (verified correct)
- **What:** the repo directory contains `.claude/worktrees/agent-a886844d1e9304c20/` (a full stale duplicate of
  an older tree), `frontend/dist/` and `frontend/.env.local`. All three are correctly ignored and **none is
  tracked**:
  ```
  git check-ignore -v .claude/worktrees/ frontend/dist frontend/.env.local
    .gitignore:14:.claude/                .claude/worktrees/
    frontend/.gitignore:2:dist/           frontend/dist
    frontend/.gitignore:4:.env.local      frontend/.env.local
  git ls-files .claude frontend/dist frontend/.env.local   -> (empty)
  ```
  `backend/.env` is likewise ignored and untracked, so no secret is in the index. Verify once more before
  pushing, as `README.md:184` already advises.
- **Fix:** none. Deleting the stale worktree would reduce clone-time confusion but is not a correctness issue.

---

## G. Working-tree hazard (not authenticity, but it will break a fresh clone)

### G1. `main.py` imports `routes_demo`, which is untracked

- **Severity:** major
- **Files:** `backend/app/main.py:18` (`from . import routes_demo`) and `:380`
  (`app.include_router(routes_demo.router)`) — both **uncommitted modifications** to a tracked file;
  `backend/app/routes_demo.py` — **untracked**
- **What:** at audit time `git status` showed:
  ```
   M backend/app/main.py            (adds "from . import routes_demo" at line 18)
   M frontend/src/main.jsx          (adds imports of Demo.jsx and Compare.jsx at lines 8-9)
   M frontend/src/components/TopBar.jsx    (imports SettingsMenu.jsx at line 2)
   M frontend/src/pages/Dashboard.jsx      (imports Collapsible.jsx at line 9)
  ?? backend/app/routes_demo.py
  ?? backend/scripts/aws_preflight.py
  ?? frontend/src/components/Collapsible.jsx
  ?? frontend/src/components/SettingsMenu.jsx
  ?? frontend/src/pages/Compare.jsx
  ?? frontend/src/pages/Demo.jsx
  ```
  Four tracked, modified files import four untracked files (importers confirmed by grep, listed above). A
  `git commit -a` or `git add -u` would commit the imports without the files, and a judge cloning the repo gets
  `ImportError: cannot import name 'routes_demo'` on `python run.py` and a Vite resolve failure on
  `npm run dev`. The project would not start at all.
- **Fix:** before the next commit:
  ```
  git add backend/app/routes_demo.py backend/scripts/aws_preflight.py \
          frontend/src/components/Collapsible.jsx frontend/src/components/SettingsMenu.jsx \
          frontend/src/pages/Compare.jsx frontend/src/pages/Demo.jsx
  ```
  then verify from a clean clone: `git clone . /tmp/clonetest && cd /tmp/clonetest/backend && python -c "import app.main"`.

---

## Summary

| Severity | Count |
|---|---|
| blocker | 2 |
| major | 2 |
| minor | 4 |
| nit | 8 |
| verified clean (no defect) | 6 areas |

**Areas that are genuinely clean, traced not assumed:** fixture provenance (B1 — three fixtures compared
property-by-property against live `api.weather.gov` with every property identical, two verified verbatim against
the IEM raw text archive including all 46 Fort Worth counties), runtime fakery (D1 — nothing found),
AgentCore SDK usage (E1 — every method name and keyword argument confirmed against the installed 1.22.0 source),
Strands API usage (E2), the after-action metrics (`report.py` is pure and deterministic), and secret hygiene
(F7 — nothing sensitive tracked).

### Top 5 fixes, ranked by judge impact × cheapness

1. **Get one full pipeline run on a real model** (C1, blocker). Not cheap in dependencies — it needs Bedrock or
   an Anthropic key — but everything else is downstream of it. All six persisted runs failed; `assess` has
   succeeded exactly once and `triage` has never completed, so no approval card, no after-action report and no
   demo footage exists yet. `ep_9189bd9e2a` already has `assess` completed and can be resumed via
   `POST /api/episodes/{id}/retry` rather than restarted.
2. **Fix the four `RESOURCES` rows in `seed.py`** (A1, blocker). Ten minutes; corrected phones and coordinates
   are all in the table above. Two real community centers sharing one fabricated phone number is the most
   googleable thing in the repo, and it directly contradicts the project's own agent rule at `pipeline.py:73`
   ("never invent phone numbers, hours"). Blank any field that cannot be re-verified.
3. **`git add` the six untracked files before committing `main.py`** (G1, major). Two minutes, and it is the
   difference between a judge running the project and getting an `ImportError` on line one.
4. **Resolve the AgentCore/Bedrock claim** (C2, major). Either the run in fix 1 covers it — then delete the two
   `[FINALIZE AFTER FIRST BEDROCK RUN]` markers and the `Repo: <link>` placeholder in
   `docs/builder-aws-posts.md` — or downgrade "Built with Amazon Bedrock / AgentCore Runtime" to "deployable
   to." Shipping a builder.aws.com post with a `FINALIZE` marker in it is worse than either.
5. **Update the four stale README passages** (C5) and **promote voice + AgentCore Memory out of "What's next"**
   (C4). Fifteen minutes, and it converts finished work into visible credit — seven passing test suites, five
   verified-genuine fixtures and a full Twilio voice channel are currently invisible or misdescribed. Bundle in
   the `smoke_resume` restatement (C3) and the console-mode banner on the report page (C7); both are one-liners
   that pre-empt the two "is this real?" questions a skeptical reviewer would actually ask.

Cheap cleanups worth doing in the same pass: delete `READ_TOOLS` (F1) and the unreachable `("flash flood", ...)`
line (F5), fix `Episode.session_id` (F6), add the missing provenance block to the Phoenix fixture (B2), and wire
or delete the three orphaned `api.js` methods (F2) — `retryEpisode` in particular is a working recovery path the
UI cannot currently reach, and fix 1 needs it.
