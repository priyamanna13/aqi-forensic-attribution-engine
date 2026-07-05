"""Weather source adapter ABC.

Mirrors the ``SourceAdapter`` pattern from ``app.sources``: the pipeline never
talks to IMD directly, it goes through a ``WeatherSourceAdapter`` so the same
classification/contract path runs on mock and live data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawWeather:
    """A raw weather snapshot as emitted by a source, *before* classification.

    All fields use the data-contract units (km/h, degrees, °C, %, hPa, oktas,
    mm, km, m). ``extra`` carries any source-specific fields.
    """

    station_name: str
    observed_at: datetime
    source: str = "IMD_Pune_Observatory"
    wind_speed_kmh: float = 0.0
    wind_direction_deg: int = 0
    temperature_c: float = 0.0
    relative_humidity_pct: int = 0
    pressure_hpa: float = 0.0
    cloud_cover_oktas: int = 0
    precipitation_mm_last_1h: float = 0.0
    visibility_km: float = 0.0
    mixing_layer_height_m: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("RawWeather.observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "wind_speed_kmh": self.wind_speed_kmh,
            "wind_direction_deg": self.wind_direction_deg,
            "temperature_c": self.temperature_c,
            "relative_humidity_pct": self.relative_humidity_pct,
            "pressure_hpa": self.pressure_hpa,
            "cloud_cover_oktas": self.cloud_cover_oktas,
            "precipitation_mm_last_1h": self.precipitation_mm_last_1h,
            "visibility_km": self.visibility_km,
            "mixing_layer_height_m": self.mixing_layer_height_m,
        }


class WeatherSourceAdapter(ABC):
    """Abstract base for weather sources."""

    name: str = "base"

    @abstractmethod
    def fetch_snapshot(
        self, station_name: str, timestamp: datetime
    ) -> RawWeather | None:
        """Fetch the weather snapshot nearest to ``timestamp``, or None."""
        raise NotImplementedError


def get_weather_source(kind: str = "mock", **kwargs) -> WeatherSourceAdapter:
    """Factory: ``mock`` (default, deterministic) or ``live`` (IMD adapter)."""
    kind = (kind or "mock").lower()
    if kind == "mock":
        from .mock import MockIMDSource

        return MockIMDSource(**kwargs)
    if kind in ("live", "imd"):
        # Reserved for a real IMD adapter; not implemented in the mock path.
        raise NotImplementedError("Live IMD source is not implemented; use --source mock")
    raise ValueError(f"Unknown weather source kind: {kind!r}")
