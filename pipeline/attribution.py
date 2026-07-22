"""Source Attribution Pipeline — Task 3.

Three-stage funnel:
  Stage 1  Spatial   — ST_DWithin(station, source, search_radius_m)
  Stage 2  Wind cone — sources inside the upwind sector polygon
  Stage 3  Scoring   — wind alignment, chemical match, temporal, proximity

Outputs the lower half of the data contract:
  wind_cone_geometry
  ranked_candidates  (with score_breakdown + compliance_profile)
  actionable_intelligence

Design principles:
  - All geometry math uses only stdlib + math module; no shapely required for
    the cone construction.  PostGIS is used only for the DB query (Stage 1).
  - Scoring functions are pure — no DB side-effects — so the test script can
    exercise them without a database.
  - The public entry-point is ``run_attribution(session, spike_payload)``.
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Any, Optional

from geoalchemy2 import functions as gfunc
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import PollutionSource, Station
from .validators import validate_aqi, validate_wind, validate_pollutant_reading
from .pipeline_logger import log_pipeline_run

log = logging.getLogger(__name__)


# ============================================================
# Wet-Scavenging Environmental Physics Model
# ============================================================
# Exponential particulate wash-out driven by live precipitation.
# When rainfall is actively detected, the engine scales down PM2.5/PM10
# concentrations to simulate real-world atmospheric cleaning (wet deposition).
# Scavenging coefficient (lambda) ~ 0.15 per mm/hr is a conservative
# estimate for below-cloud washout of coarse and fine particulate matter.
# Reference: Seinfeld & Pandis (2016), Atmospheric Chemistry & Physics.

_SCAVENGING_LAMBDA = 0.15      # exponential decay coefficient per mm/hr
_WET_AQI_CEILING = 95          # strict AQI ceiling under active rain


def _apply_wet_scavenging(
    aqi_value: float,
    precipitation_mm: float,
    pollutant_readings: Optional[dict[str, Any]] = None,
) -> tuple[float, Optional[dict[str, Any]], bool]:
    """Apply exponential wet-scavenging to AQI and PM concentrations.

    When rainfall is detected (> 0.1 mm/hr threshold), particulate-phase
    pollutants (PM2.5 and PM10) are reduced by an exponential decay factor:

        retention = exp(-lambda * precipitation_mm)

    The resulting AQI is capped at a maximum strict ceiling of 95.

    Args:
        aqi_value: Raw AQI reading from the station.
        precipitation_mm: Precipitation in the last hour (mm).
        pollutant_readings: Optional dict of pollutant concentrations.

    Returns:
        Tuple of (effective_aqi, adjusted_readings, rain_active_flag).
    """
    # Rainfall detection threshold: 0.1 mm/hr (trace rainfall)
    if precipitation_mm < 0.1:
        return aqi_value, pollutant_readings, False

    # Exponential decay: heavier rain -> stronger washout
    retention_factor = math.exp(-_SCAVENGING_LAMBDA * precipitation_mm)
    log.info(
        "Wet-scavenging active: precip=%.1f mm/hr, retention_factor=%.4f",
        precipitation_mm, retention_factor,
    )

    # Scale down particulate concentrations
    adjusted_readings = None
    if pollutant_readings:
        adjusted_readings = dict(pollutant_readings)
        for pm_key in ("pm25", "pm10"):
            if pm_key in adjusted_readings and adjusted_readings[pm_key] is not None:
                original = adjusted_readings[pm_key]
                adjusted_readings[pm_key] = round(original * retention_factor, 2)
                log.debug(
                    "Wet-scavenging %s: %.2f -> %.2f (retention=%.4f)",
                    pm_key, original, adjusted_readings[pm_key], retention_factor,
                )

    # Scale AQI by the same retention factor and enforce strict ceiling
    effective_aqi = min(aqi_value * retention_factor, _WET_AQI_CEILING)
    log.info(
        "Wet-scavenging AQI: raw=%.1f -> effective=%.1f (ceiling=%d)",
        aqi_value, effective_aqi, _WET_AQI_CEILING,
    )

    return effective_aqi, adjusted_readings, True

# ============================================================
# Geometry helpers — pure Python, no shapely dependency
# ============================================================

_EARTH_R_M = 6_371_000.0   # mean Earth radius in metres


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres between two (lon, lat) WGS-84 points."""
    lo1, la1, lo2, la2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(math.sqrt(a))


def _bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial bearing (degrees, 0 = N, clockwise) from point 1 → point 2."""
    lo1, la1, lo2, la2 = map(math.radians, [lon1, lat1, lon2, lat2])
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _destination(lon: float, lat: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Destination point from (lon, lat) travelling bearing_deg for dist_m metres."""
    d = dist_m / _EARTH_R_M
    b = math.radians(bearing_deg)
    la1 = math.radians(lat)
    lo1 = math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(la1),
        math.cos(d) - math.sin(la1) * math.sin(la2),
    )
    return math.degrees(lo2), math.degrees(la2)


def build_wind_cone_polygon(
    station_lon: float,
    station_lat: float,
    wind_direction_deg: float,   # meteorological: direction wind comes FROM
    half_angle_deg: float,
    reach_m: float,
    n_arc_steps: int = 12,
) -> dict[str, Any]:
    """Build a GeoJSON Polygon for the upwind source-search cone.

    The cone points in the direction FROM which the wind blows
    (i.e. sources upwind of the station live inside the cone).

    Returns a GeoJSON geometry dict:
        {"type": "Polygon", "coordinates": [[...]]}
    """
    # The center axis of the cone points UPWIND (same direction as wind_from)
    axis_bearing = wind_direction_deg          # axis points toward upwind origin

    # Arc from left edge to right edge
    left_bearing  = (axis_bearing - half_angle_deg) % 360
    right_bearing = (axis_bearing + half_angle_deg) % 360

    # Station is the cone apex
    apex = (station_lon, station_lat)

    # Arc points along the reach at radius=reach_m
    arc_pts: list[tuple[float, float]] = []
    for i in range(n_arc_steps + 1):
        step_bearing = (left_bearing + (right_bearing - left_bearing + 360) % 360 * i / n_arc_steps) % 360
        arc_pts.append(_destination(station_lon, station_lat, step_bearing, reach_m))

    ring = [apex] + arc_pts + [apex]
    return {"type": "Polygon", "coordinates": [[[lon, lat] for lon, lat in ring]]}


def _point_in_cone(
    lon: float, lat: float,
    station_lon: float, station_lat: float,
    wind_direction_deg: float,
    half_angle_deg: float,
    reach_m: float,
) -> bool:
    """Return True if the point (lon, lat) lies within the wind cone."""
    dist = _haversine_m(station_lon, station_lat, lon, lat)
    if dist > reach_m:
        return False
    brg = _bearing_deg(station_lon, station_lat, lon, lat)
    diff = abs((brg - wind_direction_deg + 180) % 360 - 180)
    return diff <= half_angle_deg


def _source_representative_point(source: PollutionSource, session: Session) -> tuple[float, float]:
    """Return (lon, lat) of the representative point of the source geometry."""
    stmt = select(
        gfunc.ST_X(gfunc.ST_Centroid(source.geom)),
        gfunc.ST_Y(gfunc.ST_Centroid(source.geom)),
    )
    lon, lat = session.execute(stmt).one()
    return float(lon), float(lat)


# ============================================================
# Dynamic search parameters
# ============================================================

def get_search_radius_m(wind_speed_kmh: float) -> float:
    """Wider cone at low wind (pollutants pool nearby); narrower at high wind."""
    if wind_speed_kmh < 5:
        return 1_500.0
    if wind_speed_kmh < 15:
        return 2_500.0
    if wind_speed_kmh < 25:
        return 3_500.0
    return 4_500.0


def get_half_angle_deg(wind_speed_kmh: float) -> float:
    """Half-aperture of the upwind cone (degrees)."""
    if wind_speed_kmh < 5:
        return 45.0
    if wind_speed_kmh < 15:
        return 30.0
    if wind_speed_kmh < 25:
        return 22.5
    return 18.0


# ============================================================
# Stage 1 — Spatial filter (PostGIS)
# ============================================================

def _fetch_sources_within_radius(
    session: Session,
    station_lon: float,
    station_lat: float,
    radius_m: float,
) -> list[PollutionSource]:
    """Return all pollution_sources within radius_m of the station point."""
    station_pt = f"ST_SetSRID(ST_MakePoint({station_lon}, {station_lat}), 4326)"
    from sqlalchemy import text

    stmt = (
        select(PollutionSource)
        .where(
            gfunc.ST_DWithin(
                gfunc.ST_Transform(PollutionSource.geom, 32643),   # UTM zone 43N (Pune)
                gfunc.ST_Transform(
                    gfunc.ST_GeomFromText(
                        f"POINT({station_lon} {station_lat})", 4326
                    ),
                    32643,
                ),
                radius_m,
            )
        )
    )
    return list(session.execute(stmt).scalars().all())


# ============================================================
# Stage 2 — Wind cone filter
# ============================================================

def _filter_by_wind_cone(
    sources: list[PollutionSource],
    session: Session,
    station_lon: float,
    station_lat: float,
    wind_direction_deg: float,
    half_angle_deg: float,
    reach_m: float,
) -> list[tuple[PollutionSource, float, float]]:
    """Return (source, lon, lat) tuples for sources inside the upwind cone."""
    result = []
    for src in sources:
        lon, lat = _source_representative_point(src, session)
        if _point_in_cone(lon, lat, station_lon, station_lat,
                          wind_direction_deg, half_angle_deg, reach_m):
            result.append((src, lon, lat))
    return result


# ============================================================
# Stage 3 — Scoring
# ============================================================

# Chemical signature → source type → match score
_CHEM_SCORES: dict[str, dict[str, float]] = {
    "crustal_dominant":      {"construction": 1.0, "traffic": 0.6, "waste_burning": 0.2, "industrial": 0.1},
    "combustion_vehicular":  {"traffic": 1.0, "industrial": 0.5, "waste_burning": 0.3, "construction": 0.1},
    "industrial_sulfur":     {"industrial": 1.0, "construction": 0.0, "traffic": 0.0, "waste_burning": 0.0},
    "biomass_burning":       {"waste_burning": 1.0, "construction": 0.1, "traffic": 0.1, "industrial": 0.1},
    "mixed":                 {"construction": 0.5, "traffic": 0.5, "industrial": 0.5, "waste_burning": 0.5},
}


def _chemical_match_score(signature_class: str, source_type: str) -> float:
    return _CHEM_SCORES.get(signature_class, {}).get(source_type, 0.5)


def _temporal_match_score(spike_ts: datetime, source: PollutionSource) -> float:
    """1.0 if the spike falls within the source operating window, else 0.2."""
    if source.schedule_start is None or source.schedule_end is None:
        return 0.2
    spike_time = spike_ts.astimezone(timezone(timedelta(hours=5, minutes=30))).time()
    if source.schedule_start <= source.schedule_end:
        operating = source.schedule_start <= spike_time <= source.schedule_end
    else:
        # wraps midnight
        operating = spike_time >= source.schedule_start or spike_time <= source.schedule_end
    return 1.0 if operating else 0.2


def _wind_alignment_score(
    source_lon: float, source_lat: float,
    station_lon: float, station_lat: float,
    wind_direction_deg: float,
    half_angle_deg: float,
) -> float:
    """1.0 when the source sits exactly on the upwind axis; 0.0 at the edge."""
    brg = _bearing_deg(station_lon, station_lat, source_lon, source_lat)
    diff = abs((brg - wind_direction_deg + 180) % 360 - 180)
    return max(0.0, round(1.0 - diff / half_angle_deg, 4))


def _proximity_score(dist_m: float, radius_m: float) -> float:
    return max(0.0, round(1.0 - dist_m / radius_m, 4))


def _composite_confidence(
    wind: float, chemical: float, temporal: float
) -> float:
    return round(0.40 * wind + 0.35 * chemical + 0.25 * temporal, 4)


def _compliance_penalty(source: PollutionSource) -> float:
    """Small deterministic penalty for near-school/hospital sources (visual hint)."""
    penalty = 0.0
    if source.near_school:
        penalty += 0.10
    if source.near_hospital:
        penalty += 0.05
    return round(min(penalty, 0.20), 2)


# ============================================================
# Payload builders — contract-shaped dicts
# ============================================================

def _build_compliance_profile(
    source: PollutionSource, spike_ts: datetime
) -> dict[str, Any]:
    spike_time = spike_ts.astimezone(timezone(timedelta(hours=5, minutes=30))).time()
    if source.schedule_start and source.schedule_end:
        if source.schedule_start <= source.schedule_end:
            operating = source.schedule_start <= spike_time <= source.schedule_end
        else:
            operating = spike_time >= source.schedule_start or spike_time <= source.schedule_end
    else:
        operating = False

    def fmt_time(t: Optional[dtime]) -> Optional[str]:
        return t.strftime("%H:%M") if t else None

    return {
        "permit_id": None,
        "schedule_start": fmt_time(source.schedule_start),
        "schedule_end": fmt_time(source.schedule_end),
        "operating_at_event_time": operating,
        "near_school": source.near_school,
        "school_name": None,
        "school_distance_m": None,
        "near_hospital": source.near_hospital,
        "hospital_name": None,
        "hospital_distance_m": None,
        "dust_suppression_required": source.type in ("construction", "industrial"),
        "dust_suppression_observed": False,
        "last_inspection_date": None,
        "violation_count_90d": 0,
    }


def _build_candidate_dict(
    rank: int,
    source: PollutionSource,
    src_lon: float,
    src_lat: float,
    station_lon: float,
    station_lat: float,
    spike_ts: datetime,
    wind_direction_deg: float,
    half_angle_deg: float,
    radius_m: float,
    signature_class: str,
) -> dict[str, Any]:
    dist_m = _haversine_m(station_lon, station_lat, src_lon, src_lat)
    dist_km = round(dist_m / 1000, 2)
    brg = round(_bearing_deg(station_lon, station_lat, src_lon, src_lat), 0)

    wind_score = _wind_alignment_score(
        src_lon, src_lat, station_lon, station_lat, wind_direction_deg, half_angle_deg
    )
    chem_score = round(_chemical_match_score(signature_class, source.type), 2)
    temp_score = round(_temporal_match_score(spike_ts, source), 2)
    prox_score = _proximity_score(dist_m, radius_m)
    penalty = _compliance_penalty(source)
    confidence = _composite_confidence(wind_score, chem_score, temp_score)

    # Decode geometry to a plain GeoJSON dict
    from geoalchemy2.shape import to_shape
    from geoalchemy2.elements import WKBElement
    import json
    shape = to_shape(source.geom if isinstance(source.geom, WKBElement) else WKBElement(bytes(source.geom)))
    geom_type = shape.geom_type
    if geom_type == "Point":
        geom_json = {"type": "Point", "coordinates": [shape.x, shape.y]}
    elif geom_type == "LineString":
        geom_json = {"type": "LineString", "coordinates": list(shape.coords)}
    else:  # Polygon
        geom_json = {"type": "Polygon", "coordinates": [list(shape.exterior.coords)]}

    return {
        "rank": rank,
        "id": str(source.id),
        "name": source.name,
        "type": source.type,
        "description": _source_description(source),
        "geometry": geom_json,
        "distance_from_station_km": dist_km,
        "bearing_from_station_deg": int(brg),
        "compliance_profile": _build_compliance_profile(source, spike_ts),
        "score_breakdown": {
            "wind_alignment_score": round(wind_score, 2),
            "chemical_match_score": chem_score,
            "temporal_match_score": temp_score,
            "proximity_score": round(prox_score, 2),
            "compliance_penalty": penalty,
            "confidence_score": round(confidence, 2),
        },
    }


def _source_description(source: PollutionSource) -> str:
    descs = {
        "construction": "Active construction site with earthmoving and material handling. "
                        "Fugitive dust emissions during operational hours.",
        "traffic":      "High-traffic road corridor with mixed vehicle types. "
                        "Re-suspended road dust and exhaust emissions during peak hours.",
        "industrial":   "Industrial facility with continuous operations. "
                        "Potential for stack emissions and fugitive releases.",
        "waste_burning": "Open waste burning site. Biomass and solid waste combustion "
                         "generates PM2.5, CO, and VOC emissions.",
    }
    return descs.get(source.type, "Pollution source near the station.")


# AQI thresholds for enforcement actions (Indian CPCB NAQI categories)
_AQI_MODERATE   = 100   # Moderate — begin monitoring
_AQI_POOR       = 200   # Poor     — enforcement actions warranted
_AQI_VERY_POOR  = 300   # Very Poor — public health advisory


def _recommended_actions(
    candidates: list[dict[str, Any]],
    aqi_value: float,
) -> list[str]:
    """Return enforcement actions appropriate for the current AQI level.

    Actions are only generated when AQI warrants intervention:
      < 100  (Good / Satisfactory) — no actions, just monitor sources
      ≥ 100  (Moderate)            — dispatch inspector if source is active
      ≥ 200  (Poor)                — show-cause notices, sprinklers
      ≥ 300  (Very Poor / Severe)  — public health advisory
    """
    actions: list[str] = []

    # Only trigger enforcement when AQI is at least Moderate (≥ 100)
    if aqi_value >= _AQI_MODERATE and candidates:
        top = candidates[0]
        cp = top.get("compliance_profile", {})
        src_type = top.get("type", "")

        # Dispatch inspector for any Moderate+ event with an active source
        if cp.get("operating_at_event_time"):
            actions.append("DISPATCH_INSPECTOR")

        # Show-cause notice only at Poor+ (≥ 200) near sensitive locations
        if aqi_value >= _AQI_POOR and (cp.get("near_school") or cp.get("near_hospital")):
            actions.append("ISSUE_SHOW_CAUSE_NOTICE")

        # Dust suppression at Poor+ (≥ 200)
        if aqi_value >= _AQI_POOR and src_type in ("construction", "industrial"):
            actions.append("ACTIVATE_WATER_SPRINKLERS")

        # Traffic police at Moderate+ (≥ 100) for traffic corridors
        if src_type == "traffic":
            actions.append("ALERT_NEAREST_TRAFFIC_POLICE")

        # Fire brigade any time there is active waste burning and AQI ≥ Moderate
        if src_type == "waste_burning":
            actions.append("DISPATCH_FIRE_BRIGADE")

    # Public health advisory only at Very Poor / Severe (≥ 300)
    if aqi_value >= _AQI_VERY_POOR:
        actions.append("ISSUE_PUBLIC_HEALTH_ADVISORY")

    return list(dict.fromkeys(actions))  # deduplicate, preserve order


def _enforcement_priority(
    candidates: list[dict[str, Any]],
    base_confidence: float,
) -> float:
    if not candidates:
        return round(base_confidence, 2)
    top_cp = candidates[0].get("compliance_profile", {})
    score = base_confidence
    if top_cp.get("near_school") or top_cp.get("near_hospital"):
        score += 0.10
    violations = top_cp.get("violation_count_90d", 0)
    score += min(0.05 * violations, 0.15)
    return round(min(score, 1.0), 2)


def _localized_advisory(
    station_name: str,
    aqi_value: float,
    dominant_pollutant: str,
    top_candidate: Optional[dict[str, Any]],
    confidence_pct: int,
) -> dict[str, str]:
    src_name = top_candidate["name"] if top_candidate else "Unknown source"
    src_type = top_candidate.get("type", "source") if top_candidate else "source"
    near_school = top_candidate.get("compliance_profile", {}).get("near_school", False) if top_candidate else False
    near_hospital = top_candidate.get("compliance_profile", {}).get("near_hospital", False) if top_candidate else False

    school_note = " A school is located near the primary source." if near_school else ""
    hospital_note = " A hospital is located near the source." if near_hospital else ""

    en = (
        f"AIR QUALITY ALERT — {station_name} station has recorded AQI {aqi_value:.0f} at current time. "
        f"Dominant pollutant: {dominant_pollutant}. "
        f"Wind analysis indicates the primary source is '{src_name}' (confidence: {confidence_pct}%). "
        f"Immediate inspection and enforcement action is required.{school_note}{hospital_note}"
    )
    hi = (
        f"वायु गुणवत्ता चेतावनी — {station_name} स्टेशन पर AQI {aqi_value:.0f} दर्ज किया गया है। "
        f"प्रमुख प्रदूषक: {dominant_pollutant}। "
        f"वायु विश्लेषण के अनुसार प्राथमिक स्रोत '{src_name}' है (विश्वसनीयता: {confidence_pct}%)। "
        f"तत्काल निरीक्षण और प्रवर्तन कार्रवाई आवश्यक है।"
    )
    mr = (
        f"हवा गुणवत्ता इशारा — {station_name} स्थानकावर AQI {aqi_value:.0f} नोंदवला गेला आहे। "
        f"प्रमुख प्रदूषक: {dominant_pollutant}। "
        f"वारा विश्लेषणानुसार प्राथमिक स्रोत '{src_name}' आहे (विश्वासार्हता: {confidence_pct}%)। "
        f"तात्काळ तपासणी आणि अंमलबजावणी कारवाई आवश्यक आहे।"
    )
    return {"en": en, "hi": hi, "mr": mr}


# ============================================================
# Wind-cone geometry block (contract format)
# ============================================================

def _build_wind_cone_feature(
    station_lon: float,
    station_lat: float,
    station_name: str,
    wind_direction_deg: float,
    half_angle_deg: float,
    reach_m: float,
    pasquill_class: str,
) -> dict[str, Any]:
    polygon = build_wind_cone_polygon(
        station_lon, station_lat,
        wind_direction_deg, half_angle_deg, reach_m,
    )
    return {
        "type": "Feature",
        "properties": {
            "cone_type": "upwind_source_area",
            "origin_station": station_name,
            "bearing_deg": wind_direction_deg,
            "half_angle_deg": half_angle_deg,
            "reach_km": round(reach_m / 1000, 1),
            "pasquill_class": pasquill_class,
            "style": {
                "fill_color": "#ef444480",
                "stroke_color": "#dc2626",
                "stroke_width": 2,
                "fill_opacity": 0.25,
            },
        },
        "geometry": polygon,
    }


# ============================================================
# Ambiguity check
# ============================================================

_AMBIGUITY_THRESHOLD = 0.15


def _check_ambiguity(ranked: list[dict[str, Any]]) -> bool:
    if len(ranked) < 2:
        return False
    c1 = ranked[0]["score_breakdown"]["confidence_score"]
    c2 = ranked[1]["score_breakdown"]["confidence_score"]
    return (c1 - c2) < _AMBIGUITY_THRESHOLD


# ============================================================
# Public entry-point
# ============================================================

def run_attribution(
    session: Session,
    station_lon: float,
    station_lat: float,
    station_name: str,
    spike_ts: datetime,
    aqi_value: float,
    dominant_pollutant: str,
    signature_class: str,
    wind_direction_deg: float,
    wind_speed_kmh: float,
    pasquill_class: str = "D",
    top_n: int = 4,
    pollutant_readings: Optional[dict[str, Any]] = None,
    precipitation_mm_last_1h: float = 0.0,
) -> dict[str, Any]:
    """Run the three-stage attribution funnel and return the lower-half payload dict.

    Performs input validation and structured execution timing logging.
    """
    warnings = []
    t_start = time.time()

    # Step 1: Validate AQI
    aqi_check = validate_aqi(aqi_value)
    if not aqi_check.is_valid:
        return {"error": aqi_check.reason, "attribution": None}
    if aqi_check.reason:
        warnings.append(aqi_check.reason)

    # Step 2: Validate Wind
    wind_check = validate_wind(wind_speed_kmh, wind_direction_deg)
    if not wind_check.is_valid:
        return {"error": wind_check.reason, "attribution": None}
    if wind_check.reason:
        warnings.append(wind_check.reason)

    # Step 3: Validate Pollutants
    if pollutant_readings:
        for p_name, p_val in pollutant_readings.items():
            if p_val is not None:
                p_check = validate_pollutant_reading(p_name, p_val)
                if not p_check.is_valid:
                    warnings.append(f"Invalid {p_name}: {p_check.reason}")
                elif p_check.reason:
                    warnings.append(f"{p_name}: {p_check.reason}")

    # ---- Wet-scavenging physics (rainfall wash-out) ----------------------
    rain_active = False
    if precipitation_mm_last_1h > 0.0:
        aqi_value, pollutant_readings, rain_active = _apply_wet_scavenging(
            aqi_value, precipitation_mm_last_1h, pollutant_readings,
        )
        if rain_active:
            warnings.append(
                f"Wet-scavenging applied: {precipitation_mm_last_1h:.1f} mm/hr rainfall "
                f"detected. PM concentrations and AQI reduced by exponential wash-out model."
            )

    # Gather total source count from DB for auditing
    total_sources = session.query(PollutionSource).count()

    t0 = time.time()
    radius_m = get_search_radius_m(wind_speed_kmh)
    
    # Calm wind scenario: use wide 360-degree cone (half-angle = 180 degrees)
    is_calm = wind_speed_kmh < 0.5
    half_angle = 180.0 if is_calm else get_half_angle_deg(wind_speed_kmh)

    # ---- Stage 1: spatial filter ----------------------------------------
    nearby = _fetch_sources_within_radius(session, station_lon, station_lat, radius_m)
    spatial_count = len(nearby)
    spatial_ms = round((time.time() - t0) * 1000)

    # ---- Stage 2: wind-cone filter ---------------------------------------
    t1 = time.time()
    in_cone = _filter_by_wind_cone(
        nearby, session, station_lon, station_lat,
        wind_direction_deg, half_angle, radius_m,
    )
    cone_count = len(in_cone)
    cone_ms = round((time.time() - t1) * 1000)

    # ---- Stage 3: score every surviving candidate -----------------------
    t2 = time.time()
    scored: list[dict[str, Any]] = []
    for src, src_lon, src_lat in in_cone:
        cand = _build_candidate_dict(
            rank=0,  # assigned after sorting
            source=src,
            src_lon=src_lon,
            src_lat=src_lat,
            station_lon=station_lon,
            station_lat=station_lat,
            spike_ts=spike_ts,
            wind_direction_deg=wind_direction_deg,
            half_angle_deg=half_angle,
            radius_m=radius_m,
            signature_class=signature_class,
        )
        scored.append(cand)

    # Sort by confidence desc, then proximity desc for tie-breaking
    scored.sort(
        key=lambda c: (
            c["score_breakdown"]["confidence_score"],
            c["score_breakdown"]["proximity_score"],
        ),
        reverse=True,
    )

    # Keep top_n, assign ranks
    ranked = scored[:top_n]
    for i, c in enumerate(ranked, start=1):
        c["rank"] = i

    candidate_count = len(ranked)
    chemical_count = len([c for c in scored if c["score_breakdown"]["chemical_match_score"] > 0.5])
    scoring_ms = round((time.time() - t2) * 1000)

    # ---- Ambiguity check -----------------------------------------------
    ambiguous = _check_ambiguity(ranked)

    # ---- Wind-cone geometry --------------------------------------------
    wind_cone_feature = _build_wind_cone_feature(
        station_lon, station_lat, station_name,
        wind_direction_deg, half_angle, radius_m, pasquill_class,
    )

    # ---- Actionable intelligence ---------------------------------------
    top = ranked[0] if ranked else None
    base_conf = top["score_breakdown"]["confidence_score"] if top else 0.5
    conf_pct = int(round(base_conf * 100))
    priority = _enforcement_priority(ranked, base_conf)
    advisory = _localized_advisory(
        station_name, aqi_value, dominant_pollutant, top, conf_pct
    )

    actions = _recommended_actions(ranked, aqi_value)

    priority_justification = ""
    if top:
        cp = top.get("compliance_profile", {})
        parts = []
        if cp.get("near_school"):
            parts.append(f"'{top['name']}' is located near a school")
        if cp.get("near_hospital"):
            parts.append(f"'{top['name']}' is near a hospital")
        if cp.get("violation_count_90d", 0) > 0:
            parts.append(
                f"{cp['violation_count_90d']} violation(s) recorded in 90 days"
            )
        if not cp.get("dust_suppression_observed") and cp.get("dust_suppression_required"):
            parts.append("no active dust suppression observed")
        if ambiguous:
            parts.append("multiple probable sources — field verification recommended")
        priority_justification = ". ".join(parts).capitalize() + "." if parts else ""

    actionable_intelligence: dict[str, Any] = {
        "enforcement_priority": priority,
        "priority_justification": priority_justification,
        "recommended_actions": actions,
        "estimated_response_time_min": 20,
        "localized_advisory": advisory,
        "notification_channels": ["sms", "whatsapp", "push_notification", "email"],
        "field_team_assignment": {
            "team_id": "PMC-AQ-SQUAD-01",
            "team_lead": "Inspector (On Duty)",
            "contact": "+91-20-XXXX-XXXX",
            "eta_minutes": 20,
        },
        "ambiguous": ambiguous,
    }

    total_ms = round((time.time() - t_start) * 1000)

    # Compile logging details
    spike_data = {
        "station_id": None,
        "station_name": station_name,
        "aqi": aqi_value,
        "dominant_pollutant": dominant_pollutant,
        "wind_speed": wind_speed_kmh,
        "wind_direction": wind_direction_deg,
    }

    results_data = {
        "cone_angle": half_angle * 2,
        "search_radius_m": radius_m,
        "total_sources": total_sources,
        "spatial_count": spatial_count,
        "cone_count": cone_count,
        "chemical_count": chemical_count,
        "candidate_count": candidate_count,
        "primary_source": top["name"] if top else None,
        "confidence": base_conf,
        "ambiguous": ambiguous,
        "total_ms": total_ms,
        "spatial_ms": spatial_ms,
        "cone_ms": cone_ms,
        "scoring_ms": scoring_ms,
        "warnings": warnings,
    }

    log_pipeline_run(spike_data, results_data)

    return {
        "wind_cone_geometry": wind_cone_feature,
        "ranked_candidates": ranked,
        "actionable_intelligence": actionable_intelligence,
        "warnings": warnings,
        "pipeline_timings": {
            "spatial_filter_ms": spatial_ms,
            "wind_cone_ms": cone_ms,
            "scoring_ms": scoring_ms,
            "total_ms": total_ms,
        },
    }


__all__ = [
    "run_attribution",
    "build_wind_cone_polygon",
    "get_search_radius_m",
    "get_half_angle_deg",
]
