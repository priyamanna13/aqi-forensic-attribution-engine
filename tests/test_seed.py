"""Tests for the mock source determinism + spike accuracy (the seed engine)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from app.pipeline import PipelineController
from app.sources.mock import MockCPCBSource


def _ts(h, m):
    tz = ZoneInfo("Asia/Kolkata")
    return datetime(2026, 6, 25, h, m, tzinfo=tz).astimezone(timezone.utc)


class TestDeterminism:
    def test_same_slot_repeats_exactly(self):
        m = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        r1 = m._reading_for("Shivajinagar", _ts(8, 30))
        r2 = m._reading_for("Shivajinagar", _ts(8, 30))
        assert r1.pollutants == r2.pollutants

    def test_different_stations_differ(self):
        m = MockCPCBSource()
        r1 = m._reading_for("Shivajinagar", _ts(10, 0))
        r2 = m._reading_for("Baner", _ts(10, 0))
        assert r1.pollutants != r2.pollutants


class TestSpikeAccuracy:
    def test_peak_aqi_equals_target(self):
        m = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        raw = m._reading_for("Shivajinagar", _ts(8, 30))
        # Validate + compute via the real pipeline path.
        from app.pipeline import PipelineController
        reading, _ = PipelineController(source=m).ingest_reading(raw)
        assert reading.total_aqi == 310

    def test_peak_dominant_pm10(self):
        m = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        raw = m._reading_for("Shivajinagar", _ts(8, 30))
        reading, _ = PipelineController(source=MockCPCBSource()).ingest_reading(raw)
        assert reading.dominant_pollutant == "pm10"

    def test_off_peak_aqi_below_peak(self):
        """Away from 08:30 the AQI must be well below the spike."""
        from app.pipeline import PipelineController
        m = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        ctrl = PipelineController(source=m)
        peak = ctrl.ingest_reading(m._reading_for("Shivajinagar", _ts(8, 30)))[0]
        midday = ctrl.ingest_reading(m._reading_for("Shivajinagar", _ts(13, 0)))[0]
        assert midday.total_aqi < peak.total_aqi
        assert midday.total_aqi < 200


class TestBackfillRange:
    def test_fetch_range_15min_cadence(self):
        m = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        tz = ZoneInfo("Asia/Kolkata")
        start = datetime(2026, 6, 25, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        end = start + timedelta(hours=1)
        out = m.fetch_range("Shivajinagar", start, end)
        assert len(out) == 4  # 4 slots per hour at 15-min
        # All tz-aware.
        assert all(r.timestamp.tzinfo is not None for r in out)
