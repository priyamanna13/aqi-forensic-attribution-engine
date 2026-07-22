-- ============================================================================
-- Air Quality Intelligence — PostgreSQL + PostGIS schema
-- Target city: Pune, India. All geometry uses SRID 4326 (WGS 84).
--
-- This file is:
--   * idempotent (safe to re-run),
--   * mounted into docker-entrypoint-initdb.d by docker-compose.yml so it runs
--     automatically when the data volume is first created,
--   * also executed by `python db/init_db.py` as a fallback path.
-- ============================================================================

-- Required extensions. PostGIS must exist for any geometry columns.
-- pgcrypto provides gen_random_uuid() on older PostgreSQL builds; PG16+ ships
-- gen_random_uuid() in core, so pgcrypto is best-effort here.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- no-op on PG16+; harmless otherwise

-- ---------------------------------------------------------------------------
-- stations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) UNIQUE NOT NULL,
    geom          GEOMETRY(POINT, 4326) NOT NULL,
    last_aqi      FLOAT,
    last_updated  TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_stations_geom ON stations USING GIST (geom);

-- ---------------------------------------------------------------------------
-- aqi_readings  (unique per station+timestamp)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aqi_readings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id  UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    timestamp   TIMESTAMP WITH TIME ZONE NOT NULL,
    aqi         FLOAT NOT NULL,
    pm25        FLOAT,
    pm10        FLOAT,
    no2         FLOAT,
    so2         FLOAT,
    co          FLOAT,
    o3          FLOAT,
    CONSTRAINT uq_aqi_station_timestamp UNIQUE (station_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_aqi_readings_station_ts
    ON aqi_readings (station_id, timestamp DESC);

-- ---------------------------------------------------------------------------
-- pollution_sources  (Points, LineStrings, or Polygons)
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE pollution_source_type AS ENUM (
        'industrial', 'construction', 'traffic', 'waste_burning'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS pollution_sources (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR(255) NOT NULL,
    type           VARCHAR(50) NOT NULL
                       CHECK (type IN ('industrial','construction','traffic','waste_burning')),
    geom           GEOMETRY(GEOMETRY, 4326) NOT NULL,
    schedule_start TIME,
    schedule_end   TIME,
    near_school    BOOLEAN NOT NULL DEFAULT FALSE,
    near_hospital  BOOLEAN NOT NULL DEFAULT FALSE,
    osm_id         VARCHAR(50) UNIQUE,
    source_origin  VARCHAR(20) NOT NULL DEFAULT 'curated'
                       CHECK (source_origin IN ('curated', 'osm', 'municipal')),
    description    TEXT,
    -- Natural key for idempotent upserts in seed_data.py.
    CONSTRAINT uq_pollution_sources_name_type UNIQUE (name, type)
);
CREATE INDEX IF NOT EXISTS idx_pollution_sources_geom
    ON pollution_sources USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pollution_sources_type
    ON pollution_sources (type);

-- Idempotent migrations for existing databases
ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS osm_id VARCHAR(50) UNIQUE;
ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS source_origin VARCHAR(20) NOT NULL DEFAULT 'curated';
ALTER TABLE pollution_sources ADD COLUMN IF NOT EXISTS description TEXT;

-- ---------------------------------------------------------------------------
-- wind_data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wind_data (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id          UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    timestamp           TIMESTAMP WITH TIME ZONE NOT NULL,
    wind_speed_kmh      FLOAT NOT NULL,
    wind_direction_deg  FLOAT NOT NULL
                            CHECK (wind_direction_deg BETWEEN 0 AND 360),
    temperature         FLOAT,
    weather_snapshot_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_wind_data_station_ts
    ON wind_data (station_id, timestamp DESC);

-- Idempotent migrations for existing databases
ALTER TABLE wind_data ADD COLUMN IF NOT EXISTS weather_snapshot_json JSONB;


-- ---------------------------------------------------------------------------
-- alerts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id            UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    spike_time            TIMESTAMP WITH TIME ZONE NOT NULL,
    aqi_value             FLOAT NOT NULL,
    dominant_pollutant    VARCHAR(10) NOT NULL,
    attribution_details   JSONB NOT NULL,
    enforcement_priority  FLOAT NOT NULL
                              CHECK (enforcement_priority BETWEEN 0.0 AND 1.0),
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_alerts_station_spike
    ON alerts (station_id, spike_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_priority
    ON alerts (enforcement_priority DESC);
-- GIN index for JSONB key/path lookups on attribution_details.
CREATE INDEX IF NOT EXISTS idx_alerts_attr_gin
    ON alerts USING GIN (attribution_details);
