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
        <NavLink to="/" end>Desk</NavLink>
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
      <span
        className={`pill ${health?.send_mode === 'live' ? 'green' : 'warn'}`}
        title={health?.send_mode === 'live'
          ? 'Messages are really being sent'
          : 'Messages are written to the activity feed instead of being sent. Set SEND_MODE=live in backend/.env to send.'}
      >
        {health?.send_mode === 'live' ? 'Sending for real' : 'Practice mode'}
      </span>
      <SettingsMenu health={health} refreshHealth={refreshHealth} />
    </header>
  );
}
