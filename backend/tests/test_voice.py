"""Voice channel without Twilio or a model. Run: python -m tests.test_voice"""
from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="porchlight-voice-")
os.environ["SEND_MODE"] = "console"
os.environ["VOICE_SKIP_SIGNATURE"] = "true"
os.environ["PUBLIC_BASE_URL"] = "https://porchlight.example.org"
os.environ.pop("TWILIO_ACCOUNT_SID", None)
os.environ.pop("TWILIO_AUTH_TOKEN", None)
os.environ.pop("TWILIO_FROM_NUMBER", None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import routes_voice  # noqa: E402
from app.agents.runner import runner  # noqa: E402
from app.agents.tools import dispatch_outreach_impl  # noqa: E402
from app.channels import deliver  # noqa: E402
from app.channels.twilio_voice import build_reply_twiml, build_twiml, spoken_text, voice_for  # noqa: E402
from app.config import settings  # noqa: E402
from app.events import bus  # noqa: E402
from app.models import Episode, HazardEvent  # noqa: E402
from app.seed import MEMBERS, RESOURCES, VOLUNTEERS  # noqa: E402
from app.store import store  # noqa: E402

_app = FastAPI()
_app.include_router(routes_voice.router)
client = TestClient(_app)

followup_calls: list[str] = []


async def _fake_followup(ep_id: str) -> None:
    followup_calls.append(ep_id)


runner.run_followup = _fake_followup  # type: ignore[method-assign]


def _says(xml: str) -> list[str]:
    root = ET.fromstring(xml)  # raises if the TwiML is not well-formed XML
    return [(el.text or "") for el in root.iter("Say")]


def setup():
    store.seed_if_empty(MEMBERS, VOLUNTEERS, RESOURCES)
    ep = Episode(hazard=HazardEvent(source="manual", event_name="Extreme Heat Warning", hazard_type="heat"))
    store.put_episode(ep)
    return ep


def _dispatch_voice(ep, member_id="mem_bettie", language="en"):
    r = dispatch_outreach_impl(ep.id, [{
        "member_id": member_id, "channel": "voice", "language": language,
        "body": "Bettie, it is dangerously hot today. Please stay in your coolest room and drink water. {checkin_link}",
        "call_script": "Hi Bettie, this is your neighbors network. It is dangerously hot today. Please stay in your coolest room and drink water.",
    }], "Calling Bettie, who only has a landline.")
    assert r["sent"] == 1, r
    return store.checkins(ep.id)[-1]


def test_twiml_builder():
    body = "Bettie, stay cool. Check in: https://porchlight.example.org/checkin/abc123"
    assert "http" not in spoken_text(body)
    assert spoken_text(body) == "Bettie, stay cool."
    assert spoken_text("x {checkin_link}", "Hola Rosa, hace calor.") == "Hola Rosa, hace calor."
    for language, voice in (("en", "Polly.Joanna"), ("es", "Polly.Lupe")):
        xml = build_twiml(spoken_text(body), language, "tok123")
        root = ET.fromstring(xml)
        assert root.tag == "Response"
        says = list(root.iter("Say"))
        assert says and all(s.get("voice") == voice for s in says), xml
        assert all("http" not in (s.text or "") for s in says), xml
        gather = root.find("Gather")
        assert gather is not None and gather.get("numDigits") == "1" and gather.get("method") == "POST"
        assert gather.get("action") == f"{settings.PUBLIC_BASE_URL}/api/voice/keypress/tok123"
        assert gather.find("Say") is not None
        assert voice_for(language) == voice
    es = build_twiml("Hola", "es", "t")
    assert "Presione 1" in es and "Press 1" not in es
    # XML escaping of user text
    xml = build_twiml('Tell Rosa & Earl: "stay <inside>"', "en", "t")
    assert "&amp;" in xml and "&lt;inside&gt;" in xml and _says(xml)[0] == 'Tell Rosa & Earl: "stay <inside>"'
    # no token -> no Gather, still valid
    root = ET.fromstring(build_twiml("Just a message", "en", ""))
    assert root.find("Gather") is None
    assert "Gracias" in _says(build_reply_twiml("thanks_help", "es"))[0]


def test_console_delivery_logs_script():
    bettie = store.member("mem_bettie") or MEMBERS[0]
    res = deliver(bettie, "Bettie, stay cool. Check in: https://porchlight.example.org/checkin/x", preferred="voice",
                  meta={"token": "x", "language": "en", "call_script": "Hi Bettie, please stay cool."})
    assert res.ok and res.channel == "console" and res.extra["requested_channel"] == "voice"
    assert "would say" in res.detail and "Hi Bettie, please stay cool." in res.detail and "http" not in res.detail


def test_keypress_needs_help():
    ep = setup()
    c = _dispatch_voice(ep)
    followup_calls.clear()
    before = len(bus.history())
    r = client.post(f"/api/voice/keypress/{c.token}", data={"Digits": "2", "CallSid": "CA123", "From": "+16025550114"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml"), r.text
    say = _says(r.text)[0]
    assert "neighbor will contact you" in say and "http" not in say
    cur = store.checkin(c.token)
    assert cur.status == "needs_help" and cur.responded_at and "pressed 2" in cur.note
    assert followup_calls == [ep.id]
    evs = [e for e in bus.history()[before:] if e.type == "checkin"]
    assert evs and evs[-1].data["status"] == "needs_help" and evs[-1].data["member_id"] == "mem_bettie"
    assert store.episode(ep.id).stats["responses"] == 1
    # a second keypress does not double-record or re-trigger the follow-up
    r2 = client.post(f"/api/voice/keypress/{c.token}", data={"Digits": "1"})
    assert r2.status_code == 200 and store.checkin(c.token).status == "needs_help" and followup_calls == [ep.id]


def test_keypress_ok_and_retry():
    ep = setup()
    c = _dispatch_voice(ep)
    followup_calls.clear()
    r = client.post(f"/api/voice/keypress/{c.token}", data={"Digits": "9"})
    root = ET.fromstring(r.text)
    assert root.find("Gather") is not None and store.checkin(c.token).status == "sent"  # re-prompted, nothing recorded
    r = client.post(f"/api/voice/keypress/{c.token}", data={"Digits": "1"})
    assert store.checkin(c.token).status == "ok" and followup_calls == []
    assert "glad you are okay" in _says(r.text)[0]
    r = client.post("/api/voice/keypress/nosuchtoken", data={"Digits": "1"})
    assert r.status_code == 200 and "no longer active" in _says(r.text)[0]


def test_status_callback():
    ep = setup()
    c = _dispatch_voice(ep)
    r = client.post(f"/api/voice/status/{c.token}", data={"CallStatus": "no-answer", "CallSid": "CA1"})
    assert r.status_code == 200 and r.json()["recorded"], r.text
    cur = store.checkin(c.token)
    assert cur.status == "no_response" and "no-answer" in cur.note
    assert store.episode(ep.id).timeline[-1].kind == "voice"
    ev = [e for e in bus.history() if e.data.get("call_status") == "no-answer"][-1]
    assert ev.data["member_id"] == "mem_bettie"
    # a completed call after a keypress leaves the recorded answer alone
    c2 = _dispatch_voice(ep)
    client.post(f"/api/voice/keypress/{c2.token}", data={"Digits": "1"})
    r = client.post(f"/api/voice/status/{c2.token}", data={"CallStatus": "completed"})
    assert r.json()["recorded"] is False and store.checkin(c2.token).status == "ok"
    # answered but no key pressed: still waiting, with a note
    c3 = _dispatch_voice(ep)
    client.post(f"/api/voice/status/{c3.token}", data={"CallStatus": "completed"})
    cur3 = store.checkin(c3.token)
    assert cur3.status == "sent" and "no key pressed" in cur3.note
    assert client.post("/api/voice/status/nosuchtoken", data={"CallStatus": "busy"}).json()["recorded"] is False


def test_signature_validation():
    # Worked example from Twilio's request-validation docs
    token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030", "To": "+18005551212"}
    good = "0/KCTR6DLpKmkAf8muzZqo1nDgQ="
    assert routes_voice.compute_signature(url, params, token) == good
    assert routes_voice.verify_signature(url, params, good, token)
    assert not routes_voice.verify_signature(url, params, "0/KCTR6DLpKmkAf8muzZqo1nDgX=", token)
    assert not routes_voice.verify_signature(url, params | {"Digits": "2"}, good, token)
    assert not routes_voice.verify_signature(url, params, good, "wrong-token")
    assert not routes_voice.verify_signature(url, params, "", token)

    # End to end through the router with signature checks on
    ep = setup()
    c = _dispatch_voice(ep)
    settings.VOICE_SKIP_SIGNATURE = False
    settings.TWILIO_AUTH_TOKEN = "test-auth-token"
    try:
        form = {"Digits": "1", "CallSid": "CA9"}
        signed_url = f"{settings.PUBLIC_BASE_URL}/api/voice/keypress/{c.token}"
        bad = client.post(f"/api/voice/keypress/{c.token}", data=form, headers={"X-Twilio-Signature": "nope"})
        assert bad.status_code == 403 and store.checkin(c.token).status == "sent"
        missing = client.post(f"/api/voice/keypress/{c.token}", data=form)
        assert missing.status_code == 403
        sig = routes_voice.compute_signature(signed_url, form, settings.TWILIO_AUTH_TOKEN)
        ok = client.post(f"/api/voice/keypress/{c.token}", data=form, headers={"X-Twilio-Signature": sig})
        assert ok.status_code == 200 and store.checkin(c.token).status == "ok", ok.text
    finally:
        settings.VOICE_SKIP_SIGNATURE = True
        settings.TWILIO_AUTH_TOKEN = ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL VOICE TESTS PASSED")
