const STATUS_LABEL = { sent: 'Message sent · waiting', delivered: 'Delivered · waiting', ok: "Replied: I'm OK", needs_help: 'Replied: NEEDS HELP', no_response: 'No response', escalated: 'Escalated' };
const RF_LABEL = { lives_alone: 'lives alone', age_75_plus: '75+', no_air_conditioning: 'no AC', powered_medical_device: 'medical device', mobility_limited: 'limited mobility', cognitive_impairment: 'memory issues', infant_or_young_child: 'young kids', outdoor_worker: 'works outdoors', pregnant: 'pregnant', chronic_illness: 'chronic illness', no_transport: 'no car', limited_english: 'limited English', unhoused: 'unhoused' };

export default function RosterStatus({ members, episode }) {
  const decisions = Object.fromEntries((episode?.triage?.decisions || []).map((d) => [d.member_id, d]));
  const checkins = Object.fromEntries((episode?.checkins || []).map((c) => [c.member_id, c]));
  const list = [...members].sort((a, b) => {
    const ta = decisions[a.id]?.tier ?? 9, tb = decisions[b.id]?.tier ?? 9;
    const ra = ta === 0 ? 9 : ta, rb = tb === 0 ? 9 : tb;
    return ra - rb || a.name.localeCompare(b.name);
  });
  return (
    <div className="roster-grid">
      {list.map((m) => {
        const d = decisions[m.id];
        const c = checkins[m.id];
        const st = c?.status || (d ? (d.tier === 0 ? '' : 'planned') : '');
        return (
          <div className={`mtile ${c?.status || ''}`} key={m.id}>
            <div className="nm">
              <span>{m.name}</span>
              {d ? <span className={`tier t${d.tier}`}>{d.tier === 0 ? 'no action' : `Tier ${d.tier}`}</span> : null}
            </div>
            <div className="rf">{m.risk_factors.map((r) => RF_LABEL[r] || r).join(' · ') || 'no flagged risk factors'}</div>
            {c ? <div className="st">{STATUS_LABEL[c.status] || c.status}{c.note && c.status !== 'sent' ? <span className="why"> — {c.note}</span> : null}</div>
              : d && d.tier > 0 ? <div className="st muted">Planned · {d.channel}{d.needs_visit ? ' · needs visit' : ''}</div> : null}
            {d?.reason ? <div className="why">{d.reason}</div> : null}
          </div>
        );
      })}
    </div>
  );
}
