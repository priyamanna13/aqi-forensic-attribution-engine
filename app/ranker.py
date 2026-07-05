"""Source Candidate Ranking Engine.

Accepts a list of candidate pollution-source dicts, scores each one against
the triggering station's context (wind, chemistry, time, proximity), and
returns a ranked list sorted by confidence descending.
"""
from __future__ import annotations

import json
import math

from .scoring import (
    chemical_match_score,
    compliance_penalty,
    compute_confidence,
    proximity_score,
    temporal_match_score,
    wind_alignment_score,
)


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

_R_EARTH_KM = 6371.0


def _haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = (math.radians(v) for v in (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return _R_EARTH_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial bearing in degrees (0–360) from point 1 to point 2."""
    lon1, lat1, lon2, lat2 = (math.radians(v) for v in (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360


def _centroid(geom_dict: dict) -> tuple[float, float]:
    """Compute centroid of a GeoJSON geometry (Point, LineString, or Polygon).

    Returns ``(longitude, latitude)``.
    """
    gtype = geom_dict.get("type", "")
    coords = geom_dict.get("coordinates", [])

    if gtype == "Point":
        return (coords[0], coords[1])

    if gtype == "LineString":
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return (sum(lons) / len(lons), sum(lats) / len(lats))

    if gtype == "Polygon":
        # Use the exterior ring (first ring); skip the closing duplicate vertex.
        ring = coords[0]
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        return (sum(lons) / len(lons), sum(lats) / len(lats))

    # Fallback: try to flatten and average all numbers.
    flat = _flatten_coords(coords)
    if flat:
        lons = [p[0] for p in flat]
        lats = [p[1] for p in flat]
        return (sum(lons) / len(lons), sum(lats) / len(lats))

    return (0.0, 0.0)


def _flatten_coords(obj) -> list[tuple[float, float]]:
    """Recursively extract (lon, lat) pairs from nested coordinate arrays."""
    if not obj:
        return []
    if isinstance(obj[0], (int, float)):
        return [(obj[0], obj[1])]
    result: list[tuple[float, float]] = []
    for item in obj:
        result.extend(_flatten_coords(item))
    return result


# ---------------------------------------------------------------------------
# Main ranking function
# ---------------------------------------------------------------------------

def rank_candidates(
    candidates: list[dict],
    station_coords: tuple[float, float],
    wind_direction: float,
    half_angle: float,
    max_range_km: float,
    chemical_fingerprint: dict,
    event_time: str,
) -> list[dict]:
    """Score, sort by confidence descending, assign rank 1..N.

    Parameters
    ----------
    candidates:
        List of dicts with keys matching ``PollutionSource`` fields + a
        ``geometry`` key holding a GeoJSON geometry dict.
    station_coords:
        ``(longitude, latitude)`` of the triggering station.
    wind_direction:
        Meteorological wind direction in degrees.
    half_angle:
        Half-width of the wind plume cone in degrees.
    max_range_km:
        Maximum attribution range in km.
    chemical_fingerprint:
        Dict with at least ``signature_class`` key.
    event_time:
        ``HH:MM`` string.

    Returns
    -------
    list[dict]
        Ranked candidate dicts matching the data-contract shape.
    """
    scored: list[dict] = []

    slon, slat = station_coords

    for cand in candidates:
        geom = cand.get("geometry", {})
        clon, clat = _centroid(geom)

        dist_km = round(_haversine_distance(slon, slat, clon, clat), 2)
        bearing_deg = round(_bearing(slon, slat, clon, clat), 1)

        # Sub-scores.
        w_score = wind_alignment_score(bearing_deg, wind_direction, half_angle)
        c_score = chemical_match_score(cand.get("type", ""), chemical_fingerprint)
        t_score = temporal_match_score(
            event_time,
            cand.get("schedule_start"),
            cand.get("schedule_end"),
        )
        p_score = proximity_score(dist_km, max_range_km)
        penalty = compliance_penalty(
            cand.get("violation_count_90d", 0),
            cand.get("dust_suppression_required", False),
            cand.get("dust_suppression_observed", False),
        )
        confidence = compute_confidence(w_score, c_score, t_score, p_score, penalty)

        scored.append(
            {
                "rank": 0,  # placeholder; assigned after sorting
                "id": str(cand.get("id", "")),
                "name": cand.get("name", ""),
                "type": cand.get("type", ""),
                "description": cand.get("description", ""),
                "geometry": geom,
                "distance_from_station_km": dist_km,
                "bearing_from_station_deg": bearing_deg,
                "compliance_profile": {
                    "permit_id": cand.get("permit_id"),
                    "dust_suppression_required": cand.get(
                        "dust_suppression_required", False
                    ),
                    "dust_suppression_observed": cand.get(
                        "dust_suppression_observed", False
                    ),
                    "last_inspection_date": cand.get("last_inspection_date"),
                    "violation_count_90d": cand.get("violation_count_90d", 0),
                    "near_school": cand.get("near_school", False),
                    "school_name": cand.get("school_name"),
                    "school_distance_m": cand.get("school_distance_m"),
                    "near_hospital": cand.get("near_hospital", False),
                    "hospital_name": cand.get("hospital_name"),
                    "hospital_distance_m": cand.get("hospital_distance_m"),
                },
                "score_breakdown": {
                    "wind_alignment": round(w_score, 2),
                    "chemical_match": round(c_score, 2),
                    "temporal_match": round(t_score, 2),
                    "proximity": round(p_score, 2),
                    "compliance_penalty": round(penalty, 2),
                    "confidence_score": confidence,
                },
            }
        )

    # Sort by confidence descending.
    scored.sort(
        key=lambda x: x["score_breakdown"]["confidence_score"], reverse=True
    )

    # Assign ranks 1..N.
    for i, entry in enumerate(scored, start=1):
        entry["rank"] = i

    return scored
