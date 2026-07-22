"""Dynamic GeoJSON wind cone builder.

Generates standard GeoJSON Feature polygons representing the upwind
source search area. Accepts live wind parameters and computes:
  - Dynamic half-angle from wind speed
  - Dynamic reach from wind speed and stability class
  - Meter-accurate arcs for spatial filtering

This module is called by:
  1. attribution.py — during live spike processing
  2. replay_engine.py — when generating historical wind cones
  3. api/main.py — for the /api/v1/cone endpoint (ad-hoc queries)
"""
from __future__ import annotations

from typing import Any, Optional
from pipeline.attribution import (
    build_wind_cone_polygon,
    get_search_radius_m,
    get_half_angle_deg,
    _build_wind_cone_feature,
)


def build_wind_cone(
    station_lon: float,
    station_lat: float,
    station_name: str,
    wind_direction_deg: float,
    wind_speed_kmh: float,
    pasquill_class: str = "D",
    num_arc_points: int = 32,
    search_radius_override: Optional[float] = None,
) -> dict[str, Any]:
    """Return a GeoJSON Feature with the wind cone polygon and metadata."""
    radius_m = search_radius_override if search_radius_override is not None else get_search_radius_m(wind_speed_kmh)
    is_calm = wind_speed_kmh < 0.5
    half_angle = 180.0 if is_calm else get_half_angle_deg(wind_speed_kmh)

    return _build_wind_cone_feature(
        station_lon=station_lon,
        station_lat=station_lat,
        station_name=station_name,
        wind_direction_deg=wind_direction_deg,
        half_angle_deg=half_angle,
        reach_m=radius_m,
        pasquill_class=pasquill_class,
    )
