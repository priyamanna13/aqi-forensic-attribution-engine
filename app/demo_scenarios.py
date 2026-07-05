"""Per-station demo scenario profiles for the hackathon.

Each scenario defines a unique station with its own coordinates, AQI spike
characteristics, weather conditions, pollution source candidates, and
pre-alert messages.  The API picks the matching profile by station_name
(case-insensitive) and feeds it into the existing pipeline.

Stations:
  1. Shivajinagar  — Baseline / Construction Spike (PM10 dominant)
  2. Swargate      — Heavy Traffic Corridor Spike (NO2 dominant)
  3. Hadapsar      — Industrial Emission / Factory Spike (SO2 dominant)
  4. Kothrud       — Ambiguity Scenario, multi-source flag (PM2.5 dominant)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DemoScenario:
    """All tuneable knobs for one demo station."""

    station_name: str
    city: str
    state: str
    network: str
    coordinates: tuple[float, float]   # (lon, lat) GeoJSON order
    elevation_m: int
    spike_aqi: int
    spike_local_time: str              # "HH:MM"
    dominant_pollutant: str
    # Override base pollutant profile so each station has a distinct chemical
    # fingerprint (CO in mg/m³, rest in µg/m³).
    base_profile: dict[str, float]
    # Override peak ratios so the dominant pollutant changes per scenario.
    peak_ratios: dict[str, float]
    # Weather overrides (blended into the mock weather source at spike time).
    weather_overrides: dict[str, float]
    # Candidate sources local to this station.
    candidates: list[dict[str, Any]]
    # Pre-alert block for the frontend panel.
    pre_alerts: dict[str, Any]
    # Field team assignment.
    field_team: dict[str, Any]


# =========================================================================== #
# 1. SHIVAJINAGAR — Construction Spike (Baseline)
# =========================================================================== #
_SHIVAJINAGAR = DemoScenario(
    station_name="Shivajinagar",
    city="Pune",
    state="Maharashtra",
    network="CPCB_CAAQMS",
    coordinates=(73.8567, 18.5308),
    elevation_m=560,
    spike_aqi=310,
    spike_local_time="08:30",
    dominant_pollutant="pm10",
    base_profile={
        "pm25": 45.0, "pm10": 80.0, "no2": 35.0,
        "so2": 25.0, "co": 1.2, "o3": 35.0,
    },
    peak_ratios={
        "pm25_pm10": 0.35,
        "no2": 0.20, "so2": 0.14, "o3": 0.12,
        "co_per_pm10": 0.009,
    },
    weather_overrides={
        "wind_speed_kmh": 14.5,
        "wind_direction_deg": 290,
        "temperature_c": 31.4,
        "relative_humidity_pct": 62,
        "pressure_hpa": 1006.3,
        "cloud_cover_oktas": 3,
        "precipitation_mm_last_1h": 0.0,
        "visibility_km": 4.2,
        "mixing_layer_height_m": 850,
    },
    candidates=[
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "hinjewadi-phase3-construction")),
            "name": "Hinjewadi Phase-III Construction Cluster",
            "type": "construction",
            "description": (
                "Large-scale residential and commercial construction activity "
                "in Hinjewadi Phase III. Multiple active sites with earth-moving, "
                "concrete batching, and demolition generating fugitive dust."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8215, 18.5487], [73.8241, 18.5487],
                    [73.8241, 18.5512], [73.8215, 18.5512],
                    [73.8215, 18.5487],
                ]],
            },
            "permit_id": "PMC/CONST/2026/04781",
            "schedule_start": "07:00", "schedule_end": "19:00",
            "near_school": True, "school_name": "Vibgyor High School, Balewadi",
            "school_distance_m": 380,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": True, "dust_suppression_observed": False,
            "last_inspection_date": "2026-05-18", "violation_count_90d": 3,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "pcmc-industrial-zone-unit14-acc")),
            "name": "Pimpri-Chinchwad Industrial Zone — Unit 14 (ACC Cement Silo)",
            "type": "industrial",
            "description": (
                "ACC Cement bulk silo and bagging plant in PCMC industrial zone."
            ),
            "geometry": {"type": "Point", "coordinates": [73.8193, 18.5548]},
            "permit_id": "MPCB/IND/PUN/2024/11923",
            "schedule_start": "06:00", "schedule_end": "22:00",
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": True, "hospital_name": "Aditya Birla Memorial Hospital",
            "hospital_distance_m": 620,
            "dust_suppression_required": True, "dust_suppression_observed": True,
            "last_inspection_date": "2026-06-10", "violation_count_90d": 1,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "mumbai-pune-expressway-wakad")),
            "name": "Mumbai–Pune Expressway Entry Corridor (Wakad Toll Plaza)",
            "type": "traffic",
            "description": "High-traffic corridor at the Wakad toll-plaza entry.",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [73.8168, 18.5491], [73.8201, 18.5463],
                    [73.8239, 18.5435], [73.8274, 18.5411],
                ],
            },
            "permit_id": None,
            "schedule_start": "00:00", "schedule_end": "23:59",
            "near_school": True, "school_name": "Delhi Public School, Wakad",
            "school_distance_m": 510,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 0,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "mula-mutha-riverbank-waste-burning")),
            "name": "Mula-Mutha Riverbank Open Waste Burning Site",
            "type": "waste_burning",
            "description": "Unregulated open-air waste burning along the Mula-Mutha riverbank.",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8302, 18.5395], [73.8328, 18.5395],
                    [73.8328, 18.5418], [73.8302, 18.5418],
                    [73.8302, 18.5395],
                ]],
            },
            "permit_id": None,
            "schedule_start": None, "schedule_end": None,
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": True, "hospital_name": "Sahyadri Super Speciality Hospital",
            "hospital_distance_m": 440,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 7,
        },
    ],
    pre_alerts={
        "source": "Hinjewadi Phase-III Construction Cluster",
        "eta_minutes": 34,
        "estimated_aqi_increase": 45,
        "advisory": "Construction schedule active. Heavy dust dispersion predicted.",
    },
    field_team={
        "team_id": "PMC-AQ-SQUAD-07",
        "team_lead": "Inspector R. S. Kulkarni",
        "contact": "+91-20-XXXX-XXXX",
        "eta_minutes": 18,
    },
)


# =========================================================================== #
# 2. SWARGATE — Heavy Traffic Corridor Spike (NO2 dominant)
# =========================================================================== #
_SWARGATE = DemoScenario(
    station_name="Swargate",
    city="Pune",
    state="Maharashtra",
    network="CPCB_CAAQMS",
    coordinates=(73.8553, 18.5018),
    elevation_m=555,
    spike_aqi=285,
    spike_local_time="09:15",
    dominant_pollutant="no2",
    base_profile={
        "pm25": 30.0, "pm10": 50.0, "no2": 75.0,
        "so2": 12.0, "co": 2.8, "o3": 20.0,
    },
    peak_ratios={
        "pm25_pm10": 0.20,    # low PM2.5 so it doesn't steal dominance
        "no2": 1.20,          # NO2 is the star — very high ratio to dominate AQI
        "so2": 0.06,
        "o3": 0.04,
        "co_per_pm10": 0.022, # high CO from traffic
    },
    weather_overrides={
        "wind_speed_kmh": 8.2,
        "wind_direction_deg": 210,
        "temperature_c": 33.1,
        "relative_humidity_pct": 55,
        "pressure_hpa": 1005.8,
        "cloud_cover_oktas": 2,
        "precipitation_mm_last_1h": 0.0,
        "visibility_km": 3.8,
        "mixing_layer_height_m": 720,
    },
    candidates=[
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "swargate-bus-depot")),
            "name": "Swargate ST Bus Depot & Diesel Terminal",
            "type": "traffic",
            "description": (
                "Maharashtra State Road Transport Corporation (MSRTC) central "
                "bus depot. 400+ diesel buses idling, departing, and arriving "
                "during peak hours. Major source of NO2 and PM2.5."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8535, 18.5005], [73.8570, 18.5005],
                    [73.8570, 18.5030], [73.8535, 18.5030],
                    [73.8535, 18.5005],
                ]],
            },
            "permit_id": None,
            "schedule_start": "05:00", "schedule_end": "23:30",
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": True, "hospital_name": "Sassoon General Hospital",
            "hospital_distance_m": 850,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": "2026-04-22", "violation_count_90d": 0,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "swargate-chowk-traffic")),
            "name": "Swargate Chowk — Multi-Signal Traffic Bottleneck",
            "type": "traffic",
            "description": (
                "One of Pune's busiest intersections. Stop-and-go congestion "
                "with 5,000+ vehicles/hour during morning rush. Heavy diesel "
                "trucks, autos, and two-wheelers."
            ),
            "geometry": {
                "type": "Point",
                "coordinates": [73.8548, 18.5012],
            },
            "permit_id": None,
            "schedule_start": "00:00", "schedule_end": "23:59",
            "near_school": True, "school_name": "Nutan Marathi Vidyalaya",
            "school_distance_m": 290,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 0,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "pmc-road-construction-swargate")),
            "name": "PMC Metro Construction — Swargate Station",
            "type": "construction",
            "description": (
                "Active Pune Metro underground station construction at Swargate. "
                "Tunnelling, concrete pouring, and heavy machinery operation."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8540, 18.4995], [73.8565, 18.4995],
                    [73.8565, 18.5010], [73.8540, 18.5010],
                    [73.8540, 18.4995],
                ]],
            },
            "permit_id": "PMC/METRO/2025/00892",
            "schedule_start": "06:00", "schedule_end": "22:00",
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": True, "dust_suppression_observed": True,
            "last_inspection_date": "2026-06-25", "violation_count_90d": 0,
        },
    ],
    pre_alerts={
        "source": "Swargate ST Bus Depot & Diesel Terminal",
        "eta_minutes": 22,
        "estimated_aqi_increase": 38,
        "advisory": "Peak bus dispatch hour. 400+ diesel vehicles creating NO2 plume.",
    },
    field_team={
        "team_id": "PMC-AQ-SQUAD-03",
        "team_lead": "Inspector D. P. Patil",
        "contact": "+91-20-XXXX-XXXX",
        "eta_minutes": 12,
    },
)


# =========================================================================== #
# 3. HADAPSAR — Industrial Emission / Factory Spike (SO2 dominant)
# =========================================================================== #
_HADAPSAR = DemoScenario(
    station_name="Hadapsar",
    city="Pune",
    state="Maharashtra",
    network="CPCB_CAAQMS",
    coordinates=(73.9260, 18.5089),
    elevation_m=562,
    spike_aqi=340,
    spike_local_time="07:45",
    dominant_pollutant="so2",
    base_profile={
        "pm25": 20.0, "pm10": 45.0, "no2": 18.0,
        "so2": 70.0, "co": 1.0, "o3": 12.0,
    },
    peak_ratios={
        "pm25_pm10": 0.10,    # very low PM2.5 so SO2 dominates
        "no2": 0.08,
        "so2": 2.50,          # SO2 dominant from factory flue — extremely high
        "o3": 0.04,
        "co_per_pm10": 0.005,
    },
    weather_overrides={
        "wind_speed_kmh": 6.8,
        "wind_direction_deg": 145,
        "temperature_c": 29.7,
        "relative_humidity_pct": 68,
        "pressure_hpa": 1007.1,
        "cloud_cover_oktas": 5,
        "precipitation_mm_last_1h": 0.0,
        "visibility_km": 3.2,
        "mixing_layer_height_m": 480,
    },
    candidates=[
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "hadapsar-midc-chemical")),
            "name": "Hadapsar MIDC — Bharat Forge Chemical Division",
            "type": "industrial",
            "description": (
                "Heavy industrial forging and chemical processing unit in "
                "Hadapsar MIDC. Sulfur-rich fuel combustion in furnaces and "
                "acid pickling baths generating SO2 and particulate emissions."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.9285, 18.5110], [73.9320, 18.5110],
                    [73.9320, 18.5140], [73.9285, 18.5140],
                    [73.9285, 18.5110],
                ]],
            },
            "permit_id": "MPCB/IND/PUN/2024/05567",
            "schedule_start": "06:00", "schedule_end": "22:00",
            "near_school": True, "school_name": "Hadapsar Primary School",
            "school_distance_m": 420,
            "near_hospital": True, "hospital_name": "Noble Hospital, Hadapsar",
            "hospital_distance_m": 550,
            "dust_suppression_required": True, "dust_suppression_observed": False,
            "last_inspection_date": "2026-05-02", "violation_count_90d": 5,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "hadapsar-fursungi-brick-kiln")),
            "name": "Fursungi Brick Kiln Cluster",
            "type": "industrial",
            "description": (
                "Cluster of 6 traditional brick kilns along the Fursungi "
                "road. Coal-fired kilns operating without adequate scrubbers, "
                "emitting SO2 and fly ash."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.9310, 18.5060], [73.9350, 18.5060],
                    [73.9350, 18.5085], [73.9310, 18.5085],
                    [73.9310, 18.5060],
                ]],
            },
            "permit_id": "MPCB/KILN/PUN/2025/00231",
            "schedule_start": "04:00", "schedule_end": "20:00",
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": True, "dust_suppression_observed": False,
            "last_inspection_date": "2026-03-15", "violation_count_90d": 8,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "hadapsar-magarpatta-dg-sets")),
            "name": "Magarpatta City — Backup DG Set Bank",
            "type": "industrial",
            "description": (
                "Bank of 12 diesel generator sets at Magarpatta City business "
                "park. Activated during morning power-cut window."
            ),
            "geometry": {"type": "Point", "coordinates": [73.9240, 18.5125]},
            "permit_id": None,
            "schedule_start": "07:00", "schedule_end": "10:00",
            "near_school": True, "school_name": "Magarpatta City Public School",
            "school_distance_m": 200,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 2,
        },
    ],
    pre_alerts={
        "source": "Hadapsar MIDC — Bharat Forge Chemical Division",
        "eta_minutes": 28,
        "estimated_aqi_increase": 62,
        "advisory": "Industrial furnace cycle started. SO2 plume detected downwind.",
    },
    field_team={
        "team_id": "MPCB-RAPID-RESPONSE-02",
        "team_lead": "Inspector V. K. Jadhav",
        "contact": "+91-20-XXXX-XXXX",
        "eta_minutes": 22,
    },
)


# =========================================================================== #
# 4. KOTHRUD — Ambiguity / Multi-Source Scenario (PM2.5 dominant)
# =========================================================================== #
_KOTHRUD = DemoScenario(
    station_name="Kothrud",
    city="Pune",
    state="Maharashtra",
    network="CPCB_CAAQMS",
    coordinates=(73.8077, 18.5074),
    elevation_m=575,
    spike_aqi=265,
    spike_local_time="08:00",
    dominant_pollutant="pm25",
    base_profile={
        "pm25": 50.0, "pm10": 72.0, "no2": 42.0,
        "so2": 22.0, "co": 1.8, "o3": 30.0,
    },
    peak_ratios={
        "pm25_pm10": 0.70,    # high PM2.5 ratio = mixed combustion sources
        "no2": 0.35,
        "so2": 0.18,
        "o3": 0.10,
        "co_per_pm10": 0.015,
    },
    weather_overrides={
        "wind_speed_kmh": 5.1,
        "wind_direction_deg": 180,    # wind from South
        "temperature_c": 27.8,
        "relative_humidity_pct": 74,
        "pressure_hpa": 1007.5,
        "cloud_cover_oktas": 6,
        "precipitation_mm_last_1h": 0.0,
        "visibility_km": 2.8,
        "mixing_layer_height_m": 380,
    },
    candidates=[
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "kothrud-karve-road-traffic")),
            "name": "Karve Road — Morning Rush Traffic Corridor",
            "type": "traffic",
            "description": (
                "Karve Road is a 6-lane arterial carrying 8,000+ vehicles/hour "
                "during morning rush. Diesel autorickshaws and heavy trucks "
                "dominate the mix."
            ),
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [73.8050, 18.5060], [73.8090, 18.5070],
                    [73.8130, 18.5080], [73.8170, 18.5085],
                ],
            },
            "permit_id": None,
            "schedule_start": "00:00", "schedule_end": "23:59",
            "near_school": True, "school_name": "MIT World Peace University",
            "school_distance_m": 180,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 0,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "kothrud-warje-waste-burning")),
            "name": "Warje Malwadi — Unauthorized Waste Burning",
            "type": "waste_burning",
            "description": (
                "Open burning of mixed municipal waste and construction debris "
                "in the Warje Malwadi slum area. Sporadic and unregulated, "
                "generating PM2.5 and toxic VOCs."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8020, 18.4990], [73.8055, 18.4990],
                    [73.8055, 18.5010], [73.8020, 18.5010],
                    [73.8020, 18.4990],
                ]],
            },
            "permit_id": None,
            "schedule_start": None, "schedule_end": None,
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": True, "hospital_name": "Sahyadri Hospitals, Kothrud",
            "hospital_distance_m": 350,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 4,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "kothrud-dp-road-construction")),
            "name": "DP Road Flyover Construction (PMC)",
            "type": "construction",
            "description": (
                "Active flyover construction on DP Road. Pile driving, "
                "earth-moving, and concrete mixing generating dust."
            ),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [73.8065, 18.5050], [73.8100, 18.5050],
                    [73.8100, 18.5070], [73.8065, 18.5070],
                    [73.8065, 18.5050],
                ]],
            },
            "permit_id": "PMC/CONST/2026/01155",
            "schedule_start": "07:00", "schedule_end": "19:00",
            "near_school": True, "school_name": "Kothrud High School",
            "school_distance_m": 310,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": True, "dust_suppression_observed": True,
            "last_inspection_date": "2026-06-20", "violation_count_90d": 1,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "kothrud-dahanukar-restaurant-row")),
            "name": "Dahanukar Colony — Restaurant Row (Tandoor Cluster)",
            "type": "industrial",
            "description": (
                "Dense cluster of 15+ restaurants with coal/wood-fired tandoors "
                "and open-flame grills. Combined smoke output during dinner "
                "prep (7–10 AM breakfast + 6–10 PM dinner) contributes PM2.5."
            ),
            "geometry": {
                "type": "Point",
                "coordinates": [73.8085, 18.5095],
            },
            "permit_id": None,
            "schedule_start": "06:30", "schedule_end": "23:00",
            "near_school": False, "school_name": None, "school_distance_m": None,
            "near_hospital": False, "hospital_name": None, "hospital_distance_m": None,
            "dust_suppression_required": False, "dust_suppression_observed": False,
            "last_inspection_date": None, "violation_count_90d": 0,
        },
    ],
    pre_alerts={
        "source": "AMBIGUITY — Multiple sources flagged",
        "eta_minutes": 40,
        "estimated_aqi_increase": 30,
        "advisory": (
            "Low wind speed + low mixing height creating stagnation zone. "
            "Multiple overlapping sources detected. Manual field inspection required."
        ),
    },
    field_team={
        "team_id": "PMC-AQ-SQUAD-11",
        "team_lead": "Inspector S. M. Deshmukh",
        "contact": "+91-20-XXXX-XXXX",
        "eta_minutes": 25,
    },
)


# =========================================================================== #
# Registry
# =========================================================================== #
_SCENARIOS: dict[str, DemoScenario] = {
    "shivajinagar": _SHIVAJINAGAR,
    "swargate": _SWARGATE,
    "hadapsar": _HADAPSAR,
    "kothrud": _KOTHRUD,
}


def get_scenario(station_name: str) -> DemoScenario:
    """Look up a demo scenario by station name (case-insensitive).

    Falls back to Shivajinagar if the station is unknown.
    """
    return _SCENARIOS.get(station_name.strip().lower(), _SHIVAJINAGAR)


def list_scenario_names() -> list[str]:
    """Return all available demo station names."""
    return [s.station_name for s in _SCENARIOS.values()]
