import { useState } from 'react';
import { Navigation, Check, X, MapPin } from 'lucide-react';
import { api } from '../lib/api.js';

/**
 * Suggested and in-progress trips, shown directly under the map they are drawn on.
 *
 * A card only exists because a neighbour's need was established: they asked for help, or they went
 * quiet through every reminder. Nobody is contacted until the coordinator approves, which is the same
 * rule that governs every other outbound action here.
 */
const TASK = {
  wellness_visit: 'Wellness visit',
  ride_to_cooling_center: 'Ride to somewhere cooled',
  deliver_supplies: 'Deliver supplies',
  phone_call: 'Phone call',
};

const TRIGGER = {
  needs_help: 'they asked for help',
  critical: 'no reply after every reminder',
  coordinator: 'you asked for this',
};

function mins(seconds) {
  return Math.max(0, Math.round((seconds || 0) / 60));
}

export default function DeploymentCards({ deployments = [], refresh }) {
  const [busy, setBusy] = useState('');
  const live = deployments.filter((d) => ['proposed', 'approved'].includes(d.status));
  if (live.length === 0) return null;

  const decide = async (id, decision) => {
    setBusy(id);
    try {
      await api.decideDeployment(id, { decision });
      refresh && refresh();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <div>
      {live.map((d) => {
        const pct = Math.round((d.progress || 0) * 100);
        const estimated = d.route_source === 'straight_line';
        return (
          <div className={`deploy ${d.status}`} key={d.id}>
            <div className="who">
              <Navigation size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              {d.responder_name} → {d.member_name}
              {d.destination_name ? <> → {d.destination_name}</> : null}
            </div>
            <div className="why">
              <b>{TASK[d.task] || d.task.replace(/_/g, ' ')}</b> · {TRIGGER[d.trigger] || d.trigger}
              <br />{d.reason}
            </div>

            <div className="facts">
              <span><MapPin size={12} style={{ verticalAlign: '-2px' }} /> {(d.distance_m / 1000).toFixed(1)} km</span>
              <span>about {mins(d.duration_s)} min by road</span>
              {d.responder_skills?.length ? <span>{d.responder_skills.join(' · ')}</span> : null}
            </div>

            {d.status === 'approved' ? (
              <>
                <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                <div className="est">
                  {pct >= 100
                    ? `${d.responder_name} should have arrived.`
                    : `About ${pct}% of the way · roughly ${mins(d.eta_seconds)} min left.`}
                  {' '}Estimated from the road route{estimated ? ' (no routing service reachable, so this is a straight line)' : ''}, not a GPS position.
                </div>
              </>
            ) : (
              <div className="row">
                <button className="btn primary sm" disabled={!!busy}
                        onClick={() => decide(d.id, 'approve')}>
                  <Check size={13} /> {busy === d.id ? 'Sending…' : 'Approve & send'}
                </button>
                <button className="btn ghost sm" disabled={!!busy}
                        onClick={() => decide(d.id, 'decline')}>
                  <X size={13} /> Decline
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
