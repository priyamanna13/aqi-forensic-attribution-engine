"""Geometry helpers + GeoJSON serialization for pollution sources.

Two ways geometry enters the system:
  1. As raw coordinate data in Python (lists of [lon, lat]).
  2. As WKB/EWKB bytes from a GeoAlchemy2 query.

This module normalizes both into GeoJSON (RFC 7946) Feature / FeatureCollection
strings. The serializer is required by the task spec and is used by:
  - future attribution/alert code (writing candidate sources into JSONB),
  - any API/visualization layer that needs to emit sources on a map.

Design notes:
  - When a ``PollutionSource`` ORM object is passed whose ``geom`` is a
    server-side ``ST_AsGeoJSON`` result (text), we parse it directly.
  - When ``geom`` is raw WKB/EWKB bytes (the default SQLAlchemy read path),
    we decode it locally — no DB round-trip needed.
  - A pure-Python ``source_dict`` form is also accepted so callers that build
    sources from in-memory coordinate lists (e.g. seed_data) can serialize
    without a DB session. This is what ``test_geojson.py`` exercises.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

# geoalchemy2.functions import is only needed for typed helpers below; keep it
# lazy so this module also imports cleanly without a live DB.
try:
    from geoalchemy2.elements import WKBElement
    from geoalchemy2.shape import to_shape
    _HAS_GEOALCHEMY2 = True
except Exception:  # pragma: no cover - geoalchemy2 always installed in this project
    _HAS_GEOALCHEMY2 = False


# --------------------------------------------------------------------------
# Pure-Python geometry builders (WKT) — used by seed_data and tests.
# --------------------------------------------------------------------------
def point_wkt(lon: float, lat: float) -> str:
    """Return WKT for a POINT, e.g. ``'POINT(73.844 18.531)'``."""
    return f"POINT({lon} {_lat(lat)})"


def linestring_wkt(coords: Iterable[tuple[float, float]]) -> str:
    """Return WKT for a LINESTRING from an iterable of (lon, lat) pairs."""
    inner = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"LINESTRING({inner})"


def polygon_wkt(ring: Iterable[tuple[float, float]]) -> str:
    """Return WKT for a POLYGON from a single exterior ring.

    The ring is auto-closed if the caller didn't supply a closing point.
    """
    pts = [(float(lon), float(lat)) for lon, lat in ring]
    if not pts:
        raise ValueError("polygon ring must have at least 3 points")
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    inner = ", ".join(f"{lon} {lat}" for lon, lat in pts)
    return f"POLYGON(({inner}))"


def _lat(lat: float) -> str:
    # Keep formatting stable & trim unnecessary trailing zeros.
    return f"{float(lat):.6f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------
# Geometry -> GeoJSON geometry dict
# --------------------------------------------------------------------------
def _wkb_to_geojson(wkb: Any) -> dict:
    """Decode an EWKB/WKB element into a GeoJSON geometry dict."""
    if not _HAS_GEOALCHEMY2:  # pragma: no cover
        raise RuntimeError("geoalchemy2 is required to decode WKB geometries")
    shp = to_shape(wkb if isinstance(wkb, WKBElement) else WKBElement(bytes(wkb)))
    return _shapely_to_geojson(shp)


def _shapely_to_geojson(shp: Any) -> dict:
    """Convert a shapely geometry to a GeoJSON geometry dict."""
    geom_type = shp.geom_type.upper()
    if geom_type == "POINT":
        return {"type": "Point", "coordinates": [shp.x, shp.y]}
    if geom_type == "LINESTRING":
        return {
            "type": "LineString",
            "coordinates": [[x, y] for x, y in shp.coords],
        }
    if geom_type == "POLYGON":
        rings = [
            [[x, y] for x, y in ring.coords] for ring in shp.exterior.geoms
        ] if hasattr(shp.exterior, "geoms") else [
            [[x, y] for x, y in shp.exterior.coords]
        ]
        # Interior holes (if any).
        for interior in getattr(shp, "interiors", []) or []:
            rings.append([[x, y] for x, y in interior.coords])
        return {"type": "Polygon", "coordinates": rings}
    raise ValueError(f"Unsupported geometry type: {geom_type}")


def _coerce_geometry_to_geojson(geom: Any) -> dict:
    """Accept many forms and return a GeoJSON geometry dict.

    Accepted:
      - dict already in GeoJSON form,
      - str: JSON text (GeoJSON) OR PostGIS ``ST_AsGeoJSON`` output,
      - WKBElement / raw bytes (EWKB),
      - shapely geometry.
    """
    if isinstance(geom, Mapping):
        return dict(geom)
    if isinstance(geom, str):
        s = geom.strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse geometry string as JSON: {exc}")
    if _HAS_GEOALCHEMY2 and isinstance(geom, WKBElement):
        return _wkb_to_geojson(geom)
    if isinstance(geom, (bytes, bytearray)):
        return _wkb_to_geojson(bytes(geom))
    # Shapely fallback (import lazily so the module imports without shapely
    # present in pure-Python test paths).
    try:
        from shapely.geometry.base import BaseGeometry

        if isinstance(geom, BaseGeometry):
            return _shapely_to_geojson(geom)
    except Exception:  # pragma: no cover
        pass
    raise TypeError(f"Unsupported geometry value type: {type(geom).__name__}")


# --------------------------------------------------------------------------
# Pollution-source GeoJSON serializer (the public API the spec asks for)
# --------------------------------------------------------------------------
# The non-geometry properties we expose per Feature. Keeps the Feature clean
# and predictable for downstream map consumers.
_SOURCE_FEATURE_PROPS = (
    "id",
    "name",
    "type",
    "schedule_start",
    "schedule_end",
    "near_school",
    "near_hospital",
)


def _prop_value(v: Any) -> Any:
    """Make a scalar JSON-safe (isoformat for times/datetimes)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # datetime/time -> ISO string for JSON friendliness.
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        return iso()
    return str(v)


def source_to_geojson(source: Any, include_props: Iterable[str] = _SOURCE_FEATURE_PROPS) -> str:
    """Serialize a single pollution source into a GeoJSON Feature string.

    ``source`` may be:
      - a ``db.models.PollutionSource`` ORM instance,
      - a dict with at least ``geom`` plus any of the property keys
        (used by tests and in-memory builders),
      - a SQLAlchemy Row/record whose ``geom`` came from ``ST_AsGeoJSON``.

    Returns a JSON string of shape::

        {"type": "Feature", "geometry": {...}, "properties": {...}}
    """
    is_mapping = isinstance(source, Mapping)
    geom_raw = source["geom"] if is_mapping else getattr(source, "geom", None)
    geometry = _coerce_geometry_to_geojson(geom_raw)

    props: dict[str, Any] = {}
    for key in include_props:
        val = source[key] if is_mapping else getattr(source, key, None)
        props[key] = _prop_value(val)
    feature = {"type": "Feature", "geometry": geometry, "properties": props}
    return json.dumps(feature, ensure_ascii=False)


def sources_to_geojson(sources: Iterable[Any]) -> str:
    """Serialize an iterable of pollution sources into a FeatureCollection string."""
    features = [json.loads(source_to_geojson(s)) for s in sources]
    return json.dumps(
        {"type": "FeatureCollection", "features": features}, ensure_ascii=False
    )


__all__ = [
    "point_wkt",
    "linestring_wkt",
    "polygon_wkt",
    "source_to_geojson",
    "sources_to_geojson",
]
