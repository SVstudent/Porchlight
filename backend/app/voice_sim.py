"""A recording of the check-in call Porchlight would place, voiced by Amazon Polly. No number is dialled.

The live call (channels/twilio_voice.py) speaks a script and waits for a keypress. This renders the same call as
audio a coordinator can play in the browser: the phone rings, the neighbour answers, Porchlight speaks the same
script with the same Polly voice and keypad prompt, the neighbour answers in their own words and presses a key,
and Porchlight says the same thanks the live call would.

Everything spoken comes from the case: the neighbour's name, language, risk factors, devices and notes, the
episode's hazard and assessment, the playbook's protective advice, and the nearest safe place on file. When the
outreach agent already wrote a call script for this neighbour, that script is used word for word.

Audio is 16 kHz mono WAV assembled from Polly PCM plus synthesised ring and keypad tones, cached on disk by a
hash of what is said, so playing it again costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import wave
from array import array
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .agents.playbooks import get_playbook
from .channels.twilio_voice import POLLY_VOICE, PROMPTS, lang, spoken_text
from .config import settings
from .feeds.places import haversine_km
from .models import Episode, Member
from .store import store

RATE = 16000
FORMAT_VERSION = 1
SIM_DIR = settings.DATA_DIR / "voice_sims"
SIM_ID = re.compile(r"^[0-9a-f]{20}$")

# Voices for the seeded neighbours, so each sounds like the same person every time. Anyone else gets the default.
NEIGHBOR_VOICE = {
    "mem_bettie": "Ruth", "mem_walter": "Gregory", "mem_earl": "Stephen", "mem_pete": "Matthew",
    "mem_danny": "Joey", "mem_helen": "Salli", "mem_amina": "Kendra", "mem_thanh": "Danielle",
    "mem_rosa": "Mia", "mem_gloria": "Mia", "mem_lupe": "Mia", "mem_jorge": "Andres",
}
DEFAULT_NEIGHBOR_VOICE = {"en": "Danielle", "es": "Mia"}

SAFE_KINDS = {
    "heat": ("cooling_center",), "cold": ("warming_center", "shelter"), "winter": ("warming_center", "shelter"),
    "air_quality": ("clean_air", "cooling_center"), "outage": ("cooling_center", "warming_center", "shelter"),
}

LINES = {
    "en": {
        "hello": "Hello?",
        "intro": "Hello {first}, this is Porchlight, calling for {community}.",
        "no_hazard": "We are checking on neighbors today.",
        "place": "The nearest {kind} is {name}, at {address}.",
        "pardon": "Sorry, could you say that again? I don't hear so well.",
        "bye_ok": "Okay. Thank you for calling. Bye now.",
        "bye_help": "Thank you. I'll be right here.",
        "ok": {
            "heat": "I'm alright. I've got the blinds down and plenty of water.",
            "cold": "I'm alright. The heat is on and I have extra blankets.",
            "winter": "I'm alright. The heat is on and I have extra blankets.",
            "air_quality": "I'm alright. I'm keeping the windows shut.",
            "outage": "I'm alright. I have a flashlight and some water.",
            "other": "I'm alright, thank you for checking on me.",
        },
        "help": {
            "oxygen_concentrator": "My oxygen machine needs the power, and I'm getting worried.",
            "device": "I depend on my {device}, and I'm worried about it.",
            "no_air_conditioning": "My cooler isn't keeping up. It's so hot in here I can hardly stand it.",
            "mobility": "I can't get out to the {kind} on my own.",
            "heat": "It's awful hot in here, and I've been feeling a little dizzy.",
            "cold": "The house is freezing and the heater can't keep up.",
            "winter": "The house is freezing and the heater can't keep up.",
            "air_quality": "The smoke is bothering my breathing.",
            "outage": "The power is out and I don't know how long it'll be.",
            "other": "I'm worried, and I could use some help.",
            "alone": "I'm here by myself.",
        },
        "kind": {"cooling_center": "cooling center", "warming_center": "warming center", "shelter": "shelter",
                 "clean_air": "clean air center"},
    },
    "es": {
        "hello": "¿Bueno?",
        "intro": "Hola {first}, le habla Porchlight, de parte de {community}.",
        "no_hazard": "Hoy estamos llamando a los vecinos para saber cómo están.",
        "place": "El {kind} más cercano es {name}, en {address}.",
        "pardon": "Perdón, ¿me lo puede repetir? No oigo muy bien.",
        "bye_ok": "Muy bien. Gracias por llamar. Adiós.",
        "bye_help": "Gracias. Aquí estaré.",
        "ok": {
            "heat": "Estoy bien. Tengo las cortinas cerradas y bastante agua.",
            "cold": "Estoy bien. Tengo la calefacción prendida y cobijas.",
            "winter": "Estoy bien. Tengo la calefacción prendida y cobijas.",
            "air_quality": "Estoy bien. Tengo las ventanas cerradas.",
            "outage": "Estoy bien. Tengo una linterna y agua.",
            "other": "Estoy bien, gracias por llamar.",
        },
        "help": {
            "oxygen_concentrator": "Mi máquina de oxígeno necesita la luz, y ya me estoy preocupando.",
            "device": "Dependo de mi {device} y me preocupa.",
            "no_air_conditioning": "El cooler ya no aguanta. Hace tanto calor que no lo soporto.",
            "mobility": "No puedo ir al {kind} yo sola.",
            "heat": "Hace muchísimo calor aquí y me siento un poco mareada.",
            "cold": "La casa está helada y la calefacción no alcanza.",
            "winter": "La casa está helada y la calefacción no alcanza.",
            "air_quality": "El humo me está afectando la respiración.",
            "outage": "Se fue la luz y no sé cuánto va a tardar.",
            "other": "Estoy preocupada y necesito ayuda.",
            "alone": "Estoy aquí sola.",
        },
        "kind": {"cooling_center": "centro de enfriamiento", "warming_center": "centro de calentamiento",
                 "shelter": "refugio", "clean_air": "centro de aire limpio"},
    },
}

_STREET = [(r"\bN\b", "North"), (r"\bS\b", "South"), (r"\bE\b", "East"), (r"\bW\b", "West"),
           (r"\bAve\b", "Avenue"), (r"\bRd\b", "Road"), (r"\bSt\b", "Street"), (r"\bBlvd\b", "Boulevard"),
           (r"\bDr\b", "Drive")]


# ------------------------------------------------------------------ what is said

def current_episode() -> Episode | None:
    live = [e for e in store.episodes() if e.status not in ("closed", "stood_down")]
    return max(live, key=lambda e: e.created_at) if live else None


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", (text or "").strip())
    return (m.group(1) if m else (text or "").strip())


def _spoken_address(address: str) -> str:
    street = (address or "").split(",")[0].strip()
    for pat, word in _STREET:
        street = re.sub(pat, word, street)
    return street


def _nearest_safe_place(member: Member, hazard_type: str) -> tuple[str, Any] | None:
    kinds = SAFE_KINDS.get(hazard_type, ("shelter",))
    best = None
    for r in store.resources():
        if r.kind in kinds:
            d = haversine_km(member.lat, member.lon, r.lat, r.lon)
            if best is None or d < best[0]:
                best = (d, r)
    return (best[1].kind, best[1]) if best else None


def _outcome(member: Member, episode: Episode | None, requested: str) -> str:
    if requested in ("ok", "needs_help"):
        return requested
    if episode:
        mine = [c for c in store.checkins(episode.id) if c.member_id == member.id]
        if mine:
            status = max(mine, key=lambda c: c.sent_at).status
            if status == "ok":
                return "ok"
            if status in ("needs_help", "escalated", "critical"):
                return "needs_help"
        tier = next((d.tier for d in (episode.triage.decisions if episode.triage else []) if d.member_id == member.id), None)
        if tier == 1:
            return "needs_help"
    risky = {"no_air_conditioning", "powered_medical_device", "mobility_limited", "cognitive_impairment"}
    return "needs_help" if member.devices or risky & set(member.risk_factors) else "ok"


def _help_line(member: Member, hazard_type: str, lg: str, place_kind: str) -> str:
    h = LINES[lg]["help"]
    kind = LINES[lg]["kind"].get(place_kind, LINES[lg]["kind"]["shelter"])
    rf = set(member.risk_factors)
    if "oxygen_concentrator" in member.devices:
        line = h["oxygen_concentrator"]
    elif member.devices:
        line = h["device"].format(device=member.devices[0].replace("_", " "))
    elif "no_air_conditioning" in rf and hazard_type == "heat":
        line = h["no_air_conditioning"]
    elif rf & {"mobility_limited", "no_transport"}:
        line = h["mobility"].format(kind=kind)
    else:
        line = h.get(hazard_type, h["other"])
    if "lives_alone" in rf:
        line = f"{line} {h['alone']}"
    return line


def _opening_script(member: Member, episode: Episode | None, lg: str, call_script: str) -> tuple[str, str, str]:
    """(script, source, place_kind). The outreach agent's own script wins; otherwise it is built from the case."""
    hazard_type = episode.hazard.hazard_type if episode else "other"
    place = _nearest_safe_place(member, hazard_type) if episode else None
    place_kind = place[0] if place else ""
    if call_script.strip():
        return spoken_text("", call_script), "coordinator", place_kind
    if episode and episode.outreach:
        msg = next((m for m in episode.outreach.messages if m.member_id == member.id), None)
        if msg and (msg.call_script or msg.body):
            return spoken_text(msg.body, msg.call_script), "outreach agent", place_kind

    L = LINES[lg]
    parts = [L["intro"].format(first=member.name.split()[0], community=settings.COMMUNITY_NAME)]
    if episode:
        pb = get_playbook(hazard_type)
        if lg == "es":
            parts += pb["spanish_phrases"][:2]
        else:
            h = episode.hazard
            parts.append(_first_sentence(episode.assessment.plain_summary) if episode.assessment and episode.assessment.plain_summary
                         else _first_sentence(h.headline or h.event_name))
            parts += [_first_sentence(a) for a in pb["protective_actions"][:2]]
        if place:
            kind, r = place
            parts.append(L["place"].format(kind=L["kind"].get(kind, kind), name=r.name, address=_spoken_address(r.address)))
    else:
        parts.append(L["no_hazard"])
    return " ".join(p.strip() for p in parts if p.strip()), "playbook", place_kind


def build_conversation(member: Member, episode: Episode | None, outcome: str = "auto", call_script: str = "") -> dict[str, Any]:
    lg = lang(member.language)
    L, P = LINES[lg], PROMPTS[lg]
    hazard_type = episode.hazard.hazard_type if episode else "other"
    outcome = _outcome(member, episode, outcome)
    script, source, place_kind = _opening_script(member, episode, lg, call_script)
    hard_of_hearing = "hard of hearing" in (member.notes or "").lower()

    porch = POLLY_VOICE[lg].removeprefix("Polly.")
    neigh = NEIGHBOR_VOICE.get(member.id, DEFAULT_NEIGHBOR_VOICE[lg])
    porch_rate = "85%" if hard_of_hearing else "100%"
    neigh_rate = "92%" if "age_75_plus" in member.risk_factors else "100%"
    first = member.name.split()[0]

    def p(text: str, rate: str = porch_rate) -> dict[str, Any]:
        return {"kind": "say", "speaker": "porchlight", "name": "Porchlight", "voice": porch, "rate": rate, "text": text}

    def n(text: str) -> dict[str, Any]:
        return {"kind": "say", "speaker": "neighbor", "name": first, "voice": neigh, "rate": neigh_rate, "text": text}

    digit = "1" if outcome == "ok" else "2"
    turns: list[dict[str, Any]] = [
        {"kind": "ring", "speaker": "line", "name": "Line", "text": "Ringing"},
        n(L["hello"]),
        p(script),
        p(P["gather"]),
    ]
    if hard_of_hearing:
        turns += [n(L["pardon"]), p(P["gather"], "75%")]
    turns.append(n(L["ok"].get(hazard_type, L["ok"]["other"]) if outcome == "ok" else _help_line(member, hazard_type, lg, place_kind)))
    turns.append({"kind": "dtmf", "speaker": "line", "name": "Keypad", "digit": digit,
                  "text": f"{first} pressed {digit}"})
    turns.append(p(P["thanks_ok"] if outcome == "ok" else P["thanks_help"]))
    turns.append(n(L["bye_ok"] if outcome == "ok" else L["bye_help"]))
    return {"member_id": member.id, "episode_id": episode.id if episode else None, "language": lg,
            "outcome": outcome, "script_source": source, "hard_of_hearing": hard_of_hearing,
            "voices": {"porchlight": porch, "neighbor": neigh}, "turns": turns}


# ------------------------------------------------------------------ audio

@lru_cache(maxsize=1)
def _polly():
    import boto3

    return boto3.client("polly", region_name=settings.AWS_REGION)


def synth_pcm(text: str, voice: str, rate: str = "100%") -> bytes:
    """Polly neural speech as 16 kHz signed 16-bit little-endian mono PCM."""
    ssml = f'<speak><prosody rate="{rate}">{escape(text)}</prosody></speak>'
    r = _polly().synthesize_speech(Text=ssml, TextType="ssml", OutputFormat="pcm", SampleRate=str(RATE),
                                   VoiceId=voice, Engine="neural")
    return r["AudioStream"].read()


def _pcm(raw: bytes) -> array:
    a = array("h")
    a.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder != "little":
        a.byteswap()
    return a


def _silence(seconds: float) -> array:
    return array("h", bytes(2 * int(RATE * seconds)))


def _tone(freqs: tuple[float, ...], seconds: float, level: float) -> array:
    n = int(RATE * seconds)
    fade = int(RATE * 0.01)
    out = array("h", bytes(2 * n))
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        v = sum(math.sin(2 * math.pi * f * i / RATE) for f in freqs) / len(freqs)
        out[i] = int(v * level * env * 32767)
    return out


DTMF = {"1": (697, 1209), "2": (697, 1336)}


def _render(convo: dict[str, Any], out: Path) -> dict[str, Any]:
    audio = array("h")
    prev = None
    for t in convo["turns"]:
        if audio:
            audio.extend(_silence(0.25 if t["speaker"] == prev else 0.5))
        t["start"] = round(len(audio) / RATE, 2)
        if t["kind"] == "ring":
            for _ in range(2):
                audio.extend(_tone((440, 480), 1.2, 0.18))
                audio.extend(_silence(0.9))
        elif t["kind"] == "dtmf":
            audio.extend(_tone(DTMF[t["digit"]], 0.22, 0.3))
        else:
            audio.extend(_pcm(synth_pcm(t["text"], t["voice"], t["rate"])))
        t["end"] = round(len(audio) / RATE, 2)
        prev = t["speaker"]
    audio.extend(_silence(0.4))

    data = audio if sys.byteorder == "little" else array("h", audio)
    if sys.byteorder != "little":
        data.byteswap()
    tmp = out.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    tmp.replace(out)
    convo["duration_s"] = round(len(audio) / RATE, 1)
    return convo


def simulate(member: Member, episode: Episode | None, outcome: str = "auto", call_script: str = "") -> dict[str, Any]:
    convo = build_conversation(member, episode, outcome, call_script)
    key_src = json.dumps({"v": FORMAT_VERSION, "turns": convo["turns"]}, sort_keys=True, ensure_ascii=False)
    sim_id = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:20]
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    wav, meta = SIM_DIR / f"{sim_id}.wav", SIM_DIR / f"{sim_id}.json"
    if wav.exists() and meta.exists():
        result = json.loads(meta.read_text())
        result["cached"] = True
    else:
        result = _render(convo, wav)
        result["id"] = sim_id
        meta.write_text(json.dumps(result, ensure_ascii=False))
        result["cached"] = False
    result["url"] = f"/api/voice/sim/{sim_id}.wav"
    return result


def audio_path(sim_id: str) -> Path | None:
    if not SIM_ID.match(sim_id):
        return None
    path = SIM_DIR / f"{sim_id}.wav"
    return path if path.exists() else None
