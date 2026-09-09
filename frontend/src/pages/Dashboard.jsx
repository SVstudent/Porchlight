import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Layers, History, PlusCircle, Zap } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import SentinelPanel from '../components/SentinelPanel.jsx';
import PowerPanel from '../components/PowerPanel.jsx';
import EpisodePanel from '../components/EpisodePanel.jsx';
import ActivityFeed from '../components/ActivityFeed.jsx';
import Collapsible from '../components/Collapsible.jsx';
import HazardPill from '../components/HazardPill.jsx';
import { api, useEventStream, usePoll, timeAgo } from '../lib/api.js';

const REFRESH_ON = new Set([
  'status', 'approval', 'assessment', 'dispatch', 'checkin', 'escalation',
  'node_stop', 'decision', 'brief', 'error', 'policy',
]);

export default function Dashboard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [health, refreshHealth] = usePoll(api.health, 30000);
  const [roster] = usePoll(api.roster, 120000);
  const [vols] = usePoll(api.volunteers, 120000);
  const [res] = usePoll(api.resources, 300000);
  const [episodes, refreshEpisodes] = usePoll(api.episodes, 20000);
  const [episode, setEpisode] = useState(null);

  const list = episodes?.episodes || [];
  const activeId = id || list[0]?.id;
  const pendingTotal = list.reduce((n, e) => n + (e.pending_approvals || 0), 0);

  const loadEpisode = useCallback(() => {
    if (!activeId) { setEpisode(null); return; }
    api.episode(activeId).then(setEpisode).catch(() => setEpisode(null));
  }, [activeId]);

  useEffect(() => { loadEpisode(); }, [loadEpisode]);

  // Poll the open episode only while its agents are still working; SSE covers the rest.
  const working = !!episode?.busy || ['assessing', 'triaging', 'dispatching', 'escalating'].includes(episode?.status);
  useEffect(() => {
    if (!activeId || !working) return undefined;
    const t = setInterval(loadEpisode, 6000);
    return () => clearInterval(t);
  }, [activeId, working, loadEpisode]);

  const [events, connected] = useEventStream((ev) => {
    if (REFRESH_ON.has(ev.type)) { loadEpisode(); refreshEpisodes(); }
    if (ev.type === 'scan') refreshHealth();
  });

  const onEpisode = (epId) => { refreshEpisodes(); nav(`/episodes/${epId}`); };
  const members = roster?.members || [];

  return (
    <div className="shell">
      <TopBar health={health} connected={connected} refreshHealth={refreshHealth} />
      <main className="desk">
        <div className="col">
          {/* Episodes first: this is how the coordinator navigates. */}
          <section className="panel">
            <div className="panel-h">
              <Layers size={15} />
              <h3>Episodes</h3>
              {pendingTotal ? <div className="right"><span className="pill amber small">{pendingTotal} to decide</span></div> : null}
            </div>
            <div className="panel-b">
              {list.length === 0 ? (
                <div className="small muted">
                  Nothing yet. The sentinel checks every {health?.sentinel_interval_minutes || 15} minutes, or run a
                  hazard from the <Link to="/demo">presenter view</Link>.
                </div>
              ) : null}
              {list.slice(0, 8).map((e) => (
                <Link
                  className={`ep-row ${e.id === activeId ? 'on' : ''}`}
                  to={`/episodes/${e.id}`}
                  key={e.id}
                >
                  <HazardPill type={e.hazard.hazard_type} compact />
                  <div className="ep-main">
                    <div className="t">{e.hazard.event_name}</div>
                    <div className="ep-meta">
                      {e.pending_approvals
                        ? <span className="pill amber small">{e.pending_approvals} to decide</span>
                        : <span className="pill small">{e.status.replace(/_/g, ' ')}</span>}
                      <span className="small muted">{timeAgo(e.created_at)}</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          {/* Live conditions and official alerts stay open: this is the "why now". */}
          <SentinelPanel onEpisode={onEpisode} health={health} refreshHealth={refreshHealth} compact />

          <Collapsible
            id="power"
            icon={<Zap size={15} />}
            title="Electricity-dependent neighbors"
            defaultOpen={false}
          >
            <PowerPanel onEpisode={onEpisode} embedded />
          </Collapsible>

          <Collapsible id="replay" icon={<History size={15} />} title="Replay a real alert">
            <SentinelPanel.Replay onEpisode={onEpisode} />
          </Collapsible>

          <Collapsible id="manual" icon={<PlusCircle size={15} />} title="Report a hazard yourself">
            <SentinelPanel.Manual onEpisode={onEpisode} />
          </Collapsible>
        </div>

        <div className="col">
          <EpisodePanel
            episode={episode}
            members={members}
            volunteers={vols?.volunteers || []}
            resources={res?.resources || []}
            refresh={() => { loadEpisode(); refreshEpisodes(); }}
          />
        </div>

        <ActivityFeed events={events} episodeId={activeId} />
      </main>
    </div>
  );
}
