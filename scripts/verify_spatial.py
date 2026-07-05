"""Spatial verification: find pollution sources within 3 km of each station.

Demonstrates the ``ST_DWithin`` + ``ST_Distance`` pattern that downstream
attribution code will rely on. Run AFTER ``db/seed_data.py``::

    python scripts/verify_spatial.py

The script asserts that each station has at least one source within 3 km
(consistent with the seeded data) and prints a table of matches + distances.
"""
from __future__ import annotations

import sys

# Allow running as `python scripts/verify_spatial.py` from the project root
# without installing the package.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from db.connection import SessionLocal, ping  # noqa: E402
from db.models import PollutionSource, Station  # noqa: E402

RADIUS_M = 3000  # 3 km


def find_sources_within(session, station: Station, radius_m: int):
    """Return rows of (source, distance_km) within ``radius_m`` of ``station``.

    Uses ``ST_DistanceSphere`` on the geometry columns directly so the result is
    in **meters** (plain ``ST_Distance`` on SRID 4326 returns degrees, not
    meters). The same expression is reused in the WHERE clause to filter.
    With ~13 sources a sequential scan is negligible.
    """
    distance_m = func.ST_DistanceSphere(PollutionSource.geom, station.geom)
    stmt = (
        select(PollutionSource, distance_m)
        .where(distance_m <= radius_m)
        .order_by(distance_m.asc())
    )
    rows = session.execute(stmt).all()
    return [(src, dist / 1000.0) for src, dist in rows]


def main() -> int:
    print("=" * 70)
    print(f"Spatial verification — sources within {RADIUS_M} m of each station")
    print("=" * 70)

    if not ping():
        print("FAIL: database not reachable. Run `docker compose up -d` + init_db first.")
        return 1

    overall_ok = True
    # ORM entity loading requires a Session (not a bare Connection).
    with SessionLocal() as session:
        stations = session.execute(select(Station).order_by(Station.name)).scalars().all()
        if not stations:
            print("FAIL: no stations found. Run `python db/seed_data.py` first.")
            return 2

        for st in stations:
            matches = find_sources_within(session, st, RADIUS_M)
            print(f"\nStation: {st.name}  ({len(matches)} source(s) within 3 km)")
            print("  distance(km)  type            near_school near_hospital  name")
            print("  ------------  --------------  ----------- -------------  -----------------------------")
            if not matches:
                print("  (none)")
                overall_ok = False
                continue
            for src, dist_km in matches:
                print(
                    f"  {dist_km:>11.3f}  {src.type:<14}  "
                    f"{'YES' if src.near_school else 'no':<11} "
                    f"{'YES' if src.near_hospital else 'no':<13}  {src.name}"
                )

    print()
    if overall_ok:
        print("RESULT: every station has >=1 source within 3 km. Spatial index works.")
        return 0
    print("RESULT: at least one station had no source within 3 km — check seed data.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
