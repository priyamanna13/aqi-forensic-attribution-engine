"""SQLAlchemy ORM model: ``pollution_sources``.

Stores candidate pollution sources (industrial, construction, traffic,
waste_burning) used by the Source Candidate Ranking Engine (Prompt 2C).

Geometry is stored as a GeoJSON text string for SQLite compatibility,
matching the same pattern used by ``Station`` under the non-PostGIS path.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, _guid


class PollutionSource(Base):
    """A known or suspected pollution source near a monitoring station."""

    __tablename__ = "pollution_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_guid
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # 'industrial', 'construction', 'traffic', 'waste_burning'
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    osm_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
    source_origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="curated"
    )
    # Geometry stored as GeoJSON text (SQLite compat, same pattern as Station).
    geom: Mapped[str] = mapped_column(String, nullable=False)

    permit_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    # Operating schedule in HH:MM format.
    schedule_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    schedule_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)

    # Proximity to sensitive receptors.
    near_school: Mapped[bool] = mapped_column(Boolean, default=False)
    school_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    school_distance_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    near_hospital: Mapped[bool] = mapped_column(Boolean, default=False)
    hospital_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hospital_distance_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Dust suppression compliance.
    dust_suppression_required: Mapped[bool] = mapped_column(Boolean, default=False)
    dust_suppression_observed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Inspection & violation history.
    last_inspection_date: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # YYYY-MM-DD
    violation_count_90d: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PollutionSource {self.name} ({self.type})>"
