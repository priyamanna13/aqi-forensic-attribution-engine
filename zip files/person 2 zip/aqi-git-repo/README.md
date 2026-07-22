# Air Quality Intelligence — Backend Database (Task 1)

PostgreSQL + PostGIS backend for the **AI-Powered Urban Air Quality Intelligence**
platform. Target city: **Pune, India**.

This task (Days 1–2) sets up the database, schema, and seed data for Pune.
Later tasks will add AQI ingestion, wind data, spike detection, attribution,
and advisories on top of this foundation.

---

## Stack

| Layer        | Choice                                            |
| ------------ | ------------------------------------------------- |
| Database     | PostgreSQL 16 + PostGIS 3.4 (via Docker)          |
| ORM          | SQLAlchemy 2.x + GeoAlchemy2                       |
| Driver       | psycopg2-binary                                    |
| Primary keys | UUID (`gen_random_uuid()`)                         |
| SRID         | 4326 (WGS 84) — every spatial column               |

---

## Project layout

```
aqi/
├── docker-compose.yml      # Postgres 16 + PostGIS service
├── requirements.txt        # Python deps
├── .env.example            # connection vars + OWM key (copy to .env)
├── .gitignore
├── README.md               # this file
├── data_contract_sample.json  # authoritative payload contract (Task 2+)
├── db/
│   ├── __init__.py
│   ├── config.py           # env-driven settings + URL builder
│   ├── connection.py       # engine, SessionLocal, get_session(), ping()
│   ├── models.py           # ORM models (Station, AqiReading, ...)
│   ├── schema.sql          # authoritative idempotent DDL
│   ├── init_db.py          # creates extension + tables (runs schema.sql)
│   ├── geo_utils.py        # WKT builders + pollution_sources GeoJSON serializer
│   └── seed_data.py        # seeds 4 Pune stations + 12 pollution sources
├── pipeline/               # ── Task 2: spike detection ──
│   ├── __init__.py
│   ├── naaqs.py            # Indian NAAQS limits, exceedance factors, AQI bands
│   ├── pasquill.py         # Pasquill-Gifford stability + wind-cardinal helper
│   ├── station_meta.py     # network/city/state/elevation lookup (contract fields)
│   ├── weather_client.py   # OpenWeatherMap client + offline cache (Improvement #8)
│   ├── spike_detector.py   # SpikeDetector + contract-conformant payload builder
│   └── poller.py           # mock CPCB telemetry replay driver
├── data/
│   └── replay_shivajinagar.json  # 4-step mock telemetry (AQI 90 → 310 spike)
└── scripts/
    ├── verify_spatial.py   # Task 1: ST_DWithin(<3km) demo with distances
    ├── test_geojson.py     # Task 1: offline GeoJSON serializer self-test
    ├── test_spike_detection.py  # Task 2: offline spike-detection + contract conformance
    └── verify_live_payload.py   # Task 2: live payload contract conformance check
```

---

## Setup

### Prerequisites

- **Docker** (Desktop on Windows, or Engine on Linux). Used to run Postgres+PostGIS.
- **Python 3.11+** (developed on 3.11.9).

### Steps

From the project root (`aqi/`):

```bat
:: 1. Configure connection vars (defaults already match docker-compose.yml)
copy .env.example .env

:: 2. Start Postgres + PostGIS
docker compose up -d

:: 3. Install Python deps (into your current Python)
python -m pip install -r requirements.txt

:: 4. Initialize schema (extensions, tables, indexes) — idempotent
python db/init_db.py

:: 5. Seed Pune stations + pollution sources — idempotent
python db/seed_data.py

:: 6. Verify spatial queries work
python scripts/verify_spatial.py

:: 7. (Optional) Offline GeoJSON serializer self-test — no DB needed
python scripts/test_geojson.py
```

> Replace `copy` with `cp` on Linux/macOS.

### Stopping / resetting the database

```bat
docker compose down       :: stop containers, keep data
docker compose down -v    :: stop AND delete the data volume (full reset)
```

---

## Schema overview

All geometry uses **SRID 4326**. Full DDL: [`db/schema.sql`](db/schema.sql).

| Table              | Purpose                                                | Spatial column               |
| ------------------ | ------------------------------------------------------ | ----------------------------- |
| `stations`         | AQ monitoring stations (4 in Pune)                     | `POINT` + GIST                |
| `aqi_readings`     | Per-station AQI + pollutant readings                   | — (unique on station+time)    |
| `pollution_sources`| Industrial/construction/traffic/waste-burning emitters | `GEOMETRY` (Pt/Line/Poly)+GIST|
| `wind_data`        | Wind speed/direction + temperature per station         | —                             |
| `alerts`           | AQI spikes + attribution analysis (JSONB) + priority   | —                             |

Key constraints:
- `aqi_readings` — `UNIQUE (station_id, timestamp)`
- `pollution_sources.type` — `CHECK IN ('industrial','construction','traffic','waste_burning')`
- `wind_data.wind_direction_deg` — `CHECK BETWEEN 0 AND 360`
- `alerts.enforcement_priority` — `CHECK BETWEEN 0.0 AND 1.0`
- All FKs to `stations` are `ON DELETE CASCADE`.

---

## Seeded Pune data

### Stations (exact coords from the task spec)

| Station       | Coordinates (lon, lat)        |
| ------------- | ----------------------------- |
| Shivajinagar  | `POINT(73.8440 18.5308)`      |
| Hadapsar      | `POINT(73.9268 18.5089)`      |
| Katraj        | `POINT(73.8567 18.4575)`      |
| Karve Road    | `POINT(73.8290 18.5074)`      |

### Pollution sources (12 total, all within ~5 km of a station)

| Type           | Count | Geometry    | Schedule                         | Notes                          |
| -------------- | ----- | ----------- | -------------------------------- | ------------------------------ |
| construction   | 3     | Polygon     | 09:00–18:00                      | 1 flagged `near_school`        |
| traffic        | 4     | LineString  | 08:00–10:00 (morning peak)       | 1 flagged `near_hospital`      |
| industrial     | 3     | Polygon     | 00:00–23:59:59 (24/7)            | 1 flagged `near_hospital`      |
| waste_burning  | 2     | Point       | 05:00–07:00 or 20:00–23:00       | 1 flagged `near_school`        |

> Traffic corridors also have an evening window (17:00–20:00). The seed stores
> the primary morning window per row; splitting into separate per-window rows
> is a documented future enhancement.

Seeding is **idempotent** — stations upsert by `name`, sources by `(name, type)`.

---

## GeoJSON serialization (helper API)

[`db/geo_utils.py`](db/geo_utils.py) exposes:

```python
from db.geo_utils import source_to_geojson, sources_to_geojson

# Single source -> GeoJSON Feature string
source_to_geojson(source)        # accepts ORM obj, dict, or SQLAlchemy Row

# Many sources -> FeatureCollection string
sources_to_geojson([source1, source2, ...])
```

Accepts geometries as: GeoJSON dict, `ST_AsGeoJSON` text, WKB/EWKB bytes, or
shapely geometry. Run `python scripts/test_geojson.py` to validate it offline.

---

## Troubleshooting

**`cannot reach database`** — `docker compose up -d` not running, or port 5432
already in use. Check `docker compose ps` and `docker compose logs db`. Change
`POSTGRES_PORT` in `.env` and the compose `ports:` mapping if 5432 is taken.

**`PostGIS extension is missing`** — the image should enable it automatically;
if a stale volume exists, reset with `docker compose down -v` then `up -d`.

**`psycopg2` install fails on Windows** — ensure you're on `psycopg2-binary`
(not `psycopg2`) per `requirements.txt`; the binary wheel needs no compiler.

**Re-seed after schema changes** — both `init_db.py` and `seed_data.py` are
idempotent, so just re-run them. For a clean slate: `docker compose down -v`
and start over.

---

# Task 2 — Spike Detection Engine (Days 3–4)

Detects AQI spikes from incoming telemetry, fetches concurrent weather
(OpenWeatherMap with offline caching), and emits an event payload that
**strictly conforms** to the top half of
[`data_contract_sample.json`](data_contract_sample.json)
(`event_id` → end of `weather_snapshot`).

## Detection algorithm

`pipeline/spike_detector.py` → `SpikeDetector.check_and_trigger_spike(...)` runs
two independent rules and fires when **either** trips:

- **Rule A (threshold)** — total AQI ≥ 150, *or* any pollutant's
  exceedance factor > 1.5.
- **Rule B (rate-of-change)** — AQI rose by ≥ 50 within a 1-hour window,
  proportionally scaled by the actual time gap (faster jumps need a smaller
  absolute delta to fire), with a 25-AQI floor to suppress noise.

Per-reading processing:

1. **NAAQS math** — `exceedance_factor = value / limit` (2 dp) using Indian
   NAAQS limits (pm25 60, pm10 100, no2/so2 80, co 4.0 mg/m³, o3 100).
2. **Dominant pollutant** — highest exceedance factor (reported uppercase, e.g. `"PM10"`).
3. **AQI category** — India NAQI bands (Good / Satisfactory / Moderate / Poor / Very Poor / Severe).
4. **Event severity** — `critical` (≥300) / `high` (≥200) / `warning` (≥100) / `low`.
5. **Chemical fingerprint** — pm25/pm10 & no2/so2 ratios (3 dp) + signature class:
   `crustal_dominant`, `combustion_vehicular`, `industrial_sulfur`,
   `biomass_burning`, or `mixed`.

## Weather & API integrations

`pipeline/weather_client.py` (`WeatherClient`):

- Fetches current weather from OpenWeatherMap (`/data/2.5/weather`) via `requests`.
- **Resilience caching (Improvement #8):** every successful response is cached
  to `api_cache/<key>.json`. On network failure, timeout, or HTTP 429, the last
  good cached snapshot is returned silently — the pipeline never raises for
  missing weather.
- Converts wind m/s → km/h (`* 3.6`); maps degrees → 16-point cardinal
  (`290` → `"WNW"`).
- Derives the contract's `weather_snapshot` fields: temperature (K→C), humidity,
  pressure, cloud cover (→ oktas), 1h precipitation, visibility (m→km), and a
  heuristic mixing-layer height.

`pipeline/pasquill.py` estimates the **Pasquill-Gifford stability class** from
wind speed and day/night, with full A–F dispersion coefficients (sigma_y/sigma_z).

## Telemetry replay

`pipeline/poller.py` simulates the inbound side: load
`data/replay_shivajinagar.json`, persist each reading to `aqi_readings`
(idempotent upsert on `station_id,timestamp`), and feed it to the detector.
Fired payloads are collected and optionally dumped to disk.

```bat
:: with DB running + seeded:
python -m pipeline.poller --out data/spike_events.json
```

## Verification (offline, no DB/network)

```bat
python scripts/test_spike_detection.py
```

Asserts:

1. NAAQS math matches the contract's worked example (pm25→2.48, pm10→3.87, …).
2. Detection fires **exactly once**, at the 08:30 IST spike.
3. Fingerprint classifies as `crustal_dominant` (ratios 0.384 / 1.321).
4. The emitted payload's `trigger_station` and `weather_snapshot` sections match
   `data_contract_sample.json` **exactly** — keys, nesting, and value types are
   derived from the contract itself and asserted structurally.

## Verification (live, against the DB)

After the database is up, seeded, and deps installed, run the full pipeline
end-to-end and re-check contract conformance on a **real** payload:

```bat
:: 1. Replay mock telemetry through the detector (writes aqi_readings + emits payload)
python -m pipeline.poller --out data/live_spike_payloads.json

:: 2. Structurally verify the live payload against the contract
python scripts/verify_live_payload.py
```

`verify_live_payload.py` runs the same key/nesting/type conformance check as
the offline test, but against the payload produced by the live DB + weather
path. Expected output: `RESULT: live payload conforms to data_contract_sample.json`.

## Notes

- **OpenWeatherMap key:** add `OWM_API_KEY=` to `.env`. The pipeline degrades
  gracefully to the cache (or a calm fallback) when the key is missing or the
  network is down, so all tests run fully offline.
- **Contract stability-class caveat:** the data-contract *sample* illustrates
  `pasquill_class: "D"` for its 14.5 km/h daytime wind, but the task's own
  wind-band rules put 5–15 km/h daytime at class `B`. The detector follows the
  **task's stated rules**; structural conformance to the contract (keys/types)
  is what Part 4 verifies and is what passes.
- **Schema untouched:** `trigger_station` fields not in the Task 1 `stations`
  table (`network`/`city`/`state`/`elevation_m`) are sourced from
  `pipeline/station_meta.py`; coordinates come from the station's PostGIS
  geometry.
