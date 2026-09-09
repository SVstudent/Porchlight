import { Flame, ThermometerSnowflake, Snowflake, CloudFog, Waves, CloudLightning, PlugZap, TriangleAlert } from 'lucide-react';

// One visual vocabulary for every hazard the pipeline handles (models.py HazardType).
export const HAZARDS = {
  heat: { label: 'Heat', Icon: Flame },
  cold: { label: 'Cold', Icon: ThermometerSnowflake },
  winter: { label: 'Winter storm', Icon: Snowflake },
  air_quality: { label: 'Smoke / air', Icon: CloudFog },
  flood: { label: 'Flood', Icon: Waves },
  storm: { label: 'Storm', Icon: CloudLightning },
  outage: { label: 'Outage', Icon: PlugZap },
  other: { label: 'Other', Icon: TriangleAlert },
};

export default function HazardPill({ type, size = 12, className = '' }) {
  const h = HAZARDS[type] || HAZARDS.other;
  const Icon = h.Icon;
  return (
    <span className={`pill small hz hz-${HAZARDS[type] ? type : 'other'} ${className}`} title={`Hazard type: ${h.label}`}>
      <Icon size={size} /> {h.label}
    </span>
  );
}
