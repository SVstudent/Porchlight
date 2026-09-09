import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Printer, Sparkles, ArrowLeft, RefreshCw } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import { api, usePoll } from '../lib/api.js';

const fmtDT = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const fmtT = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—');
const mins = (m) => (m == null ? 'not measured' : m < 1 ? '< 1 min' : m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`);
const pct = (p) => (p == null ? '—' : `${p}%`);
const words = (s) => (s || '').replace(/_/g, ' ');
const STATUS_LABEL = { sent: 'no reply yet', delivered: 'no reply yet', failed: 'delivery failed', ok: 'replied OK', needs_help: 'needs help', no_response: 'no response', escalated: 'escalated', not_contacted: 'not contacted' };
const STATUS_PILL = { ok: 'green', needs_help: 'red', escalated: 'red', failed: 'warn', sent: 'amber', delivered: 'amber', no_response: 'warn', not_contacted: '' };

function Counts({ obj, empty = 'none' }) {
  const e = Object.entries(obj || {});
  if (!e.length) return <span className="muted">{empty}</span>;
  return <span>{e.map(([k, v]) => `${words(k)} ${v}`).join(' · ')}</span>;
}

function Bullets({ items }) {
  if (!items?.length) return <div className="muted small">Nothing recorded.</div>;
  return <ul className="report-list">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

export default function Report() {
  const { id } = useParams();
  const [health] = usePoll(api.health, 60000);
  const [data, refresh, error] = usePoll(() => api.report(id), 30000, [id]);
  const [busy, setBusy] = useState(false);
  const [genError, setGenError] = useState('');

  const generate = async () => {
    setBusy(true); setGenError('');
    try {
      const r = await api.reportNarrative(id);
      if (!r.narrative) setGenError(r.narrative_reason || 'The narrative could not be written.');
      refresh();
    } catch (e) { setGenError(e.message); } finally { setBusy(false); }
  };

  if (error) return <div className="shell"><TopBar health={health} connected /><main className="wide"><section className="panel"><div className="empty"><div className="big">Report not available</div><div>{error}</div><Link to="/" className="btn" style={{ marginTop: 12 }}>Back to the desk</Link></div></section></main></div>;
  if (!data) return <div className="shell"><TopBar health={health} connected /><main className="wide"><div className="muted">Loading the report…</div></main></div>;

  const { episode: ep, hazard: h, metrics: m, narrative: n } = data;
  const t = m.timing, o = m.outreach, esc = m.escalations, ap = m.approvals, vol = m.volunteers;
  const rows = m.per_member || [];

  return (
    <div className="shell">
      <TopBar health={health} connected />
      <main className="wide report">
        <div className="row no-print" style={{ justifyContent: 'space-between' }}>
          <Link to={`/episodes/${ep.id}`} className="btn ghost sm"><ArrowLeft size={13} /> Back to the episode</Link>
          <div className="row">
            <button className="btn sm" onClick={refresh}><RefreshCw size={13} /> Refresh numbers</button>
            <button className="btn sm" onClick={generate} disabled={busy}><Sparkles size={13} /> {busy ? 'Writing…' : n ? 'Regenerate narrative' : 'Generate narrative'}</button>
            <button className="btn primary sm" onClick={() => window.print()}><Printer size={13} /> Print / Save as PDF</button>
          </div>
        </div>
        {genError ? <div className="report-note warn no-print">Narrative not written: {genError}. The numbers below are complete without it; a model provider is needed for the prose.</div> : null}

        <section className="panel report-sheet">
          <div className="panel-b report-head">
            <div className="eyebrow">After-action report</div>
            <h1>{h.event_name}</h1>
            <div className="report-sub">
              <span><b>{ep.community}</b> · coordinated by {ep.coordinator}</span>
              <span>{h.source === 'replay' ? 'Replay of a real NWS alert' : h.source === 'nws' ? 'Live NWS alert' : h.source === 'open-meteo' ? 'Live conditions threshold' : `${h.source} hazard`}{h.severity ? ` · ${h.severity}` : ''}{h.area ? ` · ${h.area}` : ''}</span>
              <span>Detected {fmtDT(t.detected_at)}{t.closed_at ? ` · closed ${fmtDT(t.closed_at)}` : ` · status: ${words(ep.status)}`}{t.duration_minutes != null ? ` · ${mins(t.duration_minutes)} total` : ''}</span>
              {h.headline ? <span className="muted">{h.headline}</span> : null}
              {ep.assessment?.plain_summary ? <span>{ep.assessment.plain_summary}</span> : null}
              {!ep.activated && ep.assessment ? <span className="pill">The sentinel stood down: no outreach was sent.</span> : null}
            </div>
          </div>

          <div className="report-kpis">
            <div className="kpi"><div className="v">{o.contacted}</div><div className="l">neighbors contacted</div></div>
            <div className="kpi green"><div className="v">{o.replied_ok}</div><div className="l">replied OK</div></div>
            <div className="kpi red"><div className="v">{o.needed_help}</div><div className="l">needed help</div></div>
            <div className="kpi"><div className="v">{pct(o.response_rate_pct)}</div><div className="l">response rate{o.tier1_contacted ? ` · tier 1: ${pct(o.tier1_response_rate_pct)}` : ''}</div></div>
            <div className="kpi"><div className="v">{mins(t.minutes_detection_to_first_message)}</div><div className="l">hazard detected to first message</div></div>
          </div>

          <div className="panel-b report-grid">
            <div>
              <div className="eyebrow">Outreach</div>
              <dl className="report-dl">
                <dt>Messages sent</dt><dd><Counts obj={o.sent_by_channel} /></dd>
                <dt>Delivery failed</dt><dd>{o.failed ? <Counts obj={o.failed_by_channel} empty={`${o.failed}`} /> : 'none'}</dd>
                <dt>Contacted by tier</dt><dd><Counts obj={o.contacted_by_tier} /></dd>
                <dt>Triage plan</dt><dd><Counts obj={m.roster.planned_by_tier} empty="no triage" /> ({m.roster.triaged} of {m.roster.members_opted_in} opted-in neighbors)</dd>
                <dt>Still no reply</dt><dd>{o.no_reply}</dd>
              </dl>
            </div>
            <div>
              <div className="eyebrow">Timing</div>
              <dl className="report-dl">
                <dt>Detection to assessment</dt><dd>{mins(t.minutes_detection_to_assessment)}</dd>
                <dt>Approval to first message</dt><dd>{mins(t.minutes_approval_to_first_message)}</dd>
                <dt>First reply</dt><dd>{t.first_reply_at ? `${fmtT(t.first_reply_at)} (${mins(t.minutes_detection_to_first_reply)} after detection)` : 'none yet'}</dd>
                <dt>Median time to reply</dt><dd>{mins(t.median_minutes_to_reply)}{t.max_minutes_to_reply != null ? ` (slowest ${mins(t.max_minutes_to_reply)})` : ''}</dd>
                <dt>Coordinator decisions</dt><dd>{ap.total ? `${ap.approved} approved · ${ap.declined} declined · ${ap.edited} edited${ap.pending ? ` · ${ap.pending} pending` : ''} · median ${mins(ap.median_decision_minutes)} to decide` : 'none needed'}</dd>
              </dl>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-h"><h3>Neighbors, one line each</h3><div className="right small muted">{rows.length} rows · tier 1 first</div></div>
          <div className="panel-b" style={{ overflowX: 'auto' }}>
            {rows.length ? (
              <table className="report-table">
                <thead><tr><th>Name</th><th>Tier</th><th>Channel</th><th>Sent</th><th>Status</th><th>Replied</th><th>Escalation</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.member_id}>
                      <td><b>{r.name}</b>{r.language && r.language !== 'en' ? <span className="muted small"> · {r.language}</span> : null}{r.note && r.status !== 'escalated' ? <div className="small muted">{r.note}</div> : null}</td>
                      <td>{r.tier != null ? <span className={`tier t${r.tier}`}>T{r.tier}</span> : <span className="muted">—</span>}</td>
                      <td>{r.channel || '—'}</td>
                      <td className="mono small">{fmtT(r.sent_at)}</td>
                      <td><span className={`pill small ${STATUS_PILL[r.status] || ''}`}>{STATUS_LABEL[r.status] || words(r.status)}</span></td>
                      <td className="mono small">{r.replied_at ? `${fmtT(r.replied_at)} (${mins(r.reply_minutes)})` : '—'}</td>
                      <td className="small">{r.escalation ? words(r.escalation) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="muted">No neighbors were contacted in this episode.</div>}
          </div>
        </section>

        <div className="report-cols">
          <section className="panel">
            <div className="panel-h"><h3>Escalations</h3><div className="right small muted">{esc.count} · <Counts obj={esc.by_action} /></div></div>
            <div className="panel-b">
              {esc.items.length ? esc.items.map((e, i) => (
                <div className="assign" key={i}>
                  <div><b>{e.member_name}</b> · {words(e.action)}<div className="small muted">{e.reason}</div><div className="small">{e.outcome}</div></div>
                  <span className={`pill small ${e.decision === 'declined' ? 'red' : e.decision === 'pending' ? 'amber' : 'green'}`}>{e.decision === 'policy' ? 'pre-authorised' : e.decision}{e.decision_minutes != null && e.decision !== 'policy' ? ` · ${mins(e.decision_minutes)}` : ''}</span>
                </div>
              )) : <div className="muted">No escalations were needed.</div>}
            </div>
          </section>

          <section className="panel">
            <div className="panel-h"><h3>Volunteer assignments</h3><div className="right small muted">{vol.assignments} · {vol.volunteers_used} of {vol.volunteers_available} available volunteers</div></div>
            <div className="panel-b">
              {vol.items.length ? vol.items.map((x, i) => (
                <div className="assign" key={i}>
                  <div><b>{x.volunteer_name}</b> → {x.member_name}<div className="small muted">{words(x.task)} · {x.reason}</div></div>
                  <span className={`tier t${x.priority}`}>P{x.priority}</span>
                </div>
              )) : <div className="muted">No volunteer assignments were made.</div>}
              {Object.keys(vol.by_task || {}).length ? <div className="small muted" style={{ marginTop: 8 }}>By task: <Counts obj={vol.by_task} /></div> : null}
            </div>
          </section>
        </div>

        <section className="panel">
          <div className="panel-h"><h3>Unresolved gaps</h3></div>
          <div className="panel-b report-grid">
            <div>
              <div className="eyebrow">Flagged by the logistics agent</div>
              <Bullets items={m.gaps} />
            </div>
            <div>
              <div className="eyebrow">Still open at report time</div>
              <Bullets items={[
                ...m.unresolved.no_reply.map((x) => `${x}: no reply`),
                ...m.unresolved.failed_delivery.map((x) => `${x}: message could not be delivered`),
                ...m.unresolved.not_contacted.map((x) => `${x}: triaged but never contacted`),
                ...m.unresolved.pending_approvals.map((x) => `Awaiting your decision: ${x}`),
              ]} />
            </div>
          </div>
        </section>

        {m.brief ? (
          <section className="panel">
            <div className="panel-h"><h3>Coordinator brief (written during the event)</h3></div>
            <div className="panel-b brief">{m.brief}</div>
          </section>
        ) : null}

        {n ? (
          <section className="panel report-narrative">
            <div className="panel-h"><h3>Narrative</h3><div className="right small muted">Written by the reporter agent from the numbers above · {fmtDT(data.narrative_generated_at)}</div></div>
            <div className="panel-b">
              <div className="eyebrow">Summary</div>
              <p>{n.executive_summary}</p>
              <div className="report-grid">
                <div><div className="eyebrow">What worked</div><Bullets items={n.what_worked} /></div>
                <div><div className="eyebrow">What to fix next time</div><Bullets items={n.what_to_fix} /></div>
              </div>
              <div className="eyebrow" style={{ marginTop: 10 }}>Recommendations</div>
              <Bullets items={n.recommendations} />
              <div className="eyebrow" style={{ marginTop: 10 }}>For the funder report</div>
              <p className="report-funder">{n.funder_paragraph}</p>
            </div>
          </section>
        ) : (
          <section className="panel no-print">
            <div className="panel-b muted small">No narrative yet. "Generate narrative" asks the reporter agent to write a summary, what worked, what to fix, and a funder paragraph using only the numbers on this page. It needs a configured model provider.</div>
          </section>
        )}

        <div className="small muted report-foot">Generated {fmtDT(data.generated_at)} by Porchlight · episode {ep.id} · every number comes from the episode record; the narrative, if present, paraphrases those numbers.</div>
      </main>
    </div>
  );
}
