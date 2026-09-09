import { useEffect, useRef, useState } from 'react';
import { Activity } from 'lucide-react';
import { clock } from '../lib/api.js';

const HIDE = new Set(['delta']);

function Body({ ev }) {
  const d = ev.data || {};
  if (ev.type === 'tool_call') {
    return (
      <>
        <code>{d.tool}</code>
        {d.input && Object.keys(d.input).length ? <details><summary>arguments</summary><pre>{JSON.stringify(d.input, null, 1)}</pre></details> : null}
      </>
    );
  }
  if (ev.type === 'tool_result') {
    return (
      <>
        <code>{d.tool}</code> {d.status === 'error' ? <span style={{ color: 'var(--red)' }}>error</span> : 'returned'}
        {ev.text ? <details><summary>result</summary><pre>{ev.text}</pre></details> : null}
      </>
    );
  }
  return <span>{ev.text}</span>;
}

export default function ActivityFeed({ events, episodeId }) {
  const ref = useRef(null);
  const [stick, setStick] = useState(true);
  const list = events.filter((e) => !HIDE.has(e.type) && (!episodeId || !e.episode_id || e.episode_id === episodeId));
  useEffect(() => {
    if (stick && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [list.length, stick]);
  return (
    <section className="panel col-right">
      <div className="panel-h">
        <Activity size={15} />
        <h3>Agent activity</h3>
        <div className="right">
          <label className="check small"><input type="checkbox" checked={stick} onChange={(e) => setStick(e.target.checked)} /> follow</label>
        </div>
      </div>
      <div className="feed" ref={ref} onScroll={(e) => { const el = e.target; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 30); }}>
        {list.length === 0 ? <div className="empty small">Waiting for the agents to start.</div> : null}
        {list.map((ev) => (
          <div className={`ev ${ev.type}`} key={ev.id}>
            <span className="ts">{clock(ev.ts)}</span>
            <div className="body">
              {ev.agent ? <span className={`ag ${ev.agent}`}>{ev.agent}</span> : null}
              <Body ev={ev} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
