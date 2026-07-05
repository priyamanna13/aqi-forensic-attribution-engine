"""Seed script: idempotent station upsert + historical backfill + scenario spike.

Usage
-----
    python -m app.seed                         # mock source, 7 days, 15-min, AQI 310 spike
    python -m app.seed --days 7 --interval 15  # explicit
    python -m app.seed --source live           # use the real CPCB adapter
    python -m app.seed --reset                 # drop+recreate tables first
    python -m app.seed --dry-run               # no DB; compute & print the 08:30 spike reading

The backfill generates ``days`` of readings at ``interval``-minute cadence ending
*now*, all routed through the same validate -> compute-AQI -> persist path as
live ingestion. The deterministic mock guarantees the morning spike lands at the
target AQI at 08:30 local on each day, matching the data contract scenario.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import get_session, init_db, reset_db
from .pipeline import PipelineController, upsert_station
from .sources import get_source

log = logging.getLogger("seed")


def _parse_hhmm(s: str) -> float:
    h, m = s.split(":")
    return int(h) + int(m) / 60.0


def _spike_dt(spike_hour: float, tz: ZoneInfo) -> datetime:
    """Today's spike instant as a tz-aware UTC datetime (08:30 local by default)."""
    now_local = datetime.now(tz=tz)
    return now_local.replace(
        hour=int(spike_hour),
        minute=int(round((spike_hour % 1) * 60)),
        second=0,
        microsecond=0,
    ).astimezone(timezone.utc)


def dry_run(
    spike_aqi: int = 310,
    spike_time: str = "08:30",
    station_name: str | None = None,
) -> dict:
    """No-DB path: compute the spike reading via the mock + pipeline, return a summary.

    Nothing is persisted. Used by ``--dry-run`` to verify the scenario numbers
    (AQI 310 / Very Poor / PM10-dominant at 08:30) without a database.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    spike_hour = _parse_hhmm(spike_time)
    name = station_name or settings.station_name

    mock = get_source(
        "mock", target_spike_aqi=spike_aqi, spike_local_hour=spike_hour
    )
    controller = PipelineController(source=mock)

    raw = mock._reading_for(name, _spike_dt(spike_hour, tz))
    reading, report = controller.ingest_reading(raw)  # no session -> not persisted

    if reading is None:
        return {
            "station": name,
            "source": "mock",
            "mode": "dry-run",
            "valid": False,
            "report": report.to_log(),
        }

    sp = reading.to_sub_pollutants()
    return {
        "station": name,
        "source": "mock",
        "mode": "dry-run",
        "valid": True,
        "spike_at": _spike_dt(spike_hour, tz).astimezone(tz).isoformat(),
        "spike_aqi": reading.total_aqi,
        "spike_category": reading.aqi_category,
        "spike_dominant": reading.dominant_pollutant,
        "pm10": sp["pm10"]["value"],
        "co_mgm3": sp["co"]["value"],
    }


def run_seed(
    source_kind: str = "mock",
    days: int = 7,
    interval_minutes: int = 15,
    spike_aqi: int = 310,
    spike_time: str = "08:30",
    reset: bool = False,
) -> dict:
    """Execute the seed against the database. Returns a small summary dict."""
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    spike_hour = _parse_hhmm(spike_time)

    if source_kind == "mock":
        source = get_source(
            "mock", target_spike_aqi=spike_aqi, spike_local_hour=spike_hour
        )
    else:
        source = get_source(source_kind)

    if reset:
        log.info("Resetting database (--reset)")
        reset_db()
    else:
        init_db()

    controller = PipelineController(source=source)

    now_local = datetime.now(tz=tz).replace(second=0, microsecond=0)
    # Align "now" to the interval grid.
    now_local = now_local.replace(
        minute=(now_local.minute // interval_minutes) * interval_minutes
    )
    start = now_local - timedelta(days=days)

    summary: dict = {
        "station": settings.station_name,
        "source": source_kind,
        "days": days,
        "interval_min": interval_minutes,
        "window": [start.isoformat(), now_local.isoformat()],
    }

    from sqlalchemy import select

    from .models import AqiReading

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
        ingested, rejected = controller.ingest_range(station, session, start, now_local)
        summary["ingested"] = ingested
        summary["rejected"] = rejected

        # Find the spike reading at the target local time on the most recent day.
        spike_utc = _spike_dt(spike_hour, tz)
        spike_reading = session.execute(
            select(AqiReading)
            .where(
                AqiReading.station_id == station.id,
                AqiReading.timestamp == spike_utc,
            )
            .limit(1)
        ).scalar_one_or_none()
        if spike_reading is not None:
            summary["spike_at"] = spike_utc.astimezone(tz).isoformat()
            summary["spike_aqi"] = spike_reading.total_aqi
            summary["spike_category"] = spike_reading.aqi_category
            summary["spike_dominant"] = spike_reading.dominant_pollutant

    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    p = argparse.ArgumentParser(description="Seed CPCB stations + historical backfill")
    p.add_argument("--source", default=settings.aq_source, choices=["mock", "live"])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--interval", type=int, default=15, help="minutes")
    p.add_argument("--spike-aqi", type=int, default=settings.spike_aqi)
    p.add_argument("--spike-time", default=settings.spike_local_time, help="HH:MM local")
    p.add_argument("--reset", action="store_true", help="drop+recreate all tables")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="no DB; compute & print the 08:30 spike reading only",
    )
    args = p.parse_args()

    if args.dry_run:
        summary = dry_run(spike_aqi=args.spike_aqi, spike_time=args.spike_time)
    else:
        summary = run_seed(
            source_kind=args.source,
            days=args.days,
            interval_minutes=args.interval,
            spike_aqi=args.spike_aqi,
            spike_time=args.spike_time,
            reset=args.reset,
        )

    print("\n=== Seed summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
