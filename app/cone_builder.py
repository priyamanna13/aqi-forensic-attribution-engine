"""
Dynamic Wind Cone Builder
=========================
High-level wrapper around :func:`app.wind_cone.generate_wind_cone` that
computes the Pasquill stability class from raw meteorological parameters
and supports a *search_radius_override* for city-config or user-specified
reach distances.

Two public entry points:

* :func:`build_wind_cone` — accepts individual met parameters.
* :func:`build_cone_from_weather_snapshot` — accepts a ``weather`` dict
  (as returned by *WeatherSyncService / MockIMDSource*).

Both are safe to call from ``attribution.py``, ``replay_engine.py``,
and the ``/api/v1/cone`` endpoint.
"""

from __future__ import annotations

import math
from typing import Any

from app.pasquill import classify_stability
from app.wind_cone import (
    _destination_point,
    _HALF_ANGLE_DEG,
    _REACH_KM,
    _STYLE,
    generate_wind_cone,
)


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _dynamic_half_angle(
    wind_speed_kmh: float,
    pasquill_class: str,
) -> float:
    """Return a half-angle that widens slightly for very low wind speeds.

    Light / variable winds (<6 km/h) produce more directional uncertainty,
    so the cone is widened by up to 30 % beyond the Pasquill baseline.
    Above 15 km/h the Pasquill default is used unchanged.

    Parameters
    ----------
    wind_speed_kmh : float
        Surface wind speed in km/h.
    pasquill_class : str
        Validated Pasquill class letter (A–F, uppercase).

    Returns
    -------
    float
        Half-angle in degrees.
    """
    base = _HALF_ANGLE_DEG[pasquill_class]

    # Widen cone for light / variable winds (linear ramp from 1.3× at
    # 0 km/h down to 1.0× at 15 km/h).
    if wind_speed_kmh < 15.0:
        scale = 1.0 + 0.3 * max(0.0, (15.0 - wind_speed_kmh) / 15.0)
        return round(base * scale, 1)
    return float(base)


def _rebuild_cone_with_custom_reach(
    origin_lon: float,
    origin_lat: float,
    centre_bearing: float,
    half_angle: float,
    reach_km: float,
    station_name: str,
    pasquill_class: str,
    num_arc_points: int = 32,
) -> dict:
    """Build a GeoJSON cone Feature with an arbitrary reach distance.

    This mirrors the polygon-construction logic in
    :func:`app.wind_cone.generate_wind_cone` but accepts explicit
    *half_angle* and *reach_km* values, bypassing the Pasquill look-up
    tables.

    Parameters
    ----------
    origin_lon, origin_lat : float
        Station coordinates (decimal degrees).
    centre_bearing : float
        Upwind bearing in degrees from north.
    half_angle : float
        Half-opening angle of the cone in degrees.
    reach_km : float
        Radial extent of the cone in kilometres.
    station_name : str
        Human-readable station name.
    pasquill_class : str
        Pasquill class letter (for metadata only).
    num_arc_points : int
        Number of points on the outer arc (default 32).

    Returns
    -------
    dict
        A GeoJSON Feature with Polygon geometry.
    """
    start_bearing = centre_bearing - half_angle
    end_bearing = centre_bearing + half_angle

    arc_coords: list[list[float]] = []
    for i in range(num_arc_points + 1):
        fraction = i / num_arc_points
        bearing = start_bearing + fraction * (end_bearing - start_bearing)
        pt = _destination_point(origin_lon, origin_lat, bearing, reach_km)
        arc_coords.append(list(pt))

    origin = [round(origin_lon, 4), round(origin_lat, 4)]
    ring = [origin] + arc_coords + [origin]

    return {
        "type": "Feature",
        "properties": {
            "cone_type": "upwind_source_area",
            "origin_station": station_name,
            "bearing_deg": centre_bearing,
            "half_angle_deg": half_angle,
            "reach_km": reach_km,
            "pasquill_class": pasquill_class,
            "style": dict(_STYLE),
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [ring],
        },
    }


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def build_wind_cone(
    station_lon: float,
    station_lat: float,
    wind_direction_deg: float,
    wind_speed_kmh: float,
    station_name: str,
    cloud_cover_oktas: int = 4,
    is_daytime: bool = True,
    solar_elevation_deg: float = 30.0,
    search_radius_override_km: float | None = None,
    num_arc_points: int = 32,
) -> dict:
    """Build a GeoJSON wind cone Feature with automatic Pasquill classification.

    This is the primary entry point for generating wind cones.  It computes
    the Pasquill stability class from meteorological parameters, then
    delegates to the existing :func:`~app.wind_cone.generate_wind_cone`
    function.

    If *search_radius_override_km* is provided, it overrides the
    Pasquill-based reach distance (useful for ``city_config.yml``
    ``max_radius`` settings).

    Parameters
    ----------
    station_lon, station_lat : float
        Monitoring-station coordinates (decimal degrees).
    wind_direction_deg : float
        Meteorological wind direction — the bearing wind comes FROM.
    wind_speed_kmh : float
        Surface wind speed in km/h.
    station_name : str
        Human-readable station name.
    cloud_cover_oktas : int
        Cloud cover in oktas (0–8).  Defaults to 4 (half-sky).
    is_daytime : bool
        ``True`` when the sun is up.
    solar_elevation_deg : float
        Sun elevation angle (degrees above horizon).
    search_radius_override_km : float | None
        If set, overrides the Pasquill-based reach distance.
    num_arc_points : int
        Number of points along the outer arc (default 32).

    Returns
    -------
    dict
        A GeoJSON Feature dict with Polygon geometry.
    """
    # 1. Classify atmospheric stability -----------------------------------
    stability: dict[str, Any] = classify_stability(
        wind_speed_kmh=wind_speed_kmh,
        cloud_cover_oktas=cloud_cover_oktas,
        is_daytime=is_daytime,
        solar_elevation_deg=solar_elevation_deg,
    )
    pasquill_class: str = stability["pasquill_class"]

    # 2. Resolve half-angle (dynamic widening for light winds) ------------
    half_angle = _dynamic_half_angle(wind_speed_kmh, pasquill_class)

    # 3. Resolve reach distance -------------------------------------------
    reach_km: float = (
        search_radius_override_km
        if search_radius_override_km is not None
        else _REACH_KM[pasquill_class]
    )

    # 4. Determine centre bearing (upwind = wind-from direction) ----------
    centre_bearing = wind_direction_deg % 360

    # 5. Build the cone ---------------------------------------------------
    #    When either the half-angle differs from the Pasquill default
    #    (dynamic widening) or a radius override is active we must build
    #    the polygon ourselves; otherwise delegate to generate_wind_cone.
    needs_custom_build = (
        search_radius_override_km is not None
        or half_angle != _HALF_ANGLE_DEG[pasquill_class]
        or num_arc_points != 20  # generate_wind_cone hard-codes 20
    )

    if needs_custom_build:
        feature = _rebuild_cone_with_custom_reach(
            origin_lon=station_lon,
            origin_lat=station_lat,
            centre_bearing=centre_bearing,
            half_angle=half_angle,
            reach_km=reach_km,
            station_name=station_name,
            pasquill_class=pasquill_class,
            num_arc_points=num_arc_points,
        )
    else:
        feature = generate_wind_cone(
            origin_lon=station_lon,
            origin_lat=station_lat,
            wind_direction_deg=wind_direction_deg,
            pasquill_class=pasquill_class,
            station_name=station_name,
        )

    # 6. Enrich properties with stability metadata ------------------------
    feature["properties"]["stability"] = {
        "label": stability["label"],
        "description": stability["description"],
        "dispersion_coefficient": stability["dispersion_coefficient"],
    }
    feature["properties"]["wind_speed_kmh"] = round(wind_speed_kmh, 1)

    return feature


def build_cone_from_weather_snapshot(
    station_lon: float,
    station_lat: float,
    station_name: str,
    weather: dict,
    search_radius_override_km: float | None = None,
) -> dict:
    """Convenience wrapper: build cone directly from a weather snapshot dict.

    Extracts ``wind_direction_deg``, ``wind_speed_kmh``, ``cloud_cover``,
    etc. from the *weather* dict (as returned by *WeatherSyncService* /
    *MockIMDSource*).

    Parameters
    ----------
    station_lon, station_lat : float
        Station coordinates (decimal degrees).
    station_name : str
        Human-readable station name.
    weather : dict
        Weather snapshot with at least the following keys:

        * ``wind_direction_deg`` (float)
        * ``wind_speed_kmh`` (float)

        Optional keys (with defaults):

        * ``cloud_cover_oktas`` (int, default 4)
        * ``is_daytime`` (bool, default True)
        * ``solar_elevation_deg`` (float, default 30.0)
    search_radius_override_km : float | None
        Override for the Pasquill-based reach distance.

    Returns
    -------
    dict
        A GeoJSON Feature dict with Polygon geometry.

    Raises
    ------
    KeyError
        If required keys are missing from *weather*.
    """
    return build_wind_cone(
        station_lon=station_lon,
        station_lat=station_lat,
        wind_direction_deg=weather["wind_direction_deg"],
        wind_speed_kmh=weather["wind_speed_kmh"],
        station_name=station_name,
        cloud_cover_oktas=weather.get("cloud_cover_oktas", 4),
        is_daytime=weather.get("is_daytime", True),
        solar_elevation_deg=weather.get("solar_elevation_deg", 30.0),
        search_radius_override_km=search_radius_override_km,
    )
