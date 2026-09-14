import { useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Marker, Polyline, GeoJSON, Rectangle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

/**
 * Neighbour map: who is at risk, where, and how far they are from somewhere cooled.
 *
 * Leaflet with CARTO's Positron raster tiles. Both are open and need no API key, account or billing
 * details. Two deliberate choices:
 *
 * - **Raster, not vector.** MapLibre GL on OpenFreeMap vector tiles was tried first and renders nothing
 *   on an older Intel Mac: the canvas initialises, WebGL2 reports healthy, the style fetches fine from
 *   the page, and the map silently never loads, in a production build as well as in dev. Raster tiles
 *   are plain images, which work anywhere a browser does. A basemap is not where a demo should spend
 *   its reliability budget.
 * - **OpenStreetMap's own tiles.** CARTO's basemaps were tried and now return a tile stamped
 *   "API KEY REQUIRED" — they answer 200 with a valid PNG, so only looking at the rendered pixels
 *   catches it. Esri's free layers render but are too sparse at this zoom to place a neighbour.
 *
 * The OSMF tile usage policy asks that applications not be distributed against tile.openstreetmap.org.
 * A coordinator running Porchlight for one neighbourhood is squarely within its light-use allowance; a
 * deployment serving many communities should point BASEMAP at a provider it has an agreement with, or
 * self-host. That is a one-line change and the only thing that needs to change.
 */
const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const COLOR = {
  ok: '#2f6b5a', needs_help: '#c8412b', escalated: '#c8412b', critical: '#8c1d11',
  sent: '#e39a2f', delivered: '#e39a2f', no_response: '#b8741a',
};
const TIER = { 1: '#c8412b', 2: '#b8741a', 3: '#3a6a8a', 0: '#b9b3a6' };
const NEUTRAL = '#b9b3a6';
// Where to look when there is no roster yet: the community this is set up for.
const FALLBACK_CENTRE = [33.4955, -112.1680];
// The watch list's one-word verdict, straight to a colour.
const STATE_COLOR = {
  critical: '#8c1d11', needs_help: '#c8412b', waiting: '#e39a2f',
  ok: '#2f6b5a', not_contacted: '#b9b3a6',
};

// Several responders can be moving at once, so each trip gets its own colour and each marker carries
// the name. Without that a coordinator has to hunt for which dot is which, which defeats the map.
const TRIP_COLOURS = ['#c8412b', '#2f6b5a', '#8c5bc4', '#1f6f8b', '#b8741a', '#7a4b2a'];
const tripColour = (i) => TRIP_COLOURS[i % TRIP_COLOURS.length];

/** A responder in transit: their initials in a coloured disc, so several are told apart at a glance. */
function responderIcon(colour, initials) {
  return L.divIcon({
    className: '',
    html: `<div style="width:26px;height:26px;border-radius:50%;background:${colour};color:#fff;`
      + 'border:3px solid #fff;box-shadow:0 0 0 3px rgba(0,0,0,.18),0 2px 6px rgba(0,0,0,.35);'
      + 'display:flex;align-items:center;justify-content:center;font:600 10px/1 system-ui,sans-serif;'
      + `letter-spacing:.02em">${initials}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

const initialsOf = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2)
  .map((w) => w[0]).join('').toUpperCase() || '?';

const resourceIcon = L.divIcon({
  className: '',
  html: '<div style="width:15px;height:15px;border-radius:3px;background:#3a6a8a;'
    + 'border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>',
  iconSize: [15, 15],
  iconAnchor: [7, 7],
});

/**
 * Frame everything worth seeing — but only when what is worth seeing actually changes.
 *
 * The points array is rebuilt on every render, so depending on its identity refits the map constantly:
 * hovering a card was enough to yank the view back, and because the fit covers every neighbour, every
 * resource and every route, the person being hovered ended up wherever that box happened to put them —
 * usually the edge. Comparing the contents instead means the map holds still unless the data moved.
 */
function FitToData({ points, suspended }) {
  const map = useMap();
  const signature = points.map((p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`).sort().join('|');
  const last = useRef('');
  useEffect(() => {
    // While the coordinator is looking at one neighbour, the fit must not drag the view off them.
    // A responder moving changes the point set every few seconds, which is exactly when this fires.
    if (suspended) return;
    if (!signature || signature === last.current) return;
    last.current = signature;
    if (points.length === 1) {
      map.setView(points[0], 15);
      return;
    }
    map.fitBounds(L.latLngBounds(points).pad(0.15), { animate: false });
  }, [map, signature, suspended]);   // deliberately not `points`: identity changes every render
  return null;
}

/**
 * Keep Leaflet's idea of its own size in step with the element it lives in.
 *
 * The map shares its column with the decision cards and the trip list, which appear and disappear as a
 * run progresses and change the map's height underneath it. Leaflet caches the container size at
 * initialisation, so without this every calculation that depends on it — centring most visibly — is
 * off by however much the element has changed since. It showed up as a hovered neighbour landing a
 * fifth of the way below the middle, the same distance every time.
 */
function KeepSized() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    map.invalidateSize({ animate: false });
    const ro = new ResizeObserver(() => map.invalidateSize({ animate: false }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

/**
 * Bring the hovered neighbour to the middle of the map, without changing the zoom.
 *
 * Panning is the right gesture here: a coordinator running their eye down the list wants to see where
 * each person is in the context they already have, not to be re-framed on every mouse move.
 */
function CentreOn({ point }) {
  const map = useMap();
  const lat = point ? point[0] : null;
  const lon = point ? point[1] : null;
  useEffect(() => {
    if (lat == null || lon == null) return;
    // setView rather than panTo: a pan is a request that a competing fit or a long distance can leave
    // half-finished, which is how a hovered neighbour kept ending up near the edge instead of the
    // middle. The zoom is kept so the surroundings a coordinator already has stay put.
    map.setView([lat, lon], map.getZoom(), { animate: true, duration: 0.3 });
  }, [map, lat, lon]);
  return null;
}

/** Cool blue through to hot red, for whatever the conditions field is measuring. */
function fieldColor(value, min, max) {
  if (value == null || min == null || max == null || max <= min) return '#9aa7ab';
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
  // A deliberately short ramp: the point is to see where the gradient is, not to read a value off it.
  const stops = [[74, 126, 156], [122, 163, 150], [214, 179, 96], [200, 111, 51], [176, 45, 31]];
  const i = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  const f = t * (stops.length - 1) - i;
  const [a, b] = [stops[i], stops[i + 1]];
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export default function MapView({ members, resources, episode, deployments = [], highlight = null,
                                  layers = null, showField = true, showFootprint = true }) {
  const shown = useMemo(
    () => (resources || []).filter((r) => r.kind !== 'hydration' && Number.isFinite(r.lat)),
    [resources],
  );
  const people = useMemo(
    () => (members || []).filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lon)),
    [members],
  );
  // Approved trips are drawn on the map; a declined one is not a journey anybody is making.
  const live = useMemo(
    () => deployments.filter((d) => d.status === 'approved'
      && (d.route || []).length > 1
      && (d.progress || 0) < 1
      && !d.arrived_at),
    [deployments],
  );
  const proposed = useMemo(
    () => deployments.filter((d) => d.status === 'proposed' && (d.route || []).length > 1),
    [deployments],
  );

  const points = useMemo(
    () => [
      ...people.map((m) => [m.lat, m.lon]),
      ...shown.map((r) => [r.lat, r.lon]),
      ...live.flatMap((d) => d.route),
    ],
    [people, shown, live],
  );

  const field = layers?.field || { cells: [], min: null, max: null, metric: '', unit: '' };
  const footprint = layers?.footprint || { kind: 'none', parts: [] };

  const decisions = Object.fromEntries((episode?.triage?.decisions || []).map((d) => [d.member_id, d]));
  const checkins = Object.fromEntries((episode?.checkins || []).map((c) => [c.member_id, c]));

  // Never unmount. The map is the centre of this screen, and a reload that briefly returns no
  // neighbours used to make it vanish entirely — taking its tiles, its hazard layers and the user's
  // pan and zoom with it. With no roster yet it simply shows the neighbourhood.
  const center = people.length
    ? [people.reduce((s, m) => s + m.lat, 0) / people.length,
       people.reduce((s, m) => s + m.lon, 0) / people.length]
    : [FALLBACK_CENTRE[0], FALLBACK_CENTRE[1]];

  const highlighted = people.find((m) => m.id === highlight);

  return (
    <div className="map">
      <MapContainer center={center} zoom={13} scrollWheelZoom={false} style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution={ATTRIBUTION} url={BASEMAP} maxZoom={20} />
        <KeepSized />
        <FitToData points={points} suspended={!!highlighted} />
        <CentreOn point={highlighted ? [highlighted.lat, highlighted.lon] : null} />

        {/* The conditions actually measured across the neighbourhood, underneath everything else.
            A warning is issued for a whole county; this is the part of it that is about one street. */}
        {showField && field.cells.length ? field.cells.map((c, i) => (
          <Rectangle
            key={`f-${i}`}
            bounds={c.bounds}
            pathOptions={{
              stroke: false,
              fillColor: fieldColor(c.value, field.min, field.max),
              fillOpacity: 0.38,
            }}
          >
            <Popup>
              <b>{field.metric} {c.value}{field.unit}</b><br />
              measured here, not at the centre of town<br />
              <i style={{ fontSize: 11 }}>{field.source}</i>
            </Popup>
          </Rectangle>
        )) : null}

        {/* The National Weather Service's own shape for this hazard. */}
        {showFootprint && footprint.parts.map((part, i) => (
          <GeoJSON
            key={`fp-${i}-${footprint.kind}`}
            data={part.geometry}
            // Outline only. An alert can name a dozen zones, and a dozen translucent fills stacked on
            // top of each other turn the whole map red and bury the conditions underneath.
            style={{ color: '#8c1d11', weight: 1.6, opacity: 0.65, fill: false }}
          >
            <Popup>
              <b>{footprint.event_name}</b><br />
              {part.name}<br />
              <i style={{ fontSize: 11 }}>
                {footprint.kind === 'alert_polygon'
                  ? 'The forecaster’s own warning polygon'
                  : 'National Weather Service forecast zone named by this alert'}
              </i>
            </Popup>
          </GeoJSON>
        ))}

        {/* A suggested trip, faint: nobody has agreed to make it yet. */}
        {proposed.map((d) => (
          <Polyline key={`p-${d.id}`} positions={d.route}
                    pathOptions={{ color: '#b8741a', weight: 3, opacity: 0.4, dashArray: '4 7' }} />
        ))}

        {/* Approved trips still under way. Each keeps one colour across its line, its marker and its
            label, so several running at once stay distinguishable. Arrived trips are gone from `live`
            entirely: their line and their marker come off the map rather than lingering. */}
        {live.map((d, i) => (
          <Polyline key={`r-${d.id}`} positions={d.route}
                    pathOptions={{ color: tripColour(i), weight: 5, opacity: 0.9, dashArray: '9 6' }} />
        ))}
        {live.filter((d) => d.position).map((d, i) => (
          <Marker key={`v-${d.id}`} position={d.position}
                  icon={responderIcon(tripColour(i), initialsOf(d.responder_name))}
                  zIndexOffset={1000}>
            <Tooltip permanent direction="right" offset={[15, 0]} className="trip-label">
              <b>{d.responder_name}</b> → {d.member_name}
              <span className="trip-eta">
                {Math.max(0, Math.round((d.eta_seconds || 0) / 60))} min
              </span>
            </Tooltip>
            <Popup>
              <b>{d.responder_name}</b> → {d.member_name}<br />
              {(d.task || '').replace(/_/g, ' ')}
              {d.destination_name ? <> → {d.destination_name}</> : null}<br />
              {Math.round((d.progress || 0) * 100)}% of the way · about {Math.max(0, Math.round((d.eta_seconds || 0) / 60))} min left
              <br /><i style={{ fontSize: 11 }}>Estimated from the route, not a GPS position.</i>
            </Popup>
          </Marker>
        ))}

        {shown.map((r) => (
          <Marker key={r.id} position={[r.lat, r.lon]} icon={resourceIcon}>
            <Popup>
              <b>{r.name}</b><br />{String(r.kind).replace(/_/g, ' ')}<br />{r.address}
            </Popup>
          </Marker>
        ))}

        {people.map((m) => {
          const c = checkins[m.id];
          const d = decisions[m.id];
          // The watch list hands us a neighbour's state directly; an episode view derives it.
          const color = STATE_COLOR[m.state]
            || (c ? COLOR[c.status] || NEUTRAL : d ? TIER[d.tier] : NEUTRAL);
          const urgent = m.state === 'critical' || m.state === 'needs_help' || (d && d.tier === 1);
          const lit = highlight === m.id;
          return (
            <CircleMarker
              key={m.id}
              center={[m.lat, m.lon]}
              radius={lit ? 14 : urgent ? 10 : 7}
              pathOptions={{
                color: lit ? '#1e2a2b' : '#fff',
                weight: lit ? 3 : 2,
                fillColor: color,
                fillOpacity: 0.95,
              }}
            >
              <Popup>
                <b>{m.name}</b><br />{m.address}
                {d ? <><br />Tier {d.tier}</> : null}
                {c ? ` · ${String(c.status).replace(/_/g, ' ')}` : ''}
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
