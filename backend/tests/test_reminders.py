"""How Porchlight chases someone who has not answered, and when it stops.

These encode a policy, not a model's judgement: how often an anxious 78-year-old gets texted, how many
times, and what happens when the messages run out. Run: python -m tests.test_reminders
"""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-rem-")
os.environ["SENTINEL_ENABLED"] = "false"

from app import reminders
from app.config import settings
from app.models import Checkin, Episode, HazardEvent, Member
from app.store import store


def ago(minutes: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def make(n_episodes: int = 1, sent_minutes_ago: float = 10.0) -> list[Checkin]:
    store.put_member(Member(id="mem_bettie", name="Bettie Harris", lat=33.5, lon=-112.17))
    out = []
    for i in range(n_episodes):
        ep = Episode(hazard=HazardEvent(source="test", hazard_type="heat", event_name=f"Heat {i}"))
        ep.status = "monitoring"
        store.put_episode(ep)
        c = Checkin(token=f"t{i}", episode_id=ep.id, member_id="mem_bettie",
                    channel="telegram", status="sent", sent_at=ago(sent_minutes_ago))
        store.put_checkin(c)
        out.append(c)
    return out


def test_one_reply_closes_every_open_conversation():
    """The bug that made this necessary: answering one episode left three others still chasing."""
    made = make(n_episodes=4)
    assert len(reminders.open_checkins_for("mem_bettie")) == 4

    closed = reminders.resolve_all_for("mem_bettie", "ok", "said: im fine")

    assert len(closed) == 4, f"a reply must close all four, closed {len(closed)}"
    assert reminders.open_checkins_for("mem_bettie") == [], "nothing may still be waiting on her"
    for c in made:
        got = next(x for x in store.checkins() if x.token == c.token)
        assert got.status == "ok" and got.responded_at


def test_a_reminder_waits_the_configured_gap():
    """No nagging: a neighbour is left alone between messages."""
    [c] = make(sent_minutes_ago=0.1)
    assert not reminders.due_for_reminder(c), "a message just went out; do not immediately send another"

    [c2] = make(sent_minutes_ago=settings.REMINDER_GAP_MINUTES + 1)
    assert reminders.due_for_reminder(c2), "past the gap, a reminder is due"


def test_the_gap_is_measured_from_the_last_thing_we_said():
    """Pacing must follow the last contact, not the original dispatch, or reminders bunch up."""
    [c] = make(sent_minutes_ago=60)
    c.reminders_sent = 1
    c.last_contact_at = ago(0.2)          # we spoke to her moments ago
    store.put_checkin(c)
    assert not reminders.due_for_reminder(c), "she was just messaged; the old sent_at is irrelevant"


def test_reminders_run_out_and_then_it_becomes_critical():
    """Silence from someone at risk is the finding, not a reason to keep texting."""
    [c] = make(sent_minutes_ago=60)
    c.reminders_sent = settings.MAX_REMINDERS
    c.last_contact_at = ago(settings.REMINDER_GAP_MINUTES + 1)
    store.put_checkin(c)

    assert not reminders.due_for_reminder(c), "no fourth message"
    assert reminders.exhausted(c), "out of reminders with no reply"

    reminders.mark_critical(c, store.member("mem_bettie"))
    got = next(x for x in store.checkins() if x.token == c.token)
    assert got.status == "critical", f"expected critical, got {got.status}"
    assert not reminders.due_for_reminder(got), "a critical check-in is closed to further reminders"
    ep = store.episode(c.episode_id)
    assert any(t.kind == "critical" for t in ep.timeline), "the coordinator must see it on the timeline"


def test_someone_who_answered_is_never_reminded():
    [c] = make(sent_minutes_ago=60)
    store.mutate_checkin(c.token, lambda x: setattr(x, "status", "ok"))
    got = next(x for x in store.checkins() if x.token == c.token)
    assert not reminders.due_for_reminder(got)
    assert not reminders.exhausted(got)
    assert reminders.open_checkins_for("mem_bettie") == []


def test_a_closed_episode_stops_chasing_its_neighbours():
    [c] = make(sent_minutes_ago=60)
    store.mutate_episode(c.episode_id, lambda e: setattr(e, "status", "closed"))
    assert reminders.open_checkins_for("mem_bettie") == [], "a closed episode must not keep texting"


def test_the_three_messages_escalate_in_seriousness():
    make()
    ep = store.episodes()[0]
    m = store.member("mem_bettie")
    texts = [reminders.reminder_text(m, ep, i) for i in (1, 2, 3)]
    assert len(set(texts)) == 3, "each reminder should say something different"
    assert "911" in texts[2], "the last message must point at emergency services"
    assert all(len(t) < 320 for t in texts), "these go out as text messages"


def test_three_open_episodes_do_not_become_three_texts_at_once():
    """The bug that produced six messages in one burst: the job looped over rows, not people."""
    make(n_episodes=3, sent_minutes_ago=60)
    awaiting = reminders.members_awaiting()
    assert awaiting == ["mem_bettie"], f"one person, listed once, got {awaiting}"

    c = reminders.oldest_open_for("mem_bettie")
    assert c is not None and reminders.due_for_reminder(c)

    reminders.record_reminder_for("mem_bettie")

    # every row must now show the attempt, so no other row can fire in the same cycle
    rows = reminders.open_checkins_for("mem_bettie")
    assert len(rows) == 3, "all three are still open; she has not answered"
    assert all(r.reminders_sent == 1 for r in rows), [r.reminders_sent for r in rows]
    assert reminders.attempts_for("mem_bettie") == 1
    assert not any(reminders.due_for_reminder(r) for r in rows), "nothing else may fire this cycle"


def test_the_cap_counts_the_person_not_the_rows():
    """Three episodes must still mean three messages in total, not nine."""
    make(n_episodes=3, sent_minutes_ago=60)
    for _ in range(settings.MAX_REMINDERS):
        for r in reminders.open_checkins_for("mem_bettie"):
            store.mutate_checkin(r.token, lambda x: setattr(x, "last_contact_at", ago(settings.REMINDER_GAP_MINUTES + 1)))
        c = reminders.oldest_open_for("mem_bettie")
        assert reminders.due_for_reminder(c), "each of the three is due in turn"
        reminders.record_reminder_for("mem_bettie")

    assert reminders.attempts_for("mem_bettie") == settings.MAX_REMINDERS
    for r in reminders.open_checkins_for("mem_bettie"):
        store.mutate_checkin(r.token, lambda x: setattr(x, "last_contact_at", ago(settings.REMINDER_GAP_MINUTES + 1)))
    c = reminders.oldest_open_for("mem_bettie")
    assert not reminders.due_for_reminder(c), "a fourth message must never be sent"
    assert reminders.exhausted(c)


def test_going_critical_closes_every_episode_for_that_person():
    make(n_episodes=3, sent_minutes_ago=60)
    for r in reminders.open_checkins_for("mem_bettie"):
        store.mutate_checkin(r.token, lambda x: (setattr(x, "reminders_sent", settings.MAX_REMINDERS),
                                                 setattr(x, "last_contact_at", ago(settings.REMINDER_GAP_MINUTES + 1))))
    reminders.mark_critical_for(store.member("mem_bettie"))
    assert reminders.open_checkins_for("mem_bettie") == [], "nothing may still be chasing her"
    crit = [c for c in store.checkins() if c.member_id == "mem_bettie" and c.status == "critical"]
    assert len(crit) == 3, f"every episode should show critical, got {len(crit)}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL REMINDER TESTS PASSED")
