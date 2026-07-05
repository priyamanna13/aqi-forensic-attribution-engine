"""Live CPCB CAAQMS data ingestion pipeline with synthetic fallback.

Polls the data.gov.in CPCB endpoint every 15 minutes for the 4 Pune
stations defined in city_config.yml. Each response is validated,
normalized to the internal schema, persisted to aqi_readings, and
handed to the SpikeDetector for real-time event triggering.

If CPCB_API_KEY is omitted or the data.gov.in service is unreachable,
the poller gracefully switches to the Synthetic Telemetry Engine, generating
realistic atmospheric fluctuations so live demo environments and local Docker
setups work continuously out of the box.
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import requests
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.connection import SessionLocal
from db.models import Alert, AqiReading, Station, WindData
from pipeline.attribution import run_attribution
from pipeline.naaqs import POLLUTANT_KEYS
from pipeline.poller import _resolve_station_id, _update_station_summary, persist_reading
from pipeline.spike_detector import SpikeDetector
from pipeline.validators import validate_aqi, validate_pollutant_reading

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "city_config.yml"


class CPCBPoller:
    """Live CPCB CAAQMS poller and synthetic fallback engine."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        path = config_path or Path(os.getenv("CITY_CONFIG", str(DEFAULT_CONFIG_PATH)))
        if not path.exists():
            path = DEFAULT_CONFIG_PATH
        with open(path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.stations = self.config.get("stations", [])
        self.api_key = (os.getenv("CPCB_API_KEY") or "").strip()
        self.timeout = float(os.getenv("CPCB_API_TIMEOUT", "10"))
        self._session = requests.Session()

    def fetch_station_reading(self, station_cfg: dict[str, Any], session: Session) -> dict[str, Any]:
        """GET latest reading for a station, falling back to synthetic data if needed."""
        station_name = station_cfg["name"]
        cpcb_id = station_cfg.get("cpcb_station_id", "")

        if self.api_key and cpcb_id:
            try:
                reading = self._fetch_live_cpcb(cpcb_id, station_name)
                if reading:
                    return reading
            except Exception as exc:
                log.warning("Live CPCB fetch failed for %s (%s); switching to synthetic engine.", station_name, exc)
        else:
            log.debug("No CPCB_API_KEY set; using synthetic telemetry for %s.", station_name)

        return self._generate_synthetic_reading(station_cfg, session)

    def _fetch_live_cpcb(self, cpcb_id: str, station_name: str) -> Optional[dict[str, Any]]:
        """Fetch from data.gov.in CPCB CAAQMS endpoint."""
        url = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
        params = {
            "api-key": self.api_key,
            "format": "json",
            "filters[station]": station_name,
            "limit": 1,
        }
        resp = self._session.get(url, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            return None

        data = resp.json()
        records = data.get("records", [])
        if not records:
            return None

        rec = records[0]
        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)

        try:
            aqi_val = float(rec.get("air_quality_index") or rec.get("aqi") or 100.0)
        except (ValueError, TypeError):
            return None

        reading = {
            "timestamp": now_ist,
            "aqi": aqi_val,
            "pm25": float(rec["pm25"]) if rec.get("pm25") else None,
            "pm10": float(rec["pm10"]) if rec.get("pm10") else None,
            "no2": float(rec["no2"]) if rec.get("no2") else None,
            "so2": float(rec["so2"]) if rec.get("so2") else None,
            "co": float(rec["co"]) if rec.get("co") else None,
            "o3": float(rec["o3"]) if rec.get("o3") else None,
            "synthetic": False,
        }

        if not validate_aqi(reading["aqi"]).is_valid:
            return None

        return reading

    def _generate_synthetic_reading(self, station_cfg: dict[str, Any], session: Session) -> dict[str, Any]:
        """Generate realistic synthetic reading based on last known DB reading + random variance."""
        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)
        station_name = station_cfg["name"]

        try:
            station_id = _resolve_station_id(session, station_name)
            stmt = select(AqiReading).where(AqiReading.station_id == station_id).order_by(AqiReading.timestamp.desc()).limit(1)
            last_reading = session.execute(stmt).scalars().first()
        except Exception:
            last_reading = None

        if last_reading:
            base_aqi = last_reading.aqi
            base_pm25 = last_reading.pm25 or (base_aqi * 0.45)
            base_pm10 = last_reading.pm10 or (base_aqi * 0.85)
            base_no2 = last_reading.no2 or 35.0
            base_so2 = last_reading.so2 or 15.0
            base_co = last_reading.co or 1.2
            base_o3 = last_reading.o3 or 25.0
        else:
            baselines = {
                "Shivajinagar": (115.0, 52.0, 98.0, 42.0, 18.0, 1.4, 28.0),
                "Swargate": (125.0, 58.0, 110.0, 48.0, 20.0, 1.6, 24.0),
                "Hadapsar": (135.0, 62.0, 120.0, 44.0, 22.0, 1.5, 26.0),
                "Karve Road": (108.0, 48.0, 92.0, 38.0, 15.0, 1.2, 30.0),
            }
            vals = baselines.get(station_name, (110.0, 50.0, 95.0, 40.0, 18.0, 1.3, 25.0))
            base_aqi, base_pm25, base_pm10, base_no2, base_so2, base_co, base_o3 = vals

        delta = random.uniform(-5.0, 8.0)
        new_aqi = max(35.0, min(480.0, round(base_aqi + delta, 1)))
        scale = new_aqi / base_aqi if base_aqi > 0 else 1.0

        return {
            "timestamp": now_ist,
            "aqi": new_aqi,
            "pm25": round(base_pm25 * scale, 1),
            "pm10": round(base_pm10 * scale, 1),
            "no2": round(base_no2 * max(0.8, min(1.2, scale)), 1),
            "so2": round(base_so2 * max(0.9, min(1.1, scale)), 1),
            "co": round(base_co * max(0.9, min(1.1, scale)), 2),
            "o3": round(base_o3 * max(0.8, min(1.2, scale)), 1),
            "synthetic": True,
        }

    def poll_all_stations(self, session: Optional[Session] = None) -> list[dict[str, Any]]:
        """Poll all stations in city_config, persist readings, and trigger attribution on spikes."""
        own_session = session is None
        if own_session:
            session = SessionLocal()

        payloads: list[dict[str, Any]] = []
        detector = SpikeDetector()

        try:
            for st_cfg in self.stations:
                st_name = st_cfg["name"]
                try:
                    st_id = _resolve_station_id(session, st_name)
                except ValueError as exc:
                    log.warning("Skipping station %s: %s", st_name, exc)
                    continue

                reading = self.fetch_station_reading(st_cfg, session)
                persist_reading(session, st_id, reading)
                _update_station_summary(session, st_id, reading)
                session.flush()

                top_half = detector.check_and_trigger_spike(session, st_id, reading)
                if top_half is not None:
                    log.info("Spike detected at %s (AQI=%.1f)! Running attribution...", st_name, reading["aqi"])
                    
                    stmt = select(WindData).where(WindData.station_id == st_id).order_by(WindData.timestamp.desc()).limit(1)
                    wind_row = session.execute(stmt).scalars().first()
                    
                    if wind_row and wind_row.weather_snapshot_json:
                        weather = wind_row.weather_snapshot_json
                        wind_dir = float(weather.get("wind_direction_deg", wind_row.wind_direction_deg))
                        wind_spd = float(weather.get("wind_speed_kmh", wind_row.wind_speed_kmh))
                        pasquill = weather.get("atmospheric_stability", {}).get("pasquill_class", "D")
                    elif wind_row:
                        wind_dir = float(wind_row.wind_direction_deg)
                        wind_spd = float(wind_row.wind_speed_kmh)
                        pasquill = "D"
                    else:
                        weather = top_half["weather_snapshot"]
                        wind_dir = float(weather["wind_direction_deg"])
                        wind_spd = float(weather["wind_speed_kmh"])
                        pasquill = weather["atmospheric_stability"]["pasquill_class"]

                    from geoalchemy2 import functions as gfunc
                    from sqlalchemy import select as _sel
                    station_obj = session.get(Station, st_id)
                    lon_q, lat_q = session.execute(_sel(gfunc.ST_X(station_obj.geom), gfunc.ST_Y(station_obj.geom))).one()
                    sta_lon, sta_lat = float(lon_q), float(lat_q)

                    values = {p: reading.get(p) for p in POLLUTANT_KEYS}
                    fp = top_half["trigger_station"]["reading"]["chemical_fingerprint"]
                    sig_class = fp.get("signature_class", "mixed")
                    dom = top_half["trigger_station"]["reading"].get("dominant_pollutant", "PM10")

                    try:
                        lower_half = run_attribution(
                            session=session,
                            station_lon=sta_lon,
                            station_lat=sta_lat,
                            station_name=st_name,
                            spike_ts=reading["timestamp"],
                            aqi_value=float(reading["aqi"]),
                            dominant_pollutant=dom,
                            signature_class=sig_class,
                            wind_direction_deg=wind_dir,
                            wind_speed_kmh=wind_spd,
                            pasquill_class=pasquill,
                            pollutant_readings=values,
                        )
                        full_payload = {**top_half, **lower_half}
                        
                        ai = full_payload.get("actionable_intelligence", {})
                        alert = Alert(
                            station_id=st_id,
                            spike_time=reading["timestamp"],
                            aqi_value=float(reading["aqi"]),
                            dominant_pollutant=dom,
                            attribution_details=full_payload,
                            enforcement_priority=float(ai.get("enforcement_priority", 0.5)),
                        )
                        session.add(alert)
                        payloads.append(full_payload)
                    except Exception as attr_err:
                        log.error("Attribution failed for %s: %s", st_name, attr_err)
                        payloads.append(top_half)

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
