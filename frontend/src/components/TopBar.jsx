import { NavLink, Link } from 'react-router-dom';
import SettingsMenu from './SettingsMenu.jsx';
import { timeAgo } from '../lib/api.js';

function modelLabel(id = '') {
  if (id.startsWith('bedrock:')) return `Bedrock · ${id.split(':').slice(1).join(':').split('.').pop()}`;
  if (id.startsWith('anthropic:')) return `Anthropic · ${id.split(':')[1]}`;
  return id;
}

export default function TopBar({ health, connected, refreshHealth }) {
  const sentinelOn = health?.sentinel_enabled;
  return (
    <header className="topbar">
      <Link to="/" className="wordmark">
        <span className="lamp" aria-hidden="true" />
        <span>
          <div className="name">Porchlight</div>
          <div className="community">{health?.community || 'Neighbor check-in agent'}</div>
        </span>
      </Link>
      <nav>
        <NavLink to="/" end>Watch</NavLink>
        <NavLink to="/episodes">Episodes</NavLink>
        <NavLink to="/roster">Roster</NavLink>
        <NavLink to="/compare">Compare</NavLink>
        <NavLink to="/demo">Present</NavLink>
      </nav>
      <span className="spacer" />
      <span className={`pill ${sentinelOn ? 'live' : 'off'}`} title="Deterministic hazard scan of National Weather Service alerts and live conditions">
        <span className="dot" />
        {sentinelOn
          ? `Watching · scanned ${health?.last_scan_at ? timeAgo(health.last_scan_at) : 'not yet'}`
          : 'Watching paused'}
      </span>
      <span className={`pill ${connected ? 'live' : 'off'}`} title="Live event stream from the Strands agents">
        <span className="dot" />
        {connected ? 'Agent feed live' : 'Reconnecting…'}
      </span>
      {health?.models?.length ? (
        <span className="pill mono small" title={`Model fallback order: ${health.models.join(' → ')}`}>
          {modelLabel(health.models[0])}
        </span>
      ) : (
        <span className="pill red small" title="No model provider is configured in backend/.env">No model</span>
      )}
      {/* The feeds are live whatever the send mode is: real alerts, real conditions, real routing. The
          tooltip carries whether outbound messages are actually leaving, which is a separate question. */}
      <span
        className="pill live"
        title={health?.send_mode === 'live'
          ? 'Live National Weather Service alerts, live conditions, live routing. Outbound messages are really being sent.'
          : 'Live National Weather Service alerts, live conditions, live routing. Outbound messages are written to the activity feed rather than sent.'}
      >
        <span className="dot" />
        Live ingestion
      </span>
      <SettingsMenu health={health} refreshHealth={refreshHealth} />
    </header>
  );
}
