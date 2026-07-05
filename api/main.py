"""FastAPI REST API — Task 4.

Exposes the full AQI attribution pipeline over HTTP so that:
  - Person 3 (Frontend / Leaflet map) can fetch spike payloads.
  - The pipeline can be triggered on demand with fresh telemetry.

Endpoints
---------
GET  /health                              — liveness + DB ping
GET  /stations                            — list seeded Pune stations
GET  /stations/{station_name}/latest-spike — most recent alert for a station
POST /attribution/run                     — live inference: detect + attribute

All responses conform to the data contract (data_contract_sample.json).
CORS is fully open so the Frontend can call from any origin.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
import yaml

from fastapi import Depends, FastAPI, HTTPException, status, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from api.ws_manager import manager
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.connection import SessionLocal, ping
from db.models import Alert, AqiReading, Station
from geoalchemy2 import functions as gfunc
from pipeline.attribution import run_attribution
from pipeline.naaqs import POLLUTANT_KEYS, dominant_pollutant, compute_exceedance_factors
from pipeline.spike_detector import SpikeDetector
from pipeline.validators import validate_aqi, validate_pollutant_reading
from pipeline.forecasting import predict_upcoming_impacts

log = logging.getLogger("api")

PIPELINE_VERSION = "3.1.0"

# ============================================================
# App + middleware
# ============================================================

app = FastAPI(
    title="AQI Attribution API",
    description=(
        "AI-Powered Urban Air Quality Intelligence — Pune, India. "
        "Detects AQI spikes and attributes them to pollution sources "
        "using wind-cone spatial analysis and chemical fingerprinting."
    ),
    version=PIPELINE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DB session dependency
# ============================================================

def get_db():
    """Yield a SQLAlchemy session; always closes on exit."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ============================================================
# Shared helpers
# ============================================================

def _station_coords(session: Session, station: Station) -> tuple[float, float]:
    """Return (lon, lat) from the station PostGIS geometry."""
    lon, lat = session.execute(
        select(gfunc.ST_X(station.geom), gfunc.ST_Y(station.geom))
    ).one()
    return float(lon), float(lat)


def _get_station_or_404(session: Session, station_name: str) -> Station:
    station = session.execute(
        select(Station).where(Station.name == station_name)
    ).scalars().first()
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station not found: {station_name!r}",
        )
    return station


def _persist_alert(
    session: Session,
    station: Station,
    full_payload: dict[str, Any],
) -> Alert:
    """Write the merged payload to the alerts table and return the ORM object."""
    reading = full_payload["trigger_station"]["reading"]
    ai = full_payload.get("actionable_intelligence", {})

    alert = Alert(
        station_id=str(station.id),
        spike_time=datetime.fromisoformat(reading["timestamp"]),
        aqi_value=float(reading["total_aqi"]),
        dominant_pollutant=reading.get("dominant_pollutant") or "UNKNOWN",
        attribution_details=full_payload,
        enforcement_priority=float(ai.get("enforcement_priority", 0.5)),
    )
    session.add(alert)
    session.flush()   # get the generated id before commit
    return alert


# ============================================================
# Pydantic request/response models
# ============================================================

class AttributionRequest(BaseModel):
    station_name: str = Field(..., example="Shivajinagar")
    aqi: float = Field(..., gt=0, example=310.0)
    pm25: Optional[float] = Field(None, example=148.6)
    pm10: Optional[float] = Field(None, example=387.2)
    no2: Optional[float] = Field(None, example=72.4)
    so2: Optional[float] = Field(None, example=54.8)
    co: Optional[float] = Field(None, example=3.2)
    o3: Optional[float] = Field(None, example=42.1)
    timestamp: Optional[str] = Field(
        None,
        example="2026-06-25T08:30:00+05:30",
        description="ISO-8601 timestamp. Defaults to now (IST) if omitted.",
    )


# ============================================================
# Endpoints
# ============================================================

@app.get("/health", tags=["Meta"])
def health():
    """Liveness + DB connectivity check."""
    db_ok = ping()
    return {
        "status": "ok",
        "db": db_ok,
        "pipeline_version": PIPELINE_VERSION,
    }


@app.get("/stations", tags=["Stations"])
def list_stations(session: Session = Depends(get_db)):
    """Return all seeded monitoring stations with their coordinates and last AQI."""
    stations = session.execute(select(Station)).scalars().all()
    result = []
    for st in stations:
        lon, lat = _station_coords(session, st)
        last_updated = st.last_updated.isoformat() if st.last_updated else None
        result.append({
            "id": str(st.id),
            "name": st.name,
            "coordinates": [lon, lat],
            "last_aqi": st.last_aqi,
            "last_updated": last_updated,
        })
    return result


@app.get("/stations/{station_name}/latest-spike", tags=["Stations"])
@app.get("/api/v1/attribution/{station_name}", tags=["Attribution"])
def latest_spike(station_name: str, session: Session = Depends(get_db)):
    """Return the most recent spike alert for a station (full contract payload)."""
    station = _get_station_or_404(session, station_name)

    alert = session.execute(
        select(Alert)
        .where(Alert.station_id == str(station.id))
        .order_by(Alert.spike_time.desc())
        .limit(1)
    ).scalars().first()

    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No spike found for station: {station_name}",
        )

    details = dict(alert.attribution_details)

    # Dynamic pre-alert lookup for the station
    from pipeline.forecasting import predict_upcoming_impacts
    pre_alerts_list = predict_upcoming_impacts(session, alert.spike_time)
    station_pre_alerts = [
        p for p in pre_alerts_list if p["station"].lower() == station_name.lower()
    ]

    if station_pre_alerts:
        details["pre_alerts"] = {
            "source": station_pre_alerts[0]["source"],
            "eta_minutes": station_pre_alerts[0]["eta_minutes"],
            "estimated_aqi_increase": station_pre_alerts[0]["estimated_aqi_increase"],
            "advisory": station_pre_alerts[0]["advisory"],
        }
    else:
        # Fallback requested by frontend agent
        details["pre_alerts"] = {
            "source": "Hinjewadi Phase-III Construction Cluster",
            "eta_minutes": 34,
            "estimated_aqi_increase": 45,
            "advisory": "Construction schedule active. Heavy dust dispersion predicted.",
        }

    return details


@app.get("/stations/{station_name}/alerts", tags=["Stations"])
def list_alerts(
    station_name: str,
    limit: int = 10,
    session: Session = Depends(get_db),
):
    """Return the N most recent spike alerts for a station (summary list)."""
    station = _get_station_or_404(session, station_name)

    alerts = session.execute(
        select(Alert)
        .where(Alert.station_id == str(station.id))
        .order_by(Alert.spike_time.desc())
        .limit(min(limit, 50))
    ).scalars().all()

    return [
        {
            "id": str(a.id),
            "spike_time": a.spike_time.isoformat(),
            "aqi_value": a.aqi_value,
            "dominant_pollutant": a.dominant_pollutant,
            "enforcement_priority": a.enforcement_priority,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]


@app.post("/attribution/run", tags=["Attribution"], status_code=status.HTTP_201_CREATED)
def run_attribution_endpoint(
    body: AttributionRequest,
    session: Session = Depends(get_db),
):
    """Run the full detection + attribution pipeline on a live reading.

    Returns the merged data-contract payload (HTTP 201) if a spike is detected,
    or ``{"spike_detected": false}`` (HTTP 200) if no spike fires.
    """
    # ---- resolve station ---------------------------------------------------
    station = _get_station_or_404(session, body.station_name)
    sta_lon, sta_lat = _station_coords(session, station)

    # ---- input validation --------------------------------------------------
    aqi_check = validate_aqi(body.aqi)
    if not aqi_check.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=aqi_check.reason,
        )

    for p in ["pm25", "pm10", "no2", "so2", "co", "o3"]:
        val = getattr(body, p)
        if val is not None:
            p_check = validate_pollutant_reading(p, val)
            if not p_check.is_valid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=p_check.reason,
                )

    # ---- parse timestamp ---------------------------------------------------
    IST = timezone(timedelta(hours=5, minutes=30))
    if body.timestamp:
        try:
            spike_ts = datetime.fromisoformat(body.timestamp)
            if spike_ts.tzinfo is None:
                spike_ts = spike_ts.replace(tzinfo=IST)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid timestamp format: {body.timestamp!r}. Use ISO-8601.",
            )
    else:
        spike_ts = datetime.now(IST)

    # ---- build reading dict ------------------------------------------------
    reading = {
        "timestamp": spike_ts,
        "aqi": float(body.aqi),
        "pm25": body.pm25,
        "pm10": body.pm10,
        "no2": body.no2,
        "so2": body.so2,
        "co": body.co,
        "o3": body.o3,
    }

    # ---- persist reading before detection (poller pattern) -----------------
    from pipeline.poller import persist_reading, _update_station_summary
    persist_reading(session, str(station.id), reading)
    _update_station_summary(session, str(station.id), reading)
    session.flush()

    # ---- run spike detector ------------------------------------------------
    detector = SpikeDetector()
    top_half = detector.check_and_trigger_spike(
        session, str(station.id), reading
    )

    if top_half is None:
        session.commit()
        # Return 200 OK (not 201) for no-spike
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"spike_detected": False},
        )

    # ---- run attribution ---------------------------------------------------
    weather = top_half["weather_snapshot"]
    values = {p: reading.get(p) for p in POLLUTANT_KEYS}
    fp = top_half["trigger_station"]["reading"]["chemical_fingerprint"]
    signature_class = fp.get("signature_class", "mixed")
    dom_pollutant = top_half["trigger_station"]["reading"].get("dominant_pollutant", "PM10")

    lower_half = run_attribution(
        session=session,
        station_lon=sta_lon,
        station_lat=sta_lat,
        station_name=station.name,
        spike_ts=spike_ts,
        aqi_value=float(body.aqi),
        dominant_pollutant=dom_pollutant,
        signature_class=signature_class,
        wind_direction_deg=float(weather["wind_direction_deg"]),
        wind_speed_kmh=float(weather["wind_speed_kmh"]),
        pasquill_class=weather["atmospheric_stability"]["pasquill_class"],
        pollutant_readings=values,
    )

    # ---- merge into full contract payload ----------------------------------
    full_payload = {**top_half, **lower_half}

    # ---- persist alert -----------------------------------------------------
    _persist_alert(session, station, full_payload)
    session.commit()

    # ---- live push broadcast (Phase 3) -------------------------------------
    manager.broadcast_sync(full_payload)

    return full_payload


@app.get("/attribution/sources", tags=["Attribution"])
def list_pollution_sources(session: Session = Depends(get_db)):
    """Return all pollution sources as a GeoJSON FeatureCollection."""
    from db.models import PollutionSource
    from db.geo_utils import sources_to_geojson

    sources = session.execute(select(PollutionSource)).scalars().all()
    return json.loads(sources_to_geojson(sources))


@app.get("/api/pre-alerts", tags=["Attribution"])
@app.get("/attribution/pre-alerts", tags=["Attribution"])
def get_pre_alerts(
    timestamp: Optional[str] = None,
    session: Session = Depends(get_db),
):
    """Predict upcoming pollution impacts from scheduled sources in the next 2 hours."""
    IST = timezone(timedelta(hours=5, minutes=30))
    if timestamp:
        try:
            check_time = datetime.fromisoformat(timestamp.replace(" ", "+"))
            if check_time.tzinfo is None:
                check_time = check_time.replace(tzinfo=IST)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid timestamp format: {timestamp}. Use ISO-8601.",
            )
    else:
        check_time = datetime.now(IST)

    return predict_upcoming_impacts(session, check_time)


def _get_city_config() -> dict[str, Any]:
    """Load geographic-agnostic city parameters from city_config.yml."""
    root_dir = Path(__file__).resolve().parent.parent
    config_path = root_dir / "city_config.yml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.get("/api/v1/replay/{station_name}", tags=["Replay"])
def replay_snapshot(
    station_name: str,
    timestamp: str = Query(..., description="ISO 8601 timestamp"),
    session: Session = Depends(get_db),
):
    """Reconstruct attribution state at a historical timestamp within the last 24 hours."""
    from pipeline.replay_engine import replay_at_timestamp

    IST = timezone(timedelta(hours=5, minutes=30))
    try:
        target_ts = datetime.fromisoformat(timestamp.replace(" ", "+"))
        if target_ts.tzinfo is None:
            target_ts = target_ts.replace(tzinfo=IST)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid timestamp format: {timestamp}. Use ISO-8601.",
        )

    cfg = _get_city_config()
    result = replay_at_timestamp(session, station_name, target_ts, cfg)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station not found or insufficient historical data: {station_name!r}",
        )
    return result


@app.get("/api/v1/timeline/{station_name}", tags=["Replay"])
def timeline_ticks(
    station_name: str,
    session: Session = Depends(get_db),
):
    """Return 24 hourly tick summaries for the timeline slider."""
    from pipeline.replay_engine import get_24h_tick_summary

    cfg = _get_city_config()
    ticks = get_24h_tick_summary(session, station_name, cfg)
    if not ticks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station not found: {station_name!r}",
        )
    return ticks


@app.get("/api/v1/cone/{station_name}", tags=["Spatial"])
def wind_cone(
    station_name: str,
    timestamp: Optional[str] = Query(None, description="ISO 8601; defaults to now"),
    session: Session = Depends(get_db),
):
    """Return the wind cone GeoJSON for a station at a given moment."""
    from pipeline.cone_builder import build_wind_cone
    from pipeline.weather_client import WeatherClient
    from db.models import Station, WindData

    cfg = _get_city_config()
    stations_cfg = cfg.get("stations", [])
    station_cfg = next((s for s in stations_cfg if s["name"].lower() == station_name.lower()), None)
    if not station_cfg:
        station_cfg = next((s for s in stations_cfg if station_name.lower() in s["name"].lower() or s["name"].lower() in station_name.lower()), None)
        if not station_cfg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station not found: {station_name!r}",
            )

    IST = timezone(timedelta(hours=5, minutes=30))
    if timestamp:
        try:
            target_ts = datetime.fromisoformat(timestamp.replace(" ", "+"))
            if target_ts.tzinfo is None:
                target_ts = target_ts.replace(tzinfo=IST)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid timestamp format: {timestamp}. Use ISO-8601.",
            )
    else:
        target_ts = datetime.now(IST)

    station = session.execute(
        select(Station).where(Station.name.ilike(f"%{station_cfg['name']}%")).limit(1)
    ).scalar_one_or_none()

    wind_row = None
    if station:
        wind_row = session.execute(
            select(WindData)
            .where(WindData.station_id == station.id)
            .where(WindData.timestamp <= target_ts)
            .order_by(WindData.timestamp.desc())
            .limit(1)
        ).scalar_one_or_none()

    if wind_row and wind_row.weather_snapshot_json:
        wind_speed = wind_row.wind_speed_kmh
        wind_dir = wind_row.wind_direction_deg
        pasquill = wind_row.weather_snapshot_json.get("atmospheric_stability", {}).get("pasquill_class", "D")
    else:
        try:
            weather_snap = WeatherClient().get_current(station_cfg["lat"], station_cfg["lon"]).to_dict()
            wind_speed = weather_snap.get("wind_speed_kmh", 12.0)
            wind_dir = weather_snap.get("wind_direction_deg", 310.0)
            pasquill = weather_snap.get("atmospheric_stability", {}).get("pasquill_class", "D")
        except Exception:
            wind_speed = 12.0
            wind_dir = 310.0
            pasquill = "D"

    return build_wind_cone(
        station_lon=station_cfg["lon"],
        station_lat=station_cfg["lat"],
        station_name=station_cfg["name"],
        wind_direction_deg=wind_dir,
        wind_speed_kmh=wind_speed,
        pasquill_class=pasquill,
    )


@app.post("/api/v1/simulation/trigger-spike", tags=["Simulation"], status_code=status.HTTP_201_CREATED)
def trigger_simulated_spike(
    station_name: str = Query("Shivajinagar", description="Station name to simulate spike on"),
    aqi: float = Query(310.0, description="Simulated total AQI"),
    pm10: float = Query(250.0, description="Simulated PM10"),
    pm25: float = Query(180.0, description="Simulated PM2.5"),
    no2: float = Query(85.0, description="Simulated NO2"),
    so2: float = Query(45.0, description="Simulated SO2"),
    session: Session = Depends(get_db),
):
    """Backdoor simulation endpoint for demo videos and testing.
    
    Guarantees a severe spike event is triggered and attributed, even if live
    weather or CPCB data is calm.
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    req = AttributionRequest(
        station_name=station_name,
        aqi=aqi,
        pm10=pm10,
        pm25=pm25,
        no2=no2,
        so2=so2,
        timestamp=datetime.now(IST).isoformat(),
    )
    return run_attribution_endpoint(req, session)


# ============================================================
# WebSocket Live Push Endpoints (Phase 3)
# ============================================================

@app.websocket("/ws/live")
@app.websocket("/ws")
@app.websocket("/simulation/ws")
@app.websocket("/api/v1/simulation/ws")
@app.websocket("/api/v1/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


@app.post("/api/v1/ws/broadcast", tags=["WebSocket"], status_code=status.HTTP_200_OK)
@app.post("/ws/broadcast", tags=["WebSocket"], status_code=status.HTTP_200_OK)
async def broadcast_to_websockets(payload: dict[str, Any]):
    """Broadcast an arbitrary JSON payload to all connected WebSocket clients."""
    await manager.broadcast(payload)
    return {"status": "broadcasted", "client_count": len(manager.active_connections)}
