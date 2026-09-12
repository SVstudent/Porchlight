import { useRef, useState } from 'react';
import { PhoneCall } from 'lucide-react';
import { api } from '../lib/api.js';

/**
 * The check-in call Porchlight would place, as a recording you can play.
 *
 * Amazon Polly voices both sides: Porchlight speaks the same script, voice and keypad prompt the live Twilio
 * call uses, and the neighbour answers in words drawn from their own case. Nothing is dialled. The
 * transcript follows the audio, and clicking a line jumps to it.
 */
const OUTCOMES = [
  { key: 'auto', label: 'From their case', title: 'Answer the way their current state suggests' },
  { key: 'ok', label: 'Says okay', title: 'They press 1' },
  { key: 'needs_help', label: 'Needs help', title: 'They press 2' },
];

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export default function VoiceCallSim({ memberId, episodeId, callScript = '', compact = false }) {
  const [outcome, setOutcome] = useState('auto');
  const [sim, setSim] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [now, setNow] = useState(0);
  const audio = useRef(null);

  const generate = async () => {
    setBusy(true); setErr('');
    try {
      const r = await api.voiceSim({ member_id: memberId, episode_id: episodeId || null, outcome, call_script: callScript });
      setSim(r); setNow(0);
      setTimeout(() => audio.current?.play().catch(() => {}), 50);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const seek = (t) => {
    if (!audio.current) return;
    audio.current.currentTime = t.start;
    audio.current.play().catch(() => {});
  };

  return (
    <div className={`vsim ${compact ? 'compact' : ''}`}>
      <div className="vsim-bar">
        <div className="vsim-seg" role="group" aria-label="How they answer">
          {OUTCOMES.map((o) => (
            <button key={o.key} type="button" title={o.title} className={outcome === o.key ? 'on' : ''}
                    onClick={() => setOutcome(o.key)} disabled={busy}>{o.label}</button>
          ))}
        </div>
        <button type="button" className="btn primary sm" onClick={generate} disabled={busy || !memberId}>
          <PhoneCall size={13} /> {busy ? 'Generating call…' : sim ? 'Generate again' : 'Generate call'}
        </button>
      </div>
      {err ? <div className="small vsim-err">{err}</div> : null}

      {sim ? (
        <>
          <audio ref={audio} controls src={sim.url} className="vsim-audio"
                 onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} />
          <ol className="vsim-transcript">
            {sim.turns.map((t, i) => {
              const on = now >= t.start && now < (sim.turns[i + 1]?.start ?? Infinity);
              return (
                <li key={i} className={`${t.speaker} ${t.kind} ${on ? 'on' : ''}`} onClick={() => seek(t)}>
                  <span className="ts">{clock(t.start)}</span>
                  <span className="who">{t.kind === 'say' ? t.name : ''}</span>
                  <span className="line">{t.kind === 'say' ? t.text : `[ ${t.text} ]`}</span>
                </li>
              );
            })}
          </ol>
          <div className="small muted vsim-foot">
            Simulated call · {clock(sim.duration_s)} · Porchlight is Polly {sim.voices.porchlight}, the same voice the live
            call uses; {sim.turns.find((t) => t.speaker === 'neighbor')?.name} is Polly {sim.voices.neighbor}.
            {' '}Script from the {sim.script_source}. No number was dialled.
          </div>
        </>
      ) : null}
    </div>
  );
}
