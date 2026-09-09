"""Demo community: a fictional block-captain roster in Maryvale, Phoenix AZ (real coordinates, fictional people).

Maryvale was chosen because Maricopa County records hundreds of heat-associated deaths every summer and
Phoenix NWS issues real Extreme Heat Warnings that this agent can act on live.
"""
from __future__ import annotations

from .models import Member, Resource, Volunteer

MEMBERS = [
    Member(id="mem_rosa", name="Rosa Alvarez", phone="+16025550101", language="es", preferred_channel="sms",
           address="4310 W Campbell Ave", lat=33.5017, lon=-112.1522,
           risk_factors=["age_75_plus", "lives_alone", "no_air_conditioning", "limited_english"],
           notes="Swamp cooler only. Daughter Marisol works days.", emergency_contact_name="Marisol Alvarez", emergency_contact_phone="+16025550102"),
    Member(id="mem_walter", name="Walter Boyd", phone="+16025550103", language="en", preferred_channel="voice",
           address="5106 N 43rd Dr", lat=33.5085, lon=-112.1505,
           risk_factors=["age_75_plus", "powered_medical_device", "mobility_limited"],
           notes="Home oxygen concentrator; loses it during outages.", emergency_contact_name="Denise Boyd", emergency_contact_phone="+16025550104",
           devices=["oxygen_concentrator"], backup_power_hours=2, utility="APS", backup_plan="Portable oxygen tank lasts about 2 hours; Denise can drive him to Banner Estrella."),
    Member(id="mem_thanh", name="Thanh Nguyen", phone="+16025550105", language="en", preferred_channel="sms",
           address="4742 N 47th Ave", lat=33.5062, lon=-112.1594,
           risk_factors=["chronic_illness", "no_transport"], notes="Dialysis Tue/Thu; needs rides when it's over 105.",
           devices=["home_dialysis"], backup_power_hours=0, utility="SRP", backup_plan="No backup power; clinic can take him in if a ride is arranged."),
    Member(id="mem_gloria", name="Gloria Mendoza", phone="+16025550106", language="es", preferred_channel="sms",
           address="3918 W Indian School Rd", lat=33.4947, lon=-112.1450,
           risk_factors=["infant_or_young_child", "no_air_conditioning"], notes="Two kids under 4. AC broke in July."),
    Member(id="mem_earl", name="Earl Jackson", phone="+16025550107", language="en", preferred_channel="sms",
           address="6002 W Osborn Rd", lat=33.4870, lon=-112.1870,
           risk_factors=["age_75_plus", "cognitive_impairment", "lives_alone"],
           notes="Early dementia; sometimes forgets to drink water.", emergency_contact_name="Pastor Ray Whitfield", emergency_contact_phone="+16025550108"),
    Member(id="mem_amina", name="Amina Yusuf", phone="+16025550109", language="en", preferred_channel="telegram", telegram_chat_id="",
           address="5535 W Thomas Rd", lat=33.4805, lon=-112.1790,
           risk_factors=["pregnant", "outdoor_worker"], notes="Third trimester; landscaping crew lead."),
    Member(id="mem_pete", name="Pete Kowalski", phone="+16025550110", language="en", preferred_channel="sms",
           address="4105 N 59th Ave", lat=33.4975, lon=-112.1860,
           risk_factors=["chronic_illness"], notes="Heart condition, has AC and a car."),
    Member(id="mem_lupe", name="Guadalupe Ortiz", phone="+16025550111", language="es", preferred_channel="sms",
           address="6120 W Clarendon Ave", lat=33.4925, lon=-112.1900,
           risk_factors=["age_75_plus", "mobility_limited", "no_transport"], notes="Uses a walker. Son visits weekends.",
           emergency_contact_name="Javier Ortiz", emergency_contact_phone="+16025550112"),
    Member(id="mem_danny", name="Danny Tran", phone="+16025550113", language="en", preferred_channel="sms",
           address="4820 N 51st Ave", lat=33.5075, lon=-112.1690,
           risk_factors=[], notes="Healthy, works from home, offered to help neighbors."),
    Member(id="mem_bettie", name="Bettie Harris", phone="+16025550114", language="en", preferred_channel="voice",
           address="3602 N 55th Ave", lat=33.4890, lon=-112.1780,
           risk_factors=["age_75_plus", "lives_alone"], notes="No cell phone, landline only. Hard of hearing.",
           emergency_contact_name="Carla Harris", emergency_contact_phone="+16025550115"),
    Member(id="mem_jorge", name="Jorge Ramirez", phone="+16025550116", language="es", preferred_channel="sms",
           address="5300 W Camelback Rd", lat=33.5100, lon=-112.1740,
           risk_factors=["outdoor_worker"], notes="Roofing crew; starts 5am."),
    Member(id="mem_helen", name="Helen Park", phone="+16025550117", language="en", preferred_channel="email", email="helen.park@example.com",
           address="4436 N 55th Ave", lat=33.5030, lon=-112.1785,
           risk_factors=["chronic_illness", "lives_alone"], notes="COPD; sensitive to smoke and dust.",
           devices=["cpap", "nebulizer"], backup_power_hours=6, utility="APS", backup_plan="CPAP battery pack lasts one night."),
]

VOLUNTEERS = [
    Volunteer(id="vol_marisol", name="Marisol Alvarez", phone="+16025550102", lat=33.5017, lon=-112.1522, skills=["spanish", "wellness_visit", "drive"], max_assignments=2),
    Volunteer(id="vol_ray", name="Pastor Ray Whitfield", phone="+16025550108", lat=33.4900, lon=-112.1800, skills=["wellness_visit", "phone_call"], max_assignments=3),
    Volunteer(id="vol_danny", name="Danny Tran", phone="+16025550113", lat=33.5075, lon=-112.1690, skills=["drive", "deliver", "wellness_visit"], max_assignments=2),
    Volunteer(id="vol_priya", name="Priya Natarajan (RN)", phone="+16025550118", lat=33.4960, lon=-112.1650, skills=["medical", "wellness_visit", "phone_call"], max_assignments=2),
]

# Real public buildings in Maryvale that Maricopa County's Heat Relief Network has used as cooling sites.
# Every value below was verified in September 2026 against the operator's own page (phoenixpubliclibrary.org,
# phoenix.gov Parks & Recreation, 211arizona.org) and coordinates against OpenStreetMap Nominatim.
# Hours are deliberately left for the coordinator to confirm each season: they change year to year and a wrong
# hour sends a vulnerable neighbor to a locked door.
RESOURCES = [
    Resource(id="res_paloverde", name="Palo Verde Library", kind="cooling_center",
             address="4402 N 51st Ave, Phoenix, AZ 85031",
             lat=33.5005, lon=-112.1698, hours="Confirm current hours",
             phone="+16022624636",  # Phoenix Public Library call center; no branch-direct line is published
             source="coordinator"),
    Resource(id="res_maryvalecc", name="Maryvale Community Center", kind="cooling_center",
             address="4420 N 51st Ave, Phoenix, AZ 85031",
             lat=33.5009, lon=-112.1697, hours="Confirm current hours",
             phone="+16022625030", source="coordinator"),
    Resource(id="res_desertwest", name="Desert West Community Center", kind="cooling_center",
             address="6501 W Virginia Ave, Phoenix, AZ 85035",
             lat=33.4760, lon=-112.2012, hours="Confirm current hours",
             phone="+16024953700", source="coordinator"),
    Resource(id="res_211", name="2-1-1 Arizona", kind="hydration", address="Phone service, statewide",
             lat=33.4942, lon=-112.1770,
             hours="Confirm current hours; live operators during heat season",
             phone="211", source="coordinator",
             notes="Statewide information line run by Solari. Finds cooling centers, water, utility help and transportation. Also 877-211-8661."),
]
