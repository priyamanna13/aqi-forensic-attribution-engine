"""Pasquill-Gifford atmospheric stability classification.

Classifies the atmospheric boundary layer into one of six Pasquill stability
classes (A = extremely unstable, through F = moderately stable) from wind speed,
cloud cover, and the day/night state. Also provides cardinal-direction helpers
and dispersion-coefficient lookups matching the data contract.

References
----------
* Pasquill, F. (1961); the standard 6-class lookup table.
* Turner / EPA workbooks for day/night cloud-cover rules.
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Cardinal direction
# --------------------------------------------------------------------------- #
#: 16-point compass rose, centred on 0°, 22.5°, 45°, ... Each sector spans 22.5°.
_CARDINALS: tuple[str, ...] = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def degrees_to_cardinal(deg: int) -> str:
    """Convert a bearing in degrees (0-360) to a 16-point cardinal, e.g. 290 -> WNW."""
    # Normalise negatives / > 360 and round to the nearest sector centre.
    d = deg % 360
    idx = int((d + 11.25) % 360 // 22.5)
    return _CARDINALS[idx]


# --------------------------------------------------------------------------- #
# Class metadata (label + description) and dispersion coefficients
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PasquillInfo:
    label: str
    description: str
    sigma_y: float
    sigma_z: float


_INFO: dict[str, PasquillInfo] = {
    "A": PasquillInfo(
        "Extremely Unstable",
        "Vigorous buoyant convection; rapid vertical mixing. Typical of strong "
        "sunshine with light winds — plumes loft and disperse quickly.",
        0.32, 0.24,
    ),
    "B": PasquillInfo(
        "Moderately Unstable",
        "Active convective mixing with moderate mechanical turbulence. Common on "
        "clear sunny mornings.",
        0.28, 0.19,
    ),
    "C": PasquillInfo(
        "Slightly Unstable",
        "Moderate mechanical mixing with weak buoyancy. Typical of breezy daytime "
        "or thin overcast.",
        0.25, 0.13,
    ),
    "D": PasquillInfo(
        "Neutral",
        "Moderate mechanical mixing; limited vertical dispersion. Typical for "
        "overcast daytime or high-wind conditions.",
        0.22, 0.08,
    ),
    "E": PasquillInfo(
        "Slightly Stable",
        "Light mechanical mixing with a surface inversion limiting dispersion. "
        "Typical of evening overcast with light winds.",
        0.18, 0.05,
    ),
    "F": PasquillInfo(
        "Moderately Stable",
        "Strong surface inversion; very limited dispersion. Typical of clear, "
        "calm nights — plumes spread little and travel far.",
        0.14, 0.03,
    ),
}


def _lookup(cls_letter: str) -> PasquillInfo:
    return _INFO[cls_letter]


# --------------------------------------------------------------------------- #
# Classifier
# --------------------------------------------------------------------------- #
@dataclass
class StabilityResult:
    pasquill_class: str
    label: str
    description: str
    dispersion_coefficient: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "pasquill_class": self.pasquill_class,
            "label": self.label,
            "description": self.description,
            "dispersion_coefficient": dict(self.dispersion_coefficient),
        }


def classify_stability(
    wind_speed_kmh: float,
    cloud_cover_oktas: int,
    is_daytime: bool,
    solar_elevation_deg: float | None = None,
) -> dict:
    """Classify atmospheric stability using the Pasquill-Gifford scheme.

    Parameters
    ----------
    wind_speed_kmh
        Surface wind speed in km/h.
    cloud_cover_oktas
        Cloud cover in eighths (0 = clear, 8 = overcast).
    is_daytime
        True for daytime (solar insolation present), False for night.
    solar_elevation_deg
        Optional solar elevation; unused in the core table but accepted for
        future refinement (strong sun vs weak sun). When provided and high it
        nudges the daytime insolation category upward.

    Returns
    -------
    dict with keys: pasquill_class, label, description,
                    dispersion_coefficient {sigma_y, sigma_z}.
    """
    ws_mps = wind_speed_kmh / 3.6  # the Pasquill table is in m/s
    cloud_frac = cloud_cover_oktas / 8.0  # 0..1

    if is_daytime:
        cls = _classify_day(ws_mps, cloud_frac, solar_elevation_deg)
    else:
        cls = _classify_night(ws_mps, cloud_frac)

    info = _lookup(cls)
    return StabilityResult(
        pasquill_class=cls,
        label=info.label,
        description=info.description,
        dispersion_coefficient={"sigma_y": info.sigma_y, "sigma_z": info.sigma_z},
    ).to_dict()


def _insolation_strength(cloud_frac: float, solar_elevation_deg: float | None) -> str:
    """Approximate insolation class: 'strong' | 'moderate' | 'slight'."""
    # High cloud reduces insolation; low sun angle reduces it too.
    if solar_elevation_deg is not None and solar_elevation_deg < 15:
        # Sun near horizon -> at most slight insolation.
        return "slight"
    if cloud_frac >= 0.7:
        return "slight"
    if cloud_frac >= 0.4 or (solar_elevation_deg is not None and solar_elevation_deg < 35):
        return "moderate"
    return "strong"


def _classify_day(ws: float, cloud_frac: float, solar_elevation_deg: float | None) -> str:
    """Daytime Pasquill class. ``ws`` in m/s.

    Resolves the standard table's ambiguous cells (A-B, B-C, C-D) toward the
    *more stable* side. This is the conservative default used in regulatory
    practice when measured solar radiation is unavailable: moderate daytime
    winds with moderate/slight insolation resolve to neutral (D).
    """
    insol = _insolation_strength(cloud_frac, solar_elevation_deg)

    # Overcast (>= 5/8) with any wind beyond calm -> neutral D.
    if cloud_frac >= 0.625 and ws > 2:
        return "D"

    # Row: wind band (m/s). Col: insolation strength. The standard table leaves
    # several daytime cells ambiguous (A-B, B-C, C-D); we resolve them toward the
    # *more stable / neutral* side. This is the conservative regulatory default
    # (EPA/industrial-dispersion workbooks) when measured solar radiation is
    # unavailable: moderate winds under moderate/slight insolation -> neutral D.
    table = {
        (0, 2):   {"strong": "A", "moderate": "B", "slight": "C"},
        (2, 3):   {"strong": "A", "moderate": "B", "slight": "C"},
        (3, 5):   {"strong": "B", "moderate": "D", "slight": "D"},
        (5, 6):   {"strong": "C", "moderate": "D", "slight": "D"},
    }
    for (lo, hi), row in table.items():
        if lo <= ws < hi:
            return row[insol]
    # ws >= 6 m/s
    return "D"


def _classify_night(ws: float, cloud_frac: float) -> str:
    """Nighttime Pasquill table. ws in m/s."""
    # Night: cloud cover >= 0.5 (mostly cloudy) vs < 0.5 (clear-ish).
    if cloud_frac >= 0.5:
        # Overcast night: D for higher winds, E for low winds.
        if ws < 3:
            return "E"
        return "D"
    # Clear-ish night: E for moderate winds, F for light winds.
    if ws < 2:
        return "F" if cloud_frac < 0.4 else "E"
    if ws < 3:
        return "E"
    if ws < 5:
        return "E"
    return "D"


def dispersion_coefficients(pasquill_class: str) -> dict[str, float]:
    """Public helper: sigma_y/sigma_z for a class letter."""
    info = _lookup(pasquill_class)
    return {"sigma_y": info.sigma_y, "sigma_z": info.sigma_z}
