"""Hazard playbooks: one loop, any hazard.

The pipeline is the same for every hazard (assess -> triage -> outreach + logistics -> brief -> follow-up); what
changes is *which* risk factors matter, *what* a neighbor should do, and *where* "safe" is. Each playbook is
plain-language guidance distilled from public sources (CDC, NWS, EPA AirNow, Ready.gov, FEMA) so the agents
never have to invent protective advice. Risk-factor names are the RiskFactor literals in models.py so the
sentinel's structured output stays valid.

No medical advice beyond what the cited public guidance says. Keep entries short: they are injected into prompts.
"""
from __future__ import annotations

from typing import Any, TypedDict

from ..models import HazardType, RiskFactor


class Playbook(TypedDict):
    name: str
    elevated_risk_factors: list[RiskFactor]
    protective_actions: list[str]
    spanish_phrases: list[str]
    safe_place: str
    safe_place_es: str
    volunteer_tasks: list[str]
    escalation_triggers: list[str]
    sources: list[str]


PLAYBOOKS: dict[HazardType, Playbook] = {
    "heat": {
        "name": "Extreme heat",
        "elevated_risk_factors": ["no_air_conditioning", "age_75_plus", "lives_alone", "chronic_illness", "pregnant",
                                  "infant_or_young_child", "outdoor_worker", "powered_medical_device",
                                  "cognitive_impairment", "mobility_limited", "unhoused"],
        "protective_actions": [
            "Stay in air conditioning. If you have none at home, spend the hottest hours somewhere cool: a cooling center, library, mall or a neighbor's home.",
            "Drink water before you feel thirsty; skip alcohol and sugary drinks.",
            "A fan alone will not keep you safe once indoor temperatures pass about 90 F; take cool showers and use the fan with open windows only if outside air is cooler.",
            "Stay out of the sun in the afternoon; wear light, loose clothing.",
            "Never leave a person or pet in a parked car, even briefly.",
            "Check on older neighbors and people who live alone at least twice a day.",
        ],
        "spanish_phrases": [
            "Hace un calor peligroso. Manténgase fresco y tome agua, no espere a tener sed.",
            "Si no tiene aire acondicionado, vaya a un centro de enfriamiento.",
            "Llame al 911 si alguien está confundido, se desmaya o tiene la piel muy caliente.",
        ],
        "safe_place": "cooling center (library, senior center, mall, or any air-conditioned public building)",
        "safe_place_es": "centro de enfriamiento",
        "volunteer_tasks": [
            "Ride to the nearest cooling center for a neighbor without AC or transport.",
            "Deliver water and check the home's AC or fans are actually working.",
            "In-person wellness visit for anyone who did not reply.",
        ],
        "escalation_triggers": [
            "Signs of heat stroke: confusion, fainting, hot skin, body temperature 103 F or higher -> call 911 and cool the person while waiting.",
            "A tier-1 neighbor has not replied past the grace period.",
            "Power goes out at the home of anyone without a backup for AC or a powered medical device.",
        ],
        "sources": ["CDC Heat & Health (cdc.gov/heat-health)", "NWS Heat Safety (weather.gov/heat)"],
    },
    "cold": {
        "name": "Extreme cold / freeze",
        "elevated_risk_factors": ["age_75_plus", "lives_alone", "infant_or_young_child", "chronic_illness",
                                  "powered_medical_device", "unhoused", "outdoor_worker", "cognitive_impairment",
                                  "mobility_limited"],
        "protective_actions": [
            "Stay indoors as much as possible. Dress in loose layers; cover your head, hands and face outside.",
            "Make sure the heat is on and working. If the home cannot stay warm, go to a warming center or a neighbor with heat.",
            "Never heat a home with the oven, stove, grill or a generator indoors: carbon monoxide can kill.",
            "Keep space heaters 3 feet from anything that burns and turn them off when you sleep.",
            "Let faucets drip and open cabinet doors so pipes do not freeze.",
            "Check on older neighbors and anyone who lives alone.",
        ],
        "spanish_phrases": [
            "Hace un frío peligroso. Quédese adentro y abríguese en capas.",
            "Nunca use la estufa, el horno, una parrilla o un generador para calentar la casa.",
            "Si no tiene calefacción, vaya a un centro de calentamiento.",
        ],
        "safe_place": "warming center (or any heated public building; a neighbor's warm home if closer)",
        "safe_place_es": "centro de calentamiento",
        "volunteer_tasks": [
            "Ride to a warming center for anyone whose heat is out.",
            "Deliver blankets and confirm the furnace or space heater is safe and on.",
            "Wellness visit for anyone who did not reply; look for signs of a cold home.",
        ],
        "escalation_triggers": [
            "Signs of hypothermia: shivering that stops, confusion, slurred speech, drowsiness -> call 911.",
            "Headache, dizziness or nausea in a home using fuel for heat: get everyone outside and call 911 (carbon monoxide).",
            "No working heat in the home of a tier-1 neighbor, or a powered medical device without power.",
        ],
        "sources": ["CDC Extreme Cold (cdc.gov/winter-weather)", "NWS Wind Chill / Cold Safety (weather.gov/safety/cold)"],
    },
    "winter": {
        "name": "Winter storm",
        "elevated_risk_factors": ["age_75_plus", "lives_alone", "powered_medical_device", "chronic_illness",
                                  "mobility_limited", "no_transport", "infant_or_young_child", "unhoused",
                                  "cognitive_impairment"],
        "protective_actions": [
            "Stay off the roads once the storm starts; most winter deaths happen in vehicles.",
            "Before it hits: refill medicines, stock food and water for several days, charge phones and backup batteries, have flashlights ready.",
            "If the power fails, gather in one room, layer up, and close off unused rooms. Never heat with the oven or a grill.",
            "Generators stay outside, at least 20 feet from windows and doors.",
            "Know where your nearest warming center or shelter is before the roads close.",
        ],
        "spanish_phrases": [
            "Viene una tormenta de invierno. Quédese en casa y no maneje.",
            "Cargue su teléfono y tenga a mano sus medicinas, agua y comida para varios días.",
            "Si se va la luz, reúnanse en un solo cuarto y abríguense. Nunca use el horno para calentar la casa.",
        ],
        "safe_place": "warming center or shelter opened by the county; a nearby neighbor with heat and power",
        "safe_place_es": "centro de calentamiento o refugio",
        "volunteer_tasks": [
            "Pick up medications and groceries for homebound neighbors before the storm.",
            "Give rides to a warming center before roads become impassable.",
            "Clear ice and snow from doorways and walkways of neighbors with limited mobility.",
            "Daily phone check-in with anyone on a powered medical device while the power is out.",
        ],
        "escalation_triggers": [
            "Power outage at the home of anyone on oxygen, a ventilator or dialysis.",
            "No heat and no way to reach a warming center.",
            "Signs of hypothermia or carbon monoxide poisoning -> call 911.",
            "Anyone stranded on the road.",
        ],
        "sources": ["Ready.gov Snowstorms & Extreme Cold", "NWS Winter Safety (weather.gov/safety/winter)", "CDC Winter Weather"],
    },
    "air_quality": {
        "name": "Wildfire smoke / unhealthy air",
        "elevated_risk_factors": ["chronic_illness", "age_75_plus", "infant_or_young_child", "pregnant",
                                  "outdoor_worker", "powered_medical_device", "unhoused"],
        "protective_actions": [
            "Stay indoors with windows and doors closed. Run the AC on recirculate, or use a portable HEPA air cleaner in one room.",
            "Avoid hard outdoor activity. If you must be outside for long, a well-fitted N95 respirator helps; cloth and surgical masks do not.",
            "Do not add smoke indoors: no candles, frying, fireplaces or vacuuming.",
            "People with asthma, COPD or heart disease: follow your action plan and keep medicines and inhalers close.",
            "Check the current Air Quality Index at AirNow.gov; at 'Very Unhealthy' (201+) everyone should stay inside.",
        ],
        "spanish_phrases": [
            "El aire está contaminado por el humo. Quédese adentro con las ventanas cerradas.",
            "Si tiene que salir, use una mascarilla N95.",
            "Si tiene dificultad para respirar o dolor en el pecho, llame al 911.",
        ],
        "safe_place": "clean-air space: a library, mall, community center or shelter with filtered air conditioning",
        "safe_place_es": "espacio con aire limpio",
        "volunteer_tasks": [
            "Deliver N95 respirators or a portable air cleaner to neighbors with lung or heart disease.",
            "Ride to a clean-air space for anyone whose home has no AC or filtration.",
            "Pick up refills so people with asthma or COPD do not have to go out.",
            "Check on neighbors who use oxygen.",
        ],
        "escalation_triggers": [
            "Trouble breathing, wheezing that an inhaler does not relieve, or chest pain -> call 911.",
            "AQI reaches 'Hazardous' (301+) at the home of a tier-1 neighbor with no clean room.",
            "Power outage that stops AC or filtration during heavy smoke.",
        ],
        "sources": ["EPA AirNow Wildfire Smoke guidance (airnow.gov)", "CDC Wildfire Smoke (cdc.gov/wildfires)"],
    },
    "flood": {
        "name": "Flash flooding",
        "elevated_risk_factors": ["mobility_limited", "no_transport", "age_75_plus", "lives_alone", "cognitive_impairment",
                                  "infant_or_young_child", "powered_medical_device", "unhoused", "limited_english"],
        "protective_actions": [
            "Move to higher ground now; do not wait for the water to arrive.",
            "Turn around, don't drown: never walk or drive through flood water. Six inches can knock you down; a foot can float a car.",
            "Stay away from creeks, washes, storm drains and underpasses.",
            "If water enters the building, go to the highest level, not a closed attic.",
            "Do not touch flood water or downed power lines; do not go back until officials say it is safe.",
        ],
        "spanish_phrases": [
            "Hay inundaciones repentinas. Vaya a un lugar alto ahora.",
            "No camine ni maneje por el agua. ¡Dé la vuelta, no se ahogue!",
            "Si el agua entra a la casa, suba al piso más alto y llame al 911 si queda atrapado.",
        ],
        "safe_place": "higher ground: an upper floor, or a shelter or friend's home outside the low-lying area",
        "safe_place_es": "un lugar alto, fuera de la zona de inundación",
        "volunteer_tasks": [
            "Ride out of low-lying streets, mobile home parks and ground-floor units before roads flood.",
            "Help move medical equipment and medicines upstairs.",
            "Check on unhoused neighbors camped near creeks or washes.",
            "Welfare check by phone for anyone whose street is cut off.",
        ],
        "escalation_triggers": [
            "Water entering a home, or anyone trapped by rising water -> call 911.",
            "A tier-1 neighbor with limited mobility on a ground floor in the warned area has not replied.",
            "Roads to a neighbor are flooded and no volunteer can reach them safely.",
        ],
        "sources": ["NWS Turn Around Don't Drown (weather.gov/safety/flood)", "Ready.gov Floods"],
    },
    "storm": {
        "name": "Tornado / severe storm / hurricane",
        "elevated_risk_factors": ["mobility_limited", "age_75_plus", "lives_alone", "cognitive_impairment",
                                  "powered_medical_device", "unhoused", "no_transport", "infant_or_young_child",
                                  "limited_english"],
        "protective_actions": [
            "Go to the lowest floor, in an interior room away from windows: a bathroom, closet or hallway.",
            "Mobile homes and cars are not safe in a tornado; get to a sturdy building or a community shelter.",
            "Cover your head and neck; keep shoes and your phone with you.",
            "For a hurricane, follow local evacuation orders early and know your zone.",
            "After the storm: stay away from downed power lines, and get out if you smell gas.",
        ],
        "spanish_phrases": [
            "Hay una alerta de tormenta severa. Vaya a un cuarto interior en el piso más bajo, lejos de las ventanas.",
            "Una casa móvil o un carro no son seguros. Busque un edificio sólido o un refugio.",
            "Si hay heridos, daños graves u olor a gas, llame al 911.",
        ],
        "safe_place": "storm shelter, or an interior room on the lowest floor of a sturdy building",
        "safe_place_es": "refugio contra tormentas o un cuarto interior sin ventanas",
        "volunteer_tasks": [
            "Help a neighbor with limited mobility get to their safe room or a shelter before the storm arrives.",
            "Check on mobile-home residents ahead of time and confirm they have somewhere to go.",
            "Welfare checks by phone and in person once the storm has passed.",
        ],
        "escalation_triggers": [
            "Injuries, a collapsed or damaged structure, or a gas smell -> call 911.",
            "No contact with a tier-1 neighbor after the warning expires.",
            "A mobile-home resident with no sturdy shelter within reach.",
        ],
        "sources": ["NWS Tornado Safety (weather.gov/safety/tornado)", "Ready.gov Tornadoes and Hurricanes"],
    },
    "outage": {
        "name": "Power outage",
        "elevated_risk_factors": ["powered_medical_device", "age_75_plus", "chronic_illness", "no_air_conditioning",
                                  "infant_or_young_child", "mobility_limited", "cognitive_impairment", "lives_alone"],
        "protective_actions": [
            "Keep the refrigerator and freezer closed: food stays safe about 4 hours in a fridge and 48 hours in a full freezer.",
            "Generators run outside only, at least 20 feet from windows and doors. Never inside a garage.",
            "Use flashlights, not candles. Unplug appliances so they do not surge when power returns.",
            "If indoor temperatures get dangerous, go to a cooling or warming center while the power is out.",
            "If you rely on a powered medical device, switch to backup power and call your utility's medical program or your device supplier.",
        ],
        "spanish_phrases": [
            "Se fue la luz. Mantenga el refrigerador cerrado y use linternas, no velas.",
            "Nunca use un generador dentro de la casa ni en el garaje.",
            "Si usa un aparato médico eléctrico y se está quedando sin batería, avísenos ahora o llame al 911.",
        ],
        "safe_place": "a cooling or warming center depending on the weather, or any building with power where devices can charge",
        "safe_place_es": "un lugar con electricidad, como un centro de enfriamiento o calentamiento",
        "volunteer_tasks": [
            "Charge oxygen-concentrator or other device batteries at a home with power.",
            "Ride to a place with power and safe temperature.",
            "Deliver ice and a cooler for refrigerated medicines like insulin.",
            "Check on residents of high-rise buildings who cannot use the stairs.",
        ],
        "escalation_triggers": [
            "A life-sustaining medical device with only a few hours of battery -> utility priority line and 911 if needed.",
            "Indoor temperature becoming dangerous for an older or ill neighbor.",
            "Headache, dizziness or nausea in a home running a generator or fuel heater -> get outside, call 911.",
        ],
        "sources": ["Ready.gov Power Outages", "CDC Power Outage Safety (cdc.gov/disasters/poweroutage)"],
    },
    "other": {
        "name": "Other emergency",
        "elevated_risk_factors": ["lives_alone", "age_75_plus", "mobility_limited", "cognitive_impairment",
                                  "powered_medical_device", "limited_english", "no_transport"],
        "protective_actions": [
            "Follow the instructions in the official alert exactly; local officials know the situation best.",
            "Keep your phone charged and stay reachable.",
            "Check on neighbors who live alone or may not have heard the alert.",
        ],
        "spanish_phrases": [
            "Hay una alerta oficial para nuestra área. Siga las instrucciones de las autoridades.",
            "Estamos pendientes de usted. Responda para decirnos si está bien o si necesita ayuda.",
        ],
        "safe_place": "whatever place the official alert names; otherwise the nearest open public building",
        "safe_place_es": "el lugar que indiquen las autoridades",
        "volunteer_tasks": [
            "Phone and in-person welfare checks, starting with people who live alone.",
            "Rides for anyone told to leave who has no transport.",
        ],
        "escalation_triggers": [
            "Any neighbor reports they need help.",
            "A tier-1 neighbor has not replied past the grace period.",
        ],
        "sources": ["Ready.gov Make a Plan"],
    },
}


def get_playbook(hazard_type: str) -> Playbook:
    return PLAYBOOKS.get(hazard_type, PLAYBOOKS["other"])  # type: ignore[arg-type]


def playbook_text(hazard_type: str) -> str:
    """Compact plain-text rendering for injection into the graph task."""
    pb = get_playbook(hazard_type)
    lines = [f"PLAYBOOK FOR THIS HAZARD ({pb['name']}, hazard_type={hazard_type if hazard_type in PLAYBOOKS else 'other'}):",
             "Risk factors this hazard makes dangerous: " + ", ".join(pb["elevated_risk_factors"]) + ".",
             "Protective actions (plain language):"]
    lines += [f"  - {a}" for a in pb["protective_actions"]]
    lines.append("Key phrases in Spanish:")
    lines += [f"  - {s}" for s in pb["spanish_phrases"]]
    lines.append(f"Safe place for this hazard: {pb['safe_place']} (es: {pb['safe_place_es']}).")
    lines.append("Volunteer tasks that matter:")
    lines += [f"  - {t}" for t in pb["volunteer_tasks"]]
    lines.append("Escalate when:")
    lines += [f"  - {t}" for t in pb["escalation_triggers"]]
    lines.append("Guidance sources: " + "; ".join(pb["sources"]) + ".")
    return "\n".join(lines)


def playbook_summary(hazard_type: str) -> dict[str, Any]:
    """JSON-friendly copy for the API/UI."""
    pb = get_playbook(hazard_type)
    return {"hazard_type": hazard_type if hazard_type in PLAYBOOKS else "other", **pb}
