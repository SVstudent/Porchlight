"""Episode context available to tools and hooks during a graph run."""
from __future__ import annotations

import contextvars
from typing import Any

current_episode_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_episode_id", default="")


def episode_id_from(invocation_state: dict[str, Any] | None) -> str:
    if invocation_state and invocation_state.get("episode_id"):
        return str(invocation_state["episode_id"])
    return current_episode_id.get()
