import { useState } from 'react';
import { Radar, RotateCw } from 'lucide-react';
import { api, usePoll } from '../lib/api.js';
import HazardPill from './HazardPill.jsx';

function Reading({ v, l, unit, hot, warn }) {
  return (
    <div className={`reading ${hot ? 'hot' : warn ? 'warn' : ''}`}>
      <div className="v">
        {v == null ? '—' : Math.round(v)}
        <span style={{ fontSize: 12, fontWeight: 400 }}>{unit}</span>
      </div>
      <div className="l">{l}</div>
    </div>
  );
}

/** Shared runner: calls an endpoint, then opens whatever episode it created. */
function useRunner(onEpisode, after) {
  const [busy, setBusy] = useState('');
  const run = async (label, fn) => {
    setBusy(label);
    try {
      const r = await fn();
      if (r?.episode) onEpisode?.(r.episode.id);
      else if (r?.new_episodes?.length) onEpisode?.(r.new_episodes[0].id);
      else if (r?.new_episodes) alert('No new hazards right now. Everything active for this area already has an episode.');
      after?.();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy('');
    }
  };
  return [busy, run];
}

/** Live conditions and the official alerts the sentinel is watching. */
export default function SentinelPanel({ onEpisode, health, refreshHealth }) {
  const [live, refreshLive] = usePoll(api.live, 120000);
  const [busy, run] = useRunner(onEpisode, () => { refreshHealth?.(); refreshLive(); });

  const wx = live?.weather || {};
  const aq = live?.air_quality || {};
  const th = live?.thresholds || {};
  const alerts = live?.alerts || [];
  const thresholdHazards = live?.threshold_hazards || [];

  return (
    <section className="panel">
      <div className="panel-h">
        <Radar size={15} />
        <h3>Conditions right now</h3>
        <div className="right">
          <button className="btn ghost sm" onClick={refreshLive} title="Refresh readings" aria-label="Refresh readings">
            <RotateCw size={13} />
          </button>
        </div>
      </div>

      <div className="panel-b">
        <div className="readings">
          <Reading v={wx.temp_f} unit="°F" l="Air temp" hot={wx.temp_f >= th.heat_index_f} />
          <Reading
            v={wx.feels_like_f} unit="°F" l="Feels like"
            hot={wx.feels_like_f >= th.heat_index_f}
            warn={wx.feels_like_f >= th.heat_index_f - 5}
          />
          <Reading v={aq.us_aqi} unit="" l={`Air quality · ${aq.label || '—'}`} hot={aq.us_aqi >= th.aqi} warn={aq.us_aqi > 100} />
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>
          Live readings at the roster{wx.today_max_f ? `, today's high ${Math.round(wx.today_max_f)}°F` : ''}.
          The agents wake at feels-like {th.heat_index_f}°F, air quality {th.aqi}, or {th.cold_f}°F.
        </div>
      </div>

      <div className="panel-b">
        <div className="eyebrow" style={{ marginBottom: 6 }}>Official alerts here</div>
        {!live ? <div className="muted small">Loading…</div> : null}
        {live && alerts.length === 0 && thresholdHazards.length === 0 ? (
          <div className="muted small">Nothing active from the National Weather Service for this area.</div>
        ) : null}

        {alerts.map((a, i) => (
          <div className="alert-row" key={a.external_id || i}>
            <span className={`sev ${a.severity}`} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="t">{a.event_name}{a.error ? ` (${a.error})` : ''}</div>
              <div className="d">{a.headline}</div>
              <div className="row" style={{ marginTop: 4 }}>
                {a.severity ? <span className="pill small">{a.severity}</span> : null}
                {a.seen
                  ? <span className="pill green small">handled</span>
                  : <span className="pill amber small">not yet handled</span>}
              </div>
            </div>
          </div>
        ))}

        {thresholdHazards.map((h, i) => (
          <div className="alert-row" key={h.external_id || `t${i}`}>
            <span className="sev Severe" />
            <div>
              <div className="t">{h.event_name}</div>
              <div className="d">{h.headline} · from live readings, no official alert needed</div>
            </div>
          </div>
        ))}

        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary sm" disabled={!!busy} onClick={() => run('scan', api.scan)}>
            <RotateCw size={13} /> {busy === 'scan' ? 'Checking…' : 'Check now'}
          </button>
          <span className="small muted">Checks itself every {health?.sentinel_interval_minutes || 15} min</span>
        </div>
      </div>
    </section>
  );
}

/** The archived-alert replay list, usable on its own inside a collapsible section. */
SentinelPanel.Replay = function Replay({ onEpisode }) {
  const [fixtures] = usePoll(api.fixtures, 600000);
  const [busy, run] = useRunner(onEpisode);
  const list = fixtures?.fixtures || [];
  return (
    <div className="stack">
      <div className="small muted">
        Real archived National Weather Service alerts. Replaying one runs the identical pipeline and marks the
        episode as a replay. Use these when the sky won't cooperate.
      </div>
      {list.length === 0 ? <div className="small muted">No archived alerts found.</div> : null}
      {list.map((f) => (
        <div key={f.id} className="fixture-row">
          <HazardPill type={f.hazard_type} />
          <div className="fx">
            <div className="t">{f.event}</div>
            <div className="d">{[f.place, f.date].filter(Boolean).join(' · ')}</div>
          </div>
          <button className="btn amber sm" disabled={!!busy} onClick={() => run(f.id, () => api.replay(f.id))} title={f.headline}>
            {busy === f.id ? 'Starting…' : 'Replay'}
          </button>
        </div>
      ))}
    </div>
  );
};

/** Coordinator-reported hazards, for anything no feed publishes. */
SentinelPanel.Manual = function Manual({ onEpisode }) {
  const [busy, run] = useRunner(onEpisode);
  const [form, setForm] = useState({
    event_name: '',
    hazard_type: 'outage',
    description: '',
  });
  const ready = form.event_name.trim().length > 3;
  return (
    <div className="stack">
      <div className="small muted">
        For what no feed reports: a power cut, a water main break, a building evacuation. The agents treat it
        exactly like an official alert.
      </div>
      <label className="field">
        <span>What happened</span>
        <input
          type="text" value={form.event_name} placeholder="e.g. Power outage on 51st Avenue"
          onChange={(e) => setForm({ ...form, event_name: e.target.value })}
        />
      </label>
      <label className="field">
        <span>Kind of hazard</span>
        <select value={form.hazard_type} onChange={(e) => setForm({ ...form, hazard_type: e.target.value })}>
          {['outage', 'heat', 'cold', 'air_quality', 'storm', 'flood', 'winter', 'other'].map((t) => (
            <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>What the agents should know</span>
        <textarea
          value={form.description} placeholder="Who is affected, how long it is expected to last, anything unusual"
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </label>
      <button className="btn primary sm" disabled={!!busy || !ready} onClick={() => run('manual', () => api.manual(form))}>
        {busy === 'manual' ? 'Starting the agents…' : 'Send to the agents'}
      </button>
    </div>
  );
};
