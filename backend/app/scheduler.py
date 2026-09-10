"""Background jobs: hazard scanning, follow-up cycles, and Telegram reply polling."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .agents.runner import runner
from .agents.sentinel import new_hazards
from .channels.telegram import get_updates
from .config import settings
from .events import bus
from .models import now_iso
from .store import store

log = logging.getLogger("porchlight.scheduler")
_scan_lock = asyncio.Lock()  # the manual endpoint calls sentinel_job directly, outside the scheduler
_telegram_task: asyncio.Task | None = None
scheduler = AsyncIOScheduler(
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
)


async def sentinel_job() -> None:
    if not store.get_setting("sentinel_enabled", settings.SENTINEL_ENABLED):
        return
    if _scan_lock.locked():
        log.info("a scan is already running; skipping this one")
        return
    async with _scan_lock:
        await _sentinel_scan()


async def _sentinel_scan() -> None:
    try:
        fresh = await asyncio.to_thread(new_hazards)  # blocking HTTP off the event loop
    except Exception as e:  # noqa: BLE001
        log.warning("sentinel scan failed: %s", e)
        return
    store.set_setting("last_scan_at", now_iso())
    bus.emit("scan", f"Sentinel scan complete: {len(fresh)} new hazard(s)", agent="sentinel", count=len(fresh))
    for h in fresh:
        active = [e for e in store.episodes() if e.status not in ("closed", "stood_down", "failed")]
        if any(e.hazard.hazard_type == h.hazard_type for e in active):
            # Deliberately NOT marked seen: when the open episode closes, this alert must be able to open a new one.
            log.info("skipping %s: an episode for %s is already active", h.event_name, h.hazard_type)
            continue
        try:
            ep = await runner.start(h)
        except Exception as e:  # noqa: BLE001  — one bad hazard must not abort the rest of the batch
            log.error("could not open an episode for %s: %s", h.event_name, e)
            continue
        # Only now is the alert handled. A run that later fails re-arms detection (see runner._run_graph).
        store.mark_alert_seen(h.external_id, ep.id)


async def followup_job() -> None:
    """Wake the follow-up agent for episodes that actually have someone to follow up on.

    An episode reaches "monitoring" whether or not any message went out — a run that was declined, or that
    failed before outreach, sits there with no check-ins. Running the agent on those costs a model call
    every cycle and can only conclude that there is nothing to do.
    """
    for ep in store.episodes():
        if ep.status not in ("monitoring", "escalating"):
            continue
        waiting = [c for c in store.checkins(ep.id) if c.status in ("sent", "delivered")]
        if not waiting:
            continue
        await runner.run_followup(ep.id)


def _member_for_reply(chat_id: str, text: str) -> tuple[Any, str]:
    """Work out which neighbour a Telegram reply is answering for.

    Normally each neighbour has their own chat id and the match is exact. During a demo every outbound
    message is redirected to one chat by DEMO_OVERRIDE_TELEGRAM_CHAT_ID, so replies from that chat cannot
    be told apart by sender. In that case the reply answers the neighbour named in the text if there is
    one ("ok rosa"), and otherwise the most recent check-in still waiting for an answer. The check-in note
    records that the attribution came from the override, so nothing later reads as a real reply from that
    person when it was not.
    """
    exact = next((m for m in store.members() if m.telegram_chat_id and m.telegram_chat_id == chat_id), None)
    if exact:
        return exact, ""

    override = settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID
    if not override or chat_id != str(override):
        return None, ""

    # When one member is designated as the live one, that chat is unambiguously them.
    only = settings.DEMO_LIVE_MEMBER_ID
    if only:
        m = store.member(only)
        return (m, "") if m else (None, "")

    waiting = [c for c in store.checkins()
               if c.status in ("sent", "delivered") and c.channel == "telegram"
               and (ep := store.episode(c.episode_id)) and ep.status in ("monitoring", "escalating")]
    if not waiting:
        return None, ""

    by_id = {m.id: m for m in store.members()}
    named = [c for c in waiting
             if (m := by_id.get(c.member_id)) and m.name.split()[0].lower() in text]
    chosen = max(named or waiting, key=lambda c: c.sent_at)
    member = by_id.get(chosen.member_id)
    if not member:
        return None, ""
    return member, "  (demo override: replies from one chat are matched to the newest waiting check-in)"


async def _answer_in_words(member: Any, text: str) -> None:
    """A neighbour wrote a sentence rather than tapping a button. Read it, answer them, record it."""
    from .agents import responder
    from .channels.registry import deliver

    waiting = [c for c in store.checkins()
               if c.member_id == member.id and c.status in ("sent", "delivered")
               and (ep := store.episode(c.episode_id)) and ep.status in ("monitoring", "escalating")]
    if not waiting:
        return
    checkin = max(waiting, key=lambda c: c.sent_at)
    ep = store.episode(checkin.episode_id)

    bus.emit("checkin", f"{member.name} wrote back; reading their message…",
             episode_id=ep.id, member_id=member.id, agent="responder", said=text[:200])
    outcome = await responder.respond(ep, member, text)
    responder.record(ep, member, checkin.token, text, outcome)
    res = await asyncio.to_thread(deliver, member, outcome["reply"], "telegram")
    if not res.ok:
        log.warning("could not answer %s: %s", member.name, res.detail)


async def telegram_listener() -> None:
    """Hold a long poll open against Telegram for as long as the server runs.

    A long poll does not fit a scheduled job: the job outlives its own interval, so APScheduler spends the
    time refusing to start overlapping copies. A single loop is both simpler and what the Bot API expects.
    """
    log.info("telegram listener started")
    while True:
        try:
            await telegram_job()
        except asyncio.CancelledError:
            log.info("telegram listener stopped")
            raise
        except Exception as e:  # noqa: BLE001 — a bad poll must never end the loop
            log.warning("telegram listener error: %s", e)
            await asyncio.sleep(5)


async def telegram_job() -> None:
    """Capture OK / HELP replies from Telegram and record them as check-ins."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    offset = store.get_setting("telegram_offset")
    try:
        updates = await asyncio.to_thread(get_updates, offset, settings.TELEGRAM_POLL_WAIT_S)
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
        raw = (msg.get("text") or "").strip()
        member, note = _member_for_reply(chat_id, text)
        if not member:
            continue
        # A one-word answer is unambiguous; anything else is a sentence the responder agent should read.
        status = ("ok" if text in ("ok", "okay", "im ok", "i'm ok", "bien", "estoy bien", "si", "sí", "yes", "1")
                  else "needs_help" if text in ("help", "ayuda", "no", "2") else "")
        if not status:
            await _answer_in_words(member, raw)
            continue
        for c in store.checkins():
            ep = store.episode(c.episode_id)
            if c.member_id == member.id and ep and ep.status in ("monitoring", "escalating") and c.status in ("sent", "delivered"):
                def _reply(x, _s=status, _t=text, _n=note):
                    x.status = _s
                    x.responded_at = now_iso()
                    x.note = f"telegram reply: {_t[:80]}{_n}"

                store.mutate_checkin(c.token, _reply)
                bus.emit("checkin", f"{member.name} replied via Telegram: {status.replace('_', ' ')}", episode_id=ep.id, member_id=member.id, status=status)
                break


def start() -> None:
    scheduler.add_job(sentinel_job, "interval", minutes=settings.SENTINEL_INTERVAL_MINUTES, id="sentinel",
                      next_run_time=datetime.now() + timedelta(seconds=20))  # first scan shortly after startup
    try:
        followup_minutes = max(1, int(store.get_setting("followup_interval_minutes", settings.FOLLOWUP_INTERVAL_MINUTES)))
    except (TypeError, ValueError):
        followup_minutes = settings.FOLLOWUP_INTERVAL_MINUTES
    scheduler.add_job(followup_job, "interval", minutes=followup_minutes, id="followup")
    scheduler.start()
    if settings.TELEGRAM_BOT_TOKEN:
        global _telegram_task
        _telegram_task = asyncio.create_task(telegram_listener())


def stop() -> None:
    if _telegram_task is not None:
        _telegram_task.cancel()
    if scheduler.running:
        scheduler.shutdown(wait=False)
