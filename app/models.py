"""SQLAlchemy ORM models: ``stations`` and ``aqi_readings``.

PostGIS is the production target (Geometry Point, EPSG:4326, GIST index). For
local tests and the no-DB dry-run path the same models compile against SQLite,
where the geometry is carried as a WKT/EWKT string and the GIST index is skipped.

GeoJSON / data-contract convention is used everywhere for coordinates:
``[longitude, latitude]``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Index,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_settings
from .standards import (
    POLLUTANTS,
    MG_PER_M3_POLLUTANTS,
    canonical_unit,
    compute_aqi,
    exceedance_factor,
    NAAQS_LIMITS,
    AVERAGING_PERIODS,
    aqi_category,
)

# GeoAlchemy2 is PostGIS-only. We import it lazily and only attach the typed
# Geometry column on PostGIS so the model still maps under SQLite (tests/dry-run).
_USE_POSTGIS = not get_settings().is_sqlite
if _USE_POSTGIS:
    from geoalchemy2 import Geometry  # type: ignore


def _guid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_guid
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    network: Mapped[str] = mapped_column(String(40), nullable=False, default="CPCB_CAAQMS")
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(120), nullable=False)
    elevation_m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Geometry: PostGIS Point(EPSG:4326) with a GIST spatial index in production;
    # a plain String holding EWKT ("SRID=4326;POINT(lon lat)") under SQLite.
    if _USE_POSTGIS:
        geom = mapped_column(
            Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
            nullable=False,
        )
    else:
        geom: Mapped[str] = mapped_column(String, nullable=False)

    readings: Mapped[list["AqiReading"]] = relationship(
        back_populates="station", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Station {self.name} ({self.city}, {self.state})>"

    # -- coordinate helpers (GeoJSON [lon, lat]) -------------------------------
    def coordinates(self) -> tuple[float, float]:
        """Return coordinates as GeoJSON ``(longitude, latitude)``.

        Under PostGIS we read back WKB via ST_X/ST_Y; under SQLite we parse the
        stored EWKT string.
        """
        if _USE_POSTGIS:
            from geoalchemy2.elements import WKBElement  # type: ignore
            from sqlalchemy.orm import object_session

            sess = object_session(self)
            if sess is not None:
                row = sess.execute(
                    text(
                        "SELECT ST_X(:g), ST_Y(:g)"
                    ).bindparams(g=self.geom)
                ).one()
                return float(row[0]), float(row[1])
            # Fallback for in-memory / unflushed WKBElement.
            if isinstance(self.geom, WKBElement):
                from shapely import wkb
                pt = wkb.loads(bytes(self.geom.data))
                return pt.x, pt.y
            return _parse_ewkt(self.geom)
        return _parse_ewkt(self.geom)


def _parse_ewkt(ewkt: str) -> tuple[float, float]:
    """Parse ``SRID=4326;POINT(lon lat)`` or ``POINT(lon lat)`` -> (lon, lat)."""
    body = ewkt.split(";", 1)[-1].strip()
    inner = body[body.index("(") + 1 : body.rindex(")")].strip()
    lon_s, lat_s = inner.split()
    return float(lon_s), float(lat_s)


def make_point_ewkt(longitude: float, latitude: float) -> str:
    """EWKT for a point, SRID 4326. Usable on both SQLite and PostGIS text paths."""
    return f"SRID=4326;POINT({longitude} {latitude})"


class AqiReading(Base):
    __tablename__ = "aqi_readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_guid
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    # CPCB publishes in IST; store tz-aware UTC-valued timestamps.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # total_aqi is an int and explicitly allows > 500 for extreme events.
    total_aqi: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aqi_category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dominant_pollutant: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Pollutant concentrations. CO stored in mg/m³; all others µg/m³.
    pm25: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pm10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    so2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    co: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    o3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    station: Mapped["Station"] = relationship(back_populates="readings")

    __table_args__ = (
        # 15-minute dedupe: one reading per (station, timestamp).
        UniqueConstraint("station_id", "timestamp", name="uq_station_timestamp"),
        Index("ix_readings_station_ts", "station_id", "timestamp"),
    )

    # -- contract-shaped accessors ---------------------------------------------
    def concentrations(self) -> dict[str, float]:
        """Non-null pollutant concentrations in canonical units."""
        out: dict[str, float] = {}
        for p in POLLUTANTS:
            v = getattr(self, p, None)
            if v is not None:
                out[p] = float(v)
        return out

    def to_sub_pollutants(self) -> dict[str, dict]:
        """Build the contract's ``reading.sub_pollutants`` object."""
        out: dict[str, dict] = {}
        for p, value in self.concentrations().items():
            out[p] = {
                "value": round(value, 1),
                "unit": canonical_unit(p),
                "averaging_period": AVERAGING_PERIODS[p],
                "naaqs_limit": NAAQS_LIMITS[p],
                "exceedance_factor": exceedance_factor(p, value),
            }
        return out

    def chemical_fingerprint(self) -> dict:
        """Build the contract's ``reading.chemical_fingerprint`` object.

        The signature class is a coarse heuristic from the coarse/fine PM ratio
        and the NO2/SO2 (combustion) ratio, matching the flavour of the sample.
        """
        conc = self.concentrations()
        pm25 = conc.get("pm25")
        pm10 = conc.get("pm10")
        no2 = conc.get("no2")
        so2 = conc.get("so2")

        pm_ratio = round(pm25 / pm10, 3) if (pm25 and pm10) else None
        no2_so2 = round(no2 / so2, 3) if (no2 and so2) else None

        signature = "mixed"
        notes = "Insufficient data to classify signature."
        if pm_ratio is not None:
            if pm_ratio < 0.45:
                signature = "crustal_dominant"
                notes = (
                    "High PM coarse fraction (PM2.5/PM10 < 0.45) suggests "
                    "fugitive dust / construction / road dust contribution."
                )
                if no2_so2 and no2_so2 > 1.0:
                    signature = "crustal_dominant"
                    notes = (
                        "High PM coarse fraction with moderate NO₂ suggests "
                        "combined dust + vehicular contribution"
                    )
            elif pm_ratio > 0.7:
                signature = "combustion_dominant"
                notes = (
                    "PM2.5-dominated aerosol (PM2.5/PM10 > 0.7) with fine-mode "
                    "signature typical of combustion / vehicle exhaust / biomass."
                )
            else:
                signature = "mixed"
                notes = (
                    "Balanced coarse/fine PM fraction indicates a mixed "
                    "dust + combustion source profile."
                )

        return {
            "pm25_pm10_ratio": pm_ratio,
            "no2_so2_ratio": no2_so2,
            "signature_class": signature,
            "notes": notes,
        }
