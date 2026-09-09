"""Smoke test 2: coordinator edits reach the tool, and a paused Graph resumes from a NEW Graph object built
from the same session (what the runner does after a backend restart). Run: python -m tests.smoke_resume"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from typing import Any

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder
from strands.multiagent.base import Status
from strands.session import FileSessionManager

from app.agents.model_factory import build_model

SESS = tempfile.mkdtemp(prefix="porchlight-smoke2-")
SENT: list[dict[str, Any]] = []


@tool
def send_note(who: str, text: str) -> str:
    """Send a note to a neighbor.
    Args:
        who: recipient name
        text: the note
    """
    SENT.append({"who": who, "text": text})
    return f"SENT to {who}: {text}"


class Gate(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.gate)

    def gate(self, event: BeforeToolCallEvent):
        if event.tool_use["name"] != "send_note":
            return
        resp = event.interrupt("porchlight-approval", reason={"input": event.tool_use["input"]}) or {}
        if resp.get("decision") != "approve":
            event.cancel_tool = "declined"
            return
        edits = resp.get("edits") or {}
        if edits:
            event.tool_use["input"].update(edits)


def build(model, session_id: str):
    n1 = Agent(name="n1", model=model, callback_handler=None, system_prompt="Reply with exactly: Phoenix is 108 F.")
    n2 = Agent(name="n2", model=model, tools=[send_note], hooks=[Gate()], callback_handler=None,
               system_prompt="Use send_note to send Rosa a note that says exactly 'stay cool'. Then say DONE.")
    b = GraphBuilder()
    b.add_node(n1, "lookup"); b.add_node(n2, "notify"); b.add_edge("lookup", "notify"); b.set_entry_point("lookup")
    b.set_session_manager(FileSessionManager(session_id=session_id, storage_dir=SESS))
    return b.build()


async def main():
    model = build_model()
    g1 = build(model, "resume-1")
    r1 = await g1.invoke_async("Go.", invocation_state={"episode_id": "ep_smoke"})
    print("first run:", r1.status, [i.reason for i in r1.interrupts])
    assert r1.status == Status.INTERRUPTED and r1.interrupts
    del g1  # simulate process restart: nothing in memory

    g2 = build(model, "resume-1")
    responses = [{"interruptResponse": {"interruptId": i.id, "response": {"decision": "approve", "edits": {"text": "EDITED BY COORDINATOR"}}}} for i in r1.interrupts]
    r2 = await g2.invoke_async(responses, invocation_state={"episode_id": "ep_smoke"})
    print("resumed in new graph:", r2.status, "| sent:", SENT)
    assert r2.status == Status.COMPLETED, r2.status
    assert SENT and SENT[-1]["text"] == "EDITED BY COORDINATOR", "edit did not reach the tool"
    print("\nRESUME + EDIT CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(SESS, ignore_errors=True)
