import { useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, Marker, useMap } from 'react-leaflet';
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

export default function MapView({ members, resources, episode }) {
  const shown = useMemo(
    () => (resources || []).filter((r) => r.kind !== 'hydration' && Number.isFinite(r.lat)),
    [resources],
  );
  const people = useMemo(
    () => (members || []).filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lon)),
    [members],
  );
  const points = useMemo(
    () => [...people.map((m) => [m.lat, m.lon]), ...shown.map((r) => [r.lat, r.lon])],
    [people, shown],
  );

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
          const color = c ? COLOR[c.status] || NEUTRAL : d ? TIER[d.tier] : NEUTRAL;
          return (
            <CircleMarker
              key={m.id}
              center={[m.lat, m.lon]}
              radius={d && d.tier === 1 ? 10 : 7}
              pathOptions={{ color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.95 }}
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
