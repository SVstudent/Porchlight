"""SQLite-backed store. Records are stored as JSON documents so the schema can evolve quickly."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from typing import Any

from .config import settings
from .models import Approval, Checkin, Deployment, Episode, HazardEvent, Member, Resource, Volunteer, now_iso

_TABLES = ["members", "volunteers", "resources", "hazards", "episodes", "approvals", "checkins",
           "deployments", "seen_alerts", "settings"]


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or str(settings.DB_PATH)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            for t in _TABLES:
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
            self._conn.commit()

    # ---- generic ----
    def _put(self, table: str, id: str, doc: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} (id, doc, updated_at) VALUES (?, ?, ?) "
                f"ON CONFLICT(id) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at",
                (id, json.dumps(doc), now_iso()),
            )
            self._conn.commit()

    def _get(self, table: str, id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(f"SELECT doc FROM {table} WHERE id = ?", (id,)).fetchone()
        return json.loads(row["doc"]) if row else None

    def _all(self, table: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(f"SELECT doc FROM {table} ORDER BY updated_at ASC").fetchall()
        return [json.loads(r["doc"]) for r in rows]

    def _delete(self, table: str, id: str) -> None:
        with self._lock:
            self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
            self._conn.commit()

    def _clear(self, table: str) -> None:
        with self._lock:
            self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    # ---- members ----
    def members(self) -> list[Member]:
        return [Member(**d) for d in self._all("members")]

    def member(self, id: str) -> Member | None:
        d = self._get("members", id)
        return Member(**d) if d else None

    def put_member(self, m: Member) -> Member:
        self._put("members", m.id, m.model_dump())
        return m

    def delete_member(self, id: str) -> None:
        self._delete("members", id)

    # ---- volunteers ----
    def volunteers(self) -> list[Volunteer]:
        return [Volunteer(**d) for d in self._all("volunteers")]

    def volunteer(self, id: str) -> Volunteer | None:
        d = self._get("volunteers", id)
        return Volunteer(**d) if d else None

    def put_volunteer(self, v: Volunteer) -> Volunteer:
        self._put("volunteers", v.id, v.model_dump())
        return v

    # ---- resources ----
    def resources(self) -> list[Resource]:
        return [Resource(**d) for d in self._all("resources")]

    def put_resource(self, r: Resource) -> Resource:
        self._put("resources", r.id, r.model_dump())
        return r

    # ---- hazards / seen alerts ----
    def put_hazard(self, h: HazardEvent) -> HazardEvent:
        self._put("hazards", h.id, h.model_dump())
        return h

    def hazards(self) -> list[HazardEvent]:
        return [HazardEvent(**d) for d in self._all("hazards")]

    def alert_seen(self, external_id: str) -> bool:
        return self._get("seen_alerts", external_id) is not None

    def mark_alert_seen(self, external_id: str, episode_id: str = "") -> None:
        self._put("seen_alerts", external_id, {"external_id": external_id, "episode_id": episode_id, "seen_at": now_iso()})

    def unmark_alert_seen(self, external_id: str) -> None:
        """Re-arm detection for one alert, after a run that failed before it could help anyone."""
        self._delete("seen_alerts", external_id)

    def clear_seen_alerts(self) -> None:
        self._clear("seen_alerts")

    # ---- episodes ----
    def episodes(self) -> list[Episode]:
        eps = [Episode(**d) for d in self._all("episodes")]
        eps.sort(key=lambda e: e.created_at, reverse=True)
        return eps

    def episode(self, id: str) -> Episode | None:
        d = self._get("episodes", id)
        return Episode(**d) if d else None

    def put_episode(self, e: Episode) -> Episode:
        e.updated_at = now_iso()
        self._put("episodes", e.id, e.model_dump())
        return e

    def mutate_episode(self, id: str, fn) -> Episode | None:
        """Atomic read-modify-write. Parallel graph branches and hooks all update the same episode row, so
        every update goes through here to avoid a stale write clobbering another branch's fields."""
        with self._lock:
            ep = self.episode(id)
            if ep is None:
                return None
            fn(ep)
            return self.put_episode(ep)

    # ---- approvals ----
    def approvals(self, episode_id: str | None = None, status: str | None = None) -> list[Approval]:
        out = [Approval(**d) for d in self._all("approvals")]
        if episode_id:
            out = [a for a in out if a.episode_id == episode_id]
        if status:
            out = [a for a in out if a.status == status]
        out.sort(key=lambda a: a.created_at, reverse=True)
        return out

    def approval(self, id: str) -> Approval | None:
        d = self._get("approvals", id)
        return Approval(**d) if d else None

    def put_approval(self, a: Approval) -> Approval:
        self._put("approvals", a.id, a.model_dump())
        return a

    # ---- check-ins ----
    def checkins(self, episode_id: str | None = None) -> list[Checkin]:
        out = [Checkin(**d) for d in self._all("checkins")]
        if episode_id:
            out = [c for c in out if c.episode_id == episode_id]
        return out

    def deployments(self, episode_id: str | None = None) -> list[Deployment]:
        out = [Deployment(**d) for d in self._all("deployments")]
        if episode_id:
            out = [d for d in out if d.episode_id == episode_id]
        return sorted(out, key=lambda d: d.created_at)

    def deployment(self, dep_id: str) -> Deployment | None:
        d = self._get("deployments", dep_id)
        return Deployment(**d) if d else None

    def put_deployment(self, d: Deployment) -> Deployment:
        self._put("deployments", d.id, d.model_dump())
        return d

    def mutate_deployment(self, dep_id: str, fn) -> Deployment | None:
        with self._lock:
            d = self.deployment(dep_id)
            if d is None:
                return None
            fn(d)
            return self.put_deployment(d)

    def checkin(self, token: str) -> Checkin | None:
        d = self._get("checkins", token)
        return Checkin(**d) if d else None

    def put_checkin(self, c: Checkin) -> Checkin:
        self._put("checkins", c.token, c.model_dump())
        return c

    def mutate_checkin(self, token: str, fn) -> Checkin | None:
        """Atomic read-modify-write. A member's tap, a Telegram reply and an escalation can land together."""
        with self._lock:
            c = self.checkin(token)
            if c is None:
                return None
            fn(c)
            return self.put_checkin(c)

    # ---- settings (policy) ----
    def get_setting(self, key: str, default: Any = None) -> Any:
        d = self._get("settings", key)
        return d["value"] if d else default

    def set_setting(self, key: str, value: Any) -> None:
        self._put("settings", key, {"value": value})

    # ---- maintenance ----
    def reset_runtime(self) -> None:
        """Clear episodes/approvals/check-ins/seen alerts but keep roster, volunteers, resources."""
        for t in ("hazards", "episodes", "approvals", "checkins", "deployments", "seen_alerts"):
            self._clear(t)

    def seed_if_empty(self, members: Iterable[Member], volunteers: Iterable[Volunteer], resources: Iterable[Resource]) -> bool:
        if self.members():
            return False
        for m in members:
            self.put_member(m)
        for v in volunteers:
            self.put_volunteer(v)
        for r in resources:
            self.put_resource(r)
        return True


store = Store()
