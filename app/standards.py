"""Air-quality standards: NAAQS limits + CPCB National AQI (NAQI) calculation.

References
----------
* CPCB "National Air Quality Index" report (2014) — 6-band sub-index breakpoints.
* CPCB NAAQS notification (2009), as amended. 24-hr limits for PM/NO2/SO2,
  8-hr limits for CO and O3.

Conventions (verified against data_contract_sample.json):
* Units: PM2.5, PM10, NO2, SO2, O3 in µg/m³; CO in mg/m³.
* exceedance_factor = round(concentration / naaqs_limit, 2).
  e.g. PM10 387.2/100 -> 3.87 ; CO 3.2/4 -> 0.80 ; NO2 72.4/80 -> 0.91.
* total_aqi = max over available sub-indices (CPCB rule). Supports > 500.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# --------------------------------------------------------------------------- #
# Pollutant inventory & canonical units
# --------------------------------------------------------------------------- #
UGM3 = "µg/m³"
MGM3 = "mg/m³"

#: Pollutants in their *stored / contract* units.
POLLUTANTS: tuple[str, ...] = ("pm25", "pm10", "no2", "so2", "co", "o3")
#: Pollutants whose canonical unit is mg/m³ (CO only). Everything else µg/m³.
MG_PER_M3_POLLUTANTS: frozenset[str] = frozenset({"co"})

#: Official CPCB NAAQS thresholds used for the `exceedance_factor` in the contract.
#: Limits are in the pollutant's canonical unit (CO in mg/m³, rest µg/m³).
NAAQS_LIMITS: dict[str, float] = {
    "pm25": 60.0,
    "pm10": 100.0,
    "no2": 80.0,
    "so2": 80.0,
    "co": 4.0,
    "o3": 100.0,
}

#: Official averaging period reported in the contract per pollutant.
AVERAGING_PERIODS: dict[str, str] = {
    "pm25": "24hr",
    "pm10": "24hr",
    "no2": "24hr",
    "so2": "24hr",
    "co": "8hr",
    "o3": "8hr",
}


def canonical_unit(pollutant: str) -> str:
    """Return the canonical/storage unit for a pollutant."""
    return MGM3 if pollutant in MG_PER_M3_POLLUTANTS else UGM3


def exceedance_factor(pollutant: str, concentration: float) -> Optional[float]:
    """ratio = concentration / NAAQS limit, rounded to 2 decimals.

    Returns None when the pollutant has no limit or concentration is invalid.
    """
    limit = NAAQS_LIMITS.get(pollutant)
    if limit is None or concentration is None or limit <= 0:
        return None
    # Divide in Decimal to avoid float error (e.g. 54.8/80 is 0.685 in math but
    # 0.684999... as a float), then ROUND_HALF_UP so 0.685 -> 0.69 matching the
    # data contract sample exactly (Python's built-in round() is banker's rounding).
    return float(
        (Decimal(str(concentration)) / Decimal(str(limit))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


# --------------------------------------------------------------------------- #
# CPCB National Air Quality Index (NAQI)
# --------------------------------------------------------------------------- #
#: CPCB AQI category names in increasing severity.
AQI_CATEGORIES: tuple[str, ...] = (
    "Good",
    "Satisfactory",
    "Moderate",
    "Poor",
    "Very Poor",
    "Severe",
)


@dataclass(frozen=True)
class AqiBand:
    """One CPCB NAQI sub-index band: [i_lo, i_hi] AQI for [c_lo, c_hi] conc."""

    i_lo: int
    i_hi: int
    c_lo: float
    c_hi: float

    def contains(self, c: float) -> bool:
        return self.c_lo <= c <= self.c_hi

    def sub_index(self, c: float) -> float:
        """Linear interpolation of concentration onto the AQI axis."""
        # Guard against zero-width concentration bands.
        span_c = self.c_hi - self.c_lo or 1.0
        return (self.i_hi - self.i_lo) / span_c * (c - self.c_lo) + self.i_lo


#: CPCB sub-index breakpoint tables. The AQI index axis is ALWAYS the six CPCB
#: bands 0-50 / 51-100 / 101-200 / 201-300 / 301-400 / 401-500; each pollutant
#: maps its own concentration breakpoints (CO in mg/m³, all others µg/m³) onto
#: that axis. Concentrations above the final documented band are linearly
#: extrapolated along the steepest band so AQI > 500 stays representable, as the
#: contract requires for extreme events.
_AQI_BANDS: dict[str, tuple[AqiBand, ...]] = {
    "pm25": (
        AqiBand(0, 50, 0, 30),
        AqiBand(51, 100, 31, 60),
        AqiBand(101, 200, 61, 90),
        AqiBand(201, 300, 91, 120),
        AqiBand(301, 400, 121, 250),
        AqiBand(401, 500, 251, 350),
    ),
    "pm10": (
        AqiBand(0, 50, 0, 50),
        AqiBand(51, 100, 51, 100),
        AqiBand(101, 200, 101, 250),
        AqiBand(201, 300, 251, 350),
        AqiBand(301, 400, 351, 430),
        AqiBand(401, 500, 431, 520),
    ),
    "no2": (
        AqiBand(0, 50, 0, 40),
        AqiBand(51, 100, 41, 80),
        AqiBand(101, 200, 81, 180),
        AqiBand(201, 300, 181, 280),
        AqiBand(301, 400, 281, 400),
        AqiBand(401, 500, 401, 600),
    ),
    "so2": (
        AqiBand(0, 50, 0, 40),
        AqiBand(51, 100, 41, 80),
        AqiBand(101, 200, 81, 380),
        AqiBand(201, 300, 381, 800),
        AqiBand(301, 400, 801, 1600),
        AqiBand(401, 500, 1601, 1600),  # SO2 caps at 500 in the standard
    ),
    "co": (  # mg/m³
        AqiBand(0, 50, 0, 1.0),
        AqiBand(51, 100, 1.1, 2.0),
        AqiBand(101, 200, 2.1, 10.0),
        AqiBand(201, 300, 10.1, 17.0),
        AqiBand(301, 400, 17.1, 34.0),
        AqiBand(401, 500, 34.1, 34.0),  # CO caps at 500 in the standard
    ),
    "o3": (
        AqiBand(0, 50, 0, 50),
        AqiBand(51, 100, 51, 100),
        AqiBand(101, 200, 101, 168),
        AqiBand(201, 300, 169, 208),
        AqiBand(301, 400, 209, 746),
        AqiBand(401, 500, 747, 1000),
    ),
}

#: Pollutants required before an AQI may be reported (CPCB guidance: need at least
#: 3 pollutants, of which at least one must be PM2.5 or PM10). Otherwise AQI is
#: "Insufficient Data" (None).
MIN_POLLUTANTS_FOR_AQI: int = 3


def _category_for_index(aqi: float) -> str:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Satisfactory"
    if aqi <= 200:
        return "Moderate"
    if aqi <= 300:
        return "Poor"
    if aqi <= 400:
        return "Very Poor"
    return "Severe"


def sub_index(pollutant: str, concentration: float) -> Optional[float]:
    """CPCB sub-index for a single pollutant concentration.

    For concentrations above the top documented band, the AQI is linearly
    extrapolated along the steepest (final) band's slope so values > 500 are
    representable (extreme events). Returns None for unknown pollutants.
    """
    if pollutant not in _AQI_BANDS:
        return None
    bands = _AQI_BANDS[pollutant]
    for band in bands:
        if band.contains(concentration):
            return round(band.sub_index(concentration))
    # Above the highest band -> extrapolate using the last band's slope.
    last = bands[-1]
    if concentration > last.c_hi and last.c_hi > last.c_lo:
        return round(last.sub_index(concentration))
    # Concentration below 0 (shouldn't happen post-validation).
    return round(bands[0].sub_index(max(concentration, 0.0)))


@dataclass
class AqiResult:
    total_aqi: Optional[int]
    category: Optional[str]
    dominant_pollutant: Optional[str]
    sub_indices: dict[str, int]


def compute_aqi(concentrations: dict[str, float]) -> AqiResult:
    """Compute CPCB total AQI = max(sub-indices).

    Returns total_aqi=None ("Insufficient Data") when fewer than
    MIN_POLLUTANTS_FOR_AQI valid pollutants are present, or when no PM pollutant
    is available.
    """
    subs: dict[str, int] = {}
    for p in POLLUTANTS:
        c = concentrations.get(p)
        if c is None:
            continue
        si = sub_index(p, c)
        if si is not None:
            subs[p] = si

    has_pm = any(p in subs for p in ("pm25", "pm10"))
    if len(subs) < MIN_POLLUTANTS_FOR_AQI or not has_pm:
        return AqiResult(None, None, None, subs)

    dominant = max(subs, key=subs.get)  # type: ignore[arg-type]
    total = subs[dominant]
    return AqiResult(int(total), _category_for_index(total), dominant, subs)


def aqi_category(aqi: int) -> str:
    """Public helper: category label for an integer AQI."""
    return _category_for_index(aqi)
