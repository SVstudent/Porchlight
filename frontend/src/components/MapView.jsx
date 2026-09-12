import { useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, Marker, Polyline, GeoJSON, Rectangle, useMap } from 'react-leaflet';
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
// The watch list's one-word verdict, straight to a colour.
const STATE_COLOR = {
  critical: '#8c1d11', needs_help: '#c8412b', waiting: '#e39a2f',
  ok: '#2f6b5a', not_contacted: '#b9b3a6',
};

/** A responder in transit: a filled dot with a ring, so it reads as moving rather than placed. */
const responderIcon = L.divIcon({
  className: '',
  html: '<div style="width:16px;height:16px;border-radius:50%;background:#2f6b5a;border:3px solid #fff;'
    + 'box-shadow:0 0 0 3px rgba(47,107,90,.3),0 1px 4px rgba(0,0,0,.4)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const resourceIcon = L.divIcon({
  className: '',
  html: '<div style="width:15px;height:15px;border-radius:3px;background:#3a6a8a;'
    + 'border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>',
  iconSize: [15, 15],
  iconAnchor: [7, 7],
});

/** Frame every neighbour and every resource, rather than guessing a zoom that may cut one off. */
function FitToData({ points }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 14);
      return;
    }
    map.fitBounds(L.latLngBounds(points).pad(0.15), { animate: false });
  }, [map, points]);
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
    () => deployments.filter((d) => d.status === 'approved' && (d.route || []).length > 1),
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

  if (!people.length) return null;
  const center = [
    people.reduce((s, m) => s + m.lat, 0) / people.length,
    people.reduce((s, m) => s + m.lon, 0) / people.length,
  ];

  return (
    <div className="map">
      <MapContainer center={center} zoom={13} scrollWheelZoom={false} style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution={ATTRIBUTION} url={BASEMAP} maxZoom={20} />
        <FitToData points={points} />

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
                    pathOptions={{ color: '#b8741a', weight: 3, opacity: 0.45, dashArray: '4 7' }} />
        ))}

        {/* An approved trip: the road actually being driven, and where they should be by now. */}
        {live.map((d) => (
          <Polyline key={`r-${d.id}`} positions={d.route}
                    pathOptions={{ color: '#c8412b', weight: 4, opacity: 0.85, dashArray: '8 6' }} />
        ))}
        {live.filter((d) => d.position).map((d) => (
          <Marker key={`v-${d.id}`} position={d.position} icon={responderIcon} zIndexOffset={1000}>
            <Popup>
              <b>{d.responder_name}</b> → {d.member_name}<br />
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
