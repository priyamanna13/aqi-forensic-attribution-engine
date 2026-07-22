"""Mock CPCB telemetry poller / replay driver (Task 2, Part 3).

Simulates the inbound side of the pipeline: read a sequence of telemetry
readings for a station (from a JSON replay file or generated inline), persist
each one to ``aqi_readings``, and hand it to the ``SpikeDetector``. When a
spike fires, the returned payload is collected (and optionally dumped to disk).

This is the wiring between the detector and the database; the detector itself
stays pure and DB-agnostic.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db.connection import SessionLocal, get_session, ping
from db.models import Alert, AqiReading, Station
from .spike_detector import SpikeDetector
from .attribution import run_attribution
from .naaqs import POLLUTANT_KEYS
from geoalchemy2 import functions as gfunc
from sqlalchemy import select as _sel

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY = _PROJECT_ROOT / "data" / "replay_shivajinagar.json"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def _parse_ts(raw: Any) -> datetime:
    """Parse an ISO timestamp into an aware datetime."""
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw))


def persist_reading(session: Session, station_id: str, reading: dict[str, Any]) -> None:
    """Upsert one reading into ``aqi_readings`` (unique on station+timestamp).

    Uses ON CONFLICT (station_id, timestamp) DO UPDATE so a replay can be
    re-run safely.
    """
    ts = _parse_ts(reading["timestamp"])
    row = {
        "station_id": station_id,
        "timestamp": ts,
        "aqi": float(reading["aqi"]),
        "pm25": reading.get("pm25"),
        "pm10": reading.get("pm10"),
        "no2": reading.get("no2"),
        "so2": reading.get("so2"),
        "co": reading.get("co"),
        "o3": reading.get("o3"),
    }
    stmt = (
        pg_insert(AqiReading)
        .values(**row)
        .on_conflict_do_update(
            constraint="uq_aqi_station_timestamp",
            set_={
                "aqi": row["aqi"],
                "pm25": row["pm25"],
                "pm10": row["pm10"],
                "no2": row["no2"],
                "so2": row["so2"],
                "co": row["co"],
                "o3": row["o3"],
            },
        )
    )
    session.execute(stmt)


def _update_station_summary(session: Session, station_id: str, reading: dict[str, Any]) -> None:
    """Keep ``stations.last_aqi`` / ``last_updated`` in sync (cheap convenience)."""
    station = session.get(Station, station_id)
    if station is None:
        return
    station.last_aqi = float(reading["aqi"])
    station.last_updated = _parse_ts(reading["timestamp"])


# --------------------------------------------------------------------------
# Replay file loading
# --------------------------------------------------------------------------
def load_replay_file(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(station_name, [readings...])`` from a replay JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    station_name = data["station"]
    sequence = data["sequence"]
    return station_name, sequence


def _resolve_station_id(session: Session, station_name: str) -> str:
    stmt = select(Station.id).where(Station.name == station_name)
    station_id = session.execute(stmt).scalar()
    if station_id is None:
        raise ValueError(
            f"Station {station_name!r} not found in DB. Run `python db/seed_data.py` first."
        )
    return str(station_id)


# --------------------------------------------------------------------------
# Public driver
# --------------------------------------------------------------------------
def replay_sequence(
    station_name: str,
    readings: Iterable[dict[str, Any]],
    detector: Optional[SpikeDetector] = None,
    *,
    session: Optional[Session] = None,
) -> list[dict[str, Any]]:
    """Run a sequence of readings through the detector.

    Each reading is persisted, then checked. Returns the list of spike
    payloads that fired (one per triggering reading). Owns its session unless
    one is passed in (useful for tests / transactional rollback).
    """
    detector = detector or SpikeDetector()
    payloads: list[dict[str, Any]] = []

    own_session = session is None
    if own_session:
        session = SessionLocal()
    try:
        station_id = _resolve_station_id(session, station_name)
        for reading in readings:
            persist_reading(session, station_id, reading)
            _update_station_summary(session, station_id, reading)
            # Flush so the just-written reading is visible to the detector's
            # "previous reading" lookup on the NEXT iteration.
            session.flush()
            payload = detector.check_and_trigger_spike(
                session, station_id, {**reading, "timestamp": _parse_ts(reading["timestamp"])}
            )
            if payload is not None:
                # ---- merge with attribution lower-half and persist alert ----
                try:
                    from geoalchemy2 import functions as gfunc
                    lon_q, lat_q = session.execute(
                        _sel(gfunc.ST_X(session.get(Station, station_id).geom),
                             gfunc.ST_Y(session.get(Station, station_id).geom))
                    ).one()
                    sta_lon, sta_lat = float(lon_q), float(lat_q)

                    weather = payload["weather_snapshot"]
                    fp = payload["trigger_station"]["reading"]["chemical_fingerprint"]
                    dom = payload["trigger_station"]["reading"].get("dominant_pollutant", "PM10")

                    lower = run_attribution(
                        session=session,
                        station_lon=sta_lon,
                        station_lat=sta_lat,
                        station_name=payload["trigger_station"]["name"],
                        spike_ts=reading["timestamp"] if isinstance(reading["timestamp"], __import__('datetime').datetime)
                                 else _parse_ts(reading["timestamp"]),
                        aqi_value=float(reading["aqi"]),
                        dominant_pollutant=dom,
                        signature_class=fp.get("signature_class", "mixed"),
                        wind_direction_deg=float(weather["wind_direction_deg"]),
                        wind_speed_kmh=float(weather["wind_speed_kmh"]),
                        pasquill_class=weather["atmospheric_stability"]["pasquill_class"],
                    )

                    full_payload = {**payload, **lower}

                    ai = full_payload.get("actionable_intelligence", {})
                    ts_val = _parse_ts(full_payload["trigger_station"]["reading"]["timestamp"])
                    alert = Alert(
                        station_id=station_id,
                        spike_time=ts_val,
                        aqi_value=float(full_payload["trigger_station"]["reading"]["total_aqi"]),
                        dominant_pollutant=dom,
                        attribution_details=full_payload,
                        enforcement_priority=float(ai.get("enforcement_priority", 0.5)),
                    )
                    session.add(alert)
                    payloads.append(full_payload)
                except Exception as attr_err:
                    log.warning("Attribution failed, storing top-half only: %s", attr_err)
                    payloads.append(payload)
        if own_session:
            session.commit()
    except Exception:
        if own_session:
            session.rollback()
        raise
    finally:
        if own_session:
            session.close()
    return payloads


def replay_from_file(
    path: Path = DEFAULT_REPLAY,
    detector: Optional[SpikeDetector] = None,
) -> list[dict[str, Any]]:
    """Convenience: load a replay file and run it. Returns fired payloads."""
    station_name, sequence = load_replay_file(path)
    return replay_sequence(station_name, sequence, detector=detector)


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------
def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Replay mock CPCB telemetry through the spike detector.")
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_REPLAY,
        help=f"Replay JSON file (default: {DEFAULT_REPLAY})",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Optional path to write the fired spike payloads as JSON.",
    )
    args = parser.parse_args()

    if not ping():
        print("Database not reachable. Run `docker compose up -d` and `python db/init_db.py`.")
        return 1

    payloads = replay_from_file(args.file)
    print(f"\nReplay complete: {len(payloads)} spike(s) detected.")
    for i, p in enumerate(payloads, 1):
        ts = p["trigger_station"]["reading"]["timestamp"]
        aqi = p["trigger_station"]["reading"]["total_aqi"]
        sev = p["event_severity"]
        dom = p["trigger_station"]["reading"]["dominant_pollutant"]
        print(f"  [{i}] {ts}  AQI={aqi} ({sev})  dominant={dom}")

    if args.out is not None:
        args.out.write_text(json.dumps(payloads, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {len(payloads)} payload(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
