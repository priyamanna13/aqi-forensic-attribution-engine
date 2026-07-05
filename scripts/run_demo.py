"""End-to-end demo: init -> seed(if empty) -> ingest latest -> emit contract block.

Two modes:
  * ``--dry-run`` (default when no DB): in-memory, no PostGIS. Builds the
    scenario reading directly via the mock source + pipeline and prints the
    ``trigger_station`` JSON. Works anywhere.
  * live DB: ``python scripts/run_demo.py`` against PostGIS (via docker-compose).

The emitted block is validated against the data-contract key shape on every run.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Allow running as `python scripts/run_demo.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.contract import build_trigger_station_block
from app.db import get_session, init_db
from app.models import AqiReading, Station, make_point_ewkt
from app.pipeline import PipelineController, upsert_station
from app.sources import get_source
from app.standards import compute_aqi

log = logging.getLogger("demo")


def _scenario_reading(mock_source, station_name: str, local_dt: datetime):
    """Fetch the mock reading at a fixed local time and run it through the pipeline."""
    raw = mock_source._reading_for(station_name, local_dt.astimezone(timezone.utc))
    return raw


def dry_run() -> dict:
    """No-DB path: build the contract block from the mock scenario in memory."""
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    h, m = settings.spike_local_time.split(":")
    spike_local = datetime.now(tz=tz).replace(
        hour=int(h), minute=int(m), second=0, microsecond=0
    )

    mock = get_source(
        "mock",
        target_spike_aqi=settings.spike_aqi,
        spike_local_hour=int(h) + int(m) / 60.0,
    )
    raw = _scenario_reading(mock, settings.station_name, spike_local)

    controller = PipelineController(source=mock)
    reading, report = controller.ingest_reading(raw)  # no session -> not persisted

    # Build an ephemeral Station to drive the contract emitter.
    lon, lat = settings.station_coordinates
    station = Station(
        name=settings.station_name,
        network=settings.station_network,
        city=settings.station_city,
        state=settings.station_state,
        elevation_m=settings.station_elevation_m,
        geom=make_point_ewkt(lon, lat),
    )
    # Station.id is a client-side UUID default; force-set one for the contract.
    import uuid

    station.id = uuid.uuid4()
    # The ephemeral station has EWKT geometry; coordinates() parses it.
    # reading.timestamp is UTC; the contract emitter converts to local.

    block = build_trigger_station_block(station, reading, tz_name=settings.tz)
    return block


def live_run(source_kind: str | None = None) -> dict:
    """DB path: ensure seeded, ingest latest, emit the block."""
    settings = get_settings()
    init_db()
    controller = PipelineController(source=get_source(source_kind or settings.aq_source))

    with get_session() as session:
        station = upsert_station(
            session,
            name=settings.station_name,
            city=settings.station_city,
            state=settings.station_state,
            longitude=settings.station_coordinates[0],
            latitude=settings.station_coordinates[1],
            elevation_m=settings.station_elevation_m,
            network=settings.station_network,
        )
        reading, _ = controller.ingest_latest(station, session)
        if reading is None:
            raise RuntimeError("No reading produced; check source/DB.")
        block = build_trigger_station_block(station, reading, tz_name=settings.tz)
    return block


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    p = argparse.ArgumentParser(description="Run the CPCB pipeline end-to-end")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="no DB; build the contract block from the mock scenario in memory",
    )
    p.add_argument(
        "--source",
        default=None,
        choices=["mock", "live"],
        help="ingestion source (overrides the AQ_SOURCE env var)",
    )
    args = p.parse_args()

    # Source: CLI flag wins, else fall back to the AQ_SOURCE setting.
    source_kind = args.source or settings.aq_source

    # Auto-enable dry-run if there's no DB reachable / it's SQLite-default.
    use_dry = args.dry_run or settings.is_sqlite

    if use_dry:
        log.info("Dry-run mode (no DB)")
        block = dry_run()
    else:
        block = live_run(source_kind=source_kind)

    print(json.dumps({"trigger_station": block}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
