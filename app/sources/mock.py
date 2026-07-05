"""Deterministic mock CPCB source for offline development and seeding.

The mock reproduces a realistic Pune diurnal AQI curve: low overnight, a sharp
morning-rush PM peak, and a milder evening peak. It is fully deterministic for a
given (station, timestamp) so that:

  * seed/backfill replay is stable, and
  * the 24-hour frontend replay animation has smooth, sensible data.

The morning spike is parameterised by a *target AQI* (default 310, matching the
data contract scenario). Because AQI is derived from concentrations (not the
other way around), the mock solves for the PM10 concentration that yields the
target AQI on the CPCB PM10 band, then builds a self-consistent pollutant set
around it.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from ..standards import sub_index
from .base import RawReading, SourceAdapter

# Base (non-spike) diurnal levels for Pune (canonical units; CO in mg/m³).
_BASE_PROFILE: dict[str, float] = {
    "pm25": 45.0,
    "pm10": 80.0,
    "no2": 35.0,
    "so2": 25.0,
    "co": 1.2,
    "o3": 35.0,
}

#: Diurnal modulation multiplier by hour-of-day (local). Two humps: morning rush
#: ~08:00 and evening ~19:00; clean window in the afternoon. Index = hour 0..23.
#: This modulates the *baseline* only; the morning spike is layered on top via
#: a Gaussian so the peak AQI is exact regardless of diurnal phase.
_DIURNAL: tuple[float, ...] = (
    0.55, 0.50, 0.48, 0.50, 0.60, 0.78,  # 00-05
    1.05, 1.45, 1.75, 1.55, 1.20, 1.00,  # 06-11  <- morning peak ~08
    0.85, 0.78, 0.75, 0.80, 0.95, 1.20,  # 12-17
    1.40, 1.30, 1.05, 0.85, 0.70, 0.60,  # 18-23  <- evening peak ~19
)

#: PM2.5/PM10 at the peak. Kept below the PM10-dominance threshold (~0.37 at
#: AQI 310) so the dominant pollutant stays PM10 across the whole spike, and the
#: coarse-dust signature_class fires.
_PEAK_PM25_PM10: float = 0.35
_PEAK_RATIO: dict[str, float] = {
    "no2": 0.20,   # µg/m³ per µg/m³ of pm10
    "so2": 0.14,
    "o3": 0.12,
}
#: CO at peak in mg/m³ per µg/m³ of pm10 (CO lives on a much smaller scale).
_PEAK_CO_PER_PM10: float = 0.009


def _conc_for_aqi(pollutant: str, target_aqi: int) -> float:
    """Invert a CPCB sub-index band to find the concentration giving ``target_aqi``.

    Works for any pollutant by looking up its breakpoint table from standards.
    """
    from ..standards import _AQI_BANDS
    bands = _AQI_BANDS[pollutant]
    for band in bands:
        if band.i_lo <= target_aqi <= band.i_hi:
            # Linear interpolation within the band (inverse of sub_index).
            span_i = band.i_hi - band.i_lo or 1
            return band.c_lo + (target_aqi - band.i_lo) * (band.c_hi - band.c_lo) / span_i
    # Beyond the last band — linear extrapolation from the last band.
    last = bands[-1]
    span_i = last.i_hi - last.i_lo or 1
    return last.c_hi + (target_aqi - last.i_hi) * (last.c_hi - last.c_lo) / span_i


def _pm10_for_aqi(target_aqi: int) -> float:
    """Backwards-compatible wrapper for PM10 inversion."""
    return _conc_for_aqi("pm10", target_aqi)


def _hash_seed(station_name: str, ts: datetime) -> int:
    """Stable per-slot seed so the same (station, slot) always yields the same jitter."""
    slot = int(ts.timestamp() // 900)  # 15-min bucket
    return abs(hash((station_name.strip().lower(), slot))) % (2**31)


class MockCPCBSource(SourceAdapter):
    """Deterministic mock of CPCB CAAQMS real-time data."""

    name = "mock"

    def __init__(
        self,
        target_spike_aqi: int = 310,
        spike_local_hour: float = 8.5,
        spike_sigma_hours: float = 1.6,
        base_profile: Optional[dict[str, float]] = None,
        peak_ratios: Optional[dict[str, float]] = None,
        dominant_override: Optional[str] = None,
    ) -> None:
        self.target_spike_aqi = target_spike_aqi
        self.spike_local_hour = spike_local_hour  # 8.5 == 08:30
        self.spike_sigma_hours = spike_sigma_hours
        self.base_profile = dict(base_profile or _BASE_PROFILE)
        self.dominant_override = dominant_override
        # Peak ratios can be overridden per-scenario to shift the dominant pollutant.
        pr = peak_ratios or {}
        self._pm25_pm10 = pr.get("pm25_pm10", _PEAK_PM25_PM10)
        self._no2_ratio = pr.get("no2", _PEAK_RATIO["no2"])
        self._so2_ratio = pr.get("so2", _PEAK_RATIO["so2"])
        self._o3_ratio = pr.get("o3", _PEAK_RATIO["o3"])
        self._co_per_pm10 = pr.get("co_per_pm10", _PEAK_CO_PER_PM10)
        # Pre-compute the PM10 concentration that anchors the spike AQI.
        self._spike_pm10 = _pm10_for_aqi(target_spike_aqi)

    # ------------------------------------------------------------------ #
    def _diurnal(self, local_dt: datetime) -> float:
        hour = local_dt.hour + local_dt.minute / 60.0
        i0, i1 = int(math.floor(hour)) % 24, (int(math.floor(hour)) + 1) % 24
        frac = hour - math.floor(hour)
        return _DIURNAL[i0] * (1 - frac) + _DIURNAL[i1] * frac

    def _spike_factor(self, local_dt: datetime) -> float:
        """Gaussian centred on the morning spike hour; 0 far from it."""
        dh = (local_dt.hour + local_dt.minute / 60.0) - self.spike_local_hour
        # Wrap around midnight so a 23h distance isn't double-counted.
        dh = (dh + 12) % 24 - 12
        return math.exp(-(dh**2) / (2 * self.spike_sigma_hours**2))

    def _build_peak(self) -> dict[str, float]:
        """Build the peak-hour pollutant concentrations.

        If dominant_override is set, solve for that pollutant's concentration
        at the target AQI and scale PM10 down so its sub-index stays below.
        """
        dom = self.dominant_override
        if dom is None or dom == "pm10":
            # Default: PM10 anchored at the target AQI.
            return {
                "pm10": self._spike_pm10,
                "pm25": self._spike_pm10 * self._pm25_pm10,
                "no2": self._spike_pm10 * self._no2_ratio,
                "so2": self._spike_pm10 * self._so2_ratio,
                "o3": self._spike_pm10 * self._o3_ratio,
                "co": self._spike_pm10 * self._co_per_pm10,
            }

        # Solve the dominant pollutant's concentration for the target AQI.
        dom_conc = _conc_for_aqi(dom, self.target_spike_aqi)
        # Scale PM10 down so its sub-index is ~80% of target (clearly below).
        pm10_lower = _conc_for_aqi("pm10", int(self.target_spike_aqi * 0.75))

        peak = {
            "pm10": pm10_lower,
            "pm25": pm10_lower * self._pm25_pm10,
            "no2": pm10_lower * self._no2_ratio,
            "so2": pm10_lower * self._so2_ratio,
            "o3": pm10_lower * self._o3_ratio,
            "co": pm10_lower * self._co_per_pm10,
        }
        # Override the dominant pollutant with its solved concentration.
        peak[dom] = dom_conc
        return peak

    def _reading_for(self, station_name: str, ts: datetime) -> RawReading:
        import random

        # `ts` is tz-aware UTC; convert to the station's local clock for the curve.
        local_dt = ts.astimezone(self._local_tz())
        diurnal = self._diurnal(local_dt)
        spike = self._spike_factor(local_dt)  # 0..1, Gaussian around the spike hour
        rng = random.Random(_hash_seed(station_name, ts))

        # Peak target concentrations for THIS spike intensity.
        peak = self._build_peak()

        pollutants: dict[str, object] = {}
        for p, base in self.base_profile.items():
            baseline = base * diurnal
            target = peak[p]
            # Blend baseline -> target by the spike factor. At spike==1 the value
            # is exactly the peak target (self-consistent AQI); at spike==0 it is
            # the diurnal baseline.
            value = baseline * (1 - spike) + target * spike
            # Jitter is tapered off near the spike peak so the *exact* target AQI
            # lands at 08:30; far from the peak, full ±8% jitter for realism.
            jitter_amp = 0.08 * (1.0 - spike) ** 2
            value *= 1.0 + rng.uniform(-jitter_amp, jitter_amp)
            pollutants[p] = round(max(value, 0.0), 2)

        return RawReading(
            station_name=station_name,
            timestamp=ts,
            pollutants=pollutants,
            co_input_unit="mg/m3",
        )

    def _local_tz(self):
        from zoneinfo import ZoneInfo

        from ..config import get_settings

        return ZoneInfo(get_settings().tz)

    # ------------------------------------------------------------------ #
    def fetch_latest(self, station_name: str) -> Optional[RawReading]:
        # Round "now" down to the last 15-min slot.
        now = datetime.now(tz=self._local_tz())
        slot = (now.minute // 15) * 15
        now = now.replace(minute=slot, second=0, microsecond=0)
        return self._reading_for(station_name, now)

    def fetch_range(
        self, station_name: str, start: datetime, end: datetime
    ) -> list[RawReading]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("fetch_range requires tz-aware datetimes")
        out: list[RawReading] = []
        cur = start
        step = timedelta(minutes=15)
        while cur < end:
            out.append(self._reading_for(station_name, cur))
            cur += step
        return out
