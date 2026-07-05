"""FastAPI application — full attribution pipeline endpoint (Prompt 2D).

Wires together all components (Task 1 + 2A–2D) into a single API that produces
the complete data-contract JSON response.

Now supports 4 demo scenarios:
  /api/v1/attribution/Shivajinagar  — Construction Spike (PM10)
  /api/v1/attribution/Swargate      — Traffic Corridor (NO2)
  /api/v1/attribution/Hadapsar      — Industrial / Factory (SO2)
  /api/v1/attribution/Kothrud       — Ambiguity / Multi-source (PM2.5)

Start with::

    uvicorn app.api:app --reload --port 8000
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .demo_scenarios import get_scenario, list_scenario_names

app = FastAPI(
    title="Air Quality Attribution Engine",
    version="3.1.0",
    description="CPCB AQI spike attribution with wind-cone analysis and source ranking.",
)

# CORS — allow all origins for hackathon demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok", "version": "3.1.0"}


# --------------------------------------------------------------------------- #
# Dry-run helpers (mock path, no DB)
# --------------------------------------------------------------------------- #
def _dry_run_attribution(station_name: str, target_time: datetime = None) -> dict:
    """Build the full contract response from mock data, no PostGIS required.

    Uses the per-station DemoScenario profile to generate unique data for
    each of the 4 demo stations.
    """
    scenario = get_scenario(station_name)
    settings = get_settings()
    tz = ZoneInfo(settings.tz)

    if target_time is None:
        h, m = scenario.spike_local_time.split(":")
        spike_local = datetime.now(tz=tz).replace(
            hour=int(h), minute=int(m), second=0, microsecond=0
        )
        spike_utc = spike_local.astimezone(timezone.utc)
        local_hour = int(h) + int(m) / 60.0
    else:
        spike_local = target_time.astimezone(tz)
        spike_utc = target_time.astimezone(timezone.utc)
        local_hour = spike_local.hour + spike_local.minute / 60.0

    # --- trigger_station (Task 1) ----------------------------------------
    from .contract import build_trigger_station_block
    from .models import Station, make_point_ewkt
    from .pipeline import PipelineController
    from .sources import get_source

    mock_aq = get_source(
        "mock",
        target_spike_aqi=scenario.spike_aqi,
        spike_local_hour=local_hour,
        base_profile=scenario.base_profile,
        peak_ratios=scenario.peak_ratios,
        dominant_override=scenario.dominant_pollutant,
    )
    controller = PipelineController(source=mock_aq)
    raw_aq = mock_aq._reading_for(scenario.station_name, spike_utc)
    reading, _ = controller.ingest_reading(raw_aq)
    if reading is None:
        raise HTTPException(500, "Mock AQ reading failed validation")

    lon, lat = scenario.coordinates
    station = Station(
        name=scenario.station_name,
        network=scenario.network,
        city=scenario.city,
        state=scenario.state,
        elevation_m=scenario.elevation_m,
        geom=make_point_ewkt(lon, lat),
    )
    station.id = uuid.uuid4()

    trigger_block = build_trigger_station_block(station, reading, tz_name=settings.tz)

    # --- weather_snapshot (2A) -------------------------------------------
    from .pasquill import classify_stability
    from .weather_contract import build_weather_snapshot
    from .weather_sources.mock import MockIMDSource

    # Create a per-scenario weather source with the scenario's weather values.
    weather_src = MockIMDSource(
        scenario_local_hour=local_hour,
        base=dict(scenario.weather_overrides),
        scenario_values=dict(scenario.weather_overrides),
    )
    raw_weather = weather_src.fetch_snapshot(scenario.station_name, spike_utc)
    if raw_weather is None:
        raise HTTPException(500, "Mock weather snapshot returned None")

    obs_dict = raw_weather.to_dict()
    is_daytime = 6 <= spike_local.hour < 18
    pasquill_result = classify_stability(
        obs_dict["wind_speed_kmh"],
        obs_dict["cloud_cover_oktas"],
        is_daytime=is_daytime,
        solar_elevation_deg=30.0,
    )
    weather_block = build_weather_snapshot(obs_dict, pasquill_result)

    # --- wind_cone_geometry (2B) -----------------------------------------
    from .cone_builder import build_wind_cone as build_cone

    wind_cone_block = build_cone(
        station_lon=lon,
        station_lat=lat,
        wind_direction_deg=obs_dict["wind_direction_deg"],
        wind_speed_kmh=obs_dict["wind_speed_kmh"],
        station_name=scenario.station_name,
        cloud_cover_oktas=obs_dict.get("cloud_cover_oktas", 4),
        is_daytime=is_daytime,
    )

    # --- ranked_candidates (2C) ------------------------------------------
    from .ranker import rank_candidates
    from .config import load_city_config
    
    # 1. Curated candidates
    candidates = copy.deepcopy(scenario.candidates)
    
    # 2. Add OSM-discovered candidates
    try:
        cfg = load_city_config()
        from .overpass_client import discover_and_format
        osm_sources = discover_and_format(cfg)
        
        # Merge avoiding exact name duplicates
        seen_names = {c["name"] for c in candidates}
        for osm_cand in osm_sources:
            if osm_cand["name"] not in seen_names:
                candidates.append(osm_cand)
                seen_names.add(osm_cand["name"])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"OSM discovery failed during attribution: {e}")

    fingerprint = reading.chemical_fingerprint()
    half_angle = wind_cone_block["properties"]["half_angle_deg"]
    max_range = wind_cone_block["properties"]["reach_km"]

    ranked = rank_candidates(
        candidates=candidates,
        station_coords=(lon, lat),
        wind_direction=obs_dict["wind_direction_deg"],
        half_angle=half_angle,
        max_range_km=max_range,
        chemical_fingerprint=fingerprint,
        event_time=scenario.spike_local_time,
    )

    # --- actionable_intelligence (2D) ------------------------------------
    from .intelligence import build_actionable_intelligence

    intel_block = build_actionable_intelligence(
        ranked_candidates=ranked,
        station_name=scenario.station_name,
        aqi=reading.total_aqi,
        dominant_pollutant=reading.dominant_pollutant,
    )

    # Override field_team from scenario
    intel_block["field_team_assignment"] = scenario.field_team

    # --- Assemble full contract ------------------------------------------
    return {
        "event_id": str(uuid.uuid4()),
        "event_severity": "critical" if reading.total_aqi >= 300 else "moderate",
        "pipeline_version": "3.1.0",
        "generated_at": datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]
        + "Z",
        "trigger_station": trigger_block,
        "weather_snapshot": weather_block,
        "wind_cone_geometry": wind_cone_block,
        "ranked_candidates": ranked,
        "actionable_intelligence": intel_block,
        "pre_alerts": scenario.pre_alerts,
    }


# --------------------------------------------------------------------------- #
# Main attribution endpoint
# --------------------------------------------------------------------------- #
@app.get("/api/v1/attribution/{station_name}")
def get_attribution(station_name: str):
    """Full attribution pipeline for a station.

    Supports: Shivajinagar, Swargate, Hadapsar, Kothrud.
    In mock / dry-run mode (no PostGIS), the entire pipeline runs from
    deterministic mock sources. With a live DB, reads persisted data.
    """
    settings = get_settings()

    # Always use mock/dry-run for now (hackathon demo).
    # For live DB path, we'd query Station, latest reading, etc.
    if settings.is_sqlite or settings.aq_source == "mock":
        return _dry_run_attribution(station_name)

    # Live DB path (PostGIS).
    try:
        return _live_attribution(station_name)
    except Exception as exc:
        # Fallback to dry-run if DB is not available.
        return _dry_run_attribution(station_name)


def _live_attribution(station_name: str) -> dict:
    """DB-backed attribution (PostGIS). Falls back to dry-run on failure."""
    # For now, delegate to dry-run. A full implementation would query
    # the DB for station, latest reading, weather observations, etc.
    return _dry_run_attribution(station_name)


# --------------------------------------------------------------------------- #
# Station list + readings
# --------------------------------------------------------------------------- #
@app.get("/api/v1/stations")
def list_stations():
    """List all known demo stations."""
    from .demo_scenarios import _SCENARIOS

    stations = []
    for scenario in _SCENARIOS.values():
        stations.append({
            "name": scenario.station_name,
            "city": scenario.city,
            "state": scenario.state,
            "network": scenario.network,
            "coordinates": list(scenario.coordinates),
            "elevation_m": scenario.elevation_m,
            "spike_aqi": scenario.spike_aqi,
            "dominant_pollutant": scenario.dominant_pollutant,
            "scenario_type": _scenario_label(scenario.station_name),
        })
    return {"stations": stations}


def _scenario_label(name: str) -> str:
    """Human-friendly scenario description for the frontend."""
    labels = {
        "Shivajinagar": "Construction Spike (PM10)",
        "Swargate": "Heavy Traffic Corridor (NO2)",
        "Hadapsar": "Industrial Emission (SO2)",
        "Kothrud": "Ambiguity — Multi-Source (PM2.5)",
    }
    return labels.get(name, "Unknown Scenario")


@app.get("/api/v1/stations/{station_name}/readings")
def get_readings(station_name: str, limit: int = Query(default=96, ge=1, le=1000)):
    """Recent AQI readings for a station (mock path)."""
    scenario = get_scenario(station_name)
    settings = get_settings()
    tz = ZoneInfo(settings.tz)

    from .sources import get_source
    from .pipeline import PipelineController

    h, m = scenario.spike_local_time.split(":")
    mock = get_source(
        "mock",
        target_spike_aqi=scenario.spike_aqi,
        spike_local_hour=int(h) + int(m) / 60.0,
        base_profile=scenario.base_profile,
        peak_ratios=scenario.peak_ratios,
        dominant_override=scenario.dominant_pollutant,
    )
    controller = PipelineController(source=mock)

    now_local = datetime.now(tz=tz).replace(second=0, microsecond=0)
    from datetime import timedelta

    readings = []
    for i in range(min(limit, 96)):
        ts = now_local - timedelta(minutes=15 * i)
        ts_utc = ts.astimezone(timezone.utc)
        raw = mock._reading_for(scenario.station_name, ts_utc)
        reading, report = controller.ingest_reading(raw)
        if reading is not None:
            readings.append({
                "timestamp": ts.isoformat(),
                "total_aqi": reading.total_aqi,
                "aqi_category": reading.aqi_category,
                "dominant_pollutant": reading.dominant_pollutant,
            })

    return {"station": scenario.station_name, "count": len(readings), "readings": readings}


# --------------------------------------------------------------------------- #
# Wind Cone endpoint (Spatial — Person 2)
# --------------------------------------------------------------------------- #
@app.get("/api/v1/cone/{station_name}", tags=["Spatial"])
def wind_cone_endpoint(
    station_name: str,
    wind_dir: float = Query(default=None, description="Override wind direction (deg)"),
    wind_speed: float = Query(default=None, description="Override wind speed (km/h)"),
):
    """Return the wind cone GeoJSON for a station.

    If wind_dir/wind_speed are not provided, uses the scenario defaults.
    Useful for the replay timeline (Person 3) and ad-hoc queries.
    """
    from .cone_builder import build_wind_cone

    scenario = get_scenario(station_name)
    lon, lat = scenario.coordinates
    w = scenario.weather_overrides

    direction = wind_dir if wind_dir is not None else w.get("wind_direction_deg", 290)
    speed = wind_speed if wind_speed is not None else w.get("wind_speed_kmh", 14.5)
    cloud = int(w.get("cloud_cover_oktas", 4))

    cone = build_wind_cone(
        station_lon=lon,
        station_lat=lat,
        wind_direction_deg=direction,
        wind_speed_kmh=speed,
        station_name=scenario.station_name,
        cloud_cover_oktas=cloud,
    )
    return cone


# --------------------------------------------------------------------------- #
# Overpass-discovered + curated sources endpoint (Person 2)
# --------------------------------------------------------------------------- #
@app.get("/api/v1/sources", tags=["Spatial"])
def list_sources():
    """Return all known pollution sources (curated + OSM-discovered).

    Tries to run Overpass discovery against the city bbox. If the API is
    unreachable (offline / rate-limited), returns just the curated sources
    from the demo scenarios.
    """
    from .config import load_city_config

    sources = []

    # 1. Curated sources from demo scenarios
    from .demo_scenarios import _SCENARIOS
    seen_names: set[str] = set()
    for scenario in _SCENARIOS.values():
        for cand in scenario.candidates:
            if cand["name"] not in seen_names:
                seen_names.add(cand["name"])
                sources.append({
                    "name": cand["name"],
                    "source_type": cand.get("type", "unknown"),
                    "source_origin": "curated",
                    "geometry": cand.get("geometry"),
                    "description": cand.get("type", ""),
                })

    # 2. Try OSM discovery (best-effort, non-blocking)
    try:
        cfg = load_city_config()
        from .overpass_client import discover_and_format
        osm_sources = discover_and_format(cfg)
        for s in osm_sources:
            if s["name"] not in seen_names:
                seen_names.add(s["name"])
                sources.append(s)
    except Exception:
        pass  # Offline or rate-limited — return curated only

    return {
        "count": len(sources),
        "sources": sources,
    }


# --------------------------------------------------------------------------- #
# Timeline History Replay System (Phase 2 — Person 1)
# --------------------------------------------------------------------------- #
@app.get("/api/v1/timeline/{station_name}", tags=["Replay"])
def get_timeline(station_name: str):
    """Return an array of 24 hourly tick objects for the replay slider."""
    scenario = get_scenario(station_name)
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    
    from .sources import get_source
    from .pipeline import PipelineController
    from .weather_sources.mock import MockIMDSource
    
    h, m = scenario.spike_local_time.split(":")
    mock_aq = get_source(
        "mock",
        target_spike_aqi=scenario.spike_aqi,
        spike_local_hour=int(h) + int(m) / 60.0,
        base_profile=scenario.base_profile,
        peak_ratios=scenario.peak_ratios,
        dominant_override=scenario.dominant_pollutant,
    )
    controller = PipelineController(source=mock_aq)
    
    now_local = datetime.now(tz=tz).replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta
    
    ticks = []
    # Generate 24 hours (from 23 hours ago to now)
    for i in range(24):
        ts = now_local - timedelta(hours=23 - i)
        ts_utc = ts.astimezone(timezone.utc)
        
        # Get AQI
        raw_aq = mock_aq._reading_for(scenario.station_name, ts_utc)
        reading, _ = controller.ingest_reading(raw_aq)
        
        # Get Weather for wind
        weather_src = MockIMDSource(
            scenario_local_hour=ts.hour + ts.minute / 60.0,
            base=dict(scenario.weather_overrides),
            scenario_values=dict(scenario.weather_overrides),
        )
        raw_weather = weather_src.fetch_snapshot(scenario.station_name, ts_utc)
        
        aqi = reading.total_aqi if reading else 50
        dominant = reading.dominant_pollutant if reading else "pm10"
        wind_dir = raw_weather.wind_direction_deg if raw_weather else 180
        wind_speed = raw_weather.wind_speed_kmh if raw_weather else 5.0
        
        # A spike is defined if AQI >= 150
        was_spike = aqi >= 150
        
        ticks.append({
            "timestamp": ts.isoformat(),
            "aqi": aqi,
            "was_spike": was_spike,
            "dominant_pollutant": dominant.upper(),
            "wind_dir": wind_dir,
            "wind_speed": wind_speed
        })
        
    return ticks


@app.get("/api/v1/replay/{station_name}", tags=["Replay"])
def get_replay(station_name: str, timestamp: str = Query(..., description="ISO-8601 timestamp")):
    """Full attribution pipeline reconstructed for a historical hour."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO-8601 timestamp format")
    
    return _dry_run_attribution(station_name, target_time=dt)


# --------------------------------------------------------------------------- #
# Simulation / Demo Backdoor (Risk Mitigation — Person 2)
# --------------------------------------------------------------------------- #
@app.post("/api/v1/simulation/trigger-spike", tags=["Simulation"])
def trigger_spike(
    station_name: str = Query(default="Shivajinagar"),
    spike_aqi: int = Query(default=310, ge=100, le=600),
    dominant_pollutant: str = Query(default=None),
    scenario_type: str = Query(default=None, description="construction|traffic|industrial|ambiguity"),
):
    """Manually trigger a simulated AQI spike for demo purposes.

    This is a **risk mitigation** endpoint for the hackathon demo: if July 22
    has clean air and no natural spike occurs, this endpoint lets us manually
    inject a high-AQI event and run the full attribution funnel.

    The response is identical to ``/api/v1/attribution/{station_name}`` — the
    complete 6-block data contract.

    Parameters
    ----------
    station_name : str
        Station to simulate the spike at (must be a known demo station).
    spike_aqi : int
        Target AQI value for the simulated spike (100–600).
    dominant_pollutant : str, optional
        Override the dominant pollutant (pm10/pm25/no2/so2). If not set,
        uses the scenario's default.
    scenario_type : str, optional
        Human-readable scenario label for the frontend.
    """
    from .demo_scenarios import DemoScenario, _SCENARIOS

    # Validate station exists
    scenario = get_scenario(station_name)

    # Allow AQI override
    if spike_aqi != scenario.spike_aqi:
        # Create a modified scenario with the custom AQI
        import dataclasses
        overrides = {"spike_aqi": spike_aqi}
        if dominant_pollutant:
            overrides["dominant_pollutant"] = dominant_pollutant
        scenario = dataclasses.replace(scenario, **overrides)

    # Run the full attribution pipeline with the (possibly overridden) scenario
    settings = get_settings()
    tz = ZoneInfo(settings.tz)

    h, m = scenario.spike_local_time.split(":")
    spike_local = datetime.now(tz=tz).replace(
        hour=int(h), minute=int(m), second=0, microsecond=0
    )
    spike_utc = spike_local.astimezone(timezone.utc)

    from .contract import build_trigger_station_block
    from .models import Station, make_point_ewkt
    from .pipeline import PipelineController
    from .sources import get_source

    mock_aq = get_source(
        "mock",
        target_spike_aqi=scenario.spike_aqi,
        spike_local_hour=int(h) + int(m) / 60.0,
        base_profile=scenario.base_profile,
        peak_ratios=scenario.peak_ratios,
        dominant_override=scenario.dominant_pollutant,
    )
    controller = PipelineController(source=mock_aq)
    raw_aq = mock_aq._reading_for(scenario.station_name, spike_utc)
    reading, report = controller.ingest_reading(raw_aq)

    if reading is None:
        raise HTTPException(500, f"Simulated spike ingestion failed: {report}")

    station = Station(
        name=scenario.station_name,
        network=scenario.network,
        city=scenario.city,
        state=scenario.state,
        elevation_m=scenario.elevation_m,
        geom=make_point_ewkt(*scenario.coordinates),
    )

    trigger_block = build_trigger_station_block(station, reading, tz_name=settings.tz)

    # Weather
    from .pasquill import classify_stability
    from .weather_contract import build_weather_snapshot
    from .weather_sources.mock import MockIMDSource

    weather_src = MockIMDSource(
        scenario_local_hour=int(h) + int(m) / 60.0,
        base=dict(scenario.weather_overrides),
        scenario_values=dict(scenario.weather_overrides),
    )
    raw_weather = weather_src.fetch_snapshot(scenario.station_name, spike_utc)
    if raw_weather is None:
        raise HTTPException(500, "Mock weather snapshot returned None")

    obs_dict = raw_weather.to_dict()
    is_daytime = 6 <= spike_local.hour < 18
    stability = classify_stability(
        wind_speed_kmh=obs_dict["wind_speed_kmh"],
        cloud_cover_oktas=obs_dict.get("cloud_cover_oktas", 4),
        is_daytime=is_daytime,
        solar_elevation_deg=obs_dict.get("solar_elevation_deg", 30.0),
    )
    weather_snapshot = build_weather_snapshot(obs_dict, stability)

    # Wind cone — use new cone_builder
    from .cone_builder import build_wind_cone as build_cone
    wind_cone = build_cone(
        station_lon=scenario.coordinates[0],
        station_lat=scenario.coordinates[1],
        wind_direction_deg=obs_dict["wind_direction_deg"],
        wind_speed_kmh=obs_dict["wind_speed_kmh"],
        station_name=scenario.station_name,
        cloud_cover_oktas=obs_dict.get("cloud_cover_oktas", 4),
        is_daytime=is_daytime,
    )

    # Ranked candidates
    from .ranker import rank_candidates
    from .config import load_city_config
    
    candidates = copy.deepcopy(scenario.candidates)
    try:
        cfg = load_city_config()
        from .overpass_client import discover_and_format
        osm_sources = discover_and_format(cfg)
        seen_names = {c["name"] for c in candidates}
        for osm_cand in osm_sources:
            if osm_cand["name"] not in seen_names:
                candidates.append(osm_cand)
                seen_names.add(osm_cand["name"])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"OSM discovery failed in trigger_spike: {e}")

    ranked = rank_candidates(
        candidates=candidates,
        station_coords=scenario.coordinates,
        wind_direction=obs_dict["wind_direction_deg"],
        half_angle=wind_cone["properties"]["half_angle_deg"],
        max_range_km=wind_cone["properties"]["reach_km"],
        chemical_fingerprint=reading.chemical_fingerprint(),
        event_time=scenario.spike_local_time,
    )

    # Intelligence
    from .intelligence import build_actionable_intelligence
    intelligence = build_actionable_intelligence(
        ranked_candidates=ranked,
        station_name=scenario.station_name,
        aqi=reading.total_aqi,
        dominant_pollutant=reading.dominant_pollutant,
    )
    # Override field_team from scenario
    intelligence["field_team_assignment"] = scenario.field_team

    return {
        "event_id": str(uuid.uuid4()),
        "event_severity": "critical" if reading.total_aqi >= 300 else "moderate",
        "pipeline_version": "3.1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "simulation": True,
        "simulation_params": {
            "requested_aqi": spike_aqi,
            "station": station_name,
            "dominant_pollutant": scenario.dominant_pollutant,
            "scenario_type": scenario_type or _scenario_label(station_name),
        },
        "trigger_station": trigger_block,
        "weather_snapshot": weather_snapshot,
        "wind_cone_geometry": wind_cone,
        "ranked_candidates": ranked,
        "actionable_intelligence": intelligence,
        "pre_alerts": scenario.pre_alerts,
    }

