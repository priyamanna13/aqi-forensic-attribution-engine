"""Tests for weather source + weather contract builder."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

# Ensure SQLite for tests.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.pasquill import classify_stability
from app.weather_contract import build_weather_snapshot
from app.weather_sources.base import RawWeather
from app.weather_sources.mock import SCENARIO, MockIMDSource

# 08:30 IST on the contract scenario date.
_TZ = ZoneInfo("Asia/Kolkata")
_SPIKE_DT = datetime(2026, 6, 25, 8, 30, tzinfo=_TZ)


class TestMockSourceSnapshot:
    """MockIMDSource.fetch_snapshot at the exact scenario time."""

    def test_fetch_snapshot_returns_all_required_keys(self):
        src = MockIMDSource()
        raw = src.fetch_snapshot("Shivajinagar_Pune", _SPIKE_DT)
        assert raw is not None
        d = raw.to_dict()
        for key in (
            "source",
            "observed_at",
            "wind_speed_kmh",
            "wind_direction_deg",
            "temperature_c",
            "relative_humidity_pct",
            "pressure_hpa",
            "cloud_cover_oktas",
            "precipitation_mm_last_1h",
            "visibility_km",
            "mixing_layer_height_m",
        ):
            assert key in d, f"Missing key: {key}"

    def test_fetch_snapshot_contract_values(self):
        """At exactly 08:30 IST the mock must reproduce the SCENARIO values."""
        src = MockIMDSource()
        raw = src.fetch_snapshot("Shivajinagar_Pune", _SPIKE_DT)
        assert raw is not None
        d = raw.to_dict()
        assert d["wind_speed_kmh"] == pytest.approx(SCENARIO["wind_speed_kmh"], abs=0.5)
        assert d["wind_direction_deg"] == pytest.approx(SCENARIO["wind_direction_deg"], abs=5)
        assert d["temperature_c"] == pytest.approx(SCENARIO["temperature_c"], abs=0.5)
        assert d["relative_humidity_pct"] == pytest.approx(SCENARIO["relative_humidity_pct"], abs=2)
        assert d["pressure_hpa"] == pytest.approx(SCENARIO["pressure_hpa"], abs=0.5)
        assert d["cloud_cover_oktas"] == pytest.approx(SCENARIO["cloud_cover_oktas"], abs=1)
        assert d["precipitation_mm_last_1h"] == pytest.approx(SCENARIO["precipitation_mm_last_1h"], abs=0.1)
        assert d["visibility_km"] == pytest.approx(SCENARIO["visibility_km"], abs=0.5)
        assert d["mixing_layer_height_m"] == pytest.approx(SCENARIO["mixing_layer_height_m"], abs=25)


class TestBuildWeatherSnapshot:
    """build_weather_snapshot produces the exact data-contract JSON shape."""

    def _make_snapshot(self) -> dict:
        obs = {
            "source": "IMD_Pune_Observatory",
            "observed_at": _SPIKE_DT,
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
        stability = classify_stability(14.5, 3, True, 30)
        return build_weather_snapshot(obs, stability)

    def test_output_has_all_contract_keys(self):
        snap = self._make_snapshot()
        expected_keys = {
            "source",
            "observed_at",
            "wind_speed_kmh",
            "wind_direction_deg",
            "wind_direction_cardinal",
            "temperature_c",
            "relative_humidity_pct",
            "pressure_hpa",
            "cloud_cover_oktas",
            "precipitation_mm_last_1h",
            "visibility_km",
            "mixing_layer_height_m",
            "atmospheric_stability",
        }
        assert set(snap.keys()) == expected_keys

    def test_observed_at_has_ist_offset(self):
        snap = self._make_snapshot()
        assert "+05:30" in snap["observed_at"]

    def test_observed_at_iso_format(self):
        snap = self._make_snapshot()
        assert snap["observed_at"] == "2026-06-25T08:30:00+05:30"

    def test_cardinal_direction(self):
        snap = self._make_snapshot()
        assert snap["wind_direction_cardinal"] == "WNW"

    def test_atmospheric_stability_nested(self):
        snap = self._make_snapshot()
        stab = snap["atmospheric_stability"]
        assert stab["pasquill_class"] == "D"
        assert stab["label"] == "Neutral"
        assert "dispersion_coefficient" in stab
        assert stab["dispersion_coefficient"]["sigma_y"] == pytest.approx(0.22)
        assert stab["dispersion_coefficient"]["sigma_z"] == pytest.approx(0.08)
