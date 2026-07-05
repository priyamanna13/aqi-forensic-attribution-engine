"""
Wind Cone Geometry Generator
=============================
Generates upwind source-area cone (pie/wedge) polygons as GeoJSON Features.
The cone points in the direction wind comes FROM, parameterized by
Pasquill atmospheric stability class.
"""

import math

# Earth radius in kilometres (mean)
_EARTH_RADIUS_KM = 6371.0

# Pasquill stability class look-up tables
_HALF_ANGLE_DEG = {
    "A": 25,
    "B": 22,
    "C": 20,
    "D": 18,
    "E": 15,
    "F": 12,
}

_REACH_KM = {
    "A": 2.5,
    "B": 3.0,
    "C": 3.5,
    "D": 4.5,
    "E": 5.5,
    "F": 7.0,
}

# Visual style (red tones)
_STYLE = {
    "fill_color": "#ef444480",
    "stroke_color": "#dc2626",
    "stroke_width": 2,
    "fill_opacity": 0.25,
}


def _destination_point(lon: float, lat: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """
    Compute the destination point given a start point, bearing, and distance
    using the Haversine forward (direct) formula.

    Parameters
    ----------
    lon : float
        Origin longitude in decimal degrees.
    lat : float
        Origin latitude in decimal degrees.
    bearing_deg : float
        Bearing in degrees from north (clockwise).
    distance_km : float
        Distance to travel in kilometres.

    Returns
    -------
    tuple[float, float]
        (longitude, latitude) of the destination point in decimal degrees.
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)
    angular_dist = distance_km / _EARTH_RADIUS_KM  # δ = d / R

    dest_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(angular_dist)
        + math.cos(lat_rad) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    dest_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat_rad),
        math.cos(angular_dist) - math.sin(lat_rad) * math.sin(dest_lat_rad),
    )

    return (round(math.degrees(dest_lon_rad), 4), round(math.degrees(dest_lat_rad), 4))


def generate_wind_cone(
    origin_lon: float,
    origin_lat: float,
    wind_direction_deg: float,
    pasquill_class: str,
    station_name: str,
) -> dict:
    """
    Generate an upwind source-area cone as a GeoJSON Feature.

    The cone extends in the direction the wind comes FROM.  A wind direction
    of 290° means wind arrives from bearing 290°, so the cone points at 290°.

    Parameters
    ----------
    origin_lon : float
        Longitude of the monitoring station (decimal degrees).
    origin_lat : float
        Latitude of the monitoring station (decimal degrees).
    wind_direction_deg : float
        Meteorological wind direction in degrees (direction wind comes FROM).
    pasquill_class : str
        Pasquill atmospheric stability class (A–F).
    station_name : str
        Human-readable name of the monitoring station.

    Returns
    -------
    dict
        A GeoJSON Feature dict with a Polygon geometry describing the cone.
    """
    pasquill_class = pasquill_class.upper()
    if pasquill_class not in _HALF_ANGLE_DEG:
        raise ValueError(f"Invalid Pasquill class '{pasquill_class}'. Must be A–F.")

    half_angle = _HALF_ANGLE_DEG[pasquill_class]
    reach_km = _REACH_KM[pasquill_class]

    # The cone centre bearing equals the wind direction (upwind).
    centre_bearing = wind_direction_deg % 360

    # Arc start and end bearings
    start_bearing = centre_bearing - half_angle
    end_bearing = centre_bearing + half_angle

    # Generate ~20 equally-spaced arc points along the outer edge
    num_arc_points = 20
    arc_coords = []
    for i in range(num_arc_points + 1):  # inclusive of both ends → 21 points
        fraction = i / num_arc_points
        bearing = start_bearing + fraction * (end_bearing - start_bearing)
        pt = _destination_point(origin_lon, origin_lat, bearing, reach_km)
        arc_coords.append(list(pt))

    # Build the closed ring: origin → arc → origin
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
