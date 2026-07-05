"""Emit the immutable ``trigger_station`` block of the data contract.

This module is the *only* place that knows the exact contract shape, so the
pipeline and frontend always agree. It reads from ORM objects (Station +
AqiReading) and produces a dict (json-serialisable) whose keys match
``data_contract_sample.json::trigger_station`` byte-for-byte.

Coordinate convention: GeoJSON ``[longitude, latitude]``, EPSG:4326.
Timestamp convention: ISO-8601 with the station's local offset (+05:30 for Pune).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import AqiReading, Station


def _iso_local(dt: datetime, tz_name: str = "Asia/Kolkata") -> str:
    """ISO-8601 string in the station's local timezone, e.g. 2026-06-25T08:30:00+05:30."""
    from zoneinfo import ZoneInfo

    local = dt.astimezone(ZoneInfo(tz_name))
    # %z -> +0530; insert colon -> +05:30 to match the contract sample.
    s = local.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]


def build_trigger_station_block(
    station: Station, reading: AqiReading, tz_name: str = "Asia/Kolkata"
) -> dict[str, Any]:
    """Build the contract ``trigger_station`` dict for one station + reading."""
    lon, lat = station.coordinates()
    return {
        "id": str(station.id),
        "name": station.name,
        "network": station.network,
        "city": station.city,
        "state": station.state,
        "coordinates": [round(lon, 6), round(lat, 6)],
        "elevation_m": station.elevation_m,
        "reading": {
            "timestamp": _iso_local(reading.timestamp, tz_name),
            "total_aqi": reading.total_aqi,
            "aqi_category": reading.aqi_category,
            "dominant_pollutant": reading.dominant_pollutant,
            "sub_pollutants": reading.to_sub_pollutants(),
            "chemical_fingerprint": reading.chemical_fingerprint(),
        },
    }


# The exact top-level key set of trigger_station.reading.sub_pollutants[pollutant].
SUB_POLLUTANT_KEYS: tuple[str, ...] = (
    "value",
    "unit",
    "averaging_period",
    "naaqs_limit",
    "exceedance_factor",
)
