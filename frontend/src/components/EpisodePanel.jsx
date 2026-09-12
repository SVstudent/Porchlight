import { Flame, Users, MapPin, FileText, ClipboardList, RefreshCw, Archive } from 'lucide-react';
import { Link } from 'react-router-dom';
import ApprovalCard from './ApprovalCard.jsx';
import RosterStatus from './RosterStatus.jsx';
import MapView from './MapView.jsx';
import DeploymentCards from './DeploymentCards.jsx';
import { api, clock, timeAgo } from '../lib/api.js';
import HazardPill from './HazardPill.jsx';

const STEPS = [
  { id: 'assess', n: 'Sentinel', s: 'Assess' },
  { id: 'triage', n: 'Triage', s: 'Rank neighbors' },
  { id: 'outreach', n: 'Outreach', s: 'Draft & send' },
  { id: 'logistics', n: 'Logistics', s: 'Volunteers' },
  { id: 'brief', n: 'Briefing', s: 'Coordinator' },
  { id: 'monitor', n: 'Follow-up', s: 'Check-ins' },
];

function stepState(ep, id) {
  const st = ep.status;
  const has = { assess: !!ep.assessment, triage: !!ep.triage, outreach: !!ep.outreach, logistics: !!ep.logistics, brief: !!ep.stats?.brief, monitor: ['monitoring', 'escalating', 'closed'].includes(st) };
  const pending = (ep.approvals || []).filter((a) => a.status === 'pending');
  if (has[id]) return 'done';
  if (st === 'stood_down' || st === 'failed') return '';
  if (pending.length) {
    const agents = pending.map((a) => a.agent_name);
    if ((id === 'outreach' && agents.includes('outreach')) || (id === 'logistics' && agents.includes('logistics')) || (id === 'monitor' && agents.includes('followup'))) return 'waiting';
  }
  if (id === 'assess' && st === 'assessing') return 'active';
  if (id === 'triage' && st === 'triaging' && !ep.triage) return 'active';
  if ((id === 'outreach' || id === 'logistics') && ep.triage && !has[id] && ['triaging', 'dispatching', 'awaiting_approval'].includes(st)) return 'active';
  if (id === 'brief' && ep.outreach && !has.brief && st !== 'monitoring') return 'active';
  if (id === 'monitor' && ['monitoring', 'escalating'].includes(st)) return 'active';
  return '';
}

const STATUS_PILL = { assessing: 'blue', triaging: 'blue', awaiting_approval: 'amber', dispatching: 'blue', monitoring: 'green', escalating: 'red', closed: '', stood_down: '', failed: 'red' };

export default function EpisodePanel({ episode, members, volunteers, resources, refresh, deployments = [] }) {
  if (!episode) {
    return (
      <section className="panel">
        <div className="empty">
          <div className="big">The porch light is on. Nothing needs you right now.</div>
          <div>The sentinel checks official alerts and live conditions on a schedule. When something threatens a neighbor, the agents will triage, draft outreach, and ask you before anything goes out.</div>
        </div>
      </section>
    );
  }
  const ep = episode;
  const h = ep.hazard;
  const a = ep.assessment;
  const pending = (ep.approvals || []).filter((x) => x.status === 'pending');
  const ck = ep.checkins || [];
  const n = { sent: ck.length, ok: ck.filter((c) => c.status === 'ok').length, help: ck.filter((c) => c.status === 'needs_help' || c.status === 'escalated').length, waiting: ck.filter((c) => c.status === 'sent' || c.status === 'delivered').length };
  const vById = Object.fromEntries((volunteers || []).map((v) => [v.id, v]));
  const mById = Object.fromEntries((members || []).map((m) => [m.id, m]));

  return (
    <>
      <section className={`panel hazard-card ${ep.status} hz-card-${h.hazard_type || 'other'}`}>
        <div className="panel-b">
          <div className="hazard-meta">
            <span className={`pill ${STATUS_PILL[ep.status] || ''}`}>{ep.status.replace('_', ' ')}{ep.busy ? ' · agents working' : ''}</span>
            <HazardPill type={h.hazard_type} />
            <span className="pill small">{h.source === 'replay' ? 'replay of a real NWS alert' : h.source === 'nws' ? 'live NWS alert' : h.source}</span>
            {h.severity ? <span className="pill small">{h.severity}</span> : null}
            <span className="small muted">opened {timeAgo(ep.created_at)}</span>
            <span style={{ flex: 1 }} />
            {ep.status === 'failed' ? (
              <button className="btn amber sm" disabled={ep.busy}
                      onClick={() => api.retryEpisode(ep.id).then(refresh).catch((e) => alert(e.message))}>
                <RefreshCw size={13} /> Try again
              </button>
            ) : null}
            {['monitoring', 'escalating'].includes(ep.status) ? <button className="btn sm" onClick={() => api.followup(ep.id).then(refresh)} disabled={ep.busy}><RefreshCw size={13} /> Run follow-up now</button> : null}
            {['monitoring', 'escalating', 'closed'].includes(ep.status) ? <Link className="btn sm" to={`/episodes/${ep.id}/report`} title="Numbers for funders and emergency management"><FileText size={13} /> After-action report</Link> : null}
            {!['closed', 'stood_down', 'failed'].includes(ep.status) ? <button className="btn ghost sm" onClick={() => api.close(ep.id).then(refresh)}><Archive size={13} /> Close</button> : null}
          </div>
          <h2 style={{ marginTop: 8 }}>{h.event_name}</h2>
          <div className="small muted">{h.headline}</div>
          {a ? <p className="summary">{a.plain_summary}</p>
            : ep.status === 'failed'
              ? <p className="summary" style={{ color: 'var(--red)' }}>
                  The agent run could not finish. The usual cause is that the model provider was unreachable.
                  Check the model badge in the top bar, then press Try again.
                </p>
              : <p className="summary muted">The sentinel agent is reading the alert and checking live conditions…</p>}
          {a ? (
            <div className="row" style={{ marginTop: 8 }}>
              <span className={`pill ${a.activate ? 'red' : 'green'}`}>{a.activate ? `Activate · severity ${a.severity_score}/5` : 'Stand down'}</span>
              {a.elevated_risk_factors.map((r) => <span className="pill small" key={r}>{r.replace(/_/g, ' ')}</span>)}
            </div>
          ) : null}
        </div>
        <div className="stepper" style={{ borderTop: '1px solid var(--line)' }}>
          {STEPS.map((s) => <div className={`step ${stepState(ep, s.id)}`} key={s.id}><div className="n">{s.n}</div><div className="s">{s.s}</div></div>)}
        </div>
      </section>

      {pending.map((ap, i) => (
        <div key={ap.id} className={i === 0 ? 'approval-slot' : undefined}>
          <ApprovalCard approval={ap} members={members} volunteers={volunteers} onDecided={refresh} />
        </div>
      ))}

      {ck.length ? (
        <div className="kpis">
          <div className="kpi"><div className="v">{n.sent}</div><div className="l">neighbors contacted</div></div>
          <div className="kpi green"><div className="v">{n.ok}</div><div className="l">replied OK</div></div>
          <div className="kpi red"><div className="v">{n.help}</div><div className="l">need help / escalated</div></div>
          <div className="kpi warn"><div className="v">{n.waiting}</div><div className="l">no reply yet</div></div>
        </div>
      ) : null}

      <section className="panel">
        <div className="panel-h"><Users size={15} /><h3>Neighbors</h3><div className="right small muted">{ep.triage ? ep.triage.summary : 'Triage pending'}</div></div>
        <div className="panel-b">
          {/* The outreach agent writes this for the coordinator. Showing it is the difference between
              "12 messages were sent" and knowing why these twelve. */}
          {ep.outreach?.coordinator_note ? (
            <p className="agent-note">
              <span className="eyebrow">What the outreach agent wants you to know</span>
              {ep.outreach.coordinator_note}
            </p>
          ) : null}
          <RosterStatus members={members} episode={ep} />
        </div>
      </section>

      {/* The map, and directly under it the trips it is drawing. Keeping them together means a
          coordinator approves a journey while looking at the journey. */}
      <section className="panel">
        <div className="panel-h">
          <MapPin size={15} /><h3>Map</h3>
          <div className="right small muted">
            {deployments.filter((d) => d.status === 'approved').length
              ? `${deployments.filter((d) => d.status === 'approved').length} on the way`
              : 'live conditions and the roster'}
          </div>
        </div>
        <div className="panel-b" style={{ paddingBottom: 0 }}>
          <MapView members={members} resources={resources} episode={ep} deployments={deployments} />
        </div>
        <div className="map-legend">
          <span className="k"><i className="dot" style={{ background: '#c8412b' }} /> tier 1</span>
          <span className="k"><i className="dot" style={{ background: '#b8741a' }} /> tier 2 / waiting</span>
          <span className="k"><i className="dot" style={{ background: '#2f6b5a' }} /> answered</span>
          <span className="k"><i className="dot" style={{ background: '#8c1d11' }} /> no reply at all</span>
          <span className="k"><i className="sq" /> cooled buildings</span>
          <span className="k"><i className="ln" /> responder en route</span>
        </div>
        {deployments.length ? (
          <div className="panel-b" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="eyebrow" style={{ marginBottom: 8 }}>Suggested deployments</div>
            <DeploymentCards deployments={deployments} refresh={refresh} />
          </div>
        ) : null}
      </section>

      {ep.logistics ? (
        <section className="panel">
          <div className="panel-h"><ClipboardList size={15} /><h3>Volunteer assignments</h3></div>
          <div className="panel-b">
            {ep.logistics.assignments.map((x, i) => (
              <div className="assign" key={i}>
                <div><b>{vById[x.volunteer_id]?.name || x.volunteer_id}</b> → {mById[x.member_id]?.name || x.member_id}<div className="small muted">{x.task.replace(/_/g, ' ')} · {x.reason}</div></div>
                <span className={`tier t${x.priority}`}>P{x.priority}</span>
              </div>
            ))}
            {ep.logistics.gaps?.length ? <div style={{ marginTop: 8 }}><div className="eyebrow">Gaps</div><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{ep.logistics.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul></div> : null}
          </div>
        </section>
      ) : null}

      {ep.stats?.brief ? (
        <section className="panel">
          <div className="panel-h"><FileText size={15} /><h3>Coordinator brief</h3></div>
          <div className="panel-b brief">{ep.stats.brief}</div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-h"><Flame size={15} /><h3>Timeline</h3></div>
        <div className="panel-b">
          <ul className="timeline">
            {[...(ep.timeline || [])].reverse().map((t, i) => <li key={i}><span className="ts">{clock(t.ts)}</span><span>{t.text}</span></li>)}
          </ul>
        </div>
      </section>
    </>
  );
}
