"""Source adapters for the ingestion pipeline.

The pipeline never talks to CPCB (or any mock) directly: it goes through a
``SourceAdapter``. This keeps the *same* validation/AQI/persist path running on
both the deterministic mock (offline default) and the live CPCB feed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RawReading:
    """A single raw reading as emitted by a source, *before* validation.

    ``pollutants`` is keyed by pollutant name -> raw value (sentinels/strings
    allowed; the validator cleans them). Units are whatever the source emits;
    the validator normalises.
    """

    station_name: str
    timestamp: datetime
    pollutants: dict[str, object]
    #: hint for the validator about the CO unit on this feed.
    co_input_unit: str = "mg/m3"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("RawReading.timestamp must be timezone-aware")


class SourceAdapter(ABC):
    """Abstract base for ingestion sources."""

    name: str = "base"

    @abstractmethod
    def fetch_latest(self, station_name: str) -> Optional[RawReading]:
        """Fetch the most recent reading for a station, or None if unavailable."""
        raise NotImplementedError

    @abstractmethod
    def fetch_range(
        self, station_name: str, start: datetime, end: datetime
    ) -> list[RawReading]:
        """Fetch all readings in [start, end) for a station (for backfill)."""
        raise NotImplementedError


def get_source(kind: str = "mock", **kwargs) -> SourceAdapter:
    """Factory: ``mock`` (default) or ``live`` (real CPCB adapter)."""
    kind = (kind or "mock").lower()
    if kind == "mock":
        from .mock import MockCPCBSource

        return MockCPCBSource(**kwargs)
    if kind in ("live", "cpcb"):
        from .cpcb import LiveCPCBSource

        return LiveCPCBSource(**kwargs)
    raise ValueError(f"Unknown source kind: {kind!r} (expected 'mock' or 'live')")
