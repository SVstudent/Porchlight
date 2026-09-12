import { Link } from 'react-router-dom';
import { AlertTriangle, HeartHandshake, Clock, Check, CircleDashed, Navigation } from 'lucide-react';
import { timeAgo } from '../lib/api.js';

/**
 * One neighbour, as a card in the watch list.
 *
 * The card leads with the single thing a coordinator needs to know — are they alright — and only then
 * explains why they might not be. The list is ordered so that the people in trouble are at the top,
 * which means the card's job is to be readable at a glance rather than complete.
 */
const STATE = {
  critical: {
    label: 'No reply at all', cls: 'critical', Icon: AlertTriangle,
    hint: 'Every reminder went unanswered',
  },
  needs_help: { label: 'Needs help', cls: 'needs', Icon: HeartHandshake, hint: 'They asked for help' },
  waiting: { label: 'Waiting on a reply', cls: 'waiting', Icon: Clock, hint: 'Message sent' },
  ok: { label: 'Says they are okay', cls: 'ok', Icon: Check, hint: '' },
  not_contacted: { label: 'Not contacted', cls: 'idle', Icon: CircleDashed, hint: '' },
};

const RISK_LABEL = {
  age_75_plus: '75+', lives_alone: 'lives alone', no_air_conditioning: 'no A/C',
  powered_medical_device: 'medical device', mobility_limited: 'limited mobility',
  cognitive_impairment: 'memory issues', infant_or_young_child: 'young child',
  outdoor_worker: 'works outdoors', pregnant: 'pregnant', chronic_illness: 'chronic illness',
  no_transport: 'no car', limited_english: 'limited English', unhoused: 'unhoused',
};

export default function NeighborCard({ n, active, onHover }) {
  const s = STATE[n.state] || STATE.not_contacted;
  const { Icon } = s;
  return (
    <Link
      to={`/neighbors/${n.id}`}
      className={`ncard ${s.cls} ${active ? 'on' : ''}`}
      onMouseEnter={() => onHover && onHover(n.id)}
      onMouseLeave={() => onHover && onHover(null)}
    >
      <div className="ncard-top">
        <span className={`nstate ${s.cls}`}><Icon size={13} /> {s.label}</span>
        {n.tier ? <span className={`tier t${n.tier}`}>Tier {n.tier}</span> : null}
      </div>

      <div className="ncard-name">{n.name}</div>
      <div className="ncard-addr">{n.address}</div>

      <div className="ncard-risks">
        {(n.risk_factors || []).slice(0, 4).map((r) => (
          <span className="rchip" key={r}>{RISK_LABEL[r] || r.replace(/_/g, ' ')}</span>
        ))}
      </div>

      <div className="ncard-foot">
        {n.checkin ? (
          <span>
            {n.checkin.responded_at
              ? `replied ${timeAgo(n.checkin.responded_at)}`
              : `sent ${timeAgo(n.checkin.sent_at)}`}
            {n.reminders_sent ? ` · ${n.reminders_sent} reminder${n.reminders_sent === 1 ? '' : 's'}` : ''}
          </span>
        ) : (
          <span>{s.hint || 'no message yet'}</span>
        )}
        {n.deployment ? (
          <span className={`ndeploy ${n.deployment.status}`}>
            <Navigation size={11} />
            {n.deployment.status === 'approved' ? 'on the way' : 'visit suggested'}
            {n.deployment.responder_name ? ` · ${n.deployment.responder_name.split(' ')[0]}` : ''}
          </span>
        ) : null}
      </div>
    </Link>
  );
}
