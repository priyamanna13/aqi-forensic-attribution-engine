# CPCB Data Pipeline & PostGIS Schema — Person 2, Task 1

> **Air Quality Attribution Engine** — Phase 1: Data ingestion foundation that produces the `trigger_station` block of the immutable JSON data contract.

## Quick Start (no database)

```bash
pip install -r requirements.txt
python scripts/run_demo.py --dry-run    # prints the contract trigger_station JSON
python -m pytest tests/ -v              # 53 tests, no PostGIS needed
```

## Quick Start (with PostGIS)

```bash
docker compose up -d db
cp .env.example .env                     # defaults already point at docker PostGIS
python -m app.seed --reset              # station + 7-day backfill + AQI-310 spike
python scripts/run_demo.py              # live: ingest latest → emit contract block
```

## Architecture

```
app/
├── config.py          pydantic-settings: DB URL, source, station defaults
├── db.py              engine, sessions, init_db (+ CREATE EXTENSION postgis)
├── models.py          Station (PostGIS Geometry, GIST) + AqiReading
├── standards.py       NAAQS limits + CPCB NAQI sub-index math (AQI > 500)
├── validators.py      CPCB sentinel/unit/anomaly screening → ValidationReport
├── sources/
│   ├── base.py        SourceAdapter ABC + RawReading
│   ├── mock.py        Deterministic mock (default, offline)
│   └── cpcb.py        Live CPCB CAAQMS adapter (--source live)
├── pipeline.py        ingest → validate → compute AQI → persist
├── contract.py         build_trigger_station_block() → exact contract shape
└── seed.py             CLI: station upsert + 7d × 15-min backfill + spike
scripts/
└── run_demo.py         --dry-run (no DB) or live against PostGIS
tests/
├── test_standards.py   NAAQS + AQI math (pinned to data contract sample)
├── test_validators.py  sentinel / unit / edge-case handling
├── test_pipeline.py    contract shape + DB round-trip
└── test_seed.py        mock determinism + spike accuracy
```

## Contract Mapping (trigger_station block)

| Contract key | Source | Notes |
|---|---|---|
| `id` | `Station.id` (UUID) | |
| `name` | config `station_name` | "Shivajinagar" |
| `network` | `Station.network` | "CPCB_CAAQMS" |
| `city` / `state` | config defaults | "Pune" / "Maharashtra" |
| `coordinates` | `Station.coordinates()` → `[lon, lat]` | GeoJSON EPSG:4326 |
| `elevation_m` | config default | 560 |
| `reading.timestamp` | ISO-8601 local offset | e.g. `2026-06-25T08:30:00+05:30` |
| `reading.total_aqi` | `compute_aqi()` → max(sub-indices) | CPCB NAQI |
| `reading.dominant_pollutant` | highest sub-index pollutant | |
| `sub_pollutants.{p}.exceedance_factor` | `round(conc / NAAQS, 2)` | ROUND_HALF_UP |
| `sub_pollutants.{p}.unit` | CO: `mg/m³`; others: `µg/m³` | |
| `chemical_fingerprint.signature_class` | heuristic: pm25/pm10 + no2/so2 ratios | |
| `chemical_fingerprint.notes` | generated from ratios | |

## ⚠️ AQI Note (internal consistency)

The data contract sample's `trigger_station.reading` lists **total_aqi: 310** with **PM10: 387.2 µg/m³**. Under strict CPCB NAQI breakpoints, PM10=387.2 computes to **AQI ≈ 346**, not 310. These two numbers are internally inconsistent.

This implementation chose **internal mathematical consistency**: the CPCB NAQI formula is the single source of truth, and the mock/seed tunes PM10 to **≈358 µg/m³** — the exact concentration that yields AQI 310 via the real CPCB sub-index table. All other contract fields (coordinates, units, exceedance factors, timestamp, category, fingerprint class) match the sample precisely.

## NAAQS Thresholds

| Pollutant | Limit | Unit | Averaging |
|---|---|---|---|
| PM2.5 | 60 | µg/m³ | 24hr |
| PM10 | 100 | µg/m³ | 24hr |
| NO₂ | 80 | µg/m³ | 24hr |
| SO₂ | 80 | µg/m³ | 24hr |
| CO | 4 | mg/m³ | 8hr |
| O₃ | 100 | µg/m³ | 8hr |

## Source Adapter Pattern

The ingestion pipeline never touches CPCB directly — it goes through a `SourceAdapter` ABC. The mock runs by default; the live adapter is activated via:

```bash
# CLI (--source works on both seed.py and run_demo.py)
python -m app.seed --source live
python scripts/run_demo.py --source live

# Environment variable (alternative)
AQ_SOURCE=live python scripts/run_demo.py
```

Validation logic is identical on both paths.

## Key CLI Commands

```bash
# Seed the database (mock, 7 days, 15-min cadence, AQI-310 spike at 08:30)
python -m app.seed --days 7 --interval 15 --spike-aqi 310 --spike-time 08:30

# Seed with reset (drop + recreate tables)
python -m app.seed --reset

# Dry-run seed (no DB; verify the 08:30 spike numbers only)
DATABASE_URL="sqlite:///:memory:" python -m app.seed --dry-run

# Dry-run demo (no DB, prints contract JSON)
DATABASE_URL="sqlite:///:memory:" python scripts/run_demo.py --dry-run

# Run live ingestion
python scripts/run_demo.py
```
