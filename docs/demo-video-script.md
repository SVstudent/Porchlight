# Porchlight — 5-minute demo video script

**Track:** Good Neighbor Agents · **Target 4:45, hard cap 5:00**

**Shape:** thirty seconds of what and why, then straight into the real thing running, and only then how
it is built. A judge who stops watching after two minutes has still seen the product work.

Judged on Presentation: *does the video clearly demonstrate the project working end-to-end, and does the
pitch communicate what problem is solved, who it's for, and why it matters.* Beat 1 answers all three in
thirty seconds; beat 9 returns to them with the weight of the demo behind it.

Every figure spoken aloud is sourced in [`sources.md`](sources.md). **Do not add a number that is not on
that page.**

---

## Before you record

The demo's whole claim is that nothing is staged, so the board must genuinely start empty.

1. **Tunnel up**, so check-in links open on a phone: `ngrok http 5173` → copy the https URL →
   `PUBLIC_BASE_URL` in `backend/.env`
2. **Backend:** `bash backend/scripts/restart.sh`. It waits for the new process and prints the model,
   the send mode and the public base URL. Read those three lines before continuing.
3. **Frontend:** `npm run dev` in `frontend/`. Must be 5173 — it is pinned, and check-in links are
   built from it.
4. **Open `/demo`** and clear the readiness list. "The agents can actually reach the model" must be
   green: it asks Bedrock for a completion from inside the server process, which is the only version of
   that question that matters.
5. **Send mode.** `SEND_MODE=live` with `DEMO_LIVE_MEMBER_ID=mem_bettie` contacts your own phone for
   real and logs everyone else. Say so on camera in beat 4 rather than leaving it ambiguous.
6. **Phone ready**, Telegram open on the bot conversation, mirrored or filmed.
7. **Do not pre-run an episode.** The watch should be all grey when you hit record.

---

## The beats

### Part one — what this is (0:00–0:35)

| # | Time | On screen | Narration |
|---|---|---|---|
| **1** | 0:00–0:35 | The watch screen, empty. Twelve grey cards on the left, all "Not contacted". The map on the right with twelve homes and the real cooling centres. Hold still. | This is Porchlight. It is for the one volunteer who holds a neighbourhood's contact list together — a block captain, a parish coordinator — the person who, when a heat warning hits, has one evening to work out who is in danger, text them all, and remember who never wrote back. New York City does exactly this by hand: 1,942 wellness checks last year, one volunteer at a time. Heat is the deadliest weather in the United States, and the people it kills are the ones nobody reached. This is a block captain's roster in Maryvale, Phoenix — twelve neighbours, four volunteers, real cooling centres. Nothing is running yet. I am going to click one button, and everything after that is the system. |

### Part two — the demo (0:35–3:45) · **unbroken, nothing staged**

| # | Time | On screen | Narration |
|---|---|---|---|
| **2** | 0:35–1:05 | **Click `ingestion`.** Let it run untouched. Hazard banner appears, activity feed streams, cards turn amber as tiers land. | It polls the National Weather Service and live conditions, and it has just found dangerous heat in Phoenix from live readings — not a recording. Five agents take over. Assess reads the hazard and returns a typed decision. Triage ranks every neighbour from their recorded risk factors against the conditions at their own address. Outreach and logistics run in parallel. Every tool call is on screen as it happens. |
| **3** | 1:05–1:45 | Two approval cards appear together. Scroll them. Open Rosa's message (Spanish). **Edit Walter's wording.** Approve & send. Then approve the volunteer assignments. | And here it stops. The outreach agent wants to send eleven messages, and it cannot. The whole graph is paused inside that tool call, waiting for me. I read Rosa's in Spanish, tweak Walter's, and approve — and it resumes inside the same call, with my edit. Logistics asks next: Marisol, who speaks Spanish and drives, to Rosa. Priya, the nurse, to Walter — because Walter is on a home oxygen concentrator and the system knows that. Nothing reaches a neighbour without a human yes. |
| **4** | 1:45–2:20 | Phone: the Telegram message arrives with a one-tap link. Reply in your own words: "my ac stopped working and i feel a bit dizzy". Cut to the desk: Bettie's card turns red, the feed shows the agent reading it, the reply lands back on the phone. | Neighbours get one message with two big buttons. But people do not tap buttons — they write back. So an agent reads what they actually said. She did not say "help". She said her air conditioning stopped and she feels dizzy. It understood that, answered her by name with the nearest cooled building, and flagged her on my board. During this demo one neighbour is contacted for real, on my own phone; the rest are logged. |
| **5** | 2:20–2:50 | The watch, now sorted worst-first. Walter at the top: "No reply at all · 3 reminders". Click his card → his case page: the oxygen concentrator note, his emergency contact, the two protocols. | Walter never answered. Three reminders, three minutes apart — then Porchlight stopped texting him and flagged him, because silence from a man on an oxygen concentrator is the finding, not a reason to send a fourth message. This is his case: what we know, what was said, what happened in past events. |
| **6** | 2:50–3:20 | Back to the map. Toggle the warning zones and the heat gradient so both are seen. Then the suggested deployment card. | On the map, the National Weather Service's own warning zones — and underneath, the conditions measured street by street. Ninety-three degrees on the east side, a hundred on the west, three miles apart. It is the west side where the swamp coolers are. That is why this is a map and not a number. |
| **7** | 3:20–3:45 | **Approve the deployment.** The route draws along real roads; the responder marker starts moving; the ETA counts down. | So it proposes who goes — matched to the need: a driver for a lift, a nurse for a medical device. I approve, and the route is drawn on real roads with a real travel time. That marker is where we expect them to be, computed from the route. It is not a GPS position, and the interface says so. |

### Part three — how it is built, and why it matters (3:45–4:45)

| # | Time | On screen | Narration |
|---|---|---|---|
| **8** | 3:45–4:20 | Architecture diagram, held still. Optionally cut to `agentcore invoke` in a terminal, and the coordinator brief. | Five Strands agents in a GraphBuilder graph on Amazon Bedrock, with a conditional edge and parallel branches. The pause you saw is a Strands interrupt raised from a BeforeToolCall hook on the three tools that can affect the world, with session persistence, so a paused run survives a restart. The same graph runs on Bedrock AgentCore Runtime, and every check-in outcome goes into AgentCore Memory — so next time, triage already knows Bettie prefers Telegram to a phone call. Live public data, no API keys: the National Weather Service, Open-Meteo, OpenStreetMap. |
| **9** | 4:20–4:45 | The brief: who was reached, who was visited, who was not, the gaps. Then title card: Porchlight, repo URL, "Built with Strands Agents and Amazon Bedrock". | And when it is over, the brief is the after-action record — who was reached, who was visited, who is still unaccounted for. Portland, 2021: sixty-nine people died in one county, seventy-one percent of them living alone. Every agency says to check on your neighbours. Porchlight is for the volunteer who actually does it. The porch light is on. |

---

## Editing rules

- **Beat 2 must not be cut or sped up silently.** It is the whole claim: one click, nothing staged.
  If the run is slow on the day, speed it 2× with a visible badge saying so.
- **Linger on the pause.** Beat 3 is the differentiator. Hold long enough that a judge reads a message
  body, and editing one before approving proves the human is collaborating, not rubber-stamping.
- **Say "estimated, not GPS"** in beat 7. A dot moving along a road implies a tracked phone. None is
  tracked, and implying otherwise would be the one dishonest frame in the video.
- **No stock disaster footage.** The data is the drama; the empty board turning red is the shot.
- **Captions throughout** — judges may watch muted.
- If you overrun, trim beat 6 to ten seconds and beat 5 to fifteen. Protect beats 1, 2, 3 and 9.

## What not to claim

- That volunteers are GPS-tracked. They are not; the marker is a route estimate.
- That the roster is real people. It is a fictional roster at real Maryvale coordinates, with real
  public cooling centres and their real published phone numbers.
- That the whole roster was messaged live. One neighbour is contacted for real; the rest are logged.
  Beat 4 says this out loud — keep it.
