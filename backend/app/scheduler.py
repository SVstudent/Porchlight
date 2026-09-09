"""Background jobs: hazard scanning, follow-up cycles, and Telegram reply polling."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .agents.runner import runner
from .agents.sentinel import new_hazards
from .channels.telegram import get_updates
from .config import settings
from .events import bus
from .models import now_iso
from .store import store

log = logging.getLogger("porchlight.scheduler")
scheduler = AsyncIOScheduler()


async def sentinel_job() -> None:
    if not store.get_setting("sentinel_enabled", settings.SENTINEL_ENABLED):
        return
    try:
        fresh = await asyncio.to_thread(new_hazards)  # blocking HTTP off the event loop
    except Exception as e:  # noqa: BLE001
        log.warning("sentinel scan failed: %s", e)
        return
    store.set_setting("last_scan_at", now_iso())
    bus.emit("scan", f"Sentinel scan complete: {len(fresh)} new hazard(s)", agent="sentinel", count=len(fresh))
    for h in fresh:
        store.mark_alert_seen(h.external_id)
        active = [e for e in store.episodes() if e.status not in ("closed", "stood_down", "failed")]
        if any(e.hazard.hazard_type == h.hazard_type for e in active):
            log.info("skipping %s: an episode for %s is already active", h.event_name, h.hazard_type)
            continue
        ep = await runner.start(h)
        store.mark_alert_seen(h.external_id, ep.id)


async def followup_job() -> None:
    for ep in store.episodes():
        if ep.status in ("monitoring", "escalating"):
            await runner.run_followup(ep.id)


async def telegram_job() -> None:
    """Capture OK / HELP replies from Telegram and record them as check-ins."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    offset = store.get_setting("telegram_offset")
    try:
        updates = get_updates(offset)
    except Exception as e:  # noqa: BLE001
        log.debug("telegram poll failed: %s", e)
        return
    for u in updates:
        store.set_setting("telegram_offset", u["update_id"] + 1)
        msg = u.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip().lower()
        if not chat_id or not text:
            continue
        member = next((m for m in store.members() if m.telegram_chat_id == chat_id), None)
        if not member:
            continue
        status = "ok" if text in ("ok", "okay", "im ok", "i'm ok", "bien", "estoy bien", "si", "sí", "yes", "1") else "needs_help" if any(k in text for k in ("help", "ayuda", "no", "2")) else ""
        if not status:
            continue
        for c in store.checkins():
            ep = store.episode(c.episode_id)
            if c.member_id == member.id and ep and ep.status in ("monitoring", "escalating") and c.status in ("sent", "delivered"):
                c.status = status
                c.responded_at = now_iso()
                c.note = f"telegram reply: {text[:80]}"
                store.put_checkin(c)
                bus.emit("checkin", f"{member.name} replied via Telegram: {status.replace('_', ' ')}", episode_id=ep.id, member_id=member.id, status=status)


def start() -> None:
    scheduler.add_job(sentinel_job, "interval", minutes=settings.SENTINEL_INTERVAL_MINUTES, id="sentinel",
                      next_run_time=datetime.now() + timedelta(seconds=20))  # first scan shortly after startup
    followup_minutes = store.get_setting("followup_interval_minutes", settings.FOLLOWUP_INTERVAL_MINUTES)
    scheduler.add_job(followup_job, "interval", minutes=followup_minutes, id="followup")
    scheduler.add_job(telegram_job, "interval", seconds=8, id="telegram")
    scheduler.start()
