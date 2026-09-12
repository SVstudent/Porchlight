import { Radar, Brain, ListOrdered, Send, Car, FileText } from 'lucide-react';

/**
 * Where the run has got to, as a row of stages.
 *
 * Outreach and logistics genuinely run at the same time — that is what the graph is for, and in a real
 * heat wave it is what you want. But two agents narrating at once reads as chaos unless the structure
 * is visible somewhere. This is that structure: the stages stay in order, and the two that overlap are
 * simply both lit at once, so parallel work looks deliberate instead of disorderly.
 *
 * Stage state is derived from what the episode has actually produced, never from a timer.
 */
const STAGES = [
  { id: 'detect', label: 'Detect', Icon: Radar },
  { id: 'assess', label: 'Assess', Icon: Brain },
  { id: 'triage', label: 'Triage', Icon: ListOrdered },
  { id: 'contact', label: 'Contact', Icon: Send },
  { id: 'arrange', label: 'Arrange', Icon: Car },
  { id: 'brief', label: 'Brief', Icon: FileText },
];

export default function PipelineStrip({ episode, approvals = [], busy }) {
  if (!episode) return null;

  const has = {
    detect: true,
    assess: !!episode.assessment,
    triage: !!episode.triage,
    contact: !!episode.outreach,
    arrange: !!episode.logistics,
    brief: !!(episode.stats && episode.stats.brief),
  };
  const waitingFor = new Set(
    approvals.filter((a) => a.status === 'pending').map((a) => (
      a.kind === 'outreach_dispatch' ? 'contact' : a.kind === 'volunteer_dispatch' ? 'arrange' : ''
    )),
  );

  // The first unfinished stage after the last finished one is the one in flight. Both of the parallel
  // stages can be in flight together, which is the point.
  const state = (id) => {
    if (waitingFor.has(id)) return 'waiting';
    if (has[id]) return 'done';
    if (!busy) return 'idle';
    if (id === 'assess') return 'running';
    if (id === 'triage') return has.assess ? 'running' : 'idle';
    if (id === 'contact' || id === 'arrange') return has.triage ? 'running' : 'idle';
    if (id === 'brief') return has.contact || has.arrange ? 'running' : 'idle';
    return 'idle';
  };

  return (
    <div className="pstrip" aria-label="pipeline progress">
      {STAGES.map(({ id, label, Icon }, i) => {
        const s = state(id);
        return (
          <div key={id} className={`pstage ${s}`}>
            {i > 0 ? <i className="pline" /> : null}
            <span className="pdot"><Icon size={11} /></span>
            <span className="plabel">{label}</span>
            {s === 'waiting' ? <span className="pwait">needs you</span> : null}
          </div>
        );
      })}
    </div>
  );
}
