import { useState } from 'react';
import { ShieldCheck, X, Check } from 'lucide-react';
import { api } from '../lib/api.js';

const TASK_LABEL = { wellness_visit: 'Wellness visit', ride_to_cooling_center: 'Ride to cooling center', phone_call: 'Phone call', deliver_supplies: 'Deliver supplies' };

export default function ApprovalCard({ approval, members, volunteers, onDecided }) {
  const input = approval.payload?.input || {};
  const tool = approval.payload?.tool;
  const [messages, setMessages] = useState(() => (input.messages || []).map((m) => ({ ...m })));
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const byId = Object.fromEntries((members || []).map((m) => [m.id, m]));
  const vById = Object.fromEntries((volunteers || []).map((v) => [v.id, v]));

  const decide = async (decision) => {
    setBusy(true);
    try {
      const edits = {};
      if (tool === 'dispatch_outreach') {
        const changed = messages.some((m, i) => m.body !== (input.messages[i] || {}).body || (m.call_script || '') !== ((input.messages[i] || {}).call_script || ''));
        if (changed) edits.messages = messages;
      }
      await api.decide(approval.id, { decision, note, edits });
      onDecided && onDecided();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="approval">
      <div className="head">
        <ShieldCheck size={20} color="var(--amber-ink)" />
        <div style={{ flex: 1 }}>
          <h4>{approval.title}</h4>
          <div className="who">Requested by the <b>{approval.agent_name}</b> agent · paused with a Strands interrupt until you decide</div>
        </div>
      </div>
      <div className="panel-b">
        {approval.summary ? <p style={{ margin: '0 0 10px', maxWidth: '70ch' }}>{approval.summary}</p> : null}

        {tool === 'dispatch_outreach' ? (
          <div className="msg-list">
            {messages.map((m, i) => {
              const mem = byId[m.member_id];
              return (
                <div className="msg" key={i}>
                  <div className="to">
                    {mem?.name || m.member_id}
                    <span className="ch">{m.channel} · {m.language}{mem?.phone ? ` · ${mem.phone}` : ''}</span>
                    {m.channel === 'voice' ? <span className="voice-pill">phone call · Polly voice</span> : null}
                    {m.call_script && m.channel !== 'voice' ? <details><summary className="small muted">call script</summary><div className="small">{m.call_script}</div></details> : null}
                  </div>
                  <div>
                    {m.channel === 'voice' ? (
                      <div className="voice-script">
                        <div className="eyebrow">What the call will say ({m.language === 'es' ? 'Polly.Lupe' : 'Polly.Joanna'})</div>
                        <textarea value={m.call_script || ''} placeholder="Call script (falls back to the message below, links removed)" onChange={(e) => setMessages(messages.map((x, j) => (j === i ? { ...x, call_script: e.target.value } : x)))} />
                        <div className="count">then: “Press 1 if you are okay. Press 2 if you need help.”</div>
                      </div>
                    ) : null}
                    <textarea value={m.body} onChange={(e) => setMessages(messages.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)))} />
                    <div className="count">{m.body.length} chars · {m.channel === 'voice' ? 'text fallback if the call cannot be placed' : '{checkin_link} becomes a one-tap link'}</div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        {tool === 'assign_volunteers' ? (
          <div>
            {(input.assignments || []).map((a, i) => (
              <div className="assign" key={i}>
                <div>
                  <b>{vById[a.volunteer_id]?.name || a.volunteer_id}</b> → {byId[a.member_id]?.name || a.member_id}
                  <div className="small muted">{TASK_LABEL[a.task] || a.task} · {a.reason}</div>
                </div>
                <span className={`tier t${a.priority}`}>P{a.priority}</span>
              </div>
            ))}
            {(input.gaps || []).length ? (
              <div style={{ marginTop: 10 }}>
                <div className="eyebrow">Gaps for you to solve</div>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{input.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
              </div>
            ) : null}
          </div>
        ) : null}

        {tool === 'escalate_member' ? (
          <div>
            <div><b>{byId[input.member_id]?.name || input.member_id}</b> · {String(input.action || '').replace(/_/g, ' ')}{input.volunteer_id ? ` · ${vById[input.volunteer_id]?.name || input.volunteer_id}` : ''}</div>
            <div className="small muted">{input.reason}</div>
          </div>
        ) : null}
      </div>
      <div className="foot">
        <input type="text" placeholder="Optional note back to the agent (e.g. 'skip Danny, he's out of town')" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn red sm" disabled={busy} onClick={() => decide('reject')}><X size={14} /> Decline</button>
        <button className="btn green" disabled={busy} onClick={() => decide('approve')}><Check size={15} /> {busy ? 'Resuming agents…' : 'Approve & send'}</button>
      </div>
    </div>
  );
}
