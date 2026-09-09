"""Power-outage tools: who on the roster depends on electricity to stay alive.

A power outage is deadly for neighbors on oxygen concentrators, ventilators, CPAP, home dialysis, powered
wheelchairs, or refrigerated medication, and it compounds heat and cold. This module is the single source of
truth for that list; the /api/outage endpoints and the agents' tool both use it.
"""
from __future__ import annotations

from typing import Any

from strands import tool

from ..store import store

DEVICE_LABELS = {
    "oxygen_concentrator": "oxygen concentrator",
    "ventilator": "ventilator",
    "cpap": "CPAP",
    "home_dialysis": "home dialysis",
    "powered_wheelchair": "powered wheelchair",
    "refrigerated_medication": "refrigerated medication",
    "nebulizer": "nebulizer",
}


def electricity_dependent_members() -> list[dict[str, Any]]:
    """Opted-in members with a powered medical device (declared devices or the powered_medical_device risk
    factor), sorted so the neighbor with the least backup runtime comes first."""
    out: list[dict[str, Any]] = []
    for m in store.members():
        if not m.opted_in:
            continue
        if not m.devices and "powered_medical_device" not in m.risk_factors:
            continue
        out.append({
            "member_id": m.id,
            "name": m.name,
            "language": m.language,
            "preferred_channel": m.preferred_channel,
            "address": m.address,
            "lat": m.lat,
            "lon": m.lon,
            "devices": list(m.devices),
            "device_labels": [DEVICE_LABELS.get(d, d.replace("_", " ")) for d in m.devices],
            "backup_power_hours": float(m.backup_power_hours or 0),
            "utility": m.utility,
            "backup_plan": m.backup_plan,
            "risk_factors": list(m.risk_factors),
            "notes": m.notes,
            "emergency_contact_name": m.emergency_contact_name,
            "emergency_contact_phone": m.emergency_contact_phone,
        })
    out.sort(key=lambda d: (d["backup_power_hours"], d["name"]))
    return out


@tool
def get_electricity_dependent_members() -> list[dict]:
    """List neighbors who depend on electricity for a medical device (oxygen concentrator, ventilator, CPAP,
    home dialysis, powered wheelchair, refrigerated medication, nebulizer), with how many hours of battery or
    backup power they have, which utility serves them, their backup plan, and their emergency contact.
    Sorted by least backup runtime first. During a power outage, or an outage on top of heat or cold, every one
    of these neighbors is life-threatening priority; under 4 hours of backup means someone must go in person."""
    return electricity_dependent_members()
