import { useState } from 'react';
import { Zap, PlugZap } from 'lucide-react';
import { api, usePoll } from '../lib/api.js';

const BAR_MAX_H = 12; // hours that fill the bar

function BackupBar({ hours }) {
  const h = Number(hours) || 0;
  const pct = Math.min(h / BAR_MAX_H, 1) * 100;
  const cls = h < 4 ? 'low' : h < 8 ? 'mid' : 'ok';
  return (
    <div className="backup" title={`${h} hours of backup power`}>
      <div className={`backup-bar ${cls}`}><span style={{ width: `${pct}%` }} /></div>
      <span className={`backup-h mono ${cls}`}>{h === 0 ? 'no backup' : `${h}h`}</span>
    </div>
  );
}

export default function PowerPanel({ onEpisode }) {
  const [data, refresh] = usePoll(api.electricityDependent, 60000);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ utility: 'APS', utility_other: '', area: '', description: '', estimated_restoration: '' });

  const members = data?.members || [];

  const submit = async () => {
    setBusy(true);
    try {
      const utility = form.utility === 'other' ? (form.utility_other.trim() || 'Utility') : form.utility;
      const body = {
        utility,
        area: form.area,
        description: form.description,
        estimated_restoration_iso: form.estimated_restoration ? new Date(form.estimated_restoration).toISOString() : '',
      };
      const r = await api.reportOutage(body);
      if (r?.episode) onEpisode(r.episode.id);
      setShowForm(false);
      refresh();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-h">
        <Zap size={15} />
        <h3>Electricity-dependent neighbors</h3>
        <div className="right">
          {data ? <span className={`pill small ${data.under_4h ? 'red' : ''}`}>{data.under_4h} under 4h backup</span> : null}
        </div>
      </div>
      <div className="panel-b">
        {!data ? <div className="small muted">Loading…</div> : null}
        {data && members.length === 0 ? <div className="small muted">No one on the roster has a powered medical device recorded. Add devices on the Roster page.</div> : null}
        {members.map((m) => (
          <div className="power-row" key={m.member_id}>
            <div className="power-main">
              <div className="t">{m.name}{m.utility ? <span className="pill small" style={{ marginLeft: 6 }}>{m.utility}</span> : null}</div>
              <div className="d">{m.device_labels?.length ? m.device_labels.join(', ') : 'powered medical device (details not recorded)'}</div>
              {m.backup_plan ? <div className="d muted">{m.backup_plan}</div> : null}
            </div>
            <BackupBar hours={m.backup_power_hours} />
          </div>
        ))}
        <div className="small muted" style={{ marginTop: 8 }}>Sorted by least backup runtime. Under 4 hours means someone needs to go in person when the power fails.</div>
      </div>
      <div className="panel-b">
        <div className="row">
          <div className="eyebrow">Report an outage</div>
          <div style={{ marginLeft: 'auto' }}><button className="btn ghost sm" onClick={() => setShowForm((s) => !s)}>{showForm ? 'Hide' : 'Open'}</button></div>
        </div>
        {showForm ? (
          <div className="stack" style={{ marginTop: 8 }}>
            <div className="small muted">Opens an outage episode. If a heat or cold episode is already active, the agents are told it is a compound hazard and treat every neighbor above as life-threatening priority.</div>
            <div className="row">
              <select value={form.utility} onChange={(e) => setForm({ ...form, utility: e.target.value })} style={{ width: 'auto', flex: 1 }}>
                <option value="APS">APS</option>
                <option value="SRP">SRP</option>
                <option value="other">Other utility</option>
              </select>
              {form.utility === 'other' ? <input type="text" placeholder="Utility name" value={form.utility_other} onChange={(e) => setForm({ ...form, utility_other: e.target.value })} style={{ flex: 1 }} /> : null}
            </div>
            <input type="text" placeholder="Area affected (zip codes, streets, or 'whole neighborhood')" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} />
            <textarea placeholder="What the utility or neighbors are reporting" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <label className="small muted" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              Estimated restoration (optional)
              <input type="datetime-local" value={form.estimated_restoration} onChange={(e) => setForm({ ...form, estimated_restoration: e.target.value })} />
            </label>
            <button className="btn primary sm" disabled={busy} onClick={submit} style={{ alignSelf: 'flex-start' }}>
              <PlugZap size={13} /> {busy ? 'Starting agents…' : 'Report outage to the agents'}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
