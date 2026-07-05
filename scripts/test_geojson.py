"""Offline self-test for the pollution_sources GeoJSON serializer.

Runs WITHOUT a database — it builds source dicts from WKT coordinates (the
same helpers seed_data uses) and asserts the serialized output is valid
GeoJSON with the expected geometry type and properties.

Run::

    python scripts/test_geojson.py

Exit code 0 = pass, non-zero = fail.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.geo_utils import (  # noqa: E402
    linestring_wkt,
    point_wkt,
    polygon_wkt,
    source_to_geojson,
    sources_to_geojson,
)


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_single_point_source() -> None:
    src = {
        "id": "src-1",
        "name": "Katraj Hillock Open Dump",
        "type": "waste_burning",
        "geom": point_wkt(73.8575, 18.4440),
        "schedule_start": "05:00:00",
        "schedule_end": "07:00:00",
        "near_school": True,
        "near_hospital": False,
    }
    # Build a Feature; note point_wkt returns WKT text, which our serializer
    # accepts only if it's JSON-parseable. WKT is NOT GeoJSON, so we feed the
    # serializer a GeoJSON dict here instead (this is the contract used by the
    # API path; for raw WKT the DB round-trip via ST_AsGeoJSON is the path).
    geom_geojson = {"type": "Point", "coordinates": [73.8575, 18.4440]}
    src_for_serial = dict(src)
    src_for_serial["geom"] = geom_geojson

    feat = json.loads(source_to_geojson(src_for_serial))
    _expect(feat["type"] == "Feature", "single source -> Feature")
    _expect(feat["geometry"]["type"] == "Point", "geometry type is Point")
    _expect(
        feat["geometry"]["coordinates"] == [73.8575, 18.4440],
        "coordinates preserved [lon, lat]",
    )
    _expect(
        feat["properties"]["near_school"] is True, "near_school flag propagated"
    )
    _expect(
        feat["properties"]["name"] == src["name"], "name propagated as property"
    )


def test_linestring_and_polygon_wkt() -> None:
    # The WKT builders themselves should produce parseable PostGIS WKT.
    ls = linestring_wkt([(73.815, 18.5074), (73.829, 18.5074), (73.843, 18.508)])
    _expect(ls.startswith("LINESTRING("), "linestring_wkt prefix")
    _expect(ls.count(",") == 2, "linestring has 3 vertices (2 commas)")

    poly = polygon_wkt([
        (73.8320, 18.5400), (73.8350, 18.5400),
        (73.8350, 18.5375), (73.8320, 18.5375),
    ])
    _expect(poly.startswith("POLYGON(("), "polygon_wkt prefix")
    # Auto-closing: first and last coordinate pair must match.
    # Split on ", " to get coordinate pairs, then on " " for lon/lat.
    pairs = poly.split("((")[1].rstrip(")").split(", ")
    first = pairs[0].split(" ")
    last = pairs[-1].split(" ")
    _expect(first == last, "polygon ring auto-closed by builder")


def test_feature_collection() -> None:
    sources = [
        {
            "id": "a",
            "name": "Site A",
            "type": "traffic",
            "geom": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            "schedule_start": None,
            "schedule_end": None,
            "near_school": False,
            "near_hospital": False,
        },
        {
            "id": "b",
            "name": "Site B",
            "type": "industrial",
            "geom": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "schedule_start": "00:00:00",
            "schedule_end": "23:59:59",
            "near_school": False,
            "near_hospital": True,
        },
    ]
    fc = json.loads(sources_to_geojson(sources))
    _expect(fc["type"] == "FeatureCollection", "is FeatureCollection")
    _expect(len(fc["features"]) == 2, "contains 2 features")
    _expect(
        fc["features"][1]["properties"]["near_hospital"] is True,
        "polygon source near_hospital propagated",
    )


def main() -> int:
    print("=" * 60)
    print("Offline GeoJSON serializer self-test")
    print("=" * 60)
    tests = [
        ("single Point source", test_single_point_source),
        ("WKT builders (LineString/Polygon)", test_linestring_and_polygon_wkt),
        ("FeatureCollection", test_feature_collection),
    ]
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            fn()
        except AssertionError as exc:
            print(f"\nFAIL: {name}: {exc}")
            return 1
    print("\nAll GeoJSON serializer tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
