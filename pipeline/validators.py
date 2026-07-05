"""Input Validators — Task 5 (Gap 5).

Handles CPCB telemetry edge cases, calm wind scenarios, out-of-bounds degrees,
and pollutant unit/range checks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("aq_pipeline")

@dataclass
class ValidationResult:
    is_valid: bool
    cleaned_value: Any = None
    reason: str = ""


def validate_aqi(raw_aqi: Any) -> ValidationResult:
    """Validate CPCB AQI value.

    Edge cases:
      - Negative value (e.g. -999) represents a sensor error.
      - Zero represents a station likely offline.
      - Values above 500 are valid but rare (severe events).
      - Non-numeric value represents data corruption.
    """
    try:
        aqi = float(raw_aqi)
    except (TypeError, ValueError):
        logger.warning("Non-numeric AQI value received: %s", raw_aqi)
        return ValidationResult(False, reason=f"Non-numeric AQI: {raw_aqi}")

    if aqi < 0:
        logger.warning("Negative AQI (sensor error code): %s", aqi)
        return ValidationResult(False, reason=f"Negative AQI: {aqi}")

    if aqi == 0:
        logger.warning("Zero AQI (station likely offline)")
        return ValidationResult(False, reason="Zero AQI — station offline")

    if aqi > 500:
        logger.info("AQI > 500 (%s) — valid but flagged as severe", aqi)
        return ValidationResult(True, cleaned_value=aqi, reason="Severe AQI, valid")

    return ValidationResult(True, cleaned_value=aqi)


def validate_wind(speed_kmh: Any, direction_deg: Any) -> ValidationResult:
    """Validate OWM/wind sensor telemetry.

    Edge cases:
      - Speed = 0 or null represents calm conditions; upwind direction is unknown.
      - Negative speed/direction represents sensor errors.
      - Direction outside 0-360 represents a data error.
    """
    try:
        speed = float(speed_kmh)
        direction = float(direction_deg)
    except (TypeError, ValueError):
        logger.warning("Non-numeric wind data: speed=%s, dir=%s", speed_kmh, direction_deg)
        return ValidationResult(False, reason="Non-numeric wind data")

    if speed < 0:
        logger.warning("Negative wind speed: %s", speed)
        return ValidationResult(False, reason=f"Negative wind speed: {speed}")

    if speed < 0.5:
        logger.info("Calm wind conditions — attribution direction unreliable")
        return ValidationResult(
            True,
            cleaned_value={"speed": speed, "direction": direction},
            reason="Calm wind — wide scatter mode",
        )

    if not (0 <= direction <= 360):
        logger.warning("Wind direction out of range: %s", direction)
        return ValidationResult(False, reason=f"Direction out of range: {direction}")

    return ValidationResult(
        True,
        cleaned_value={"speed": speed, "direction": direction},
    )


REASONABLE_RANGES = {
    "pm25": (0.0, 1000.0),
    "pm10": (0.0, 2000.0),
    "no2":  (0.0, 500.0),
    "so2":  (0.0, 300.0),
    "co":   (0.0, 50.0),   # mg/m3
    "o3":   (0.0, 400.0),
}


def validate_pollutant_reading(pollutant_name: str, value: Any) -> ValidationResult:
    """Validate individual pollutant concentration readings."""
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ValidationResult(False, reason=f"Non-numeric {pollutant_name}: {value}")

    if val < 0:
        return ValidationResult(False, reason=f"Negative {pollutant_name}: {val}")

    low, high = REASONABLE_RANGES.get(pollutant_name.lower(), (0.0, 5000.0))
    if val > high:
        logger.warning(
            "%s = %s exceeds reasonable range (%s-%s). Possible unit mismatch or sensor error.",
            pollutant_name, val, low, high
        )
        return ValidationResult(True, cleaned_value=val, reason="Out of typical range — flagged")

    return ValidationResult(True, cleaned_value=val)
