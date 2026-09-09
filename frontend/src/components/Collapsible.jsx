import { useState } from 'react';
import { ChevronRight } from 'lucide-react';

/** A panel that can fold away. Keeps the coordinator's desk short enough to read at a glance. */
export default function Collapsible({ icon, title, badge, defaultOpen = false, children, id }) {
  const storageKey = id ? `porchlight.open.${id}` : null;
  const [open, setOpen] = useState(() => {
    if (!storageKey) return defaultOpen;
    try {
      const saved = localStorage.getItem(storageKey);
      return saved === null ? defaultOpen : saved === '1';
    } catch {
      return defaultOpen;
    }
  });
  const toggle = () => {
    setOpen((o) => {
      const next = !o;
      try { if (storageKey) localStorage.setItem(storageKey, next ? '1' : '0'); } catch { /* ignore */ }
      return next;
    });
  };
  return (
    <section className={`panel fold ${open ? 'open' : ''}`}>
      <button className="fold-h" onClick={toggle} aria-expanded={open}>
        <ChevronRight size={14} className="chev" aria-hidden="true" />
        {icon}
        <h3>{title}</h3>
        {badge ? <span className="fold-badge">{badge}</span> : null}
      </button>
      {open ? <div className="fold-b">{children}</div> : null}
    </section>
  );
}
