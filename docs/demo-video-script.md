# Porchlight demo video — 5-minute script

Record at 1440x900, dashboard on the left monitor, a phone (or the check-in page in a mobile-sized window) visible for the check-in beat. Narration is voice-over; no camera needed.

| Beat | Time | Screen | Narration |
|---|---|---|---|
| 1. Problem | 0:00–0:35 | Title card, then one slide: "645 heat deaths, Maricopa County, 2023" and "most lived alone, no AC" | Extreme heat kills more Americans than any other weather. The people who die are mostly older, alone, without AC, and nobody checked on them. That job falls on one volunteer with a spreadsheet: the block captain. |
| 2. Who and why | 0:35–1:00 | Roster page: 12 neighbors with risk factors, 4 volunteers, real Maryvale cooling centers | Porchlight is for that volunteer. It watches the weather in the background and only asks for a decision. Built on the Strands Agents SDK and Amazon Bedrock. |
| 3. Live detection | 1:00–1:30 | Desk: sentinel panel with live readings and the real NWS Extreme Heat Warning | This is live: National Weather Service alerts and Open-Meteo conditions for the roster. The sentinel is deterministic; no model decides when to wake up. Press Scan now (or Replay this alert). |
| 4. Agents work | 1:30–2:40 | Activity feed streaming; stepper advancing; assessment pill; neighbor tiles filling with tiers | Five Strands agents in a graph. Assess reads the alert and returns a typed decision. Triage ranks every neighbor: Rosa, 80, alone, swamp cooler only, Spanish, tier 1. Walter's oxygen concentrator. Every tool call is on screen. |
| 5. The pause | 2:40–3:30 | Decision card appears; scroll the messages; edit one; approve | The outreach agent wants to send 10 messages. It cannot: this is a Strands interrupt on the send tool. I read Rosa's message in Spanish, tweak Walter's, press Approve. The graph resumes exactly where it stopped. Logistics asks next: Marisol, who speaks Spanish and drives, to Rosa; Priya the nurse to Walter. Approve. |
| 6. Close the loop | 3:30–4:20 | Phone: SMS arrives (or check-in link); tap I need help; desk tile turns red; follow-up agent escalates; approval card for volunteer visit | Neighbors get a page with two buttons. Earl taps I need help. The follow-up agent escalates and asks me before dispatching a volunteer. With the standing policy on, it would just go. |
| 7. Brief + architecture | 4:20–4:50 | Coordinator brief; architecture diagram; AgentCore invoke in a terminal | The brief tells the captain what happened and what to do next. Same graph runs on Bedrock AgentCore Runtime. |
| 8. Close | 4:50–5:00 | Title card with repo URL | Porchlight. The porch light is on. |

Cuts to make: never show a loading spinner longer than 2 seconds; speed up agent runs 4x with a badge; zoom into the decision card and the interrupt line in the feed.
