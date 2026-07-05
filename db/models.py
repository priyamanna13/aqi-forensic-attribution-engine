"""ORM table definitions for the Air Quality Intelligence platform.

Each table mirrors the schema spec (Task 1). Key conventions:
  - Primary keys are UUID, defaulted by Postgres ``gen_random_uuid()``.
  - Every spatial column uses SRID 4326 (WGS 84) and is GIST-indexed.
  - ``pollution_sources.geom`` is generic GEOMETRY so it can hold Points,
    LineStrings (traffic corridors), and Polygons (industrial/construction).

The authoritative DDL lives in ``db/schema.sql`` (used by init_db and the
docker-entrypoint auto-init). This ORM file is what application code and the
seed scripts use to talk to those tables. Both are kept in sync by init_db's
``Base.metadata.create_all`` path, which is schema-idempotent.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common declarative base for all models."""


# Postgres default-expression: emit gen_random_uuid() server-side.
# PG16+ has it built-in; pgcrypto is enabled in schema.sql for older builds.
_UUID_DEFAULT = text("gen_random_uuid()")


class Station(Base):
    """Air quality monitoring station (Pune)."""

    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # POINT in WGS 84; spatial index via GIST (added in schema.sql + below).
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    last_aqi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    readings: Mapped[list["AqiReading"]] = relationship(
        back_populates="station", cascade="all, delete-orphan"
    )
    wind_data: Mapped[list["WindData"]] = relationship(
        back_populates="station", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="station", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Station name={self.name!r} last_aqi={self.last_aqi}>"


class AqiReading(Base):
    """A single AQI observation at a station/time. Unique per (station, time)."""

    __tablename__ = "aqi_readings"
    __table_args__ = (
        UniqueConstraint("station_id", "timestamp", name="uq_aqi_station_timestamp"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, server_default=_UUID_DEFAULT)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    aqi: Mapped[float] = mapped_column(Float, nullable=False)
    pm25: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pm10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    so2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    co: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    o3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    station: Mapped["Station"] = relationship(back_populates="readings")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AqiReading station_id={self.station_id} ts={self.timestamp} aqi={self.aqi}>"


class PollutionSource(Base):
    """A pollution emitter near stations.

    ``geom`` is generic (Point/LineString/Polygon). Operational window is
    defined by ``schedule_start``/``schedule_end``. ``near_school`` /
    ``near_hospital`` flag sensitive nearby receptors for vulnerability logic.
    """

    __tablename__ = "pollution_sources"
    __table_args__ = (
        CheckConstraint(
            "type IN ('industrial','construction','traffic','waste_burning')",
            name="ck_pollution_source_type",
        ),
        CheckConstraint(
            "source_origin IN ('curated', 'osm', 'municipal')",
            name="ck_pollution_source_origin",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Generic geometry: Points, LineStrings, or Polygons.
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True),
        nullable=False,
    )
    schedule_start: Mapped[Optional[Any]] = mapped_column(Time, nullable=True)
    schedule_end: Mapped[Optional[Any]] = mapped_column(Time, nullable=True)
    near_school: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    near_hospital: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    osm_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
    source_origin: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'curated'")
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PollutionSource name={self.name!r} type={self.type!r} origin={self.source_origin!r}>"


class WindData(Base):
    """Meteorological reading (wind + temperature), typically per-station."""

    __tablename__ = "wind_data"

    id: Mapped[str] = mapped_column(primary_key=True, server_default=_UUID_DEFAULT)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    wind_speed_kmh: Mapped[float] = mapped_column(Float, nullable=False)
    wind_direction_deg: Mapped[float] = mapped_column(Float, nullable=False)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weather_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    station: Mapped["Station"] = relationship(back_populates="wind_data")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<WindData station_id={self.station_id} ts={self.timestamp} "
            f"speed={self.wind_speed_kmh} dir={self.wind_direction_deg}>"
        )


class Alert(Base):
    """An AQI spike event + its attribution analysis (JSONB) and priority."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "enforcement_priority BETWEEN 0.0 AND 1.0",
            name="ck_alert_enforcement_priority_range",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, server_default=_UUID_DEFAULT)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    spike_time: Mapped[datetime] = mapped_column(nullable=False)
    aqi_value: Mapped[float] = mapped_column(Float, nullable=False)
    dominant_pollutant: Mapped[str] = mapped_column(String(10), nullable=False)
    # Arbitrary JSON: candidate sources, confidence breakdowns, wind snapshot,
    # generated advisory text.
    attribution_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enforcement_priority: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    station: Mapped["Station"] = relationship(back_populates="alerts")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Alert station_id={self.station_id} spike={self.spike_time} "
            f"aqi={self.aqi_value} prio={self.enforcement_priority}>"
        )


__all__ = [
    "Base",
    "Station",
    "AqiReading",
    "PollutionSource",
    "WindData",
    "Alert",
]
