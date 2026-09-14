"""Smoke test for the exact Strands features Porchlight depends on. Run: python -m tests.smoke_strands

Verifies on the configured model: @tool with pydantic params, BeforeToolCallEvent interrupt + resume,
stream_async event keys, FileSessionManager resume in a fresh Agent, structured_output_model, and a Graph
whose node raises an interrupt and resumes.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from typing import Any

from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder
from strands.multiagent.base import Status
from strands.session import FileSessionManager

from app.agents.model_factory import build_model, candidate_names

SESS = tempfile.mkdtemp(prefix="porchlight-smoke-")


class Note(BaseModel):
    who: str
    text: str = Field(description="short note")


@tool
def send_note(who: str, text: str) -> str:
    """Send a note to a neighbor.
    Args:
        who: recipient name
        text: short note
    """
    return f"SENT to {who}: {text}"


@tool
def lookup_temp(city: str) -> str:
    """Look up the temperature in a city. Args: city: city name"""
    return f"{city}: 108 F"


class Gate(HookProvider):
    def __init__(self):
        self.seen: list[Any] = []

    def register_hooks(self, registry: HookRegistry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.gate)

    def gate(self, event: BeforeToolCallEvent):
        if event.tool_use["name"] != "send_note":
            return
        resp = event.interrupt("smoke-approval", reason={"input": event.tool_use["input"]})
        self.seen.append(resp)
        if isinstance(resp, dict) and resp.get("decision") == "reject":
            event.cancel_tool = "declined"


class Verdict(BaseModel):
    activate: bool
    score: int = Field(ge=1, le=5)
    summary: str


async def main():
    print("model candidates:", candidate_names())
    model = build_model()

    # 1. tool + interrupt + resume on a plain agent, with session persistence
    gate = Gate()
    sm = FileSessionManager(session_id="smoke-1", storage_dir=SESS)
    agent = Agent(model=model, tools=[lookup_temp, send_note], hooks=[gate], callback_handler=None, session_manager=sm,
                  system_prompt="You are terse. Use tools when asked. After sending a note, say DONE.")
    keys = set()
    result = None
    async for ev in agent.stream_async("Look up the temperature in Phoenix, then send a note to Rosa saying to stay cool."):
        keys |= set(ev.keys())
        if "result" in ev:
            result = ev["result"]
    print("stream keys:", sorted(k for k in keys if not k.startswith("_"))[:20])
    print("stop_reason:", result.stop_reason, "| interrupts:", [(i.name, i.reason) for i in result.interrupts])
    assert result.stop_reason == "interrupt", "expected an interrupt from the gate hook"

    # resume in a FRESH agent restored from the session (simulates process restart)
    sm2 = FileSessionManager(session_id="smoke-1", storage_dir=SESS)
    gate2 = Gate()
    agent2 = Agent(model=model, tools=[lookup_temp, send_note], hooks=[gate2], callback_handler=None, session_manager=sm2,
                   system_prompt="You are terse. Use tools when asked. After sending a note, say DONE.")
    responses = [{"interruptResponse": {"interruptId": i.id, "response": {"decision": "approve"}}} for i in result.interrupts]
    r2 = await agent2.invoke_async(responses)
    print("after resume:", r2.stop_reason, "|", str(r2)[:120].replace("\n", " "))
    print("gate2 saw response:", gate2.seen)
    assert gate2.seen and gate2.seen[0].get("decision") == "approve"
    executed = any("SENT to" in json.dumps(m, default=str) for m in agent2.messages)
    print("tool executed after approval:", executed)

    # 2. structured output
    a3 = Agent(model=model, callback_handler=None, system_prompt="Answer as JSON matching the schema.")
    r3 = await a3.invoke_async("An Extreme Heat Warning with 108 F heat index for elderly residents. Should we activate?", structured_output_model=Verdict)
    print("structured:", r3.structured_output)
    assert isinstance(r3.structured_output, Verdict)

    # 3. graph with an interrupt inside a node, then resume
    g1 = Gate()
    n1 = Agent(name="n1", model=model, tools=[lookup_temp], callback_handler=None, system_prompt="Look up the temperature for the city in the task and report it in one line.")
    n2 = Agent(name="n2", model=model, tools=[send_note], hooks=[g1], callback_handler=None, system_prompt="Send a note to Rosa with the temperature from the previous node. Then say DONE.")
    b = GraphBuilder()
    b.add_node(n1, "lookup"); b.add_node(n2, "notify"); b.add_edge("lookup", "notify"); b.set_entry_point("lookup")
    b.set_session_manager(FileSessionManager(session_id="smoke-graph", storage_dir=SESS))
    graph = b.build()
    types = []
    gres = None
    async for ev in graph.stream_async("City: Phoenix", invocation_state={"episode_id": "ep_smoke"}):
        types.append(ev.get("type"))
        if ev.get("type") == "multiagent_result":
            gres = ev.get("result")
    print("graph event types:", sorted({t for t in types if t}))
    print("graph status:", gres.status if gres else None, "| interrupts:", [i.name for i in (gres.interrupts if gres else [])])
    assert gres and gres.status == Status.INTERRUPTED
    responses = [{"interruptResponse": {"interruptId": i.id, "response": {"decision": "approve"}}} for i in gres.interrupts]
    gres2 = await graph.invoke_async(responses, invocation_state={"episode_id": "ep_smoke"})
    print("graph after resume:", gres2.status, "| nodes:", list(gres2.results.keys()))
    assert gres2.status == Status.COMPLETED
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(SESS, ignore_errors=True)
