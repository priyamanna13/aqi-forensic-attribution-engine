"""
Tests for app.wind_cone – Wind Cone Geometry Generator
======================================================
"""

import pytest

from app.wind_cone import generate_wind_cone

# ---------------------------------------------------------------------------
# Fixture: Shivajinagar station, wind from 290°, Pasquill class D
# ---------------------------------------------------------------------------
@pytest.fixture
def cone():
    return generate_wind_cone(73.8567, 18.5308, 290, "D", "Shivajinagar")


# ---------------------------------------------------------------------------
# 1. Output is a valid GeoJSON Feature with geometry.type == "Polygon"
# ---------------------------------------------------------------------------
def test_geojson_feature_structure(cone):
    assert cone["type"] == "Feature"
    assert "properties" in cone
    assert "geometry" in cone
    assert cone["geometry"]["type"] == "Polygon"


# ---------------------------------------------------------------------------
# 2. Origin point (first & last coordinate) matches station coordinates
# ---------------------------------------------------------------------------
def test_origin_matches_station(cone):
    ring = cone["geometry"]["coordinates"][0]
    expected_origin = [73.8567, 18.5308]
    assert ring[0] == expected_origin, f"First coord {ring[0]} != {expected_origin}"
    assert ring[-1] == expected_origin, f"Last coord {ring[-1]} != {expected_origin}"


# ---------------------------------------------------------------------------
# 3. Number of coordinates >= 5 (minimum valid polygon)
# ---------------------------------------------------------------------------
def test_minimum_coordinate_count(cone):
    ring = cone["geometry"]["coordinates"][0]
    assert len(ring) >= 5, f"Ring has only {len(ring)} points; need >= 5"


# ---------------------------------------------------------------------------
# 4. Properties contain all required keys
# ---------------------------------------------------------------------------
def test_required_property_keys(cone):
    required = {
        "cone_type",
        "origin_station",
        "bearing_deg",
        "half_angle_deg",
        "reach_km",
        "pasquill_class",
        "style",
    }
    assert required.issubset(cone["properties"].keys())


# ---------------------------------------------------------------------------
# 5. Pasquill class D → half_angle == 18, reach == 4.5
# ---------------------------------------------------------------------------
def test_pasquill_d_parameters(cone):
    props = cone["properties"]
    assert props["half_angle_deg"] == 18
    assert props["reach_km"] == 4.5


# ---------------------------------------------------------------------------
# 6. All generated coordinates within Pune bounding box
# ---------------------------------------------------------------------------
def test_coordinates_within_pune_bbox(cone):
    ring = cone["geometry"]["coordinates"][0]
    for lon, lat in ring:
        assert 73.7 <= lon <= 74.0, f"Longitude {lon} outside Pune bbox"
        assert 18.4 <= lat <= 18.7, f"Latitude {lat} outside Pune bbox"


# ---------------------------------------------------------------------------
# 7. Polygon ring is closed (first coord == last coord)
# ---------------------------------------------------------------------------
def test_polygon_ring_closed(cone):
    ring = cone["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1], "Polygon ring is not closed"
