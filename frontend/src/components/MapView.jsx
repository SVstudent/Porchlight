import { MapContainer, TileLayer, CircleMarker, Popup, Marker } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const COLOR = { ok: '#2f6b5a', needs_help: '#c8412b', escalated: '#c8412b', sent: '#e39a2f', delivered: '#e39a2f', no_response: '#b8741a' };
const TIER = { 1: '#c8412b', 2: '#b8741a', 3: '#3a6a8a', 0: '#b9b3a6' };
const resIcon = L.divIcon({ className: '', html: '<div style="width:16px;height:16px;border-radius:3px;background:#3a6a8a;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>', iconSize: [16, 16], iconAnchor: [8, 8] });

export default function MapView({ members, resources, episode }) {
  if (!members.length) return null;
  const decisions = Object.fromEntries((episode?.triage?.decisions || []).map((d) => [d.member_id, d]));
  const checkins = Object.fromEntries((episode?.checkins || []).map((c) => [c.member_id, c]));
  const center = [members.reduce((s, m) => s + m.lat, 0) / members.length, members.reduce((s, m) => s + m.lon, 0) / members.length];
  return (
    <div className="map">
      <MapContainer center={center} zoom={13} scrollWheelZoom={false} style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {(resources || []).filter((r) => r.kind !== 'hydration').map((r) => (
          <Marker key={r.id} position={[r.lat, r.lon]} icon={resIcon}><Popup><b>{r.name}</b><br />{r.kind.replace('_', ' ')}<br />{r.address}</Popup></Marker>
        ))}
        {members.map((m) => {
          const c = checkins[m.id];
          const d = decisions[m.id];
          const color = c ? COLOR[c.status] : d ? TIER[d.tier] : '#b9b3a6';
          const r = d && d.tier === 1 ? 10 : 7;
          return (
            <CircleMarker key={m.id} center={[m.lat, m.lon]} radius={r} pathOptions={{ color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.95 }}>
              <Popup><b>{m.name}</b><br />{m.address}<br />{d ? `Tier ${d.tier}` : ''}{c ? ` · ${c.status.replace('_', ' ')}` : ''}</Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
