import { useState } from 'react';
import { Upload, UserPlus } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import { api, usePoll } from '../lib/api.js';

const RF = ['lives_alone', 'age_75_plus', 'no_air_conditioning', 'powered_medical_device', 'mobility_limited', 'cognitive_impairment', 'infant_or_young_child', 'outdoor_worker', 'pregnant', 'chronic_illness', 'no_transport', 'limited_english', 'unhoused'];
const DEVICES = ['oxygen_concentrator', 'ventilator', 'cpap', 'home_dialysis', 'powered_wheelchair', 'refrigerated_medication', 'nebulizer'];
const EMPTY = { name: '', phone: '', email: '', telegram_chat_id: '', preferred_channel: 'sms', language: 'en', address: '', lat: 33.49, lon: -112.18, risk_factors: [], notes: '', emergency_contact_name: '', emergency_contact_phone: '', opted_in: true, devices: [], backup_power_hours: 0, utility: '', backup_plan: '' };

export default function Roster() {
  const [health] = usePoll(api.health, 60000);
  const [roster, refresh] = usePoll(api.roster, 30000);
  const [vols] = usePoll(api.volunteers, 30000);
  const [res] = usePoll(api.resources, 60000);
  const [form, setForm] = useState(null);

  const save = async () => { await api.saveMember({ ...form, lat: Number(form.lat), lon: Number(form.lon), backup_power_hours: Number(form.backup_power_hours) || 0, devices: form.devices || [] }); setForm(null); refresh(); };
  const upload = async (e) => { const f = e.target.files[0]; if (!f) return; const r = await api.importRoster(f); alert(`Imported ${r.imported} members`); refresh(); };

  return (
    <div className="shell">
      <TopBar health={health} connected />
      <main className="wide">
        <section className="panel">
          <div className="panel-h"><h3>Neighbors ({roster?.members?.length || 0})</h3>
            <div className="right">
              <label className="btn sm"><Upload size={13} /> Import CSV<input type="file" accept=".csv" style={{ display: 'none' }} onChange={upload} /></label>
              <button className="btn primary sm" onClick={() => setForm({ ...EMPTY })}><UserPlus size={13} /> Add neighbor</button>
            </div>
          </div>
          <div className="panel-b" style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Name</th><th>Reach</th><th>Lang</th><th>Risk factors</th><th>Powered devices</th><th>Notes</th><th>Emergency contact</th><th></th></tr></thead>
              <tbody>
                {(roster?.members || []).map((m) => (
                  <tr key={m.id}>
                    <td><b>{m.name}</b><div className="small muted">{m.address}</div></td>
                    <td className="mono small">{m.preferred_channel}<br />{m.phone || m.email || m.telegram_chat_id}</td>
                    <td>{m.language}</td>
                    <td><div className="tags">{m.risk_factors.map((r) => <span className="tag" key={r}>{r.replace(/_/g, ' ')}</span>)}</div></td>
                    <td className="small">
                      {(m.devices || []).length ? <div className="tags">{m.devices.map((d) => <span className="tag" key={d}>{d.replace(/_/g, ' ')}</span>)}</div> : <span className="muted">—</span>}
                      {(m.devices || []).length ? <div className={`muted ${Number(m.backup_power_hours) < 4 ? 'backup-low' : ''}`}>{Number(m.backup_power_hours) > 0 ? `${m.backup_power_hours}h backup` : 'no backup power'}{m.utility ? ` · ${m.utility}` : ''}</div> : null}
                    </td>
                    <td className="small">{m.notes}</td>
                    <td className="small">{m.emergency_contact_name}<br /><span className="mono">{m.emergency_contact_phone}</span></td>
                    <td><button className="btn ghost sm" onClick={() => setForm({ ...m })}>Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="small muted" style={{ marginTop: 8 }}>CSV columns: name, phone, email, language, preferred_channel, address, lat, lon, risk_factors (semicolon-separated), notes, emergency_contact_name, emergency_contact_phone. Powered devices, backup hours, utility and backup plan are edited here after import.</div>
          </div>
        </section>

        {form ? (
          <section className="panel">
            <div className="panel-h"><h3>{form.id ? 'Edit neighbor' : 'New neighbor'}</h3></div>
            <div className="panel-b" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
              <input type="text" placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <input type="text" placeholder="Phone (+1…)" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              <input type="text" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <input type="text" placeholder="Telegram chat id" value={form.telegram_chat_id} onChange={(e) => setForm({ ...form, telegram_chat_id: e.target.value })} />
              <select value={form.preferred_channel} onChange={(e) => setForm({ ...form, preferred_channel: e.target.value })}>{['sms', 'telegram', 'email', 'voice'].map((c) => <option key={c}>{c}</option>)}</select>
              <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}><option value="en">English</option><option value="es">Español</option></select>
              <input type="text" placeholder="Address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
              <input type="number" step="0.0001" placeholder="Latitude" value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} />
              <input type="number" step="0.0001" placeholder="Longitude" value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })} />
              <input type="text" placeholder="Emergency contact name" value={form.emergency_contact_name} onChange={(e) => setForm({ ...form, emergency_contact_name: e.target.value })} />
              <input type="text" placeholder="Emergency contact phone" value={form.emergency_contact_phone} onChange={(e) => setForm({ ...form, emergency_contact_phone: e.target.value })} />
              <div style={{ gridColumn: '1 / -1' }} className="tags">
                {RF.map((r) => (
                  <label className="check" key={r} style={{ marginRight: 10 }}>
                    <input type="checkbox" checked={form.risk_factors.includes(r)} onChange={(e) => setForm({ ...form, risk_factors: e.target.checked ? [...form.risk_factors, r] : form.risk_factors.filter((x) => x !== r) })} />
                    {r.replace(/_/g, ' ')}
                  </label>
                ))}
              </div>
              <div style={{ gridColumn: '1 / -1' }} className="tags">
                <span className="eyebrow" style={{ marginRight: 8 }}>Powered devices</span>
                {DEVICES.map((d) => (
                  <label className="check" key={d} style={{ marginRight: 10 }}>
                    <input type="checkbox" checked={(form.devices || []).includes(d)} onChange={(e) => setForm({ ...form, devices: e.target.checked ? [...(form.devices || []), d] : (form.devices || []).filter((x) => x !== d) })} />
                    {d.replace(/_/g, ' ')}
                  </label>
                ))}
              </div>
              <input type="number" step="0.5" min="0" placeholder="Backup power (hours)" title="Hours of battery or backup power" value={form.backup_power_hours ?? 0} onChange={(e) => setForm({ ...form, backup_power_hours: e.target.value })} />
              <input type="text" placeholder="Utility (APS, SRP…)" value={form.utility || ''} onChange={(e) => setForm({ ...form, utility: e.target.value })} />
              <input type="text" placeholder="Backup plan when the power fails" value={form.backup_plan || ''} onChange={(e) => setForm({ ...form, backup_plan: e.target.value })} />
              <textarea style={{ gridColumn: '1 / -1' }} placeholder="Notes the agents should know (AC status, devices, who visits)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              <div className="row" style={{ gridColumn: '1 / -1' }}>
                <button className="btn primary" onClick={save} disabled={!form.name}>Save</button>
                <button className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
                {form.id ? <button className="btn ghost" style={{ marginLeft: 'auto', color: 'var(--red)' }} onClick={() => { if (confirm('Remove this neighbor?')) api.deleteMember(form.id).then(() => { setForm(null); refresh(); }); }}>Remove</button> : null}
              </div>
            </div>
          </section>
        ) : null}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <section className="panel">
            <div className="panel-h"><h3>Volunteers</h3></div>
            <div className="panel-b">
              <table><thead><tr><th>Name</th><th>Skills</th><th>Max</th></tr></thead>
                <tbody>{(vols?.volunteers || []).map((v) => <tr key={v.id}><td><b>{v.name}</b><div className="mono small muted">{v.phone}</div></td><td><div className="tags">{v.skills.map((s) => <span className="tag" key={s}>{s.replace(/_/g, ' ')}</span>)}</div></td><td>{v.max_assignments}</td></tr>)}</tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <div className="panel-h"><h3>Community resources</h3></div>
            <div className="panel-b">
              <table><thead><tr><th>Name</th><th>Kind</th><th>Hours</th></tr></thead>
                <tbody>{(res?.resources || []).map((r) => <tr key={r.id}><td><b>{r.name}</b><div className="small muted">{r.address}</div></td><td>{r.kind.replace(/_/g, ' ')}</td><td className="small">{r.hours}<div className="mono muted">{r.phone}</div></td></tr>)}</tbody>
              </table>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
