"""Emit the ``weather_snapshot`` block of the data contract.

Combines a raw weather observation (from ``RawWeather.to_dict()`` or any dict
with the canonical weather field names) with a Pasquill-Gifford stability
classification to produce the exact JSON shape specified in the data contract.

Coordinate convention: cardinal direction via 16-point compass rose.
Timestamp convention: ISO-8601 with the station's local offset (+05:30 for Pune).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .pasquill import degrees_to_cardinal


def _iso_local(dt: datetime, tz_name: str = "Asia/Kolkata") -> str:
    """ISO-8601 string in the station's local timezone, e.g. 2026-06-25T08:30:00+05:30."""
    from zoneinfo import ZoneInfo

    local = dt.astimezone(ZoneInfo(tz_name))
    # %z -> +0530; insert colon -> +05:30 to match the contract sample.
    s = local.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]


def build_weather_snapshot(
    observation_dict: dict[str, Any],
    pasquill_result: dict[str, Any],
    tz_name: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Build the contract ``weather_snapshot`` dict.

    Parameters
    ----------
    observation_dict
        Dict with keys matching ``RawWeather.to_dict()`` output: source,
        observed_at, wind_speed_kmh, wind_direction_deg, temperature_c,
        relative_humidity_pct, pressure_hpa, cloud_cover_oktas,
        precipitation_mm_last_1h, visibility_km, mixing_layer_height_m.
    pasquill_result
        Dict returned by ``classify_stability()``: pasquill_class, label,
        description, dispersion_coefficient.
    tz_name
        IANA timezone name for formatting ``observed_at``.

    Returns
    -------
    dict matching the ``weather_snapshot`` block of the data contract.
    """
    observed_at = observation_dict["observed_at"]
    if isinstance(observed_at, datetime):
        observed_at_str = _iso_local(observed_at, tz_name)
    else:
        observed_at_str = str(observed_at)

    wind_dir_deg = observation_dict["wind_direction_deg"]

    return {
        "source": observation_dict["source"],
        "observed_at": observed_at_str,
        "wind_speed_kmh": observation_dict["wind_speed_kmh"],
        "wind_direction_deg": wind_dir_deg,
        "wind_direction_cardinal": degrees_to_cardinal(wind_dir_deg),
        "temperature_c": observation_dict["temperature_c"],
        "relative_humidity_pct": observation_dict["relative_humidity_pct"],
        "pressure_hpa": observation_dict["pressure_hpa"],
        "cloud_cover_oktas": observation_dict["cloud_cover_oktas"],
        "precipitation_mm_last_1h": observation_dict["precipitation_mm_last_1h"],
        "visibility_km": observation_dict["visibility_km"],
        "mixing_layer_height_m": observation_dict["mixing_layer_height_m"],
        "atmospheric_stability": pasquill_result,
    }
