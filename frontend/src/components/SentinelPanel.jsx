import { useState } from 'react';
import { Radar, RotateCw, History, PlusCircle } from 'lucide-react';
import { api, usePoll, timeAgo } from '../lib/api.js';
import HazardPill from './HazardPill.jsx';

function Reading({ v, l, unit, hot, warn }) {
  return (
    <div className={`reading ${hot ? 'hot' : warn ? 'warn' : ''}`}>
      <div className="v">{v == null ? '—' : Math.round(v)}<span style={{ fontSize: 12, fontWeight: 400 }}>{unit}</span></div>
      <div className="l">{l}</div>
    </div>
  );
}

export default function SentinelPanel({ onEpisode, health, refreshHealth }) {
  const [live, refreshLive] = usePoll(api.live, 120000);
  const [fixtures] = usePoll(api.fixtures, 600000);
  const [busy, setBusy] = useState('');
  const [manual, setManual] = useState({ event_name: 'Power outage during extreme heat', hazard_type: 'outage', description: 'APS reports an outage affecting the 85031 and 85033 zip codes; restoration estimate 6+ hours. Daytime high 108 F.' });
  const [showManual, setShowManual] = useState(false);

  const wx = live?.weather || {};
  const aq = live?.air_quality || {};
  const th = live?.thresholds || {};

  const run = async (label, fn) => {
    setBusy(label);
    try {
      const r = await fn();
      if (r?.episode) onEpisode(r.episode.id);
      if (r?.new_episodes?.length) onEpisode(r.new_episodes[0].id);
      refreshHealth && refreshHealth();
      refreshLive();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <>
      <section className="panel">
        <div className="panel-h">
          <Radar size={15} />
          <h3>What the sentinel sees</h3>
          <div className="right">
            <button className="btn ghost sm" onClick={refreshLive} title="Refresh readings"><RotateCw size={13} /></button>
          </div>
        </div>
        <div className="panel-b">
          <div className="readings">
            <Reading v={wx.temp_f} unit="°F" l="Air temp" hot={wx.temp_f >= th.heat_index_f} />
            <Reading v={wx.feels_like_f} unit="°F" l="Feels like" hot={wx.feels_like_f >= th.heat_index_f} warn={wx.feels_like_f >= th.heat_index_f - 5} />
            <Reading v={aq.us_aqi} unit="" l={`AQI · ${aq.label || '—'}`} hot={aq.us_aqi >= th.aqi} warn={aq.us_aqi > 100} />
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>
            Live Open-Meteo readings near the roster{wx.today_max_f ? ` · today's high ${Math.round(wx.today_max_f)}°F` : ''}. Thresholds: feels-like ≥ {th.heat_index_f}°F, AQI ≥ {th.aqi}, air ≤ {th.cold_f}°F.
          </div>
        </div>
        <div className="panel-b">
          <div className="eyebrow" style={{ marginBottom: 6 }}>Official alerts for this area (NWS)</div>
          {!live ? <div className="muted small">Loading…</div> : null}
          {live && live.alerts?.length === 0 ? <div className="muted small">No active National Weather Service alerts for the roster's area right now.</div> : null}
          {(live?.alerts || []).map((a, i) => (
            <div className="alert-row" key={i}>
              <span className={`sev ${a.severity}`} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="t">{a.event_name}{a.error ? ` (${a.error})` : ''}</div>
                <div className="d">{a.headline}</div>
                <div className="row" style={{ marginTop: 4 }}>
                  <span className="pill small">{a.severity || 'n/a'}</span>
                  {a.seen ? <span className="pill green small">episode opened</span> : <span className="pill amber small">not yet handled</span>}
                </div>
              </div>
            </div>
          ))}
          {(live?.threshold_hazards || []).map((h, i) => (
            <div className="alert-row" key={`t${i}`}>
              <span className="sev Severe" />
              <div>
                <div className="t">{h.event_name}</div>
                <div className="d">{h.headline} · from live readings, no official alert needed</div>
              </div>
            </div>
          ))}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn primary sm" disabled={!!busy} onClick={() => run('scan', api.scan)}>
              <RotateCw size={13} /> {busy === 'scan' ? 'Scanning…' : 'Scan now'}
            </button>
            <span className="small muted">Auto every {health?.sentinel_interval_minutes || 15} min</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-h"><History size={15} /><h3>Replay a real alert</h3></div>
        <div className="panel-b stack">
          <div className="small muted">Real archived NWS alerts, any hazard, run through the identical pipeline and labelled as replays. Use when the sky won't cooperate.</div>
          {(fixtures?.fixtures || []).map((f) => (
            <div key={f.id} className="fixture-row">
              <HazardPill type={f.hazard_type} />
              <div className="fx-main">
                <div className="fx-t">{f.event}</div>
                <div className="small muted fx-d">{[f.place, f.date].filter(Boolean).join(' · ')}</div>
              </div>
              <button className="btn amber sm" disabled={!!busy} onClick={() => run(f.id, () => api.replay(f.id))} title={f.headline}>
                {busy === f.id ? 'Starting…' : 'Replay'}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-h"><PlusCircle size={15} /><h3>Report a hazard</h3>
          <div className="right"><button className="btn ghost sm" onClick={() => setShowManual((s) => !s)}>{showManual ? 'Hide' : 'Open'}</button></div>
        </div>
        {showManual ? (
          <div className="panel-b stack">
            <div className="small muted">For hazards no feed reports: a power outage, a water main break, a building evacuation.</div>
            <input type="text" value={manual.event_name} onChange={(e) => setManual({ ...manual, event_name: e.target.value })} placeholder="What happened" />
            <select value={manual.hazard_type} onChange={(e) => setManual({ ...manual, hazard_type: e.target.value })}>
              {['outage', 'heat', 'cold', 'air_quality', 'storm', 'flood', 'winter', 'other'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
            </select>
            <textarea value={manual.description} onChange={(e) => setManual({ ...manual, description: e.target.value })} placeholder="Details the agents should know" />
            <button className="btn primary sm" disabled={!!busy} onClick={() => run('manual', () => api.manual(manual))}>{busy === 'manual' ? 'Starting agents…' : 'Send to the agents'}</button>
          </div>
        ) : null}
      </section>
    </>
  );
}
