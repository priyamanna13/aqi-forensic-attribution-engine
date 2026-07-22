"""Pasquill-Gifford atmospheric stability classification + dispersion coeffs.

The stability class is estimated from wind speed and day/night (a proxy for
insolation). The task specifies these bands (wind speed in km/h):

    Wind speed < 5     : Class A (day) / Class F (night)
    Wind speed 5–15    : Class B (day) / Class E (night)
    Wind speed 15–25   : Class C (day) / Class D (night)
    Wind speed >= 25   : Class D (day/night)

Each class maps to a human-readable label, a description, and P-G dispersion
coefficients (sigma_y, sigma_z) consistent with the data contract's
``atmospheric_stability`` sub-object.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StabilityProfile:
    pasquill_class: str          # single uppercase letter, e.g. "D"
    label: str
    description: str
    sigma_y: float               # P-G horizontal dispersion coefficient
    sigma_z: float               # P-G vertical dispersion coefficient


# Full table for all six Pasquill classes (A–F). Class D matches the data
# contract sample; the others follow the same structure.
STABILITY_TABLE: dict[str, StabilityProfile] = {
    "A": StabilityProfile(
        pasquill_class="A",
        label="Extremely Unstable",
        description="Strong solar radiation and low wind speed. Vigorous vertical "
                    "mixing; plumes loft and disperse rapidly upward.",
        sigma_y=0.40, sigma_z=0.25,
    ),
    "B": StabilityProfile(
        pasquill_class="B",
        label="Moderately Unstable",
        description="Moderate solar radiation with light wind. Active convective "
                    "mixing; favorable for dispersion.",
        sigma_y=0.32, sigma_z=0.16,
    ),
    "C": StabilityProfile(
        pasquill_class="C",
        label="Slightly Unstable",
        description="Weak solar radiation or broken clouds with moderate wind. "
                    "Moderate convective + mechanical mixing.",
        sigma_y=0.22, sigma_z=0.11,
    ),
    "D": StabilityProfile(
        pasquill_class="D",
        label="Neutral",
        description="Moderate mechanical mixing; limited vertical dispersion. "
                    "Typical for overcast daytime or high-wind conditions.",
        sigma_y=0.22, sigma_z=0.08,
    ),
    "E": StabilityProfile(
        pasquill_class="E",
        label="Slightly Stable",
        description="Clear night with moderate wind. Limited vertical mixing; "
                    "plumes tend to stay near the surface.",
        sigma_y=0.18, sigma_z=0.06,
    ),
    "F": StabilityProfile(
        pasquill_class="F",
        label="Moderately Stable",
        description="Clear night, low wind speed. Strong stratification; very "
                    "limited vertical dispersion, pollutants accumulate.",
        sigma_y=0.12, sigma_z=0.04,
    ),
}


def is_daytime(hour: int) -> bool:
    """Day/night proxy. 06:00–17:59 inclusive is 'day' for insolation purposes."""
    return 6 <= hour < 18


def classify_stability(wind_speed_kmh: float, hour: int) -> StabilityProfile:
    """Pick the Pasquill class from wind speed + hour-of-day per the task rules.

    Wind bands (km/h):
        < 5      -> A (day) / F (night)
        5–15     -> B (day) / E (night)
        15–25    -> C (day) / D (night)
        >= 25    -> D (day/night)
    """
    day = is_daytime(hour)
    if wind_speed_kmh < 5:
        cls = "A" if day else "F"
    elif wind_speed_kmh < 15:
        cls = "B" if day else "E"
    elif wind_speed_kmh < 25:
        cls = "C" if day else "D"
    else:
        cls = "D"
    return STABILITY_TABLE[cls]


# --------------------------------------------------------------------------
# Cardinal wind direction helper (shared by weather client + spike detector).
# --------------------------------------------------------------------------
# 16-point compass. Index = round(deg / 22.5) % 16.
_CARDINALS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def wind_direction_cardinal(deg: float) -> str:
    """Convert wind direction in degrees to a 16-point cardinal string.

    ``290`` -> ``"WNW"`` as in the data contract sample.
    """
    deg = deg % 360
    idx = int((deg + 11.25) // 22.5) % 16
    return _CARDINALS_16[idx]


__all__ = [
    "StabilityProfile",
    "STABILITY_TABLE",
    "is_daytime",
    "classify_stability",
    "wind_direction_cardinal",
]
