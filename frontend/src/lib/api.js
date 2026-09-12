import { useEffect, useRef, useState, useCallback } from 'react';

const BASE = import.meta.env.VITE_API_URL || '';

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => req('/api/health'),
  settings: (body) => req('/api/settings', { method: 'POST', body: JSON.stringify(body) }),
  events: (episodeId) => req(`/api/events?limit=300${episodeId ? `&episode_id=${episodeId}` : ''}`),
  roster: () => req('/api/roster'),
  saveMember: (m) => req('/api/roster', { method: 'POST', body: JSON.stringify(m) }),
  deleteMember: (id) => req(`/api/roster/${id}`, { method: 'DELETE' }),
  volunteers: () => req('/api/volunteers'),
  saveVolunteer: (v) => req('/api/volunteers', { method: 'POST', body: JSON.stringify(v) }),
  resources: () => req('/api/resources'),
  live: () => req('/api/hazards/live'),
  scan: () => req('/api/hazards/scan', { method: 'POST' }),
  fixtures: () => req('/api/hazards/fixtures'),
  replay: (fixture_id) => req('/api/hazards/replay', { method: 'POST', body: JSON.stringify({ fixture_id }) }),
  manual: (body) => req('/api/hazards/manual', { method: 'POST', body: JSON.stringify(body) }),
  episodes: () => req('/api/episodes'),
  episode: (id) => req(`/api/episodes/${id}`),
  followup: (id) => req(`/api/episodes/${id}/followup`, { method: 'POST' }),
  close: (id) => req(`/api/episodes/${id}/close`, { method: 'POST' }),
  approvals: () => req('/api/approvals'),
  neighbors: () => req('/api/neighbors'),
  mapLayers: () => req('/api/map/layers'),
  ingest: (body = {}) => req('/api/demo/ingest', { method: 'POST', body: JSON.stringify(body) }),
  neighbor: (id) => req(`/api/neighbors/${id}`),
  checkup: (id) => req(`/api/neighbors/${id}/checkup`, { method: 'POST' }),
  escalateNeighbor: (id) => req(`/api/neighbors/${id}/escalate`, { method: 'POST' }),
  deployments: (id) => req(`/api/episodes/${id}/deployments`),
  decideDeployment: (id, body) => req(`/api/deployments/${id}/decide`, { method: 'POST', body: JSON.stringify(body) }),
  sweepDeployments: (id) => req(`/api/episodes/${id}/deployments/sweep`, { method: 'POST' }),
  decide: (id, body) => req(`/api/approvals/${id}/decide`, { method: 'POST', body: JSON.stringify(body) }),
  checkin: (token) => req(`/api/checkin/${token}`),
  submitCheckin: (token, body) => req(`/api/checkin/${token}`, { method: 'POST', body: JSON.stringify(body) }),
  reset: () => req('/api/admin/reset', { method: 'POST' }),
  retryEpisode: (id) => req(`/api/episodes/${id}/retry`, { method: 'POST' }),
  pacing: () => req('/api/demo/pacing'),
  setPacing: (body) => req('/api/demo/pacing', { method: 'POST', body: JSON.stringify(body) }),
  readiness: () => req('/api/demo/readiness'),
  compare: () => req('/api/demo/compare'),
  latestCheckin: (episodeId) => req(`/api/demo/latest-checkin${episodeId ? `?episode_id=${episodeId}` : ''}`),
  report: (id) => req(`/api/episodes/${id}/report`),
  reportNarrative: (id) => req(`/api/episodes/${id}/report/narrative`, { method: 'POST' }),
  memberHistory: (id) => req(`/api/roster/${id}/history`),
  rosterHistory: (excludeEpisodeId) => req(`/api/roster/history${excludeEpisodeId ? `?exclude=${excludeEpisodeId}` : ''}`),
  addLesson: (episodeId, body) => req(`/api/episodes/${episodeId}/lessons`, { method: 'POST', body: JSON.stringify(body) }),
  importRoster: async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${BASE}/api/roster/import`, { method: 'POST', body: fd });
    return res.json();
  },
  // ---- outage ----
  electricityDependent: () => req('/api/outage/electricity-dependent'),
  reportOutage: (body) => req('/api/outage/report', { method: 'POST', body: JSON.stringify(body) }),
};

/** Subscribe to the live agent event stream. Returns [events, connected]. */
export function useEventStream(onEvent) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    let es;
    let closed = false;
    api.events().then((d) => setEvents(d.events || [])).catch(() => {});
    const open = () => {
      es = new EventSource(`${BASE}/api/events/stream`);
      es.onopen = () => setConnected(true);
      es.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data);
          setEvents((prev) => [...prev.slice(-400), ev]);
          cb.current && cb.current(ev);
        } catch { /* ignore */ }
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        if (!closed) setTimeout(open, 2500);
      };
    };
    open();
    return () => { closed = true; es && es.close(); };
  }, []);
  return [events, connected];
}

/** Poll a fetcher on an interval; refresh() forces a reload. */
export function usePoll(fetcher, ms, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  // Keep the last good payload on a transient failure; a blank screen mid-demo is worse than slightly stale data.
  const refresh = useCallback(
    () => fetcher().then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message)),
    deps,
  ); // eslint-disable-line
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, ms);
    return () => clearInterval(t);
  }, [refresh, ms]);
  return [data, refresh, error];
}

export function timeAgo(iso) {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function clock(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
