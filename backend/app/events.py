"""In-process event bus feeding the dashboard SSE stream and the episode timeline."""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

from .models import AgentEvent


class EventBus:
    def __init__(self, history: int = 500):
        self._history: deque[AgentEvent] = deque(maxlen=history)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: AgentEvent) -> AgentEvent:
        with self._lock:
            self._history.append(event)
            subs = list(self._subscribers)
        loop = self._loop
        for q in subs:
            if loop and loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, event)
            else:
                try:
                    q.put_nowait(event)
                except Exception:
                    pass
        return event

    def emit(self, type: str, text: str = "", episode_id: str = "", agent: str = "", **data: Any) -> AgentEvent:
        return self.publish(AgentEvent(type=type, text=text, episode_id=episode_id, agent=agent, data=data))

    def history(self, episode_id: str | None = None, limit: int = 200) -> list[AgentEvent]:
        with self._lock:
            items = list(self._history)
        if episode_id:
            items = [e for e in items if e.episode_id == episode_id]
        return items[-limit:]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


bus = EventBus()
