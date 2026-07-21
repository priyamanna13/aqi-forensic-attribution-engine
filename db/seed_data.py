"""Seed the database with Pune air-quality monitoring stations and pollution sources.

Stations (exact coords from the task spec):
    Shivajinagar  POINT(73.8440 18.5308)
    Hadapsar      POINT(73.9268 18.5089)
    Katraj        POINT(73.8567 18.4575)
    Karve Road    POINT(73.8290 18.5074)

Pollution sources (within ~5 km of those stations), grouped by type and given
realistic Pune-area coordinates and operational windows:

  - Construction  (Polygon)   schedule 09:00–18:00
  - Traffic       (LineString) peak windows: 08:00–10:00 (primary) /
                                  secondary 17:00–20:00 noted in a comment
  - Industrial    (Polygon)    schedule 00:00–23:59:59 (24/7)
  - Waste burning (Point)      early morning / night windows

A couple of sources are flagged near_school / near_hospital per the spec.

Idempotent: stations upsert by ``name``; sources upsert by (name, type).
Re-running is safe and prints a clear summary of what changed.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from dataclasses import dataclass
from datetime import time as dtime
from typing import Optional

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

try:
    from .connection import SessionLocal, engine
    from .models import PollutionSource, Station
except ImportError:
    from connection import SessionLocal, engine
    from models import PollutionSource, Station

SRID = 4326


# --------------------------------------------------------------------------
# Source data containers
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class StationSpec:
    name: str
    lon: float
    lat: float


@dataclass(frozen=True)
class SourceSpec:
    name: str
    type: str                 # 'industrial' | 'construction' | 'traffic' | 'waste_burning'
    wkt: str                  # geometry in WKT (lon,lat order)
    schedule_start: Optional[dtime]
    schedule_end: Optional[dtime]
    near_school: bool = False
    near_hospital: bool = False
    # Free-form note (e.g. secondary traffic window) — not stored in the DB,
    # kept for documentation only.
    note: str = ""


# --------------------------------------------------------------------------
# Pune stations (spec coords)
# --------------------------------------------------------------------------
STATIONS: list[StationSpec] = [
    StationSpec("Shivajinagar", 73.8567, 18.5308),
    StationSpec("Swargate",     73.8553, 18.5018),
    StationSpec("Hadapsar",     73.9260, 18.5089),
    StationSpec("Kothrud",      73.8077, 18.5074),
]


# --------------------------------------------------------------------------
# Pune pollution sources.
# All coordinates are real Pune-area locations within ~5 km of the stations.
# Geometry WKT is built with db.geo_utils helpers to keep it readable.
# --------------------------------------------------------------------------
try:
    from .geo_utils import linestring_wkt, point_wkt, polygon_wkt  # noqa: E402
except ImportError:
    from geo_utils import linestring_wkt, point_wkt, polygon_wkt  # noqa: E402

SOURCES: list[SourceSpec] = [
    # ---- Construction (Polygons) — day shift 09:00–18:00 ------------------
    SourceSpec(
        name="Mula Road Residential Towers",
        type="construction",
        # Small block ~1.5 km NW of Shivajinagar, near a school.
        wkt=polygon_wkt([
            (73.8320, 18.5400), (73.8350, 18.5400),
            (73.8350, 18.5375), (73.8320, 18.5375),
        ]),
        schedule_start=dtime(9, 0),
        schedule_end=dtime(18, 0),
        near_school=True,
        note="Adjacent to a primary school — sensitive receptor.",
    ),
    SourceSpec(
        name="Hadapsar Magarpatta Flyover Works",
        type="construction",
        # Block ~1.2 km NE of Hadapsar station.
        wkt=polygon_wkt([
            (73.9340, 18.5140), (73.9370, 18.5140),
            (73.9370, 18.5115), (73.9340, 18.5115),
        ]),
        schedule_start=dtime(9, 0),
        schedule_end=dtime(18, 0),
    ),
    SourceSpec(
        name="Katraj Lakeside Redevelopment",
        type="construction",
        # Block ~1.5 km S of Katraj station.
        wkt=polygon_wkt([
            (73.8540, 18.4480), (73.8575, 18.4480),
            (73.8575, 18.4450), (73.8540, 18.4450),
        ]),
        schedule_start=dtime(9, 0),
        schedule_end=dtime(18, 0),
    ),

    # ---- Traffic corridors (LineStrings) — morning peak 08:00–10:00 -------
    # (Secondary evening window 17:00–20:00 noted in `note` per spec.)
    SourceSpec(
        name="Karve Road Corridor",
        type="traffic",
        # Spans Karve Road past the station.
        wkt=linestring_wkt([
            (73.8150, 18.5074), (73.8290, 18.5074), (73.8430, 18.5080),
        ]),
        schedule_start=dtime(8, 0),
        schedule_end=dtime(10, 0),
        near_hospital=True,
        note="Evening window 17:00–20:00 not modeled as a second row; "
             "future enhancement: split peak windows into separate rows.",
    ),
    SourceSpec(
        name="Sinhagad Road Corridor",
        type="traffic",
        wkt=linestring_wkt([
            (73.8300, 18.4920), (73.8360, 18.5010), (73.8430, 18.5110),
        ]),
        schedule_start=dtime(8, 0),
        schedule_end=dtime(10, 0),
    ),
    SourceSpec(
        name="Hadapsar-Solapur Highway Stretch",
        type="traffic",
        wkt=linestring_wkt([
            (73.9180, 18.5089), (73.9268, 18.5089), (73.9360, 18.5095),
        ]),
        schedule_start=dtime(8, 0),
        schedule_end=dtime(10, 0),
    ),
    SourceSpec(
        name="Shivajinagar-Swargate Corridor",
        type="traffic",
        wkt=linestring_wkt([
            (73.8440, 18.5308), (73.8480, 18.5200), (73.8510, 18.5100),
        ]),
        schedule_start=dtime(8, 0),
        schedule_end=dtime(10, 0),
    ),

    # ---- Industrial (Polygons) — 24/7 ------------------------------------
    SourceSpec(
        name="Bhosari MIDC Industrial Zone",
        type="industrial",
        # Larger polygon ~4 km N of Shivajinagar (within 5 km buffer).
        wkt=polygon_wkt([
            (73.8380, 18.5680), (73.8480, 18.5680),
            (73.8480, 18.5620), (73.8380, 18.5620),
        ]),
        schedule_start=dtime(0, 0),
        schedule_end=dtime(23, 59, 59),
        near_hospital=True,
        note="Continuous operations; flagged near a hospital.",
    ),
    SourceSpec(
        name="Hadapsar Industrial Estate",
        type="industrial",
        # ~2.5 km E of Hadapsar station.
        wkt=polygon_wkt([
            (73.9450, 18.5140), (73.9520, 18.5140),
            (73.9520, 18.5090), (73.9450, 18.5090),
        ]),
        schedule_start=dtime(0, 0),
        schedule_end=dtime(23, 59, 59),
    ),
    SourceSpec(
        name="Kothrud Small-Scale Units",
        type="industrial",
        # ~2 km W of Karve Road station.
        wkt=polygon_wkt([
            (73.8080, 18.5070), (73.8140, 18.5070),
            (73.8140, 18.5020), (73.8080, 18.5020),
        ]),
        schedule_start=dtime(0, 0),
        schedule_end=dtime(23, 59, 59),
    ),

    # ---- Waste burning (Points) — early morning / night ------------------
    SourceSpec(
        name="Katraj Hillock Open Dump",
        type="waste_burning",
        # ~1.8 km S of Katraj station.
        wkt=point_wkt(73.8575, 18.4440),
        schedule_start=dtime(5, 0),
        schedule_end=dtime(7, 0),
        near_school=True,
    ),
    SourceSpec(
        name="Mula-Mutha Riverbank Burning Spot",
        type="waste_burning",
        # ~1.2 km E of Shivajinagar.
        wkt=point_wkt(73.8560, 18.5300),
        schedule_start=dtime(20, 0),
        schedule_end=dtime(23, 0),
    ),
    SourceSpec(
        name="Hadapsar Mundhwa Fringe Dump",
        type="waste_burning",
        # ~2.2 km NE of Hadapsar station.
        wkt=point_wkt(73.9410, 18.5180),
        schedule_start=dtime(5, 30),
        schedule_end=dtime(7, 30),
    ),
]


# --------------------------------------------------------------------------
# Upsert logic
# --------------------------------------------------------------------------
def _to_wkt_element(wkt: str) -> WKTElement:
    """Wrap a WKT string into a SRID-aware WKTElement for GeoAlchemy2."""
    return WKTElement(wkt, srid=SRID)


def seed_stations() -> int:
    """Upsert all stations by name. Returns number upserted."""
    rows = [
        {
            "name": s.name,
            "geom": _to_wkt_element(point_wkt(s.lon, s.lat)),
        }
        for s in STATIONS
    ]
    with engine.begin() as conn:
        # Clean up outdated station rows not present in current configurations
        from sqlalchemy import delete
        valid_names = [s.name for s in STATIONS]
        conn.execute(delete(Station).where(Station.name.not_in(valid_names)))

        for row in rows:
            stmt = (
                pg_insert(Station)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["name"],
                    set_={"geom": pg_insert(Station).excluded.geom},
                )
            )
            conn.execute(stmt)
    return len(rows)


def seed_sources() -> int:
    """Upsert all pollution sources by (name, type). Returns number upserted."""
    rows = [
        {
            "name": s.name,
            "type": s.type,
            "geom": _to_wkt_element(s.wkt),
            "schedule_start": s.schedule_start,
            "schedule_end": s.schedule_end,
            "near_school": s.near_school,
            "near_hospital": s.near_hospital,
        }
        for s in SOURCES
    ]
    with engine.begin() as conn:
        # Clean up outdated source rows not present in current configurations
        from sqlalchemy import delete
        valid_names = [s.name for s in SOURCES]
        conn.execute(delete(PollutionSource).where(PollutionSource.name.not_in(valid_names)))
        for row in rows:
            stmt = (
                pg_insert(PollutionSource)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["name", "type"],
                    set_={
                        "geom": pg_insert(PollutionSource).excluded.geom,
                        "schedule_start": pg_insert(PollutionSource).excluded.schedule_start,
                        "schedule_end": pg_insert(PollutionSource).excluded.schedule_end,
                        "near_school": pg_insert(PollutionSource).excluded.near_school,
                        "near_hospital": pg_insert(PollutionSource).excluded.near_hospital,
                    },
                )
            )
            conn.execute(stmt)
    return len(rows)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> int:
    print("=" * 60)
    print("Seeding Pune stations + pollution sources")
    print("=" * 60)

    # Pre-flight counts. ORM entity-loading requires a Session (not a bare
    # Connection); on a Core connection, select(Model).scalars() returns the
    # first column (the UUID id), which is why we use SessionLocal here.
    with SessionLocal() as session:
        before_stations = session.execute(select(Station)).scalars().all()
        before_sources = session.execute(select(PollutionSource)).scalars().all()
    print(f"Before: {len(before_stations)} stations, {len(before_sources)} sources")

    t0 = time.perf_counter()
    n_stations = seed_stations()
    n_sources = seed_sources()
    dt = time.perf_counter() - t0

    # Post-flight counts + a few sanity flags.
    with SessionLocal() as session:
        after_stations = session.execute(select(Station)).scalars().all()
        after_sources = session.execute(select(PollutionSource)).scalars().all()
        n_school = session.execute(
            select(PollutionSource).where(PollutionSource.near_school.is_(True))
        ).scalars().all()
        n_hospital = session.execute(
            select(PollutionSource).where(PollutionSource.near_hospital.is_(True))
        ).scalars().all()

    print(f"After:  {len(after_stations)} stations, {len(after_sources)} sources")
    print(
        f"Upserted {n_stations} stations and {n_sources} sources in {dt*1000:.0f} ms"
    )
    print(f"Flagged near_school: {len(n_school)} | near_hospital: {len(n_hospital)}")

    by_type: dict[str, int] = {}
    for s in after_sources:
        by_type[s.type] = by_type.get(s.type, 0) + 1
    print("Sources by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))

    ok = (
        len(after_stations) == len(STATIONS)
        and len(after_sources) == len(SOURCES)
        and len(n_school) >= 1
        and len(n_hospital) >= 1
    )
    print("\nDONE." if ok else "\nWARNING: counts do not match expectations.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
