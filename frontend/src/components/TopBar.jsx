import { NavLink, Link } from 'react-router-dom';
import { timeAgo } from '../lib/api.js';

export default function TopBar({ health, connected }) {
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
      </nav>
      <span className="spacer" />
      <span className={`pill ${sentinelOn ? 'live' : 'off'}`} title="Deterministic hazard scan of NWS + Open-Meteo">
        <span className="dot" />
        {sentinelOn ? `Sentinel watching · scanned ${health?.last_scan_at ? timeAgo(health.last_scan_at) : 'not yet'}` : 'Sentinel paused'}
      </span>
      <span className={`pill ${connected ? 'live' : 'off'}`} title="Server-sent events from the Strands agents">
        <span className="dot" />
        {connected ? 'Live agent feed' : 'Reconnecting…'}
      </span>
      {health?.models?.length ? (
        <span className="pill mono small" title="Strands model provider (fallback order)">
          {health.models[0].replace('bedrock:', 'Bedrock · ').replace('anthropic:', 'Anthropic · ').replace('ollama:', 'Ollama · ')}
        </span>
      ) : null}
      <span className={`pill ${health?.send_mode === 'live' ? 'green' : 'warn'}`} title="SEND_MODE in backend/.env">
        {health?.send_mode === 'live' ? 'Sending live' : 'Console send mode'}
      </span>
    </header>
  );
}
