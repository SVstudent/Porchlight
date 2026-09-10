import { useEffect, useMemo, useRef } from 'react';
import { Map as MLMap, Marker, Popup, LngLatBounds, NavigationControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

/**
 * Neighbour map.
 *
 * MapLibre GL (the community fork of Mapbox GL) rendering OpenFreeMap vector tiles. Both are open
 * source and OpenFreeMap needs no API key, account or billing details — the style, the tiles, the
 * glyphs and the sprites are all public. openstreetmap.org's own raster tiles are deliberately not
 * used: their usage policy restricts that server to light use and asks that applications not be
 * distributed against it.
 *
 * "positron" is a deliberately muted basemap, so the neighbour markers carry the colour instead of
 * competing with road labels.
 */
const STYLE = 'https://tiles.openfreemap.org/styles/positron';

const COLOR = {
  ok: '#2f6b5a', needs_help: '#c8412b', escalated: '#c8412b',
  sent: '#e39a2f', delivered: '#e39a2f', no_response: '#b8741a',
};
const TIER = { 1: '#c8412b', 2: '#b8741a', 3: '#3a6a8a', 0: '#b9b3a6' };
const NEUTRAL = '#b9b3a6';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** A neighbour: coloured circle, larger when they are tier 1. */
function memberEl(color, big) {
  const d = big ? 22 : 16;
  const el = document.createElement('div');
  el.style.cssText = `width:${d}px;height:${d}px;border-radius:50%;background:${color};`
    + 'border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);cursor:pointer';
  return el;
}

/** A cooling centre or other community resource: square, so it reads differently at a glance. */
function resourceEl() {
  const el = document.createElement('div');
  el.style.cssText = 'width:15px;height:15px;border-radius:3px;background:#3a6a8a;'
    + 'border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);cursor:pointer';
  return el;
}

export default function MapView({ members, resources, episode }) {
  const holder = useRef(null);
  const map = useRef(null);
  const markers = useRef([]);

  const shown = useMemo(
    () => (resources || []).filter((r) => r.kind !== 'hydration'),
    [resources],
  );

  // What each neighbour looks like right now: their triage tier until they answer, then their reply.
  const points = useMemo(() => {
    const decisions = Object.fromEntries((episode?.triage?.decisions || []).map((d) => [d.member_id, d]));
    const checkins = Object.fromEntries((episode?.checkins || []).map((c) => [c.member_id, c]));
    return [
      ...members.map((m) => {
        const c = checkins[m.id];
        const d = decisions[m.id];
        return {
          key: `m-${m.id}`,
          lat: m.lat,
          lon: m.lon,
          el: () => memberEl(c ? COLOR[c.status] || NEUTRAL : d ? TIER[d.tier] : NEUTRAL, d?.tier === 1),
          html: `<b>${esc(m.name)}</b><br>${esc(m.address)}`
            + (d ? `<br>Tier ${esc(d.tier)}` : '')
            + (c ? ` · ${esc(String(c.status).replace(/_/g, ' '))}` : ''),
        };
      }),
      ...shown.map((r) => ({
        key: `r-${r.id}`,
        lat: r.lat,
        lon: r.lon,
        el: resourceEl,
        html: `<b>${esc(r.name)}</b><br>${esc(String(r.kind).replace(/_/g, ' '))}<br>${esc(r.address)}`,
      })),
    ].filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  }, [members, shown, episode]);

  // Create the map once.
  useEffect(() => {
    if (map.current || !holder.current || !points.length) return undefined;
    const m = new MLMap({
      container: holder.current,
      style: STYLE,
      center: [points[0].lon, points[0].lat],
      zoom: 12,
      attributionControl: { compact: true },
      // The map sits inside a scrolling column; grabbing the page's scroll would be hostile.
      scrollZoom: false,
    });
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, [points.length]);

  // Redraw the markers whenever tiers or replies change, and keep everything in frame.
  useEffect(() => {
    const m = map.current;
    if (!m || !points.length) return;

    const draw = () => {
      markers.current.forEach((mk) => mk.remove());
      markers.current = points.map((p) => new Marker({ element: p.el() })
        .setLngLat([p.lon, p.lat])
        .setPopup(new Popup({ offset: 14, closeButton: false }).setHTML(p.html))
        .addTo(m));

      const b = points.reduce(
        (acc, p) => acc.extend([p.lon, p.lat]),
        new LngLatBounds([points[0].lon, points[0].lat], [points[0].lon, points[0].lat]),
      );
      m.fitBounds(b, { padding: 48, maxZoom: 15, animate: false });
    };

    if (m.isStyleLoaded()) draw();
    else m.once('load', draw);
  }, [points]);

  if (!members.length) return null;
  return <div className="map" ref={holder} />;
}
