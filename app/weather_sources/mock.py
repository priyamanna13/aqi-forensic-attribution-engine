"""Deterministic mock IMD weather source.

For the 08:30 IST spike scenario it MUST reproduce the data-contract values
exactly:

    wind_speed=14.5 km/h, wind_direction=290°, temperature=31.4°C,
    humidity=62%, pressure=1006.3 hPa, cloud_cover=3 oktas, precip=0.0mm,
    visibility=4.2km, mixing_height=850m

Outside the scenario window it generates a smooth, deterministic diurnal curve
so the 24-hour frontend replay has plausible weather.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Optional

from .base import RawWeather, WeatherSourceAdapter

#: Exact contract scenario values at the 08:30 IST spike.
SCENARIO: dict[str, float] = {
    "wind_speed_kmh": 14.5,
    "wind_direction_deg": 290,
    "temperature_c": 31.4,
    "relative_humidity_pct": 62,
    "pressure_hpa": 1006.3,
    "cloud_cover_oktas": 3,
    "precipitation_mm_last_1h": 0.0,
    "visibility_km": 4.2,
    "mixing_layer_height_m": 850,
}

#: Baseline (non-scenario) diurnal anchors for a realistic Pune morning.
_BASE: dict[str, float] = {
    "wind_speed_kmh": 8.0,
    "wind_direction_deg": 270,
    "temperature_c": 28.0,
    "relative_humidity_pct": 70,
    "pressure_hpa": 1008.0,
    "cloud_cover_oktas": 2,
    "precipitation_mm_last_1h": 0.0,
    "visibility_km": 6.0,
    "mixing_layer_height_m": 600,
}


def _hash_seed(station_name: str, ts: datetime) -> int:
    slot = int(ts.timestamp() // 900)  # 15-min bucket
    return abs(hash((station_name.strip().lower(), slot))) % (2**31)


class MockIMDSource(WeatherSourceAdapter):
    """Deterministic mock of IMD Pune observatory data."""

    name = "mock"

    def __init__(
        self,
        scenario_local_hour: float = 8.5,  # 08:30 IST
        scenario_sigma_hours: float = 0.75,
        base: Optional[dict[str, float]] = None,
        scenario_values: Optional[dict[str, float]] = None,
    ) -> None:
        self.scenario_local_hour = scenario_local_hour
        self.scenario_sigma_hours = scenario_sigma_hours
        self.base = dict(base or _BASE)
        self.scenario = dict(scenario_values or SCENARIO)

    def _local_tz(self):
        from zoneinfo import ZoneInfo

        from ..config import get_settings

        return ZoneInfo(get_settings().tz)

    def _scenario_factor(self, local_dt: datetime) -> float:
        """Gaussian centred on the scenario hour; ~1 at 08:30, ~0 far from it."""
        dh = (local_dt.hour + local_dt.minute / 60.0) - self.scenario_local_hour
        dh = (dh + 12) % 24 - 12  # wrap around midnight
        return math.exp(-(dh**2) / (2 * self.scenario_sigma_hours**2))

    def _reading_for(self, station_name: str, ts: datetime) -> RawWeather:
        local_dt = ts.astimezone(self._local_tz())
        factor = self._scenario_factor(local_dt)
        rng = random.Random(_hash_seed(station_name, ts))

        fields: dict[str, float | int] = {}
        for key, base_val in self.base.items():
            scen_val = self.scenario[key]
            value = base_val * (1 - factor) + scen_val * factor
            # Clamp + round to the field's natural type.
            if key in ("wind_direction_deg", "relative_humidity_pct",
                       "cloud_cover_oktas", "mixing_layer_height_m"):
                value = int(round(value))
            elif key in ("wind_speed_kmh", "temperature_c", "pressure_hpa", "visibility_km"):
                value = round(value, 1)
            else:  # precipitation
                value = round(value, 1)
            fields[key] = value

        return RawWeather(station_name=station_name, observed_at=ts, source="IMD_Pune_Observatory", **fields)

    # ------------------------------------------------------------------ #
    def fetch_snapshot(self, station_name: str, timestamp: datetime) -> RawWeather | None:
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return self._reading_for(station_name, timestamp)

    def fetch_range(
        self, station_name: str, start: datetime, end: datetime, step_min: int = 15
    ) -> list[RawWeather]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start/end must be timezone-aware")
        out: list[RawWeather] = []
        cur = start
        step = timedelta(minutes=step_min)
        while cur < end:
            out.append(self._reading_for(station_name, cur))
            cur += step
        return out
