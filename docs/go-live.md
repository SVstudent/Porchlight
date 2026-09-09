# Taking Porchlight live

Everything below goes in `backend/.env` (copy from `backend/.env.example`). That file is git-ignored and is the only place secrets belong. Nothing here is needed to run the demo in console mode; this is the list for making the agent send real messages to real people.

There are four tiers. Tier 1 alone gets you a working, judge-testable product.

---

## Tier 1 — required for the agent to think at all

Without a model provider the pipeline cannot run. Pick one.

| Variable | Value | Notes |
|---|---|---|
| `MODEL_PROVIDER` | `bedrock` | Or `auto` to fall back Bedrock → Anthropic |
| `BEDROCK_MODEL_ID` | a Claude model id enabled in your account | Confirm with the preflight below |
| `AWS_REGION` | `us-east-1` | Must be a region where the model is enabled |

AWS credentials come from the standard chain, so `aws configure` is enough and no key needs to go in `.env`. If you prefer explicit values, set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or a single `AWS_BEARER_TOKEN_BEDROCK`.

**Preflight before anything else.** Model access is the most common failure:

```bash
aws sts get-caller-identity
aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic \
  --query 'modelSummaries[].modelId' --output text | tr '\t' '\n' | head
```

If the list is empty or your chosen id is missing, request access in the Bedrock console under Model access. Then set `BEDROCK_MODEL_ID` to an id that appeared.

An alternative that needs no AWS: `MODEL_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`.

---

## Tier 2 — required to actually reach a neighbor

Set the mode, then at least one channel.

| Variable | Value | Notes |
|---|---|---|
| `SEND_MODE` | `live` | `console` only logs the message |
| `PUBLIC_BASE_URL` | the URL a neighbor's phone can open | Check-in links are built from this |

`PUBLIC_BASE_URL` must be reachable from outside your laptop or the check-in links are dead. For a demo, run one command and paste the URL it prints:

```bash
cloudflared tunnel --url http://localhost:5173     # no account needed
```

### Pick at least one channel

**Text messages (Twilio).** The simplest path.

| Variable | Notes |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio console |
| `TWILIO_AUTH_TOKEN` | Twilio console |
| `TWILIO_FROM_NUMBER` | e.g. `+16025550100`, must be voice-capable if you also want calls |

On a trial account you can only message numbers you have verified, and every message carries a trial prefix.

**Telegram.** Free, instant, and the only channel where replies come back automatically without a tunnel.

| Variable | Notes |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |

Each member also needs their `telegram_chat_id` filled in on the Roster page. Replies of "OK" or "HELP" are captured by the poller.

**Email (Amazon SES).**

| Variable | Notes |
|---|---|
| `SES_FROM_EMAIL` | A verified sender address |

In the SES sandbox you can only send to verified addresses. Uses the same AWS credentials.

### Safety valve for the demo

Point every outbound message at a phone or inbox you control, so no fictional neighbor is ever contacted:

| Variable | Notes |
|---|---|
| `DEMO_OVERRIDE_PHONE` | Overrides every SMS and call recipient |
| `DEMO_OVERRIDE_TELEGRAM_CHAT_ID` | Overrides every Telegram recipient |
| `DEMO_OVERRIDE_EMAIL` | Overrides every email recipient |

Use these for the video. Turn them off only for a real deployment.

---

## Tier 3 — voice calls for landline-only neighbors

Uses the same Twilio credentials as SMS, plus a publicly reachable `PUBLIC_BASE_URL` so the keypad press can come back.

| Variable | Notes |
|---|---|
| `VOICE_SKIP_SIGNATURE` | Leave `false`. Set `true` only to test webhooks locally with curl |

Requirements: the Twilio number must be voice-capable, and on a trial account the callee hears Twilio's preamble and must press a key before the script plays. The tunnel URL must match `PUBLIC_BASE_URL` exactly, including https and no trailing slash, or signature validation rejects the webhook.

---

## Tier 4 — optional polish

**Long-term memory (Amazon Bedrock AgentCore Memory).** Neighbor history already works locally without this; this adds LLM-distilled long-term memories.

```bash
cd backend && python scripts/create_agentcore_memory.py --region us-east-1   # prints the id
```

| Variable | Notes |
|---|---|
| `AGENTCORE_MEMORY_ID` | From the script above |
| `AGENTCORE_MEMORY_NAMESPACE` | Defaults to `/porchlight/neighbors/{actorId}/` |

**Tracing.** Set `OTEL_EXPORTER_OTLP_ENDPOINT` to send Strands traces to any OpenTelemetry backend, or enable CloudWatch GenAI Observability on an AgentCore runtime.

---

## Everything else has a working default

Identity: `COMMUNITY_NAME`, `COORDINATOR_NAME`. Detection: `NWS_USER_AGENT` (set it to a real contact address, which the National Weather Service asks for), `SENTINEL_INTERVAL_MINUTES`, `SENTINEL_ENABLED`, `HEAT_INDEX_ACTIVATE_F`, `AQI_ACTIVATE`, `COLD_ACTIVATE_F`. Follow-up: `FOLLOWUP_INTERVAL_MINUTES`, `FOLLOWUP_GRACE_MINUTES`. Policy: `AUTO_APPROVE_ESCALATIONS`. Server: `HOST`, `PORT`, `CORS_ORIGINS`, `DATA_DIR`. Model tuning: `MODEL_TEMPERATURE`, `GRAPH_TIMEOUT_S`, `NODE_TIMEOUT_S`.

---

## Minimum live configuration

```bash
MODEL_PROVIDER=bedrock
BEDROCK_MODEL_ID=<an id your account can invoke>
AWS_REGION=us-east-1

SEND_MODE=live
PUBLIC_BASE_URL=https://<your-tunnel>.trycloudflare.com

TWILIO_ACCOUNT_SID=<sid>
TWILIO_AUTH_TOKEN=<token>
TWILIO_FROM_NUMBER=+1<voice-capable number>

DEMO_OVERRIDE_PHONE=+1<your own phone>
NWS_USER_AGENT=porchlight (your@email)
```

## Then verify, in this order

1. `curl localhost:8000/api/health` and confirm `models` names Bedrock and `channels` shows your provider as true.
2. Press **Replay this alert** on the Phoenix heat warning and watch the pipeline reach the approval card.
3. Approve, and confirm the text arrives on your own phone.
4. Open the check-in link, tap **I need help**, and watch the follow-up agent escalate.
5. Open the after-action report and confirm the numbers are populated.

## Before you publish the repo

Run `git status` and confirm `backend/.env` is not listed. It is git-ignored, but check anyway. Rotate any credential that has ever been pasted into a chat, a screenshot, or a commit.
