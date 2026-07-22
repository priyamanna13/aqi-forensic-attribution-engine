"""Idempotent database initializer.

What it does, in order:
  1. Pings the DB to confirm connectivity + PostGIS extension.
  2. Executes db/schema.sql against the target database (creates extensions,
     tables, indexes, constraints). The script is fully idempotent, so this
     is safe to run repeatedly.
  3. Cross-checks that every expected table exists and prints a summary.

Run it directly::

    python db/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

try:
    from . import config
    from .connection import engine, ping
except ImportError:
    import config
    from connection import engine, ping

# Tables this task is expected to create, in dependency order.
EXPECTED_TABLES = [
    "stations",
    "aqi_readings",
    "pollution_sources",
    "wind_data",
    "alerts",
]

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def _execute_schema_sql() -> None:
    """Run schema.sql via psycopg2's execute() on the raw connection."""
    raw_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    
    # Strip out the CREATE EXTENSION lines so we can run them separately
    filtered_sql = []
    for line in raw_sql.splitlines():
        if not line.strip().upper().startswith("CREATE EXTENSION"):
            filtered_sql.append(line)
    safe_sql = "\n".join(filtered_sql)

    with engine.connect() as conn:
        dbapi_conn = conn.connection
        
        # 1. Run Extensions outside of transaction
        dbapi_conn.autocommit = True
        try:
            with dbapi_conn.cursor() as cur:
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
                except Exception:
                    pass
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
                except Exception:
                    pass
        finally:
            dbapi_conn.autocommit = False
            
        # 2. Run tables/indexes inside transaction
        with dbapi_conn.cursor() as cur:
            cur.execute(safe_sql)
            for line in safe_sql.splitlines():
                line_str = line.strip()
                if line_str.startswith("ALTER TABLE") or line_str.startswith("CREATE INDEX"):
                    try:
                        cur.execute(line_str)
                    except Exception:
                        pass
        conn.commit()


def _verify_tables() -> dict[str, bool]:
    """Return {table_name: exists?} for every expected table."""
    present: dict[str, bool] = {}
    with engine.connect() as conn:
        for table in EXPECTED_TABLES:
            exists = conn.execute(
                text(
                    "SELECT to_regclass(:t) IS NOT NULL"
                ),
                {"t": table},
            ).scalar()
            present[table] = bool(exists)
    return present


def main() -> int:
    print("=" * 60)
    print("Air Quality Intelligence — DB initialization")
    print("=" * 60)
    print(f"Target: {config.describe()['url']}")
    print()

    print("[1/3] Connectivity + PostGIS check...")
    if not ping():
        print("FAILED: cannot reach database or PostGIS extension is missing.")
        print("       Is `docker compose up -d` running? See README.md.")
        return 1
    print("      OK — database reachable, PostGIS present.")
    print()

    print(f"[2/3] Applying {SCHEMA_FILE.name} (idempotent)...")
    try:
        _execute_schema_sql()
    except Exception as exc:
        print(f"FAILED while applying schema: {exc}")
        return 2
    print("      OK — schema applied.")
    print()

    print("[3/3] Verifying tables...")
    present = _verify_tables()
    missing = [t for t, ok in present.items() if not ok]
    width = max(len(t) for t in EXPECTED_TABLES)
    for table in EXPECTED_TABLES:
        flag = "OK " if present[table] else "MISSING"
        print(f"      [{flag}] {table:<{width}}")
    if missing:
        print(f"\nFAILED: missing tables: {missing}")
        return 3

    print("\nAll expected tables are present. Database is ready for seeding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
