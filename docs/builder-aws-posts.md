# builder.aws.com post drafts (bonus points: +0.2 each, up to +0.6; title must contain "Agents for Humans")

Publish before Sep 14, 2026 5:00 PM PT. Add screenshots from the desk and the architecture diagram.

---

## Post 1 — "Agents for Humans: teaching a Strands graph to stop and ask the block captain"

When we started Porchlight, a neighbor check-in agent for community groups during heat waves, the hard part was not getting the model to write good messages. It was making sure nothing left the system until a human said so.

The Strands Agents SDK has a primitive that fits exactly: interrupts raised from hooks. Every world-changing tool in Porchlight (`dispatch_outreach`, `assign_volunteers`, `escalate_member`) is gated by one hook:

```python
class ApprovalGateHook(HookProvider):
    def register_hooks(self, registry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.gate)

    def gate(self, event):
        if event.tool_use["name"] not in GATED_TOOLS:
            return
        response = event.interrupt("porchlight-approval", reason={...card payload...})
        if response.get("decision") != "approve":
            event.cancel_tool = "The coordinator declined this action. Do not retry."
        elif response.get("edits"):
            event.tool_use["input"].update(response["edits"])
```

The whole `GraphBuilder` graph stops with `Status.INTERRUPTED`. Our FastAPI layer turns each interrupt's `reason` into a decision card on the coordinator's desk. When the block captain presses Approve (or edits a message and then approves), we call the graph again with `interruptResponse` content and it resumes inside the same tool call. Because the graph has a `FileSessionManager`, this works even if the backend restarted in between.

What surprised us: editing the tool input inside the hook on resume is enough to let a human rewrite a message the agent drafted, without the agent ever knowing. That is the right amount of human in the loop for a volunteer.

Stack: Strands Agents 1.55, Amazon Bedrock (Claude), AgentCore Runtime entrypoint, FastAPI, React. Repo: <link>.

---

## Post 2 — "Agents for Humans: keep the LLM out of the decision to wake up"

Porchlight watches National Weather Service alerts and Open-Meteo conditions for a neighborhood roster and activates a Strands multi-agent graph when a hazard threatens vulnerable neighbors. Early on we let an agent decide whether to poll and whether an alert mattered. It was slow, expensive, and occasionally wrong in ways that are hard to explain to a volunteer.

We moved everything that can be a rule out of the model: polling on a schedule, mapping NWS event names to hazard types, thresholds (feels-like at or above 105 F, US AQI at or above 151, air at or below 15 F), ignoring marine and fog advisories, and de-duplicating alert ids. Only once a real hazard exists does the sentinel agent read the alert text and return a typed `HazardAssessment` through `structured_output_model`, and a graph edge condition reads that Pydantic object to decide whether triage runs at all.

Two lessons for anyone building "background" agents on Strands: put the deterministic part in plain Python and give the model structured outputs to fill, and make your live data sources keyless and public (NWS and Open-Meteo are both free) so judges and volunteers can run it without an account.

---

## Post 3 — "Agents for Humans: one model config from a $0 laptop to Bedrock and AgentCore"

We built Porchlight on a 2017 laptop with no AWS credentials for the first day. Strands made that painless. A `ModelRouter` with the default fallback strategy tries Amazon Bedrock first, then the Anthropic API, then a local Ollama model:

```python
ModelRouter(models=[BedrockModel(model_id=..., region_name=...), AnthropicModel(...), OllamaModel(host=..., model_id="qwen2.5:3b")])
```

The graph, hooks, interrupts, session persistence and structured output all behaved identically on the 3B local model (slowly) and on Claude through Bedrock (fast). Our smoke test runs the exact features we depend on against whatever provider is configured. Deploying the same graph to Amazon Bedrock AgentCore Runtime is a `BedrockAgentCoreApp` entrypoint that streams graph events and resumes on interrupt responses.

Gotchas we hit: the Python AgentCore starter toolkit is deprecated in favour of the `@aws/agentcore` npm CLI; nested Pydantic tool arguments confuse small local models, so we flatten action-tool inputs to lists of dicts and validate inside the tool; and never let an SSE endpoint buffer behind nginx (`proxy_buffering off`).
