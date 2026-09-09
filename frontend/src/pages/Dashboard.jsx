import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Layers } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import SentinelPanel from '../components/SentinelPanel.jsx';
import PowerPanel from '../components/PowerPanel.jsx';
import EpisodePanel from '../components/EpisodePanel.jsx';
import ActivityFeed from '../components/ActivityFeed.jsx';
import { api, useEventStream, usePoll, timeAgo } from '../lib/api.js';

const REFRESH_ON = new Set(['status', 'approval', 'assessment', 'dispatch', 'checkin', 'escalation', 'node_stop', 'decision', 'brief', 'error', 'policy']);

export default function Dashboard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [health, refreshHealth] = usePoll(api.health, 30000);
  const [roster] = usePoll(api.roster, 60000);
  const [vols] = usePoll(api.volunteers, 60000);
  const [res] = usePoll(api.resources, 120000);
  const [episodes, refreshEpisodes] = usePoll(api.episodes, 15000);
  const [episode, setEpisode] = useState(null);

  const activeId = id || episodes?.episodes?.[0]?.id;

  const loadEpisode = useCallback(() => {
    if (!activeId) { setEpisode(null); return; }
    api.episode(activeId).then(setEpisode).catch(() => setEpisode(null));
  }, [activeId]);

  useEffect(() => { loadEpisode(); }, [loadEpisode]);
  useEffect(() => { const t = setInterval(loadEpisode, 6000); return () => clearInterval(t); }, [loadEpisode]);

  const [events, connected] = useEventStream((ev) => {
    if (REFRESH_ON.has(ev.type)) { loadEpisode(); refreshEpisodes(); }
    if (ev.type === 'scan') refreshHealth();
  });

  const onEpisode = (epId) => { refreshEpisodes(); nav(`/episodes/${epId}`); };
  const members = roster?.members || [];

  return (
    <div className="shell">
      <TopBar health={health} connected={connected} />
      <main className="desk">
        <div className="col">
          <SentinelPanel onEpisode={onEpisode} health={health} refreshHealth={refreshHealth} />
          <PowerPanel onEpisode={onEpisode} />
          <section className="panel">
            <div className="panel-h"><Layers size={15} /><h3>Episodes</h3></div>
            <div className="panel-b">
              {(episodes?.episodes || []).length === 0 ? <div className="small muted">None yet.</div> : null}
              {(episodes?.episodes || []).slice(0, 8).map((e) => (
                <Link className="ep-row" to={`/episodes/${e.id}`} key={e.id} style={{ fontWeight: e.id === activeId ? 700 : 400 }}>
                  <span className="t">{e.hazard.event_name}</span>
                  {e.pending_approvals ? <span className="pill amber small">{e.pending_approvals} to decide</span> : <span className="pill small">{e.status.replace('_', ' ')}</span>}
                  <span className="small muted">{timeAgo(e.created_at)}</span>
                </Link>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-h"><h3>Standing policy</h3></div>
            <div className="panel-b stack">
              <label className="check">
                <input type="checkbox" checked={!!health?.auto_approve_escalations} onChange={(e) => api.settings({ auto_approve_escalations: e.target.checked }).then(refreshHealth)} />
                Let the follow-up agent dispatch a volunteer to a Tier 1 neighbor who hasn't replied, without asking me
              </label>
              <label className="check">
                <input type="checkbox" checked={!!health?.sentinel_enabled} onChange={(e) => api.settings({ sentinel_enabled: e.target.checked }).then(refreshHealth)} />
                Sentinel scans automatically
              </label>
              <button className="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={() => { if (confirm('Clear all episodes, approvals and check-ins? The roster stays.')) api.reset().then(() => { refreshEpisodes(); nav('/'); }); }}>Reset episodes</button>
            </div>
          </section>
        </div>
        <div className="col">
          <EpisodePanel episode={episode} members={members} volunteers={vols?.volunteers || []} resources={res?.resources || []} refresh={() => { loadEpisode(); refreshEpisodes(); }} />
        </div>
        <ActivityFeed events={events} episodeId={activeId} />
      </main>
    </div>
  );
}
