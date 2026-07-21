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
    """Live CPCB and WAQI poller with synthetic fallback engine."""

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

    def _fetch_live_waqi(self, lat: float, lon: float, station_name: str) -> Optional[dict[str, Any]]:
        """Fetch real-time data from WAQI API using exact station UIDs mapping."""
        waqi_key = (os.getenv("WAQI_API_KEY") or "").strip()
        if not waqi_key:
            return None

        # Map Pune station names to their exact WAQI UIDs to ensure distinct real-time readings
        WAQI_STATION_MAP = {
            "shivajinagar": "@14120",
            "swargate": "@14122",
            "hadapsar": "@14121",
            "kothrud": "@14123"
        }

        station_key = station_name.lower().strip()
        uid = WAQI_STATION_MAP.get(station_key)
        if uid:
            url = f"https://api.waqi.info/feed/{uid}/"
        else:
            url = f"https://api.waqi.info/feed/geo:{lat};{lon}/"

        try:
            resp = self._session.get(url, params={"token": waqi_key}, timeout=self.timeout)
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("status") == "ok":
                    data = res_json.get("data", {})
                    aqi = data.get("aqi")
                    iaqi = data.get("iaqi", {})
                    
                    # Convert WAQI's US EPA sub-index readings back to raw concentrations
                    # so we can compute mathematically precise Indian CPCB AQI values.
                    pollutants = {
                        "pm25": us_aqi_to_concentration("pm25", iaqi.get("pm25", {}).get("v")) if iaqi.get("pm25") else None,
                        "pm10": us_aqi_to_concentration("pm10", iaqi.get("pm10", {}).get("v")) if iaqi.get("pm10") else None,
                        "no2": us_aqi_to_concentration("no2", iaqi.get("no2", {}).get("v")) if iaqi.get("no2") else None,
                        "so2": us_aqi_to_concentration("so2", iaqi.get("so2", {}).get("v")) if iaqi.get("so2") else None,
                        "co": us_aqi_to_concentration("co", iaqi.get("co", {}).get("v")) if iaqi.get("co") else None,
                        "o3": us_aqi_to_concentration("o3", iaqi.get("o3", {}).get("v")) if iaqi.get("o3") else None,
                    }
                    
                    return {
                        "aqi": float(aqi) if aqi is not None else None,
                        "pollutants": pollutants
                    }
        except Exception as e:
            log.warning("WAQI fetch failed for %s: %s", station_name, e)
        return None

    def fetch_station_reading(self, station_cfg: dict[str, Any], session: Session) -> dict[str, Any]:
        """GET latest reading for a station, merging live CPCB and WAQI data."""
        station_name = station_cfg["name"]
        cpcb_id = station_cfg.get("cpcb_station_id", "")
        lat = station_cfg.get("lat")
        lon = station_cfg.get("lon")

        waqi_data = None
        cpcb_data = None

        # 1. Fetch from WAQI (if coordinates available)
        if lat is not None and lon is not None:
            try:
                waqi_data = self._fetch_live_waqi(lat, lon, station_name)
                if waqi_data:
                    log.info("WAQI fetch succeeded for %s. Raw AQI: %s", station_name, waqi_data["aqi"])
            except Exception as exc:
                log.warning("WAQI fetch failed for %s: %s", station_name, exc)

        # 2. Fetch from CPCB (if key and cpcb_id available)
        if self.api_key and cpcb_id:
            try:
                cpcb_data = self._fetch_live_cpcb(cpcb_id, station_name)
                if cpcb_data:
                    log.info("CPCB fetch succeeded for %s. AQI: %s", station_name, cpcb_data["aqi"])
            except Exception as exc:
                log.warning("CPCB fetch failed for %s: %s", station_name, exc)

        # 3. Merge data sources
        if waqi_data or cpcb_data:
            IST = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(IST)

            # Default fallback structures
            merged_pollutants = {
                "pm25": None, "pm10": None, "no2": None,
                "so2": None, "co": None, "o3": None
            }

            # Merge WAQI values first (high-quality real-time baseline)
            if waqi_data:
                for k, v in waqi_data["pollutants"].items():
                    if v is not None:
                        merged_pollutants[k] = v

            # Merge/Overlay with CPCB values
            if cpcb_data:
                # Check individual CPCB chemical concentrations
                for p_key in ["pm25", "pm10", "no2", "so2", "co", "o3"]:
                    val = cpcb_data.get(p_key)
                    if val is not None:
                        merged_pollutants[p_key] = val

            merged_aqi = calculate_indian_aqi(merged_pollutants)

            return {
                "timestamp": now_ist,
                "aqi": float(round(merged_aqi, 1)),
                "pm25": merged_pollutants["pm25"],
                "pm10": merged_pollutants["pm10"],
                "no2": merged_pollutants["no2"],
                "so2": merged_pollutants["so2"],
                "co": merged_pollutants["co"],
                "o3": merged_pollutants["o3"],
                "synthetic": False,
            }

        # 4. Fallback to synthetic if both failed
        log.warning("Both WAQI and CPCB failed for %s; using synthetic telemetry.", station_name)
        return self._generate_synthetic_reading(station_cfg, session)

    def _fetch_live_cpcb(self, cpcb_id: str, station_name: str) -> Optional[dict[str, Any]]:
        """Fetch from data.gov.in CPCB CAAQMS endpoint."""
        url = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
        params = {
            "api-key": self.api_key,
            "format": "json",
            "filters[city]": "Pune",
            "limit": 100,
        }
        resp = self._session.get(url, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            return None

        data = resp.json()
        records = data.get("records", [])
        if not records:
            return None

        # Filter records matching station name (e.g. "Shivajinagar" in "Revenue Colony-Shivajinagar, Pune - IITM")
        matching_recs = [r for r in records if station_name.lower() in r.get("station", "").lower()]
        if not matching_recs:
            # Try matching by first word (e.g. Katraj, Hadapsar, Karve)
            first_word = station_name.split()[0].lower()
            matching_recs = [r for r in records if first_word in r.get("station", "").lower()]

        if not matching_recs:
            return None

        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)

        pollutants = {}
        for r in matching_recs:
            pid = r.get("pollutant_id", "").upper().replace(".", "").replace("_", "")  # PM2.5 -> PM25
            # CPCB endpoint has returned both field names across versions:
            #   avg_value  — primary field (older schema)
            #   pollutant_avg — alternate field key (newer schema, identified by teammate)
            val_str = (
                r.get("avg_value")
                or r.get("pollutant_avg")
                or r.get("max_value")
                or r.get("min_value")
            )
            try:
                if val_str and str(val_str).upper() not in ("NA", "None", ""):
                    pollutants[pid] = float(val_str)
            except (ValueError, TypeError):
                pass

        pm25 = pollutants.get("PM25")
        pm10 = pollutants.get("PM10")
        no2 = pollutants.get("NO2")
        so2 = pollutants.get("SO2")
        co = pollutants.get("CO")
        o3 = pollutants.get("OZONE") or pollutants.get("O3")

        # Calculate or extract AQI
        aqi_val = None
        if "AQI" in pollutants:
            aqi_val = pollutants["AQI"]
        elif "AIR_QUALITY_INDEX" in pollutants:
            aqi_val = pollutants["AIR_QUALITY_INDEX"]
        elif pm10 is not None or pm25 is not None:
            # Estimate AQI from CPCB PM10/PM2.5 sub-index approximation for demo continuity
            if pm10 is not None and pm10 > 100:
                aqi_val = max(100.0, pm10 * 1.5)
            elif pm25 is not None and pm25 > 60:
                aqi_val = max(100.0, pm25 * 2.5)
            elif pm10 is not None:
                aqi_val = max(50.0, pm10 * 1.0)
            elif pm25 is not None:
                aqi_val = max(50.0, pm25 * 1.6)
            else:
                aqi_val = 110.0
        else:
            return None

        reading = {
            "timestamp": now_ist,
            "aqi": float(round(aqi_val, 1)),
            "pm25": pm25,
            "pm10": pm10,
            "no2": no2,
            "so2": so2,
            "co": co,
            "o3": o3,
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

    def _push_to_websocket(self, payload: dict[str, Any]) -> None:
        """Push spike payload to local WebSocket manager and remote backend service."""
        try:
            from api.ws_manager import manager
            manager.broadcast_sync(payload)
        except Exception as exc:
            log.debug("Local ws broadcast skipped: %s", exc)

        for host in ["http://backend:5000", "http://localhost:5000"]:
            try:
                requests.post(f"{host}/api/v1/ws/broadcast", json=payload, timeout=2)
                break
            except Exception:
                continue

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
                        self._push_to_websocket(full_payload)
                    except Exception as attr_err:
                        log.error("Attribution failed for %s: %s", st_name, attr_err)
                        payloads.append(top_half)
                        self._push_to_websocket(top_half)

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


def calculate_indian_aqi(pollutants: dict[str, float | None]) -> float:
    """Calculate the official Indian CPCB National Air Quality Index (NAQI)."""
    sub_indices = []

    # PM2.5 breakpoints
    pm25 = pollutants.get("pm25") or pollutants.get("PM25")
    if pm25 is not None:
        if pm25 <= 30:
            sub_indices.append(pm25 * 50 / 30)
        elif pm25 <= 60:
            sub_indices.append(50 + (pm25 - 30) * 50 / 30)
        elif pm25 <= 90:
            sub_indices.append(100 + (pm25 - 60) * 100 / 30)
        elif pm25 <= 120:
            sub_indices.append(200 + (pm25 - 90) * 100 / 30)
        elif pm25 <= 250:
            sub_indices.append(300 + (pm25 - 120) * 100 / 130)
        else:
            sub_indices.append(400 + (pm25 - 250) * 100 / 100)

    # PM10 breakpoints
    pm10 = pollutants.get("pm10") or pollutants.get("PM10")
    if pm10 is not None:
        if pm10 <= 50:
            sub_indices.append(pm10)
        elif pm10 <= 100:
            sub_indices.append(50 + (pm10 - 50) * 50 / 50)
        elif pm10 <= 250:
            sub_indices.append(100 + (pm10 - 100) * 100 / 150)
        elif pm10 <= 350:
            sub_indices.append(200 + (pm10 - 250) * 100 / 100)
        elif pm10 <= 430:
            sub_indices.append(300 + (pm10 - 350) * 100 / 80)
        else:
            sub_indices.append(400 + (pm10 - 430) * 100 / 100)

    # NO2 breakpoints
    no2 = pollutants.get("no2") or pollutants.get("NO2")
    if no2 is not None:
        if no2 <= 40:
            sub_indices.append(no2 * 50 / 40)
        elif no2 <= 80:
            sub_indices.append(50 + (no2 - 40) * 50 / 40)
        elif no2 <= 180:
            sub_indices.append(100 + (no2 - 80) * 100 / 100)
        elif no2 <= 280:
            sub_indices.append(200 + (no2 - 180) * 100 / 100)
        elif no2 <= 400:
            sub_indices.append(300 + (no2 - 280) * 100 / 120)
        else:
            sub_indices.append(400 + (no2 - 400) * 100 / 100)

    # SO2 breakpoints
    so2 = pollutants.get("so2") or pollutants.get("SO2")
    if so2 is not None:
        if so2 <= 40:
            sub_indices.append(so2 * 50 / 40)
        elif so2 <= 80:
            sub_indices.append(50 + (so2 - 40) * 50 / 40)
        elif so2 <= 380:
            sub_indices.append(100 + (so2 - 80) * 100 / 300)
        elif so2 <= 800:
            sub_indices.append(200 + (so2 - 380) * 100 / 420)
        elif so2 <= 1600:
            sub_indices.append(300 + (so2 - 800) * 100 / 800)
        else:
            sub_indices.append(400 + (so2 - 1600) * 100 / 800)

    # CO breakpoints
    co = pollutants.get("co") or pollutants.get("CO")
    if co is not None:
        if co <= 1.0:
            sub_indices.append(co * 50)
        elif co <= 2.0:
            sub_indices.append(50 + (co - 1.0) * 50)
        elif co <= 10.0:
            sub_indices.append(100 + (co - 2.0) * 100 / 8.0)
        elif co <= 17.0:
            sub_indices.append(200 + (co - 10.0) * 100 / 7.0)
        elif co <= 34.0:
            sub_indices.append(300 + (co - 17.0) * 100 / 17.0)
        else:
            sub_indices.append(400 + (co - 34.0) * 100 / 10.0)

    # O3 breakpoints
    o3 = pollutants.get("o3") or pollutants.get("O3") or pollutants.get("OZONE")
    if o3 is not None:
        if o3 <= 50:
            sub_indices.append(o3)
        elif o3 <= 100:
            sub_indices.append(50 + (o3 - 50) * 50 / 50)
        elif o3 <= 168:
            sub_indices.append(100 + (o3 - 100) * 100 / 68)
        elif o3 <= 208:
            sub_indices.append(200 + (o3 - 168) * 100 / 40)
        elif o3 <= 748:
            sub_indices.append(300 + (o3 - 208) * 100 / 540)
        else:
            sub_indices.append(400 + (o3 - 748) * 100 / 100)

    if not sub_indices:
        return 50.0
    return float(round(max(sub_indices), 1))


def us_aqi_to_concentration(pollutant: str, aqi: Optional[float]) -> Optional[float]:
    """Convert US EPA AQI sub-index value back to raw physical concentration."""
    if aqi is None:
        return None
    
    pollutant = pollutant.lower()
    if pollutant == "pm25":
        if aqi <= 50:
            return (aqi / 50.0) * 12.0
        elif aqi <= 100:
            return 12.0 + ((aqi - 50.0) / 50.0) * (35.4 - 12.0)
        elif aqi <= 150:
            return 35.4 + ((aqi - 100.0) / 50.0) * (55.4 - 35.4)
        elif aqi <= 200:
            return 55.4 + ((aqi - 150.0) / 50.0) * (150.4 - 55.4)
        elif aqi <= 300:
            return 150.4 + ((aqi - 200.0) / 100.0) * (250.4 - 150.4)
        else:
            return 250.4 + ((aqi - 300.0) / 200.0) * (500.4 - 250.4)
            
    elif pollutant == "pm10":
        if aqi <= 50:
            return (aqi / 50.0) * 54.0
        elif aqi <= 100:
            return 54.0 + ((aqi - 50.0) / 50.0) * (154.0 - 54.0)
        elif aqi <= 150:
            return 154.0 + ((aqi - 100.0) / 50.0) * (254.0 - 154.0)
        elif aqi <= 200:
            return 254.0 + ((aqi - 150.0) / 50.0) * (354.0 - 254.0)
        elif aqi <= 300:
            return 354.0 + ((aqi - 200.0) / 100.0) * (424.0 - 354.0)
        else:
            return 424.0 + ((aqi - 300.0) / 200.0) * (604.0 - 424.0)

    elif pollutant == "co":
        if aqi <= 50:
            ppm = (aqi / 50.0) * 4.4
        elif aqi <= 100:
            ppm = 4.4 + ((aqi - 50.0) / 50.0) * (9.4 - 4.4)
        elif aqi <= 150:
            ppm = 9.4 + ((aqi - 100.0) / 50.0) * (12.4 - 9.4)
        elif aqi <= 200:
            ppm = 12.4 + ((aqi - 150.0) / 50.0) * (15.4 - 12.4)
        else:
            ppm = 15.4 + ((aqi - 200.0) / 100.0) * (30.4 - 15.4)
        return ppm * 1.145

    elif pollutant == "no2":
        if aqi <= 50:
            ppb = (aqi / 50.0) * 53.0
        elif aqi <= 100:
            ppb = 53.0 + ((aqi - 50.0) / 50.0) * (100.0 - 53.0)
        elif aqi <= 150:
            ppb = 100.0 + ((aqi - 100.0) / 50.0) * (360.0 - 100.0)
        else:
            ppb = 360.0 + ((aqi - 150.0) / 50.0) * (649.0 - 360.0)
        return ppb * 1.88

    elif pollutant == "so2":
        if aqi <= 50:
            ppb = (aqi / 50.0) * 35.0
        elif aqi <= 100:
            ppb = 35.0 + ((aqi - 50.0) / 50.0) * (75.0 - 35.0)
        elif aqi <= 150:
            ppb = 75.0 + ((aqi - 100.0) / 50.0) * (185.0 - 75.0)
        else:
            ppb = 185.0 + ((aqi - 150.0) / 50.0) * (304.0 - 185.0)
        return ppb * 2.62

    elif pollutant == "o3":
        if aqi <= 50:
            ppb = (aqi / 50.0) * 54.0
        elif aqi <= 100:
            ppb = 54.0 + ((aqi - 50.0) / 50.0) * (70.0 - 54.0)
        elif aqi <= 150:
            ppb = 70.0 + ((aqi - 100.0) / 50.0) * (85.0 - 70.0)
        else:
            ppb = 85.0 + ((aqi - 150.0) / 50.0) * (105.0 - 85.0)
        return ppb * 1.96

    return aqi
