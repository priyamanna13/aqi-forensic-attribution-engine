"""Multi-factor scoring engine for pollution source attribution.

Each function returns a normalised 0.0–1.0 score (or penalty).  The final
``compute_confidence`` combines them with domain-appropriate weights.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Wind alignment
# ---------------------------------------------------------------------------

def wind_alignment_score(
    source_bearing: float, wind_direction: float, half_angle: float
) -> float:
    """0.0–1.0. Perfect alignment = 1.0, outside cone = 0.0.

    ``source_bearing`` is the compass bearing *from* station *to* source.
    ``wind_direction`` is the meteorological wind direction (wind blows *from*).
    A source is "upwind" when its bearing matches the wind direction.
    ``half_angle`` defines the half-width of the plume cone.
    """
    diff = abs(source_bearing - wind_direction)
    if diff > 180:
        diff = 360 - diff
    cone_width = half_angle * 2
    if diff > cone_width:
        return 0.0
    return max(0.0, 1.0 - (diff / cone_width))


# ---------------------------------------------------------------------------
# Chemical fingerprint match
# ---------------------------------------------------------------------------

# Lookup table of (source_type, signature_class) → match score.
_CHEMICAL_SCORES: dict[tuple[str, str], float] = {
    ("construction", "crustal_dominant"): 0.88,
    ("construction", "combustion_dominant"): 0.35,
    ("construction", "mixed"): 0.55,
    ("industrial", "crustal_dominant"): 0.91,
    ("industrial", "combustion_dominant"): 0.60,
    ("industrial", "mixed"): 0.65,
    ("traffic", "crustal_dominant"): 0.40,
    ("traffic", "combustion_dominant"): 0.85,
    ("traffic", "mixed"): 0.60,
    ("waste_burning", "crustal_dominant"): 0.30,
    ("waste_burning", "combustion_dominant"): 0.82,
    ("waste_burning", "mixed"): 0.70,
}


def chemical_match_score(source_type: str, chemical_fingerprint: dict) -> float:
    """0.0–1.0. Match chemical signature to source type."""
    sig = chemical_fingerprint.get("signature_class", "mixed")
    return _CHEMICAL_SCORES.get((source_type, sig), 0.5)


# ---------------------------------------------------------------------------
# Temporal match
# ---------------------------------------------------------------------------

def _hhmm_to_minutes(hhmm: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def temporal_match_score(
    event_time_str: str,
    schedule_start: str | None,
    schedule_end: str | None,
) -> float:
    """1.0 if operating, 0.3 if outside schedule but plausible, 0.0 if clearly inactive.

    ``event_time_str`` is in HH:MM format.
    If no schedule is provided (both None), the source is assumed to be
    intermittent → return 0.7.
    """
    if schedule_start is None or schedule_end is None:
        return 0.7

    event_min = _hhmm_to_minutes(event_time_str)
    start_min = _hhmm_to_minutes(schedule_start)
    end_min = _hhmm_to_minutes(schedule_end)

    # Handle schedules that do not wrap midnight.
    if start_min <= end_min:
        if start_min <= event_min <= end_min:
            return 1.0
    else:
        # Wraps midnight (e.g. 22:00–06:00).
        if event_min >= start_min or event_min <= end_min:
            return 1.0

    return 0.3


# ---------------------------------------------------------------------------
# Proximity (inverse distance)
# ---------------------------------------------------------------------------

def proximity_score(distance_km: float, max_range_km: float) -> float:
    """Inverse distance. Closer = higher."""
    if distance_km <= 0:
        return 1.0
    if distance_km >= max_range_km:
        return 0.0
    return max(0.0, 1.0 - (distance_km / max_range_km))


# ---------------------------------------------------------------------------
# Compliance penalty
# ---------------------------------------------------------------------------

def compliance_penalty(
    violation_count_90d: int,
    dust_suppression_required: bool,
    dust_suppression_observed: bool,
) -> float:
    """0.0–1.0.  Higher value = worse compliance (penalty boost)."""
    penalty = min(violation_count_90d * 0.04, 0.3)
    if dust_suppression_required and not dust_suppression_observed:
        penalty += 0.15
    return min(penalty, 1.0)


# ---------------------------------------------------------------------------
# Weighted confidence
# ---------------------------------------------------------------------------

def compute_confidence(
    wind: float,
    chemical: float,
    temporal: float,
    proximity: float,
    penalty: float,
) -> float:
    """Weighted combination of sub-scores.  Returns 0.0–1.0."""
    base = wind * 0.30 + chemical * 0.25 + temporal * 0.20 + proximity * 0.15
    boosted = base + penalty * 0.10
    return round(min(max(boosted, 0.0), 1.0), 2)
