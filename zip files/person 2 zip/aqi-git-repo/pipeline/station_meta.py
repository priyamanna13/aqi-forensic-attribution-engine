"""Station metadata not stored in the Task 1 ``stations`` table.

The data contract's ``trigger_station`` block needs ``network``, ``city``,
``state``, and ``elevation_m``. These are stable reference attributes of each
monitoring station rather than per-reading telemetry, so they live in a lookup
here instead of in the normalized schema (kept minimal in Task 1).

Coordinates come from the station's geometry at runtime — this table only
holds the non-spatial reference metadata, keyed by station name.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StationMeta:
    network: str
    city: str
    state: str
    elevation_m: int


# Default values for any Pune CPCB station. Individual station overrides
# (e.g. a station on a ridge) can be added below if/when needed.
_DEFAULT = StationMeta(
    network="CPCB_CAAQMS",
    city="Pune",
    state="Maharashtra",
    elevation_m=560,
)

# Per-station overrides. Empty for now — all seeded Pune stations use the
# default CPCB Pune metadata. Kept as a dict so adding a station-specific
# override is a one-line change.
_OVERRIDES: dict[str, StationMeta] = {
    # e.g. "Lonavala": StationMeta("CPCB_CAAQMS", "Lonavala", "Maharashtra", 624),
}


def get_station_meta(name: str) -> StationMeta:
    """Return the reference metadata for a station by name."""
    return _OVERRIDES.get(name, _DEFAULT)


__all__ = ["StationMeta", "get_station_meta"]
