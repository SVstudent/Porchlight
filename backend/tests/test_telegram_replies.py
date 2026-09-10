"""A neighbour's Telegram reply has to reach the right check-in, or the dashboard silently lies.

No network: these drive the poller's attribution logic directly. The Telegram API itself is covered by
scripts/telegram_setup.py, which makes real calls.

Run: python -m tests.test_telegram_replies
"""
from __future__ import annotations

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-tg-")
os.environ["SENTINEL_ENABLED"] = "false"

from app import scheduler  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Checkin, Episode, HazardEvent, Member  # noqa: E402
from app.store import store  # noqa: E402

MY_CHAT = "987654321"


def setup() -> Episode:
    for m in list(store.members()):
        store.delete_member(m.id) if hasattr(store, "delete_member") else None
    ep = Episode(hazard=HazardEvent(source="test", hazard_type="heat", event_name="Extreme Heat Warning"))
    ep.status = "monitoring"
    store.put_episode(ep)
    store.put_member(Member(id="mem_rosa", name="Rosa Alvarez", lat=33.5, lon=-112.17, preferred_channel="telegram"))
    store.put_member(Member(id="mem_walter", name="Walter Boyd", lat=33.5, lon=-112.17, preferred_channel="telegram"))
    store.put_checkin(Checkin(token="t_rosa", episode_id=ep.id, member_id="mem_rosa",
                              channel="telegram", status="sent", sent_at="2026-09-09T10:00:00Z"))
    store.put_checkin(Checkin(token="t_walter", episode_id=ep.id, member_id="mem_walter",
                              channel="telegram", status="sent", sent_at="2026-09-09T10:05:00Z"))
    return ep


def test_a_neighbor_with_their_own_chat_id_is_matched_exactly():
    """The production case: each neighbour has their own chat, so the sender identifies them."""
    setup()
    store.put_member(Member(id="mem_amina", name="Amina Yusuf", lat=33.5, lon=-112.17,
                            telegram_chat_id="111222", preferred_channel="telegram"))
    member, note = scheduler._member_for_reply("111222", "ok")
    assert member and member.id == "mem_amina", "an exact chat id must win"
    assert note == "", "an exact match needs no caveat"


def test_only_the_designated_member_is_really_messaged():
    """A demo has one phone. Twelve neighbours must not become twelve messages on it."""
    setup()
    from app.channels.registry import live_for
    settings.SEND_MODE = "live"
    settings.DEMO_LIVE_MEMBER_ID = "mem_rosa"
    try:
        assert live_for(store.member("mem_rosa")) is True, "the designated neighbour must really be messaged"
        assert live_for(store.member("mem_walter")) is False, "everyone else must fall back to the activity feed"
    finally:
        settings.SEND_MODE = "console"
        settings.DEMO_LIVE_MEMBER_ID = ""


def test_with_no_designated_member_everyone_is_live():
    setup()
    from app.channels.registry import live_for
    settings.SEND_MODE = "live"
    settings.DEMO_LIVE_MEMBER_ID = ""
    try:
        assert live_for(store.member("mem_rosa")) is True
        assert live_for(store.member("mem_walter")) is True
    finally:
        settings.SEND_MODE = "console"


def test_the_designated_member_owns_the_override_chat():
    """One chat, one neighbour: a reply from it is unambiguously theirs."""
    setup()
    settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID = MY_CHAT
    settings.DEMO_LIVE_MEMBER_ID = "mem_rosa"
    try:
        member, note = scheduler._member_for_reply(MY_CHAT, "ok")
        assert member and member.id == "mem_rosa", "the designated neighbour owns that chat"
        assert note == "", "no guesswork means no caveat"
    finally:
        settings.DEMO_LIVE_MEMBER_ID = ""


def test_the_demo_override_matches_the_newest_waiting_checkin():
    """Every message went to one chat, so a bare 'ok' answers the most recent one still waiting."""
    setup()
    settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID = MY_CHAT
    settings.DEMO_LIVE_MEMBER_ID = ""
    member, note = scheduler._member_for_reply(MY_CHAT, "ok")
    assert member and member.id == "mem_walter", f"expected the newest check-in, got {member and member.id}"
    assert "demo override" in note, "the note must record that this was not a real reply from that person"


def test_naming_a_neighbor_answers_for_that_neighbor():
    """'ok rosa' should answer for Rosa even though Walter's check-in is newer."""
    setup()
    settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID = MY_CHAT
    member, _ = scheduler._member_for_reply(MY_CHAT, "ok rosa")
    assert member and member.id == "mem_rosa", f"naming a neighbour should select them, got {member and member.id}"


def test_an_unknown_chat_is_ignored():
    """A stranger messaging the bot must not be able to answer on a neighbour's behalf."""
    setup()
    settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID = MY_CHAT
    member, _ = scheduler._member_for_reply("555000", "ok")
    assert member is None, "a chat that is neither a neighbour nor the override must be ignored"


def test_nothing_waiting_means_nothing_matched():
    ep = setup()
    settings.DEMO_OVERRIDE_TELEGRAM_CHAT_ID = MY_CHAT
    for c in store.checkins(ep.id):
        store.mutate_checkin(c.token, lambda x: setattr(x, "status", "ok"))
    member, _ = scheduler._member_for_reply(MY_CHAT, "ok")
    assert member is None, "with every check-in answered there is nothing left to attribute a reply to"


def test_followup_skips_episodes_with_nobody_waiting():
    """An episode reaches monitoring whether or not a message ever went out.

    Running the follow-up agent on one with no check-ins costs a model call every cycle and can only
    conclude there is nothing to do, so those are skipped.
    """
    import asyncio

    ep = setup()
    woken: list[str] = []

    class FakeRunner:
        async def run_followup(self, ep_id):
            woken.append(ep_id)

    real = scheduler.runner
    scheduler.runner = FakeRunner()
    try:
        asyncio.run(scheduler.followup_job())
        assert ep.id in woken, "an episode with people waiting must be followed up"

        for c in store.checkins(ep.id):          # everyone has now answered
            store.mutate_checkin(c.token, lambda x: setattr(x, "status", "ok"))
        woken.clear()
        asyncio.run(scheduler.followup_job())
        assert woken == [], f"nothing is waiting, so nothing should be woken: {woken}"
    finally:
        scheduler.runner = real


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL TELEGRAM REPLY TESTS PASSED")

