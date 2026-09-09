import { useEffect, useState } from 'react';
import { api } from '../lib/api.js';

const OUTCOME_CLASS = { ok: 'green', needs_help: 'red', no_reply: 'warn', not_reached: 'red', not_contacted: '' };

/** Past-episode history for one neighbor: the same summary the triage and follow-up agents read. */
export default function MemberHistory({ member }) {
  const [hist, setHist] = useState(null);
  const [error, setError] = useState(null);
  const [lesson, setLesson] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => api.memberHistory(member.id).then((h) => { setHist(h); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [member.id]); // eslint-disable-line

  if (error) return <div className="hist small muted">Could not load history: {error}</div>;
  if (!hist) return <div className="hist small muted">Loading history…</div>;

  const rel = hist.reliability || {};
  const latest = hist.episodes?.[0];
  const saveLesson = async () => {
    if (!lesson.trim() || !latest) return;
    setSaving(true);
    try { await api.addLesson(latest.episode_id, { member_id: member.id, text: lesson.trim() }); setLesson(''); await load(); }
    catch (e) { alert(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="hist">
      <div className="hist-insight">{hist.insight}</div>
      {hist.episodes.length ? (
        <div className="row hist-pills">
          <span className="pill small">{rel.replied} of {rel.contacted} replied{rel.reply_rate != null ? ` (${Math.round(rel.reply_rate * 100)}%)` : ''}</span>
          {rel.median_minutes_to_reply != null ? <span className="pill small green">usually {rel.median_minutes_to_reply} min to reply</span> : null}
          {rel.escalations ? <span className="pill small red">escalated {rel.escalations}×</span> : null}
          {rel.visits_needed ? <span className="pill small amber">needed a visit {rel.visits_needed}×</span> : null}
        </div>
      ) : null}
      {hist.episodes.length ? (
        <table className="hist-table">
          <thead><tr><th>Date</th><th>Hazard</th><th>Tier</th><th>Channel</th><th>Outcome</th><th>Escalations</th><th>Notes</th></tr></thead>
          <tbody>
            {hist.episodes.map((e) => (
              <tr key={e.episode_id}>
                <td className="mono small">{e.date}</td>
                <td>{e.event_name}</td>
                <td>{e.tier != null ? (e.tier === 0 ? 'no action' : `Tier ${e.tier}`) : '—'}{e.needs_visit ? <span className="small muted"> · visit</span> : null}</td>
                <td className="mono small">{e.channel || '—'}</td>
                <td><span className={`pill small ${OUTCOME_CLASS[e.outcome] || ''}`}>{e.outcome_label}{e.minutes_to_reply != null ? ` in ${e.minutes_to_reply}m` : ''}</span></td>
                <td className="small">{e.escalations.length ? e.escalations.map((s, i) => <div key={i}>{s.action.replace(/_/g, ' ')}{s.detail ? <span className="muted"> — {s.detail}</span> : null}</div>) : '—'}</td>
                <td className="small">
                  {e.note && !['no_reply', 'not_contacted'].includes(e.outcome) ? <div>{e.note}</div> : null}
                  {e.lessons.map((l, i) => <div key={i} className="hist-lesson">“{l}”</div>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {hist.agentcore_memories?.length ? (
        <div className="hist-memories">
          <div className="small muted">Long-term memory (Amazon Bedrock AgentCore Memory)</div>
          <ul>{hist.agentcore_memories.map((m, i) => <li key={i} className="small">{m.text}</li>)}</ul>
        </div>
      ) : null}
      <div className="row hist-lesson-form">
        <input type="text" placeholder={latest ? `Note for next time about ${member.name.split(' ')[0]} (e.g. "her daughter Marisol answers when Rosa doesn't")` : 'Notes attach to an episode; none on record yet'}
          value={lesson} onChange={(e) => setLesson(e.target.value)} disabled={!latest || saving} onKeyDown={(e) => { if (e.key === 'Enter') saveLesson(); }} />
        <button className="btn sm" onClick={saveLesson} disabled={!latest || !lesson.trim() || saving}>Save note</button>
      </div>
    </div>
  );
}
