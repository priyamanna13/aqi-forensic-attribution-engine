"""Integration tests: pipeline -> persist -> contract block shape.

Verifies the emitted ``trigger_station`` block matches the immutable data
contract structure, and that the seeded scenario produces AQI 310 / Very Poor /
PM10-dominant at 08:30 local — the exact scenario in data_contract_sample.json.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.contract import SUB_POLLUTANT_KEYS, build_trigger_station_block
from app.db import get_session, init_db
from app.models import AqiReading, Station, make_point_ewkt
from app.pipeline import PipelineController, latest_reading, upsert_station
from app.sources.mock import MockCPCBSource


@pytest.fixture()
def scenario():
    """Build the 08:30 spike reading through the full mock + pipeline path."""
    init_db()
    mock = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
    tz = ZoneInfo("Asia/Kolkata")
    spike_ts = datetime(2026, 6, 25, 8, 30, tzinfo=tz).astimezone(timezone.utc)
    raw = mock._reading_for("Shivajinagar", spike_ts)
    controller = PipelineController(source=mock)
    reading, report = controller.ingest_reading(raw)
    return reading, report


class TestScenarioNumbers:
    def test_spike_aqi_is_310(self, scenario):
        reading, _ = scenario
        assert reading.total_aqi == 310

    def test_spike_category_very_poor(self, scenario):
        reading, _ = scenario
        assert reading.aqi_category == "Very Poor"

    def test_dominant_is_pm10(self, scenario):
        reading, _ = scenario
        assert reading.dominant_pollutant == "pm10"

    def test_co_stored_in_mgm3(self, scenario):
        reading, _ = scenario
        # CO around 3.2 mg/m³, not 3200 (would be µg/m³).
        assert 1.0 < reading.co < 6.0


class TestContractShape:
    def test_block_has_exact_top_level_keys(self, scenario):
        reading, _ = scenario
        station = _station()
        block = build_trigger_station_block(station, reading)
        assert set(block.keys()) == {
            "id", "name", "network", "city", "state",
            "coordinates", "elevation_m", "reading",
        }

    def test_coordinates_are_lon_lat(self, scenario):
        reading, _ = scenario
        block = build_trigger_station_block(_station(), reading)
        lon, lat = block["coordinates"]
        assert lon == pytest.approx(73.8567, abs=1e-4)
        assert lat == pytest.approx(18.5308, abs=1e-4)

    def test_reading_keys(self, scenario):
        reading, _ = scenario
        block = build_trigger_station_block(_station(), reading)["reading"]
        assert set(block.keys()) == {
            "timestamp", "total_aqi", "aqi_category",
            "dominant_pollutant", "sub_pollutants", "chemical_fingerprint",
        }

    def test_sub_pollutant_shape(self, scenario):
        reading, _ = scenario
        sp = build_trigger_station_block(_station(), reading)["reading"]["sub_pollutants"]
        for pollutant, block in sp.items():
            assert set(block.keys()) == set(SUB_POLLUTANT_KEYS), pollutant
        # All six pollutants present.
        assert set(sp.keys()) == {"pm25", "pm10", "no2", "so2", "co", "o3"}

    def test_co_unit_is_mgm3_others_ugm3(self, scenario):
        reading, _ = scenario
        sp = build_trigger_station_block(_station(), reading)["reading"]["sub_pollutants"]
        assert sp["co"]["unit"] == "mg/m³"
        for p in ("pm25", "pm10", "no2", "so2", "o3"):
            assert sp[p]["unit"] == "µg/m³", p

    def test_timestamp_is_iso_local_with_offset(self, scenario):
        reading, _ = scenario
        ts = build_trigger_station_block(_station(), reading)["reading"]["timestamp"]
        assert ts.endswith("+05:30")
        assert "T08:30:00" in ts

    def test_chemical_fingerprint_shape(self, scenario):
        reading, _ = scenario
        fp = build_trigger_station_block(_station(), reading)["reading"]["chemical_fingerprint"]
        assert set(fp.keys()) == {
            "pm25_pm10_ratio", "no2_so2_ratio", "signature_class", "notes",
        }


class TestPersistRoundTrip:
    def test_upsert_and_latest(self):
        init_db()
        mock = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        controller = PipelineController(source=mock)
        tz = ZoneInfo("Asia/Kolkata")
        ts = datetime(2026, 6, 25, 8, 30, tzinfo=tz).astimezone(timezone.utc)
        raw = mock._reading_for("Shivajinagar", ts)

        with get_session() as session:
            station = upsert_station(
                session, "Shivajinagar", "Pune", "Maharashtra",
                73.8567, 18.5308, elevation_m=560,
            )
            controller.ingest_reading(raw, session=session, station=station)
            got = latest_reading(session, station)
            # Access all attributes inside the session to avoid DetachedInstanceError.
            aqi, dom = got.total_aqi, got.dominant_pollutant
        assert aqi == 310
        assert dom == "pm10"

    def test_upsert_reading_is_idempotent(self):
        """Re-ingesting the same slot updates, doesn't duplicate."""
        init_db()
        mock = MockCPCBSource(target_spike_aqi=310, spike_local_hour=8.5)
        controller = PipelineController(source=mock)
        tz = ZoneInfo("Asia/Kolkata")
        ts = datetime(2026, 6, 25, 8, 30, tzinfo=tz).astimezone(timezone.utc)
        raw = mock._reading_for("Shivajinagar", ts)

        with get_session() as session:
            station = upsert_station(
                session, "Shivajinagar", "Pune", "Maharashtra",
                73.8567, 18.5308, elevation_m=560,
            )
            controller.ingest_reading(raw, session=session, station=station)
            controller.ingest_reading(raw, session=session, station=station)
            from sqlalchemy import select
            n = session.execute(
                select(AqiReading).where(AqiReading.station_id == station.id)
            ).scalars().all()
        assert len(n) == 1


def _station() -> Station:
    s = Station(
        name="Shivajinagar", network="CPCB_CAAQMS", city="Pune",
        state="Maharashtra", elevation_m=560,
        geom=make_point_ewkt(73.8567, 18.5308),
    )
    import uuid
    s.id = uuid.uuid4()
    return s
