"""Recovery paths that only ever fire after a run has already gone wrong.

Nothing here talks to a model. Each test drives one of the runner's recovery branches with a fake graph
that raises exactly what the Strands SDK raises (strands/interrupt.py, _InterruptState.resume), so the
branch is exercised without a live provider.

Run: python -m tests.test_recovery
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="porchlight-recovery-"))

from app.agents.runner import EpisodeRunner
from app.config import settings
from app.models import Approval, Episode, HazardEvent
from app.store import store


def _episode(ep_id: str, external_id: str = "") -> Episode:
    ep = Episode(
        id=ep_id,
        hazard=HazardEvent(source="test", hazard_type="heat", event_name="Excessive Heat Warning",
                           headline="Test hazard", severity="Severe", external_id=external_id),
    )
    store.put_episode(ep)
    return ep


def _approval(ep_id: str, interrupt_id: str) -> None:
    store.put_approval(Approval(
        episode_id=ep_id, kind="outreach_dispatch", title="Send 3 messages", summary="s", payload={},
        interrupt_id=interrupt_id, scope="graph", status="approved", decision_note="go ahead",
    ))


class FakeGraph:
    """Replays a scripted outcome per stream_async call, recording the task it was handed."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list = []

    def stream_async(self, task, invocation_state=None):
        self.calls.append(task)
        outcome = self.outcomes.pop(0)

        async def gen():
            if isinstance(outcome, Exception):
                raise outcome
            yield {"type": "done"}

        return gen()


def _runner(first: FakeGraph, ep_id: str, rebuilt: FakeGraph | None = None) -> EpisodeRunner:
    r = EpisodeRunner()
    r._graphs[ep_id] = first
    r._rebuild_clean = lambda _id: rebuilt  # type: ignore[method-assign]
    r._finish_graph = _noop  # type: ignore[method-assign]
    return r


async def _noop(*a, **k):
    return None


# The exact messages the SDK raises, so a wording change upstream shows up here rather than in production.
PAUSED = TypeError("prompt_type=<class 'str'> | must resume from interrupt with list of interruptResponse's")
STALE = KeyError("interrupt_id=<int_gone> | no interrupt found")


def test_paused_graph_is_resumed_with_the_stored_decisions():
    """A saved graph mid-approval rejects a plain task. Retry with the decisions already made."""
    ep = _episode("ep_paused")
    _approval(ep.id, "int_1")
    g = FakeGraph(PAUSED, "ok")

    asyncio.run(_runner(g, ep.id)._run_graph(ep.id, "the task", allow_recovery=True))

    assert isinstance(g.calls[0], str), "the first attempt should be the ordinary task"
    resumed = g.calls[1]
    assert resumed[0]["interruptResponse"]["interruptId"] == "int_1"
    assert resumed[0]["interruptResponse"]["response"]["decision"] == "approve"
    assert store.episode(ep.id).status != "failed"


def test_a_stale_interrupt_id_starts_the_graph_over():
    """KeyError from resume means the restored state never knew that interrupt. Rebuild, don't die."""
    ep = _episode("ep_stale")
    _approval(ep.id, "int_gone")
    first, fresh = FakeGraph(PAUSED, STALE), FakeGraph("ok")

    asyncio.run(_runner(first, ep.id, fresh)._run_graph(ep.id, "the task", allow_recovery=True))

    assert fresh.calls == ["the task"], "the rebuilt graph gets the plain task, not the stale responses"
    assert store.episode(ep.id).status != "failed"


def test_an_unpaused_graph_never_sees_interrupt_responses():
    """The common case. A graph that is not paused runs the ordinary task straight through."""
    ep = _episode("ep_plain")
    _approval(ep.id, "int_old")  # a decided approval from an earlier, finished pause
    g = FakeGraph("ok")

    asyncio.run(_runner(g, ep.id)._run_graph(ep.id, "the task", allow_recovery=True))

    assert g.calls == ["the task"], "stale responses must not be sent to a graph that is not waiting"


def test_recovery_is_off_unless_asked_for():
    """A first run has nothing to resume from, so a TypeError there is a real failure."""
    ep = _episode("ep_norecover")
    g = FakeGraph(PAUSED)

    asyncio.run(_runner(g, ep.id)._run_graph(ep.id, "the task"))

    assert store.episode(ep.id).status == "failed"


def test_reset_session_deletes_the_directory_the_sdk_actually_creates():
    """FileSessionManager stores under session_<session_id>; ours is graph-<episode id>."""
    d = settings.SESSION_DIR / "session_graph-ep_session"
    (d / "agents").mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps({"session_id": "graph-ep_session"}))

    EpisodeRunner()._reset_session("ep_session")

    assert not d.exists(), "a stale session directory would be restored on the next run"


def test_a_failed_run_lets_the_sentinel_see_the_alert_again():
    ep = _episode("ep_failed", external_id="urn:test:recovery")
    store.mark_alert_seen(ep.hazard.external_id)
    g = FakeGraph(RuntimeError("the model went away"))

    asyncio.run(_runner(g, ep.id)._run_graph(ep.id, "the task"))

    assert store.episode(ep.id).status == "failed"
    assert not store.alert_seen(ep.hazard.external_id), "a failed run must not suppress the alert forever"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL RECOVERY TESTS PASSED")
