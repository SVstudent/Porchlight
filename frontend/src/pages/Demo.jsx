import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, XCircle, Smartphone, Play, RotateCcw, Gauge, Columns3, ExternalLink } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import HazardPill from '../components/HazardPill.jsx';
import { api, usePoll } from '../lib/api.js';

/**
 * Presenter view. Every control here calls the same API the coordinator's desk calls.
 * Nothing on this page fabricates agent output; it only makes the real thing easy to trigger and watch.
 */
export default function Demo() {
  const nav = useNavigate();
  const [health, refreshHealth] = usePoll(api.health, 30000);
  const [readiness, refreshReadiness] = usePoll(api.readiness, 20000);
  const [fixtures] = usePoll(api.fixtures, 600000);
  const [pacing, setPacing] = useState(null);
  const [checkin, setCheckin] = useState(null);
  const [busy, setBusy] = useState('');
  const [phoneKey, setPhoneKey] = useState(0);

  useEffect(() => { api.pacing().then(setPacing).catch(() => {}); }, []);

  const loadCheckin = useCallback(() => {
    api.latestCheckin().then(setCheckin).catch(() => setCheckin(null));
  }, []);
  useEffect(() => {
    loadCheckin();
    const t = setInterval(loadCheckin, 5000);
    return () => clearInterval(t);
  }, [loadCheckin]);

  const run = async (key, fn, then) => {
    setBusy(key);
    try {
      const r = await fn();
      refreshReadiness();
      then && then(r);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy('');
    }
  };

  const savePacing = (patch) => {
    setPacing((p) => ({ ...p, ...patch }));
    api.setPacing(patch).then(setPacing).catch(() => {});
  };

  const checks = readiness?.checks || [];
  const blocking = checks.filter((c) => !c.ok && ['model', 'model_reachable', 'roster', 'public_url_serves'].includes(c.id));
  const unmet = checks.filter((c) => !c.ok);

  return (
    <div className="shell">
      <TopBar health={health} connected refreshHealth={refreshHealth} />
      <main className="wide demo-page">
        <div className="demo-intro">
          <h1>Presenter view</h1>
          <p>
            Every button here calls the same API the coordinator's desk calls. It exists so a five-minute
            recording does not require hunting through logs.
          </p>
        </div>

        <div className="demo-grid">
          {/* ---------------- readiness ---------------- */}
          <section className="panel">
            <div className="panel-h">
              <Gauge size={15} />
              <h3>Before you hit record</h3>
              <div className="right">
                <span className={`pill ${blocking.length ? 'red' : unmet.length ? 'warn' : 'green'}`}>
                  {blocking.length
                    ? `${blocking.length} blocker${blocking.length === 1 ? '' : 's'}`
                    : unmet.length
                      ? `${unmet.length} still to do`
                      : 'All set'}
                </span>
              </div>
            </div>
            <div className="panel-b">
              {blocking.length === 0 && unmet.length > 0 ? (
                <p className="small muted" style={{ marginTop: 0 }}>
                  The agents will run, but the items below are what stand between this and a real send.
                </p>
              ) : null}
              <ul className="checklist">
                {checks.map((c) => (
                  <li key={c.id} className={c.ok ? 'ok' : 'no'}>
                    {c.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                    <div>
                      <div className="l">{c.label}</div>
                      <div className="d">{c.detail}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* ---------------- run a hazard ---------------- */}
          <section className="panel">
            <div className="panel-h"><Play size={15} /><h3>Run a hazard</h3></div>
            <div className="panel-b">
              <p className="small muted" style={{ marginTop: 0 }}>
                Each of these is a real National Weather Service alert, saved with its source URL. Replaying one
                runs the identical pipeline and labels the episode as a replay.
              </p>
              <div className="fixture-list">
                {(fixtures?.fixtures || []).map((f) => (
                  <div className="fixture-row" key={f.id}>
                    <HazardPill type={f.hazard_type} />
                    <div className="fx">
                      <div className="t">{f.event}</div>
                      <div className="d">{f.place} · {f.date}</div>
                    </div>
                    <button
                      className="btn amber sm"
                      disabled={!!busy}
                      onClick={() => run(f.id, () => api.replay(f.id), (r) => nav(`/episodes/${r.episode.id}`))}
                    >
                      {busy === f.id ? 'Starting…' : 'Run'}
                    </button>
                  </div>
                ))}
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn sm" disabled={!!busy} onClick={() => run('scan', api.scan, (r) => {
                  if (r.new_episodes?.length) nav(`/episodes/${r.new_episodes[0].id}`);
                  else alert('No new hazards right now. The sentinel already handled everything active for this area.');
                })}>
                  {busy === 'scan' ? 'Scanning…' : 'Scan live weather now'}
                </button>
                <button className="btn ghost sm" disabled={!!busy} onClick={() => {
                  if (confirm('Clear all episodes, approvals and check-ins? The roster, volunteers and resources stay.')) {
                    run('reset', api.reset, () => { setCheckin(null); nav('/'); });
                  }
                }}>
                  <RotateCcw size={13} /> Clear episodes
                </button>
              </div>
            </div>
          </section>

          {/* ---------------- pacing ---------------- */}
          <section className="panel">
            <div className="panel-h"><Gauge size={15} /><h3>Pacing</h3></div>
            <div className="panel-b">
              {pacing ? (
                <>
                  <label className="field">
                    <span>Wait for a reply before escalating</span>
                    <div className="row">
                      <input type="number" min="0" max="240" value={pacing.followup_grace_minutes}
                             onChange={(e) => savePacing({ followup_grace_minutes: Number(e.target.value) })} />
                      <span className="small muted">minutes</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>Check for replies every</span>
                    <div className="row">
                      <input type="number" min="1" max="60" value={pacing.followup_interval_minutes}
                             onChange={(e) => savePacing({ followup_interval_minutes: Number(e.target.value) })} />
                      <span className="small muted">minutes</span>
                    </div>
                  </label>
                  <p className="small muted">
                    A real deployment waits {pacing.defaults?.followup_grace_minutes} minutes before treating silence as a
                    problem. Shorten it here so the escalation happens while the camera is running. This changes the
                    agent's actual behaviour, not a display value.
                  </p>
                </>
              ) : <div className="small muted">Loading…</div>}
            </div>
          </section>

          {/* ---------------- phone preview ---------------- */}
          <section className="panel demo-phone-panel">
            <div className="panel-h">
              <Smartphone size={15} />
              <h3>What the neighbor sees</h3>
              <div className="right">
                {checkin?.path ? (
                  <>
                    <button className="btn ghost sm" onClick={() => setPhoneKey((k) => k + 1)}>Reload</button>
                    <a className="btn ghost sm" href={checkin.path} target="_blank" rel="noreferrer">
                      <ExternalLink size={13} /> Open
                    </a>
                  </>
                ) : null}
              </div>
            </div>
            <div className="panel-b">
              {checkin?.path ? (
                <>
                  <div className="small muted" style={{ marginBottom: 8 }}>
                    Most recent message: <b>{checkin.member}</b> via {checkin.channel}. This is the real page, at the
                    real link. Tapping a button here records a real check-in.
                  </div>
                  <div className="phone">
                    <iframe key={phoneKey} src={checkin.path} title={`Check-in page for ${checkin.member}`} />
                  </div>
                  {checkin.pending?.length > 1 ? (
                    <div className="row" style={{ marginTop: 8 }}>
                      <span className="small muted">Others waiting:</span>
                      {checkin.pending.slice(1, 5).map((p) => (
                        <a key={p.token} className="btn ghost sm" href={p.path} target="_blank" rel="noreferrer">{p.member}</a>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="empty small">
                  No messages have gone out yet. Run a hazard and approve the outreach, then the neighbor's page
                  appears here.
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="row" style={{ marginTop: 4 }}>
          <button className="btn primary" onClick={() => nav('/compare')}>
            <Columns3 size={15} /> Same roster, every hazard
          </button>
          <span className="small muted">
            {readiness?.hazard_types_shown?.length
              ? `${readiness.hazard_types_shown.length} hazard type(s) run so far: ${readiness.hazard_types_shown.join(', ')}`
              : 'Run two or three hazards first, then this view compares them.'}
          </span>
        </div>
      </main>
    </div>
  );
}
