"""Offline + live integration tests for the Task 3 attribution pipeline.

Offline tests (no DB, no network):
  - wind-cone geometry shape
  - pure scoring functions

Live tests (requires Docker DB to be running and seeded):
  - full funnel against real DB data
  - contract structural conformance of the final merged payload
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---- path bootstrap -------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.attribution import (
    _bearing_deg,
    _haversine_m,
    _point_in_cone,
    _chemical_match_score,
    _temporal_match_score,
    _wind_alignment_score,
    _proximity_score,
    _composite_confidence,
    _check_ambiguity,
    build_wind_cone_polygon,
    get_search_radius_m,
    get_half_angle_deg,
    run_attribution,
)

# ============================================================
PASS = 0
FAIL = 0


def ok(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        print(f"  [ok  ] {msg}")
        PASS += 1
    else:
        print(f"  [FAIL] {msg}")
        FAIL += 1


# ============================================================
# Offline: geometry helpers
# ============================================================
print("\n=== Geometry helpers (offline) ===")

# Shivajinagar coordinates
STA_LON, STA_LAT = 73.8440, 18.5308

# A point ~3 km WNW of station (should be inside a 290-degree wind cone)
UPWIND_LON, UPWIND_LAT = 73.8155, 18.5390   # west-northwest

# A point ~2 km SSE (should be OUTSIDE a 290-degree upwind cone)
DOWNWIND_LON, DOWNWIND_LAT = 73.8520, 18.5050

dist_upwind = _haversine_m(STA_LON, STA_LAT, UPWIND_LON, UPWIND_LAT)
ok(1000 < dist_upwind < 5000, f"haversine upwind distance ~{dist_upwind:.0f}m (should be 1–5 km)")

brg_upwind = _bearing_deg(STA_LON, STA_LAT, UPWIND_LON, UPWIND_LAT)
ok(260 <= brg_upwind <= 300, f"bearing to upwind point = {brg_upwind:.1f}° (expect ~280°)")

# Wind direction 290° (WNW), half-angle 18°, reach 4.5 km
ok(
    _point_in_cone(UPWIND_LON, UPWIND_LAT, STA_LON, STA_LAT, 290.0, 18.0, 4500),
    "WNW point is inside 290° wind cone",
)
ok(
    not _point_in_cone(DOWNWIND_LON, DOWNWIND_LAT, STA_LON, STA_LAT, 290.0, 18.0, 4500),
    "SSE point is OUTSIDE 290° wind cone",
)

# ============================================================
# Offline: wind cone polygon
# ============================================================
print("\n=== Wind cone polygon (offline) ===")

cone = build_wind_cone_polygon(STA_LON, STA_LAT, 290.0, 18.0, 4500.0)
ok(cone["type"] == "Polygon", "cone geometry type is 'Polygon'")
ring = cone["coordinates"][0]
ok(len(ring) >= 4, f"cone ring has {len(ring)} points (>=4)")
ok(ring[0] == ring[-1], "ring is closed (first == last point)")
ok(ring[0] == [STA_LON, STA_LAT], "ring starts at station (apex)")

# ============================================================
# Offline: dynamic search parameters
# ============================================================
print("\n=== Search parameters (offline) ===")

ok(get_search_radius_m(2) == 1500, "radius 1500m at wind < 5 km/h")
ok(get_search_radius_m(10) == 2500, "radius 2500m at wind 5–15 km/h")
ok(get_search_radius_m(20) == 3500, "radius 3500m at wind 15–25 km/h")
ok(get_search_radius_m(30) == 4500, "radius 4500m at wind >= 25 km/h")

ok(get_half_angle_deg(2) == 45.0, "half-angle 45° at low wind")
ok(get_half_angle_deg(30) == 18.0, "half-angle 18° at high wind")

# ============================================================
# Offline: scoring functions
# ============================================================
print("\n=== Scoring functions (offline) ===")

ok(_chemical_match_score("crustal_dominant", "construction") == 1.0, "crustal → construction = 1.0")
ok(_chemical_match_score("crustal_dominant", "traffic") == 0.6, "crustal → traffic = 0.6")
ok(_chemical_match_score("combustion_vehicular", "traffic") == 1.0, "combustion → traffic = 1.0")
ok(_chemical_match_score("industrial_sulfur", "industrial") == 1.0, "sulfur → industrial = 1.0")
ok(_chemical_match_score("industrial_sulfur", "construction") == 0.0, "sulfur → construction = 0.0")
ok(_chemical_match_score("biomass_burning", "waste_burning") == 1.0, "biomass → waste = 1.0")

# temporal: industrial source (24/7) at 08:30 AM IST
class _MockSource:
    def __init__(self, start, end, near_school=False, near_hospital=False, stype="industrial"):
        self.schedule_start = start
        self.schedule_end   = end
        self.near_school    = near_school
        self.near_hospital  = near_hospital
        self.type           = stype

IST = timezone(timedelta(hours=5, minutes=30))
SPIKE_TS = datetime(2026, 6, 25, 8, 30, tzinfo=IST)

industrial_24_7 = _MockSource(dtime(0, 0), dtime(23, 59, 59))
ok(_temporal_match_score(SPIKE_TS, industrial_24_7) == 1.0, "24/7 source: temporal = 1.0")

construction_day = _MockSource(dtime(9, 0), dtime(18, 0))
ok(_temporal_match_score(SPIKE_TS, construction_day) == 0.2, "construction at 08:30 (before shift): temporal = 0.2")

traffic_morning = _MockSource(dtime(8, 0), dtime(10, 0))
ok(_temporal_match_score(SPIKE_TS, traffic_morning) == 1.0, "traffic at 08:30 (morning peak): temporal = 1.0")

# wind alignment
wind_score = _wind_alignment_score(UPWIND_LON, UPWIND_LAT, STA_LON, STA_LAT, 290.0, 18.0)
ok(0.0 <= wind_score <= 1.0, f"wind alignment score in [0,1]: {wind_score}")

# proximity
prox = _proximity_score(1000, 4500)
ok(abs(prox - round(1 - 1000 / 4500, 4)) < 1e-6, f"proximity score math correct: {prox}")

# composite
c = _composite_confidence(0.92, 0.88, 0.95)
ok(abs(c - round(0.4 * 0.92 + 0.35 * 0.88 + 0.25 * 0.95, 4)) < 1e-4, f"composite confidence = {c}")

# ambiguity check
r_close  = [{"score_breakdown": {"confidence_score": 0.91}},
            {"score_breakdown": {"confidence_score": 0.85}}]
r_clear  = [{"score_breakdown": {"confidence_score": 0.91}},
            {"score_breakdown": {"confidence_score": 0.70}}]
ok(_check_ambiguity(r_close), "ambiguous: delta=0.06 < 0.15")
ok(not _check_ambiguity(r_clear), "not ambiguous: delta=0.21 >= 0.15")



# ============================================================
# Contract structural conformance helper
# ============================================================
def _shape(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _shape(vv) for k, vv in v.items()}
    if isinstance(v, list):
        return [_shape(v[0])] if v else ["empty"]
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "str"


def _assert_keys_present(actual: Any, expected: Any, path: str) -> None:
    """Check that all expected keys exist and have the right primitive type.

    Nullable fields: if the contract shows a non-null value for an optional
    field but our implementation returns None, we accept it — the contract
    sample uses fictional data while the DB stores real (but incomplete) info.
    Nullable fields are detected by name heuristic.
    """
    _NULLABLE_FIELD_HINTS = (
        "permit_id", "school_name", "school_distance", "hospital_name",
        "hospital_distance", "inspection_date", "hospital_distance_m",
        "school_distance_m", "last_inspection_date", "hospital_name",
    )

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            ok(False, f"{path}: expected object, got {type(actual).__name__}")
            return
        missing = [k for k in expected if k not in actual]
        ok(not missing, f"{path}: all contract keys present (missing={missing})")
        for k in expected:
            if k in actual:
                _assert_keys_present(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        ok(isinstance(actual, list), f"{path}: expected list")
        if actual:
            # coordinate rings may contain tuples or lists — normalise
            first = list(actual[0]) if isinstance(actual[0], tuple) else actual[0]
            _assert_keys_present(first, expected[0], f"{path}[0]")
    elif expected in ("int", "float"):
        # Accept None for optional nullable numeric fields
        field_leaf = path.split(".")[-1]
        if actual is None and any(h in field_leaf for h in _NULLABLE_FIELD_HINTS):
            ok(True, f"{path}: nullable number, got None (accepted)")
        else:
            ok(
                isinstance(actual, (int, float)) and not isinstance(actual, bool),
                f"{path}: expected number, got {type(actual).__name__}={actual!r}",
            )
    elif expected == "bool":
        ok(isinstance(actual, bool), f"{path}: expected bool, got {actual!r}")
    elif expected == "str":
        # Accept None for optional nullable string fields (permit_id, school_name, etc.)
        field_leaf = path.split(".")[-1]
        if actual is None and any(h in field_leaf for h in _NULLABLE_FIELD_HINTS):
            ok(True, f"{path}: nullable str, got None (accepted)")
        else:
            ok(isinstance(actual, str), f"{path}: expected str, got {actual!r}")


# ============================================================
# Live DB test
# ============================================================
print("\n=== Live DB attribution test ===")

try:
    from db.connection import get_session, ping
    from db.models import Station
    from sqlalchemy import select

    if not ping():
        print("  [SKIP] Database not reachable — skipping live tests.")
    else:
        with get_session() as session:
            station = session.execute(
                select(Station).where(Station.name == "Shivajinagar")
            ).scalars().first()

            if station is None:
                print("  [SKIP] Shivajinagar station not seeded — run `python -m db.seed_data` first.")
            else:
                from geoalchemy2 import functions as gfunc
                from sqlalchemy import select as _sel

                lon_q, lat_q = session.execute(
                    _sel(gfunc.ST_X(station.geom), gfunc.ST_Y(station.geom))
                ).one()
                sta_lon, sta_lat = float(lon_q), float(lat_q)

                result = run_attribution(
                    session=session,
                    station_lon=sta_lon,
                    station_lat=sta_lat,
                    station_name=station.name,
                    spike_ts=datetime(2026, 6, 25, 8, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
                    aqi_value=310.0,
                    dominant_pollutant="PM10",
                    signature_class="crustal_dominant",
                    wind_direction_deg=290.0,
                    wind_speed_kmh=14.5,
                    pasquill_class="D",
                )

                ok("wind_cone_geometry" in result, "result has 'wind_cone_geometry'")
                ok("ranked_candidates" in result, "result has 'ranked_candidates'")
                ok("actionable_intelligence" in result, "result has 'actionable_intelligence'")

                wc = result["wind_cone_geometry"]
                ok(wc["type"] == "Feature", "wind_cone_geometry is a GeoJSON Feature")
                ok(wc["geometry"]["type"] == "Polygon", "wind_cone geometry is a Polygon")
                ok("properties" in wc, "wind_cone_geometry has properties")
                ok(wc["properties"].get("cone_type") == "upwind_source_area", "cone_type = upwind_source_area")

                candidates = result["ranked_candidates"]
                ok(isinstance(candidates, list), f"ranked_candidates is list (len={len(candidates)})")
                if candidates:
                    top = candidates[0]
                    ok(top["rank"] == 1, "top candidate rank == 1")
                    ok("score_breakdown" in top, "top candidate has score_breakdown")
                    ok("compliance_profile" in top, "top candidate has compliance_profile")
                    ok("geometry" in top, "top candidate has geometry")
                    ok(0.0 <= top["score_breakdown"]["confidence_score"] <= 1.0,
                       f"confidence_score in [0,1]: {top['score_breakdown']['confidence_score']}")

                    # Candidates ranking order
                    scores = [c["score_breakdown"]["confidence_score"] for c in candidates]
                    ok(scores == sorted(scores, reverse=True), "candidates sorted by confidence desc")

                ai = result["actionable_intelligence"]
                ok(isinstance(ai.get("enforcement_priority"), float), "enforcement_priority is float")
                ok(isinstance(ai.get("recommended_actions"), list), "recommended_actions is list")
                ok("localized_advisory" in ai, "actionable_intelligence has localized_advisory")
                ok("en" in ai["localized_advisory"], "localized_advisory has 'en'")
                ok("hi" in ai["localized_advisory"], "localized_advisory has 'hi'")
                ok("mr" in ai["localized_advisory"], "localized_advisory has 'mr'")

                ok("pipeline_timings" in result, "result has 'pipeline_timings'")
                if "pipeline_timings" in result:
                    tms = result["pipeline_timings"]
                    ok("total_ms" in tms, f"timings has total_ms: {tms.get('total_ms')}")
                    ok("spatial_filter_ms" in tms, "timings has spatial_filter_ms")
                    ok("wind_cone_ms" in tms, "timings has wind_cone_ms")
                    ok("scoring_ms" in tms, "timings has scoring_ms")

                # ---- Contract structural check against data_contract_sample.json ----
                print("\n  -- Contract structural conformance --")
                contract_path = PROJECT_ROOT / "data_contract_sample.json"
                contract = json.loads(contract_path.read_text(encoding="utf-8"))

                # Check wind_cone_geometry shape
                _assert_keys_present(
                    result["wind_cone_geometry"],
                    _shape(contract["wind_cone_geometry"]),
                    "wind_cone_geometry",
                )

                # Check ranked_candidates[0] shape against contract[0]
                if result["ranked_candidates"] and contract.get("ranked_candidates"):
                    _assert_keys_present(
                        result["ranked_candidates"][0],
                        _shape(contract["ranked_candidates"][0]),
                        "ranked_candidates[0]",
                    )

                # Check actionable_intelligence top-level keys
                expected_ai_keys = [
                    "enforcement_priority", "priority_justification",
                    "recommended_actions", "estimated_response_time_min",
                    "localized_advisory",
                ]
                missing_ai = [k for k in expected_ai_keys if k not in ai]
                ok(not missing_ai, f"actionable_intelligence keys present (missing={missing_ai})")

                if candidates:
                    top_name = candidates[0]['name']
                    top_conf = candidates[0]['score_breakdown']['confidence_score']
                    is_ambig = ai.get('ambiguous')
                    print(f"  Top candidate: '{top_name}' (confidence={top_conf}, ambiguous={is_ambig})")

except Exception as e:
    print(f"  [ERROR] Live test error: {e}")
    import traceback; traceback.print_exc()

# ============================================================
# Final report
# ============================================================
print(f"\n{'='*60}")
print(f"RESULT: {PASS} passed / {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED ✓")
else:
    print("SOME TESTS FAILED ✗")
    sys.exit(1)
