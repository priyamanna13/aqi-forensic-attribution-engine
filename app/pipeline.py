"""Ingestion pipeline: fetch -> validate -> compute AQI -> persist -> emit contract.

The controller is source-agnostic (mock or live via the adapter) and DB-optional:
call ``ingest_reading()`` without a session to get a computed reading + report
without persisting (used by the dry-run demo and tests).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contract import build_trigger_station_block
from .models import AqiReading, Station, make_point_ewkt
from .sources import SourceAdapter, get_source
from .standards import compute_aqi
from .validators import ReadingValidator, ValidationReport

log = logging.getLogger(__name__)


class PipelineController:
    """Orchestrates ingestion for one source + validator set."""

    def __init__(
        self,
        source: Optional[SourceAdapter] = None,
        validator: Optional[ReadingValidator] = None,
    ) -> None:
        self.source = source or get_source()
        self.validator = validator or ReadingValidator()

    # ------------------------------------------------------------------ #
    def ingest_reading(
        self,
        raw,
        session: Optional[Session] = None,
        station: Optional[Station] = None,
    ) -> tuple[Optional[AqiReading], ValidationReport]:
        """Validate one RawReading, compute AQI, optionally persist.

        Returns ``(reading_or_None, report)``. ``reading`` is None when the raw
        data fails validation (the report explains why). When ``session`` is
        provided the reading is persisted (upserted on station+timestamp).
        """
        # Accept either a RawReading or a bare dict (for tests/convenience).
        from .sources.base import RawReading

        if isinstance(raw, dict):
            raw = RawReading(
                station_name=raw["station_name"],
                timestamp=raw["timestamp"],
                pollutants=raw["pollutants"],
                co_input_unit=raw.get("co_input_unit", "mg/m3"),
            )

        report = self.validator.validate(raw.pollutants)
        if not report.is_valid:
            log.info("Rejected reading for %s: %s", raw.station_name, report.to_log())
            return None, report

        aqi = compute_aqi(report.clean)
        reading = AqiReading(
            timestamp=raw.timestamp,
            total_aqi=aqi.total_aqi,
            aqi_category=aqi.category,
            dominant_pollutant=aqi.dominant_pollutant,
            **report.clean,
        )

        if session is not None:
            if station is None:
                raise ValueError("station is required when persisting")
            reading.station_id = station.id
            self._upsert_reading(session, reading)
        return reading, report

    def _upsert_reading(self, session: Session, reading: AqiReading) -> AqiReading:
        """Insert or replace a reading keyed on (station_id, timestamp)."""
        existing = session.execute(
            select(AqiReading).where(
                AqiReading.station_id == reading.station_id,
                AqiReading.timestamp == reading.timestamp,
            )
        ).scalar_one_or_none()
        if existing is not None:
            for col in (
                "total_aqi",
                "aqi_category",
                "dominant_pollutant",
                "pm25",
                "pm10",
                "no2",
                "so2",
                "co",
                "o3",
            ):
                setattr(existing, col, getattr(reading, col))
            session.flush()
            return existing
        session.add(reading)
        session.flush()
        return reading

    # ------------------------------------------------------------------ #
    def ingest_latest(
        self, station: Station, session: Session
    ) -> tuple[Optional[AqiReading], ValidationReport]:
        """Fetch the latest reading from the source and persist it."""
        raw = self.source.fetch_latest(station.name)
        if raw is None:
            log.warning("No reading returned from source for %s", station.name)
            return None, ValidationReport()
        return self.ingest_reading(raw, session=session, station=station)

    def ingest_range(
        self,
        station: Station,
        session: Session,
        start: datetime,
        end: datetime,
    ) -> tuple[int, int]:
        """Backfill a time range. Returns (ingested, rejected) counts."""
        raws = self.source.fetch_range(station.name, start, end)
        ingested = rejected = 0
        for raw in raws:
            reading, _ = self.ingest_reading(raw, session=session, station=station)
            if reading is not None:
                ingested += 1
            else:
                rejected += 1
        return ingested, rejected

    # ------------------------------------------------------------------ #
    def emit_trigger_block(
        self, station: Station, reading: AqiReading, tz_name: str = "Asia/Kolkata"
    ) -> dict:
        """Convenience: build the contract trigger_station block."""
        return build_trigger_station_block(station, reading, tz_name=tz_name)


# --------------------------------------------------------------------------- #
# Station helpers
# --------------------------------------------------------------------------- #
def upsert_station(
    session: Session,
    name: str,
    city: str,
    state: str,
    longitude: float,
    latitude: float,
    elevation_m: int = 0,
    network: str = "CPCB_CAAQMS",
) -> Station:
    """Idempotently upsert a station by (name, city). Returns the ORM object."""
    st = session.execute(
        select(Station).where(Station.name == name, Station.city == city)
    ).scalar_one_or_none()
    ewkt = make_point_ewkt(longitude, latitude)
    if st is None:
        st = Station(
            name=name,
            city=city,
            state=state,
            network=network,
            elevation_m=elevation_m,
            geom=ewkt,
        )
        session.add(st)
        session.flush()
    else:
        st.state = state
        st.network = network
        st.elevation_m = elevation_m
        st.geom = ewkt
        session.flush()
    return st


def latest_reading(session: Session, station: Station) -> Optional[AqiReading]:
    return session.execute(
        select(AqiReading)
        .where(AqiReading.station_id == station.id)
        .order_by(AqiReading.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()
