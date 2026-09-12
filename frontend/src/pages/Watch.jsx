import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Users, Radar, PlusCircle, Antenna } from 'lucide-react';
import TopBar from '../components/TopBar.jsx';
import MapView from '../components/MapView.jsx';
import NeighborCard from '../components/NeighborCard.jsx';
import DeploymentCards from '../components/DeploymentCards.jsx';
import ApprovalCard from '../components/ApprovalCard.jsx';
import PipelineStrip from '../components/PipelineStrip.jsx';
import { api, useEventStream, usePoll } from '../lib/api.js';

/**
 * The watch: everyone being looked after on the left, where they are on the right.
 *
 * A coordinator's actual question is "who is not alright", and their second is "where are they and who
 * can reach them". Those are two halves of one screen, not two tabs, so the list and the map sit side
 * by side and stay in step: hovering a card lifts that neighbour on the map, and the map shows the
 * trips the list is talking about.
 */
// Anything that can change what the board shows. The agents' own narration — reasoning, streamed text,
// individual tool results — is excluded because it arrives many times a second and the feed covers it.
const REFRESH = new Set(['checkin', 'critical', 'deployment', 'dispatch', 'escalation', 'decision',
                         'status', 'brief', 'error', 'assessment', 'approval', 'interrupt',
                         'approval_requested', 'node_start', 'node_stop', 'scan', 'policy', 'gap']);

export default function Watch() {
  const [health, refreshHealth] = usePoll(api.health, 30000);
  const [res] = usePoll(api.resources, 300000);
  const [data, setData] = useState(null);
  const [deployments, setDeployments] = useState([]);
  const [hovered, setHovered] = useState(null);
  const [layers, setLayers] = useState(null);
  const [show, setShow] = useState({ field: true, footprint: true });
  const [filter, setFilter] = useState('all');
  const [ingesting, setIngesting] = useState(false);
  const [loadErr, setLoadErr] = useState('');
  const [approvals, setApprovals] = useState([]);
  const [vols] = usePoll(api.volunteers, 300000);
  const timer = useRef(null);

  const load = useCallback(() => {
    api.neighbors().then((d) => {
      setLoadErr('');
      setData(d);
      if (d.episode_id) {
        api.deployments(d.episode_id).then((x) => setDeployments(x.deployments || [])).catch(() => {});
        api.episode(d.episode_id)
          .then((e) => setApprovals((e.approvals || []).filter((a) => a.status === 'pending')))
          .catch(() => {});
      } else {
        setDeployments([]);
        setApprovals([]);
      }
    }).catch((e) => setLoadErr(e.message || 'could not reach the backend'));
  }, []);

  const queue = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { timer.current = null; load(); }, 400);
  }, [load]);

  useEffect(() => { load(); }, [load]);

  // The hazard footprint and the conditions field change on the scale of an hour, not a click.
  useEffect(() => {
    const get = () => api.mapLayers().then(setLayers).catch(() => {});
    get();
    const t = setInterval(get, 300000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const [, connected] = useEventStream((ev) => { if (REFRESH.has(ev.type)) queue(); });

  // A responder in transit needs a steady tick; the list itself is not changing while they drive.
  const travelling = deployments.some((d) => d.status === 'approved' && (d.progress || 0) < 1);
  useEffect(() => {
    // Always poll. Events drive the fast updates, but a poll is the only thing that recovers from a
    // fetch that failed — during a restart, say — and an empty screen with no explanation is worse
    // than a slow one. Faster while someone is travelling or while something is wrong.
    const every = travelling ? 5000 : loadErr ? 3000 : connected ? 15000 : 6000;
    const t = setInterval(load, every);
    return () => clearInterval(t);
  }, [travelling, connected, loadErr, load]);

  const all = data?.neighbors || [];
  const counts = useMemo(() => {
    const c = { all: all.length, critical: 0, needs_help: 0, waiting: 0, ok: 0 };
    all.forEach((n) => { if (c[n.state] !== undefined) c[n.state] += 1; });
    return c;
  }, [all]);
  const shown = filter === 'all' ? all : all.filter((n) => n.state === filter);
  const attention = counts.critical + counts.needs_help;

  const members = all.map((n) => ({ ...n, id: n.id }));
  const episode = data?.episode || null;

  return (
    <div className="shell">
      <TopBar health={health} connected={connected} refreshHealth={refreshHealth} />

      <main className="watch">
        {/* ---------------- left: who we are watching ---------------- */}
        <section className="watch-list">
          <header className="watch-head">
            <div>
              <h2><Users size={16} /> The watch</h2>
              <p className="small muted">
                {episode
                  ? <>Responding to <b>{episode.hazard.event_name}</b> · {all.length} neighbours</>
                  : <>{all.length} neighbours · nothing active right now</>}
              </p>
            </div>
            <div className="watch-head-right">
              {attention > 0 ? (
                <span className="pill red">{attention} need{attention === 1 ? 's' : ''} you</span>
              ) : null}
              {/* Clears everything and sets the real pipeline going: a live alert if the National
                  Weather Service has one for this area, an archived real one if it does not. */}
              <button
                className="ingest-btn"
                disabled={ingesting}
                title="Start from nothing: clear every episode and let the sentinel ingest what is actually happening"
                onClick={async () => {
                  setIngesting(true);
                  try {
                    const r = await api.ingest({ pace: 'filming' });
                    setLayers(null);
                    load();
                    api.mapLayers().then(setLayers).catch(() => {});
                    console.info('[porchlight] ingested', r.source, '—', r.hazard);
                  } catch (e) {
                    alert(e.message);
                  } finally {
                    setIngesting(false);
                  }
                }}
              >
                <Antenna size={12} /> {ingesting ? 'ingesting…' : 'ingestion'}
              </button>
            </div>
          </header>

          {/* Outreach and logistics run at the same time; this is what keeps that legible. */}
          <PipelineStrip episode={episode} approvals={approvals} busy={!!episode?.busy} />

          <div className="watch-filters">
            {[['all', 'Everyone'], ['critical', 'No reply'], ['needs_help', 'Needs help'],
              ['waiting', 'Waiting'], ['ok', 'Okay']].map(([k, label]) => (
              <button key={k} className={`fchip ${filter === k ? 'on' : ''}`}
                      onClick={() => setFilter(k)} disabled={k !== 'all' && !counts[k]}>
                {label}{counts[k] ? <b> {counts[k]}</b> : null}
              </button>
            ))}
          </div>

          <div className="watch-scroll">
            {loadErr ? (
              <div className="load-err small">
                Cannot reach the backend — {loadErr}. Retrying every few seconds.
              </div>
            ) : null}
            {!loadErr && shown.length === 0 ? (
              <div className="empty small">
                {data === null
                  ? 'Loading the roster…'
                  : all.length === 0
                    ? 'No neighbours on the roster yet.'
                    : 'Nobody in this state right now.'}
              </div>
            ) : null}
            {shown.map((n) => (
              <NeighborCard key={n.id} n={n} active={hovered === n.id} onHover={setHovered} />
            ))}

            {!episode ? (
              <div className="watch-cta small">
                <Radar size={14} /> Nothing is running. Start from the{' '}
                <Link to="/demo">presenter view</Link>, or{' '}
                <Link to="/episodes">open a past episode</Link>.
              </div>
            ) : null}
          </div>
        </section>

        {/* ---------------- right: where they are ---------------- */}
        <section className="watch-map">
          <div className="watch-map-inner">
            <MapView
              members={members}
              resources={res?.resources || []}
              episode={episode}
              deployments={deployments}
              highlight={hovered}
              layers={layers}
              showField={show.field}
              showFootprint={show.footprint}
            />
          </div>
          <div className="map-legend">
            {layers?.footprint?.parts?.length ? (
              <button className={`lchip ${show.footprint ? 'on' : ''}`}
                      onClick={() => setShow((s) => ({ ...s, footprint: !s.footprint }))}>
                <i className="fp" /> {layers.footprint.kind === 'alert_polygon'
                  ? 'warning area' : `${layers.footprint.parts.length} forecast zones`}
              </button>
            ) : null}
            {layers?.field?.cells?.length ? (
              <button className={`lchip ${show.field ? 'on' : ''}`}
                      onClick={() => setShow((s) => ({ ...s, field: !s.field }))}>
                <i className="fld" /> {layers.field.metric} {Math.round(layers.field.min)}–{Math.round(layers.field.max)}{layers.field.unit}
              </button>
            ) : null}
            <span className="k"><i className="dot" style={{ background: '#c8412b' }} /> needs help</span>
            <span className="k"><i className="dot" style={{ background: '#8c1d11' }} /> no reply at all</span>
            <span className="k"><i className="dot" style={{ background: '#e39a2f' }} /> waiting</span>
            <span className="k"><i className="dot" style={{ background: '#2f6b5a' }} /> okay</span>
            <span className="k"><i className="sq" /> cooled buildings</span>
            <span className="k"><i className="ln" /> responder en route</span>
          </div>
          {approvals.length ? (
            <div className="watch-approvals">
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                {approvals.length} waiting on your decision
              </div>
              {approvals.map((a) => (
                <ApprovalCard
                  key={a.id}
                  approval={a}
                  members={all}
                  volunteers={vols?.volunteers || []}
                  onDecided={load}
                />
              ))}
            </div>
          ) : null}
          {deployments.length ? (
            <div className="watch-deploys">
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                <PlusCircle size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />
                Suggested deployments
              </div>
              <DeploymentCards deployments={deployments} refresh={load} />
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}
