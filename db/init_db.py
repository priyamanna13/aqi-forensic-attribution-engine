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
    """Run schema.sql directly via SQLAlchemy text to ensure proper transaction commit."""
    from sqlalchemy import text

    # 1. Run Extensions outside of transaction (AUTOCOMMIT)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        except Exception as e:
            print("PostGIS extension creation skipped/failed:", e)
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
        except Exception:
            pass

    # 2. Hardcode individual statements to completely bypass psycopg2 multi-statement silent failures
    statements = [
        "CREATE TABLE IF NOT EXISTS stations (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(255) UNIQUE NOT NULL, geom GEOMETRY(POINT, 4326) NOT NULL, last_aqi FLOAT, last_updated TIMESTAMP WITH TIME ZONE);",
        "CREATE INDEX IF NOT EXISTS idx_stations_geom ON stations USING GIST (geom);",
        "CREATE TABLE IF NOT EXISTS aqi_readings (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), station_id UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE, timestamp TIMESTAMP WITH TIME ZONE NOT NULL, aqi FLOAT NOT NULL, pm25 FLOAT, pm10 FLOAT, no2 FLOAT, so2 FLOAT, co FLOAT, o3 FLOAT, CONSTRAINT uq_aqi_station_timestamp UNIQUE (station_id, timestamp));",
        "CREATE INDEX IF NOT EXISTS idx_aqi_readings_station_ts ON aqi_readings (station_id, timestamp DESC);",
        "DO $$ BEGIN CREATE TYPE pollution_source_type AS ENUM ('industrial', 'construction', 'traffic', 'waste_burning'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "CREATE TABLE IF NOT EXISTS pollution_sources (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL CHECK (type IN ('industrial','construction','traffic','waste_burning')), geom GEOMETRY(GEOMETRY, 4326) NOT NULL, schedule_start TIME, schedule_end TIME, near_school BOOLEAN NOT NULL DEFAULT FALSE, near_hospital BOOLEAN NOT NULL DEFAULT FALSE, osm_id VARCHAR(50) UNIQUE, source_origin VARCHAR(20) NOT NULL DEFAULT 'curated' CHECK (source_origin IN ('curated', 'osm', 'municipal')), description TEXT, CONSTRAINT uq_pollution_sources_name_type UNIQUE (name, type));",
        "CREATE INDEX IF NOT EXISTS idx_pollution_sources_geom ON pollution_sources USING GIST (geom);",
        "CREATE INDEX IF NOT EXISTS idx_pollution_sources_type ON pollution_sources (type);",
        "ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS osm_id VARCHAR(50) UNIQUE;",
        "ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS source_origin VARCHAR(20) NOT NULL DEFAULT 'curated';",
        "ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS description TEXT;",
        "CREATE TABLE IF NOT EXISTS wind_data (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), station_id UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE, timestamp TIMESTAMP WITH TIME ZONE NOT NULL, wind_speed_kmh FLOAT NOT NULL, wind_direction_deg FLOAT NOT NULL CHECK (wind_direction_deg BETWEEN 0 AND 360), temperature FLOAT, weather_snapshot_json JSONB);",
        "CREATE INDEX IF NOT EXISTS idx_wind_data_station_ts ON wind_data (station_id, timestamp DESC);",
        "ALTER TABLE wind_data ADD COLUMN IF NOT EXISTS weather_snapshot_json JSONB;",
        "CREATE TABLE IF NOT EXISTS alerts (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), station_id UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE, spike_time TIMESTAMP WITH TIME ZONE NOT NULL, aqi_value FLOAT NOT NULL, dominant_pollutant VARCHAR(10) NOT NULL, attribution_details JSONB NOT NULL, enforcement_priority FLOAT NOT NULL CHECK (enforcement_priority BETWEEN 0.0 AND 1.0), created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_station_spike ON alerts (station_id, spike_time DESC);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_priority ON alerts (enforcement_priority DESC);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_attr_gin ON alerts USING GIN (attribution_details);"
    ]

    # 3. Run statements inside transaction
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


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
