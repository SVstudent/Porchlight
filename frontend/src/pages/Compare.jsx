import { useNavigate } from 'react-router-dom';
import TopBar from '../components/TopBar.jsx';
import HazardPill from '../components/HazardPill.jsx';
import { api, usePoll } from '../lib/api.js';

const RF_LABEL = {
  lives_alone: 'lives alone', age_75_plus: '75+', no_air_conditioning: 'no AC',
  powered_medical_device: 'medical device', mobility_limited: 'limited mobility',
  cognitive_impairment: 'memory issues', infant_or_young_child: 'young kids',
  outdoor_worker: 'works outdoors', pregnant: 'pregnant', chronic_illness: 'chronic illness',
  no_transport: 'no car', limited_english: 'limited English', unhoused: 'unhoused',
};

const CHECKIN_MARK = { ok: '✓', needs_help: '!', escalated: '!', no_response: '·', failed: '×' };

/**
 * One screen that answers "is this only a heat demo?".
 * Built from episodes that actually ran; empty until at least one hazard has been triaged.
 */
export default function Compare() {
  const nav = useNavigate();
  const [health] = usePoll(api.health, 60000);
  const [data] = usePoll(api.compare, 15000);

  const episodes = data?.episodes || [];
  const members = data?.members || [];

  return (
    <div className="shell">
      <TopBar health={health} connected />
      <main className="wide">
        <div className="demo-intro">
          <h1>Same roster, every hazard</h1>
          <p>
            The same twelve neighbors, ranked by a different agent run for each hazard. Nothing here is
            pre-written: each column is an episode that actually ran through the pipeline.
          </p>
        </div>

        {episodes.length === 0 ? (
          <section className="panel">
            <div className="empty">
              <div className="big">No completed runs yet.</div>
              <div>Run two or three hazards from the presenter view, then this table fills in.</div>
              <button className="btn primary" style={{ marginTop: 12 }} onClick={() => nav('/demo')}>Go to presenter view</button>
            </div>
          </section>
        ) : (
          <>
            <div className="cmp-heads">
              {episodes.map((e) => (
                <div className="cmp-head" key={e.episode_id}>
                  <HazardPill type={e.hazard_type} />
                  <div className="t">{e.event_name}</div>
                  <div className="d">{e.area?.slice(0, 60)}</div>
                  <div className="row" style={{ marginTop: 6 }}>
                    <span className={`pill small ${e.activated ? 'red' : ''}`}>
                      {e.activated ? `severity ${e.severity_score}/5` : 'stood down'}
                    </span>
                    <span className="pill small">{e.tier1} tier 1</span>
                    <span className="pill small">{e.contacted} contacted</span>
                  </div>
                  {e.summary ? <p className="cmp-sum">{e.summary}</p> : null}
                  <button className="btn ghost sm" onClick={() => nav(`/episodes/${e.episode_id}`)}>Open episode</button>
                </div>
              ))}
            </div>

            <section className="panel">
              <div className="panel-b" style={{ overflowX: 'auto' }}>
                <table className="cmp-table">
                  <thead>
                    <tr>
                      <th>Neighbor</th>
                      {episodes.map((e) => (
                        <th key={e.episode_id}>{e.event_name.replace(/ (Warning|Alert|Advisory)$/, '')}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((m) => (
                      <tr key={m.member_id}>
                        <td>
                          <b>{m.name}</b>
                          <div className="small muted">
                            {m.risk_factors.map((r) => RF_LABEL[r] || r).join(' · ') || 'no flagged risk factors'}
                          </div>
                        </td>
                        {episodes.map((e) => {
                          const d = e.decisions[m.member_id];
                          if (!d) return <td key={e.episode_id} className="cmp-cell"><span className="muted small">—</span></td>;
                          return (
                            <td key={e.episode_id} className="cmp-cell">
                              <span className={`tier t${d.tier}`}>{d.tier === 0 ? 'no action' : `Tier ${d.tier}`}</span>
                              {d.needs_visit ? <span className="pill red small">visit</span> : null}
                              {d.checkin ? <span className="cmp-mark" title={d.checkin}>{CHECKIN_MARK[d.checkin] || ''}</span> : null}
                              {d.reason ? <div className="cmp-why">{d.reason}</div> : null}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <p className="small muted">
              Tier 1 means contact within the hour and probably an in-person visit. The reason under each tier is
              the agent's own words for that hazard.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
