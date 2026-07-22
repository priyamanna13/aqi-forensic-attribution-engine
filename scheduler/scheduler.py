"""Background job scheduler for live data pipelines.

Runs as a separate process (or Docker service) that triggers:
  - CPCB polling every 15 minutes
  - OWM weather sync every 10 minutes
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import os
import time
from typing import Optional
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from db.connection import ping
from pipeline.cpcb_poller import CPCBPoller
from pipeline.weather_sync import WeatherSyncService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("aqi.scheduler")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "city_config.yml"


def cpcb_poll_job() -> None:
    log.info("Starting scheduled CPCB CAAQMS poll...")
    try:
        poller = CPCBPoller()
        payloads = poller.poll_all_stations()
        log.info("CPCB poll complete. Spikes triggered: %d", len(payloads))
    except Exception as exc:
        log.error("Error during CPCB poll job: %s", exc, exc_info=True)


def weather_sync_job() -> None:
    log.info("Starting scheduled OWM weather sync...")
    try:
        service = WeatherSyncService()
        count = service.sync_all_stations()
        log.info("OWM weather sync complete. Stations updated: %d", count)
    except Exception as exc:
        log.error("Error during weather sync job: %s", exc, exc_info=True)


def overpass_refresh_job() -> None:
    log.info("Starting scheduled Overpass source discovery...")
    try:
        from pipeline.overpass_client import OverpassSourceDiscovery
        from db.connection import SessionLocal
        with SessionLocal() as session:
            count = OverpassSourceDiscovery().discover_sources(session)
            log.info("Overpass source discovery complete. Sources discovered/updated: %d", count)
    except ImportError:
        log.warning("pipeline.overpass_client not found (Person 2 module not merged yet). Skipping Overpass job.")
    except Exception as exc:
        log.error("Error during Overpass refresh job: %s", exc, exc_info=True)


def create_scheduler(config_path: Optional[Path] = None) -> BlockingScheduler:
    path = config_path or Path(os.getenv("CITY_CONFIG", str(DEFAULT_CONFIG_PATH)))
    if not path.exists():
        path = DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cpcb_interval = config.get("polling", {}).get("cpcb_interval_minutes", 15)
    owm_interval = config.get("polling", {}).get("owm_interval_minutes", 10)
    overpass_hours = config.get("polling", {}).get("overpass_refresh_hours", 6)

    scheduler = BlockingScheduler()

    scheduler.add_job(
        cpcb_poll_job,
        "interval",
        minutes=cpcb_interval,
        id="cpcb_poller",
        misfire_grace_time=60,
    )

    scheduler.add_job(
        weather_sync_job,
        "interval",
        minutes=owm_interval,
        id="weather_sync",
        misfire_grace_time=60,
    )

    scheduler.add_job(
        overpass_refresh_job,
        "interval",
        hours=overpass_hours,
        id="overpass_refresh",
        misfire_grace_time=300,
    )

    return scheduler


def main() -> int:
    log.info("=" * 60)
    log.info("AQI Live Pipeline Scheduler — Starting up...")
    log.info("=" * 60)

    # Wait for DB to be ready
    retries = 12
    while retries > 0:
        if ping():
            log.info("Database reachable and ready.")
            break
        log.warning("Database not reachable yet. Waiting 5s... (%d retries left)", retries)
        time.sleep(5)
        retries -= 1
    else:
        log.error("Database unreachable after 60s. Exiting scheduler.")
        return 1

    # Apply schema migrations automatically on startup
    log.info("Applying database schema migrations...")
    try:
        from db.init_db import _execute_schema_sql
        _execute_schema_sql()
        log.info("Schema migrations applied successfully.")
    except Exception as exc:
        log.error("Failed while applying schema migrations: %s", exc)

    # Seed the database automatically on startup
    log.info("Seeding database with stations and sources...")
    try:
        from db.seed_data import main as seed_main
        seed_main()
        log.info("Database seeded successfully.")
    except Exception as exc:
        log.error("Failed while seeding database: %s", exc)

    # Run initial sync immediately on startup
    log.info("Running initial startup data sync...")
    weather_sync_job()
    cpcb_poll_job()

    scheduler = create_scheduler()
    log.info("Scheduler configured. Entering blocking loop...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler shutting down cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
