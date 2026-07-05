"""SQLAlchemy model for weather observations (Task 2A).

Builds on the existing ``Base`` from ``app.models`` (shared metadata) so
``init_db()`` creates this table alongside ``stations`` / ``aqi_readings``.

The model mirrors the scalar fields of the data-contract ``weather_snapshot``
block; the derived ``atmospheric_stability`` sub-object is computed at read time
by ``app.pasquill`` and is therefore NOT stored.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, _guid


class WeatherObservation(Base):
    """One weather observation row, sourced from an IMD-style station."""

    __tablename__ = "weather_observations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_guid
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="IMD_Pune_Observatory")

    wind_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_direction_deg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    relative_humidity_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pressure_hpa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cloud_cover_oktas: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    precipitation_mm_last_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    visibility_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mixing_layer_height_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("station_id", "observed_at", name="uq_weather_station_time"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WeatherObservation {self.source} @ {self.observed_at}>"
