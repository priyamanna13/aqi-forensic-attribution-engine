"""Scheduled OWM weather synchronization.

Fetches current weather for each station every 10 minutes and persists
to the wind_data table. The attribution funnel reads from wind_data
instead of making ad-hoc OWM calls during spike processing.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.connection import SessionLocal
from db.models import Station, WindData
from pipeline.poller import _resolve_station_id
from pipeline.weather_client import WeatherClient

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "city_config.yml"


class WeatherSyncService:
    """Scheduled OpenWeatherMap synchronization service."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        path = config_path or Path(os.getenv("CITY_CONFIG", str(DEFAULT_CONFIG_PATH)))
        if not path.exists():
            path = DEFAULT_CONFIG_PATH
        with open(path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.stations = self.config.get("stations", [])
        self.client = WeatherClient()

    def sync_all_stations(self, session: Optional[Session] = None) -> int:
        """Fetch and persist current weather for all stations in city_config."""
        own_session = session is None
        if own_session:
            session = SessionLocal()

        count = 0
        try:
            for st_cfg in self.stations:
                st_name = st_cfg["name"]
                try:
                    st_id = _resolve_station_id(session, st_name)
                except ValueError as exc:
                    log.warning("Skipping weather sync for station %s: %s", st_name, exc)
                    continue

                lat = float(st_cfg["lat"])
                lon = float(st_cfg["lon"])

                try:
                    snapshot = self.client.get_weather(lat=lat, lon=lon)
                except Exception as exc:
                    log.error("WeatherClient failed for %s: %s", st_name, exc)
                    continue

                IST = timezone(timedelta(hours=5, minutes=30))
                try:
                    obs_ts = datetime.fromisoformat(snapshot.observed_at)
                    if obs_ts.tzinfo is None:
                        obs_ts = obs_ts.replace(tzinfo=IST)
                except Exception:
                    obs_ts = datetime.now(IST)

                wind_entry = WindData(
                    station_id=st_id,
                    timestamp=obs_ts,
                    wind_speed_kmh=float(snapshot.wind_speed_kmh),
                    wind_direction_deg=float(snapshot.wind_direction_deg),
                    temperature=float(snapshot.temperature_c),
                    weather_snapshot_json=snapshot.to_dict(),
                )
                session.add(wind_entry)
                count += 1

            if own_session:
                session.commit()
            log.info("Weather sync complete: %d station(s) updated.", count)
        except Exception:
            if own_session:
                session.rollback()
            raise
        finally:
            if own_session:
                session.close()

        return count
