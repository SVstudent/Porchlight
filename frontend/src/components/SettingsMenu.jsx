import { useEffect, useRef, useState } from 'react';
import { Settings2 } from 'lucide-react';
import { api } from '../lib/api.js';

/** Standing policy and pacing, tucked into the top bar so they don't crowd the desk. */
export default function SettingsMenu({ health, refreshHealth }) {
  const [open, setOpen] = useState(false);
  const [pacing, setPacing] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (open && !pacing) api.pacing().then(setPacing).catch(() => {});
  }, [open, pacing]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const savePacing = (patch) => {
    setPacing((p) => ({ ...p, ...patch }));
    api.setPacing(patch).then(setPacing).catch(() => {});
  };

  return (
    <div className="menu-wrap" ref={ref}>
      <button className="btn ghost sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Settings">
        <Settings2 size={15} />
      </button>
      {open ? (
        <div className="menu-pop" role="dialog" aria-label="Settings">
          <div className="eyebrow">Standing policy</div>
          <label className="check">
            <input
              type="checkbox"
              checked={!!health?.auto_approve_escalations}
              onChange={(e) => api.settings({ auto_approve_escalations: e.target.checked }).then(refreshHealth)}
            />
            <span>Let the follow-up agent send a volunteer to a Tier 1 neighbor who hasn't replied, without asking me</span>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={!!health?.sentinel_enabled}
              onChange={(e) => api.settings({ sentinel_enabled: e.target.checked }).then(refreshHealth)}
            />
            <span>Watch for hazards automatically</span>
          </label>

          <div className="eyebrow" style={{ marginTop: 12 }}>Follow-up pacing</div>
          {pacing ? (
            <>
              <label className="field">
                <span>Wait this long for a reply before escalating</span>
                <div className="row">
                  <input
                    type="number" min="0" max="240"
                    value={pacing.followup_grace_minutes}
                    onChange={(e) => savePacing({ followup_grace_minutes: Number(e.target.value) })}
                  />
                  <span className="small muted">minutes</span>
                </div>
              </label>
              <label className="field">
                <span>Check for replies every</span>
                <div className="row">
                  <input
                    type="number" min="1" max="60"
                    value={pacing.followup_interval_minutes}
                    onChange={(e) => savePacing({ followup_interval_minutes: Number(e.target.value) })}
                  />
                  <span className="small muted">minutes</span>
                </div>
              </label>
              <div className="small muted">
                Real deployments use {pacing.defaults?.followup_grace_minutes} minutes. Shorten it to show escalation on camera.
              </div>
            </>
          ) : <div className="small muted">Loading…</div>}
        </div>
      ) : null}
    </div>
  );
}
