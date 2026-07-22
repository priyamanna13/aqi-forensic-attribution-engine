"""Indian NAAQS limits, exceedance-factor calculation, and AQI classification.

CPCB National Ambient Air Quality Standards (NAAQS) limits used as the
denominator for ``exceedance_factor = value / limit``. Each pollutant has a
fixed averaging period (24hr for most, 8hr for CO and O3) — this is reflected
in the data contract's ``averaging_period`` field and is part of the
information shown alongside each reading.

Units matter: CO is in **mg/m³** (the others in µg/m³). The unit string is
exposed so downstream code and the data contract stay consistent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PollutantStandard:
    """A NAAQS limit + its averaging period and unit."""

    limit: float
    averaging_period: str  # '24hr' or '8hr' — contract uses no space
    unit: str              # 'µg/m³' or 'mg/m³'

    def exceedance_factor(self, value: float | None) -> float | None:
        """Return value/limit rounded to 2 decimals, or None if value missing.

        Contract sample: pm25=148.6, limit=60 -> 2.48 (148.6/60 = 2.4766...).
        We round half-up to match the contract's apparent intent.
        """
        if value is None:
            return None
        return round(value / self.limit + 1e-9, 2)


# CPCB NAAQS limits (Indian standard). Keyed by the lowercase pollutant name
# used in ``aqi_readings`` columns; the contract's ``dominant_pollutant`` uses
# the UPPER form (e.g. "PM10").
NAAQS: dict[str, PollutantStandard] = {
    "pm25": PollutantStandard(limit=60.0, averaging_period="24hr", unit="µg/m³"),
    "pm10": PollutantStandard(limit=100.0, averaging_period="24hr", unit="µg/m³"),
    "no2":  PollutantStandard(limit=80.0, averaging_period="24hr", unit="µg/m³"),
    "so2":  PollutantStandard(limit=80.0, averaging_period="24hr", unit="µg/m³"),
    "co":   PollutantStandard(limit=4.0, averaging_period="8hr", unit="mg/m³"),
    "o3":   PollutantStandard(limit=100.0, averaging_period="8hr", unit="µg/m³"),
}

# The pollutant columns we analyze, in stable order.
POLLUTANT_KEYS: list[str] = ["pm25", "pm10", "no2", "so2", "co", "o3"]

# Upper-case display form for the contract's ``dominant_pollutant`` field.
POLLUTANT_DISPLAY: dict[str, str] = {k: k.upper() for k in POLLUTANT_KEYS}


def compute_exceedance_factors(
    values: dict[str, float | None],
) -> dict[str, float | None]:
    """Return {pollutant: exceedance_factor or None} for every NAAQS pollutant."""
    return {
        p: NAAQS[p].exceedance_factor(values.get(p))
        for p in POLLUTANT_KEYS
    }


def dominant_pollutant(
    values: dict[str, float | None],
) -> tuple[str | None, float | None]:
    """Pick the pollutant with the highest (non-None) exceedance factor.

    Returns ``(pollutant_key_lower, factor)`` or ``(None, None)`` if all values
    are missing. Ties are broken by POLLUTANT_KEYS order (stable, deterministic).
    """
    factors = compute_exceedance_factors(values)
    best_key: str | None = None
    best_factor: float | None = None
    for key in POLLUTANT_KEYS:
        f = factors[key]
        if f is None:
            continue
        if best_factor is None or f > best_factor:
            best_key, best_factor = key, f
    return best_key, best_factor


# --------------------------------------------------------------------------
# India National Air Quality Index (NAQI) band classification.
# Source: CPCB "National Air Quality Index" 2014.
# --------------------------------------------------------------------------
_AQI_BANDS: list[tuple[int, str]] = [
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (10_000, "Severe"),
]


def aqi_category(total_aqi: float) -> str:
    """Return the India NAQI category label for a given total AQI."""
    if total_aqi < 0:
        raise ValueError("AQI must be non-negative")
    for ceiling, label in _AQI_BANDS:
        if total_aqi <= ceiling:
            return label
    return "Severe"  # defensive — never reached due to the 10_000 ceiling


def event_severity(total_aqi: float) -> str:
    """Map total AQI to the pipeline's own severity bucket (lowercase)."""
    if total_aqi >= 300:
        return "critical"
    if total_aqi >= 200:
        return "high"
    if total_aqi >= 100:
        return "warning"
    return "low"


__all__ = [
    "PollutantStandard",
    "NAAQS",
    "POLLUTANT_KEYS",
    "POLLUTANT_DISPLAY",
    "compute_exceedance_factors",
    "dominant_pollutant",
    "aqi_category",
    "event_severity",
]
