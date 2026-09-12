import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft, Phone, MessageSquare, AlertTriangle, HeartHandshake, Clock, Check,
  CircleDashed, ShieldAlert, Send, History,
} from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import MapView from '../components/MapView.jsx';
import DeploymentCards from '../components/DeploymentCards.jsx';
import { api, useEventStream, usePoll, timeAgo } from '../lib/api.js';

/**
 * One neighbour's case.
 *
 * The watch answers "who is not alright". This answers "what do I do about this person", so everything
 * here is about them: what we know, what has been said, who is going, and the two things a coordinator
 * can set in motion — ask them how they are, or treat them as needing help now.
 */
const STATE = {
  critical: { label: 'No reply to any message', cls: 'critical', Icon: AlertTriangle },
  needs_help: { label: 'Asked for help', cls: 'needs', Icon: HeartHandshake },
  waiting: { label: 'Waiting on a reply', cls: 'waiting', Icon: Clock },
  ok: { label: 'Says they are okay', cls: 'ok', Icon: Check },
  not_contacted: { label: 'Not contacted yet', cls: 'idle', Icon: CircleDashed },
};

const RISK_LABEL = {
  age_75_plus: 'Over 75', lives_alone: 'Lives alone', no_air_conditioning: 'No air conditioning',
  powered_medical_device: 'Powered medical device', mobility_limited: 'Limited mobility',
  cognitive_impairment: 'Memory issues', infant_or_young_child: 'Young child at home',
  outdoor_worker: 'Works outdoors', pregnant: 'Pregnant', chronic_illness: 'Chronic illness',
  no_transport: 'No transport', limited_english: 'Limited English', unhoused: 'Unhoused',
};

export default function Neighbor() {
  const { id } = useParams();
  const [health, refreshHealth] = usePoll(api.health, 30000);
  const [res] = usePoll(api.resources, 300000);
  const [n, setN] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');

  const load = useCallback(() => {
    api.neighbor(id).then((d) => { setN(d); setErr(''); }).catch((e) => setErr(e.message));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const [, connected] = useEventStream((ev) => {
    if (!ev.member_id || ev.member_id === id) load();
  });
  useEffect(() => {
    const t = setInterval(load, connected ? 15000 : 6000);
    return () => clearInterval(t);
  }, [load, connected]);

  const run = async (key, fn) => {
    setBusy(key); setNote('');
    try {
      const r = await fn();
      if (r.already_waiting) setNote('A check-in is already out with them; waiting on a reply.');
      else if (r.sent) setNote(`Sent via ${r.channel}.`);
      else if (r.proposed) setNote('A visit has been suggested — approve it below.');
      else if (r.reason) setNote(r.reason);
      load();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy('');
    }
  };

  if (err && !n) {
    return (
      <div className="shell">
        <TopBar health={health} connected={connected} refreshHealth={refreshHealth} />
        <main className="wide"><div className="panel"><div className="panel-b">{err}</div></div></main>
      </div>
    );
  }
  if (!n) {
    return (
      <div className="shell">
        <TopBar health={health} connected={connected} refreshHealth={refreshHealth} />
        <main className="wide"><div className="panel"><div className="panel-b small muted">Loading…</div></div></main>
      </div>
    );
  }

  const s = STATE[n.state] || STATE.not_contacted;
  const { Icon } = s;
  const deployments = n.deployments || [];
  const hist = n.history || {};

  return (
    <div className="shell">
      <TopBar health={health} connected={connected} refreshHealth={refreshHealth} />
      <main className="case">
        <div className="case-main">
          <Link to="/" className="back small"><ArrowLeft size={13} /> Back to the watch</Link>

          <section className="panel">
            <div className="panel-b">
              <div className={`case-state ${s.cls}`}><Icon size={15} /> {s.label}</div>
              <h1 className="case-name">{n.name}</h1>
              <div className="small muted">{n.address}</div>

              <div className="case-risks">
                {(n.risk_factors || []).map((r) => (
                  <span className="rchip big" key={r}>{RISK_LABEL[r] || r.replace(/_/g, ' ')}</span>
                ))}
              </div>
              {n.notes ? <p className="case-notes">{n.notes}</p> : null}

              <div className="case-contact small muted">
                <span><Phone size={12} /> {n.phone || 'no phone on file'}</span>
                <span><MessageSquare size={12} /> prefers {n.preferred_channel}</span>
                {n.emergency_contact_name
                  ? <span><ShieldAlert size={12} /> {n.emergency_contact_name} · {n.emergency_contact_phone}</span>
                  : <span><ShieldAlert size={12} /> no emergency contact on file</span>}
              </div>
            </div>
          </section>

          {/* ------------ what the coordinator can set in motion ------------ */}
          <section className="panel">
            <div className="panel-h"><Send size={15} /><h3>Protocols</h3></div>
            <div className="panel-b">
              <div className="proto">
                <div>
                  <b>Check on them</b>
                  <div className="small muted">
                    Sends a check-in now and starts the reminder ladder: three messages, three minutes
                    apart, then they are flagged if nothing comes back.
                  </div>
                </div>
                <button className="btn primary sm" disabled={!!busy}
                        onClick={() => run('checkup', () => api.checkup(n.id))}>
                  {busy === 'checkup' ? 'Sending…' : 'Run check-in'}
                </button>
              </div>

              <div className="proto">
                <div>
                  <b>Treat as needing help</b>
                  <div className="small muted">
                    Skips the waiting. Marks them as needing help and works out who should go to them,
                    matched to what they need — a driver, or someone medical.
                  </div>
                </div>
                <button className="btn amber sm" disabled={!!busy}
                        onClick={() => run('escalate', () => api.escalateNeighbor(n.id))}>
                  {busy === 'escalate' ? 'Working…' : 'Escalate'}
                </button>
              </div>

              {note ? <div className="proto-note small">{note}</div> : null}
              <p className="small muted" style={{ marginBottom: 0 }}>
                Nothing leaves the system without your approval. A suggested visit appears below and on
                the map; it only starts when you approve it.
              </p>
            </div>
          </section>

          {deployments.length ? (
            <section className="panel">
              <div className="panel-h"><HeartHandshake size={15} /><h3>Response</h3></div>
              <div className="panel-b">
                <DeploymentCards deployments={deployments} refresh={load} />
              </div>
            </section>
          ) : null}

          {/* ------------ the conversation so far ------------ */}
          <section className="panel">
            <div className="panel-h"><MessageSquare size={15} /><h3>This episode</h3></div>
            <div className="panel-b">
              {n.checkin ? (
                <>
                  <div className="small">
                    Message sent {timeAgo(n.checkin.sent_at)} via {n.checkin.channel || 'console'}
                    {n.reminders_sent ? ` · ${n.reminders_sent} reminder${n.reminders_sent === 1 ? '' : 's'} since` : ''}
                  </div>
                  {n.checkin.note ? <p className="said">{n.checkin.note.replace(/^said: /, '“') + (n.checkin.note.startsWith('said: ') ? '”' : '')}</p> : null}
                  {n.checkin.responded_at
                    ? <div className="small muted">Replied {timeAgo(n.checkin.responded_at)}</div>
                    : <div className="small muted">No reply yet</div>}
                </>
              ) : (
                <div className="small muted">Nothing has been sent to them in this episode.</div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-h"><History size={15} /><h3>Before today</h3></div>
            <div className="panel-b">
              {hist.insight
                ? <p className="small" style={{ marginTop: 0 }}>{hist.insight}</p>
                : <div className="small muted">No earlier episodes on file for them.</div>}
              {(hist.episodes || []).slice(0, 4).map((e, i) => (
                <div className="hist-row small" key={i}>
                  <b>{e.event_name}</b> · tier {e.tier} · {e.outcome?.replace(/_/g, ' ') || 'no reply'}
                  {e.minutes_to_reply ? ` after ${e.minutes_to_reply} min` : ''}
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* ------------ their corner of the map ------------ */}
        <div className="case-map">
          <div className="case-map-inner">
            <MapView
              members={[n]}
              resources={res?.resources || []}
              episode={n.episode}
              deployments={deployments}
              highlight={n.id}
            />
          </div>
          <div className="map-legend">
            <span className="k"><i className="dot" style={{ background: '#c8412b' }} /> {n.name.split(' ')[0]}</span>
            <span className="k"><i className="sq" /> cooled buildings</span>
            <span className="k"><i className="ln" /> responder en route</span>
          </div>
        </div>
      </main>
    </div>
  );
}
