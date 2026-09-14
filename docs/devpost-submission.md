# Devpost submission text (paste into the form)

## Elevator pitch

When a heat, smoke or freeze alert hits, Porchlight finds the neighbors in danger, writes to each one, lines up volunteers, and waits for a human to approve before anything goes out.

## Built with

strands-agents, python, amazon-bedrock, amazon-nova, amazon-bedrock-agentcore, agentcore-memory, amazon-polly, amazon-ses, amazon-ec2, amazon-cloudfront, aws-lambda, fastapi, react, vite, leaflet, openstreetmap, national-weather-service-api, open-meteo, valhalla, osrm, twilio, telegram-bot-api, sqlite, pydantic, docker

## About the project

## Inspiration

In the June 2021 Pacific Northwest heat dome, 69 people died in Multnomah County, Oregon. 78% were 60 or older and **71% lived alone**. They died at home, because nobody reached them in time. Oregon's after-action review found that *"neighbors checking on neighbors saved lives."* Eight months later, the Texas winter storm killed 246 people; 25 of them died because power to their oxygen, dialysis or medical equipment stopped.

Every agency's advice is the same sentence: *check on your neighbors.* New York City actually runs that as a program, Be a Buddy, and made 1,942 wellness checks during heat events in 2025, by hand, from a spreadsheet and a phone. Maricopa County, where our demo roster lives, has 28,833 Medicare beneficiaries whose medical equipment needs electricity.

The bottleneck is never the volunteers. It's the one coordinator holding the list together at 11pm. Porchlight is Be a Buddy with an agent: the agent does the reading, ranking, writing and chasing, and the coordinator keeps every decision.

## What it does

A plain-Python sentinel polls National Weather Service alerts and live Open-Meteo conditions every 15 minutes. When a real hazard appears, a **Strands Agents** graph takes over:

- **Assess** reads the alert and returns a typed decision. A mild advisory stops here and nobody is disturbed.
- **Triage** ranks every neighbor from recorded risk factors (lives alone, no AC, home oxygen, dialysis, memory issues) against conditions measured at their own address.
- **Outreach** writes each neighbor a personal message in English or Spanish with a one-tap check-in link, then **pauses for the coordinator**.
- **Logistics** matches volunteers by skill, distance and load, finds the nearest real cooling center, and **pauses again**.
- **Brief** says who was reached, who was visited, and who is still unaccounted for.

Then comes the part a spreadsheet can't do:

- **Replies.** People write sentences, not button taps. A responder agent reads free text in either language and answers by name. Symptoms that mean *call 911* are matched **before any model call**, so that answer never depends on a model being reachable.
- **Reminders.** Three reminders, three minutes apart, counted per person across every open episode. Any reply closes all of them.
- **Critical.** If someone runs out of reminders with no reply, Porchlight stops texting and flags them. Silence from someone on home oxygen is the finding, not a reason to send a fourth message.
- **Deployments.** A volunteer is suggested only on evidence and matched to the need, with a real road route and travel time, and goes out only after approval.
- **Voice.** For neighbors without a smartphone, Amazon Polly voices the check-in call.
- **Memory.** Every outcome goes to Amazon Bedrock AgentCore Memory, and triage reads the distilled lessons back the next time heat hits the same street.

The same loop runs for heat, smoke, freeze, flood, tornado and power outages. Five real archived NWS alerts ship as replays.

**Try it live:** https://d3mb3p2bf8o8jp.cloudfront.net (press **ingestion**; messages are logged, never sent).

## How we built it

Five Strands `Agent`s, each with its own prompt and tools, are wired into a `GraphBuilder` graph with a conditional edge (triage runs only if the assessment activates) and parallel outreach and logistics branches that join at the brief.

**Human approval is a real Strands interrupt, not a UI trick.** An `ApprovalGateHook` on `BeforeToolCallEvent` calls `event.interrupt()` on every world-changing tool. The graph stops *inside the tool call*; the coordinator's decision returns as an `interruptResponse`, and edited message text is written back into the tool input before it runs. `FileSessionManager` persists the paused graph, so an approval can arrive hours later, even after a restart. The assessment comes back through `structured_output_model` as a Pydantic object that drives the graph edge, an `AuditHook` streams every model and tool event to the dashboard over server-sent events, and `ModelRouter` puts Amazon Nova Pro on Bedrock first with an optional fallback. A `BedrockAgentCoreApp` entrypoint runs the identical graph on AgentCore Runtime.

The backend is FastAPI with SQLite; the frontend is React, Vite and Leaflet over OpenStreetMap, with NWS warning polygons, a street-level conditions grid, and Valhalla/OSRM road routes, all keyless.

The public demo runs on AWS: one EC2 instance with an IAM role (no keys anywhere) behind CloudFront. To keep it nearly free, it sleeps when unused; CloudFront fails over to a small Lambda that wakes it, and the page opens by itself in under a minute.

## Challenges we ran into

- **Keeping the model out of decisions that should be deterministic.** When to poll, what counts as a hazard, how many reminders is enough, and whether a symptom means 911 are all plain Python. The model writes and reasons; it never decides whether to stop reminding someone.
- **The coordinator got asked the same question twice.** Agents re-proposed an already-answered decision in new words. We now fingerprint approvals on the material tool input with the model's rewording stripped out, so a repeat is told it was already decided.
- **Six reminders at 4am.** Counting reminders per episode row meant one person in overlapping episodes got several at once. Counting per person fixed it.
- **"Stop" didn't stop.** An open dashboard stream kept the server draining while the scheduler went on sending for nine minutes. Shutdown now halts scheduled work immediately.
- **Our own data was wrong.** We had adversarial reviewers audit the repo. They found that three of four phone numbers for real Phoenix institutions were wrong, and one belonged to a hotel. The unedited audits are published in the repo along with the fixes.
- **Honesty in the interface.** We caught the UI reporting a message as *sent* when it had only been logged. It now says exactly what happened.
- **Hosting a stateful agent cheaply.** Paused graphs, SQLite and a live event stream rule out stateless serverless hosting, so we built the sleep-and-wake setup instead.

## What we learned

Interrupts plus session persistence are the difference between a demo and something a volunteer could trust: the agent can be stopped in the middle of an action and resumed hours later on the same decision, with the human's edits applied. We also learned to prove things instead of asserting them. `test_pipeline_mechanics.py` drives the real graph, the real approval hook and the real tools through both pauses with a scripted model, in seconds, so the approval flow is tested rather than just described.

## What's next

Utility outage feeds and Open311 as hazard sources alongside the Weather Service, a pilot with a real neighborhood group and their own roster, and multi-community deployments on AgentCore Runtime, where each group keeps its own coordinator and memory.
