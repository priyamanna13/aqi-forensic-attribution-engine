"""Pre-Alert Forecasting Engine — Task 6 (Improvement #6).

Finds pollution sources scheduled to become active in the next 2 hours,
performs wind-vector downwind alignment checks, and estimates travel times
and AQI increases.
"""
from __future__ import annotations

import math
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import PollutionSource, Station, WindData
from pipeline.attribution import _bearing_deg, _haversine_m, _source_representative_point
from pipeline.weather_client import WeatherClient

# Base estimated AQI increase for each source type
SOURCE_IMPACT_TABLE = {
    "construction": 80.0,
    "traffic": 50.0,
    "waste_burning": 60.0,
    "industrial": 40.0,
}


def _get_station_coords(session: Session, station: Station) -> tuple[float, float]:
    from geoalchemy2 import functions as gfunc
    lon, lat = session.execute(
        select(gfunc.ST_X(station.geom), gfunc.ST_Y(station.geom))
    ).one()
    return float(lon), float(lat)


def _get_station_wind(session: Session, station: Station, lon: float, lat: float) -> tuple[float, float]:
    """Get the latest wind speed (km/h) and direction (deg) for a station."""
    # Try database first
    stmt = (
        select(WindData)
        .where(WindData.station_id == str(station.id))
        .order_by(WindData.timestamp.desc())
        .limit(1)
    )
    w = session.execute(stmt).scalars().first()
    if w is not None:
        return w.wind_speed_kmh, w.wind_direction_deg

    # Fallback to live / cached OWM weather snapshot
    try:
        client = WeatherClient()
        snapshot = client.get_weather(lat=lat, lon=lon)
        return snapshot.wind_speed_kmh, snapshot.wind_direction_deg
    except Exception:
        # Default safety fallback (calm/moderate westerly wind)
        return 10.0, 270.0


def generate_pre_alert(
    source: PollutionSource,
    wind_speed_kmh: float,
    wind_direction_deg: float,
    station: Station,
    station_lon: float,
    station_lat: float,
    source_lon: float,
    source_lat: float,
) -> Optional[dict[str, Any]]:
    """Determine if a source poses a downwind risk to a station.

    If the source is upwind and wind is blowing towards the station, returns
    pre-alert details (ETA, expected AQI impact, advisory).
    """
    wind_speed_ms = wind_speed_kmh / 3.6
    if wind_speed_ms < 0.5:
        # Wind is too calm to have a reliable direction
        return None

    # Calculate distance and bearing from station to source
    distance_m = _haversine_m(station_lon, station_lat, source_lon, source_lat)

    # Bearing from station to source is the direction pointing towards the source.
    # Meteorological wind direction is the direction wind blows FROM.
    # If wind is blowing from the source to the station, then bearing_deg should
    # align with wind_direction_deg.
    bearing_deg = _bearing_deg(station_lon, station_lat, source_lon, source_lat)
    
    # Calculate angular difference
    diff = abs((bearing_deg - wind_direction_deg + 180) % 360 - 180)
    
    # Check if station is downwind of the source (within 45 degrees sector)
    if diff > 45.0:
        return None

    # Travel time (ETA)
    travel_time_min = (distance_m / wind_speed_ms) / 60.0

    # AQI impact calculation with distance decay (linear decay up to 3km)
    base_impact = SOURCE_IMPACT_TABLE.get(source.type, 40.0)
    distance_decay = max(0.3, 1.0 - (distance_m / 3000.0))
    estimated_impact = base_impact * distance_decay

    start_time_str = source.schedule_start.strftime("%H:%M") if source.schedule_start else "operating hours"

    advisory = (
        f"{source.name} becomes active at {start_time_str}. "
        f"Wind direction indicates AQI at {station.name} may increase "
        f"by ~{round(estimated_impact)} points in ~{round(travel_time_min)} minutes. "
        f"Recommend pre-emptive action."
    )

    return {
        "source": source.name,
        "type": source.type,
        "station": station.name,
        "distance_m": round(distance_m, 1),
        "bearing_deg": int(round(bearing_deg)),
        "eta_minutes": int(round(travel_time_min)),
        "estimated_aqi_increase": int(round(estimated_impact)),
        "schedule_start": start_time_str,
        "advisory": advisory,
    }


def predict_upcoming_impacts(session: Session, check_time: datetime) -> list[dict[str, Any]]:
    """Query scheduled sources starting in the next 2 hours and generate pre-alerts."""
    # Convert check_time to minutes since midnight for robust wrap-around logic
    local_time = check_time.time()
    current_mins = local_time.hour * 60 + local_time.minute
    window_end_mins = current_mins + 120  # 2 hours lookahead

    # Fetch all stations
    stations = session.execute(select(Station)).scalars().all()
    if not stations:
        return []

    # Fetch all sources
    sources = session.execute(select(PollutionSource)).scalars().all()
    pre_alerts = []

    for src in sources:
        if src.schedule_start is None:
            continue

        # Check if schedule_start falls within the [current_mins, current_mins + 120] window
        start_mins = src.schedule_start.hour * 60 + src.schedule_start.minute

        is_in_window = False
        if window_end_mins < 1440:
            is_in_window = current_mins <= start_mins <= window_end_mins
        else:
            # Wrap-around midnight
            is_in_window = (start_mins >= current_mins) or (start_mins <= window_end_mins % 1440)

        # 24/7 sources (like Bhosari MIDC starting at 00:00) should only alert if it is currently near midnight
        # Otherwise, they are already active and do not warrant an "upcoming active" alert
        if src.type == "industrial" and src.schedule_start == dtime(0, 0):
            # Only trigger if within the first 2 hours of the day
            if current_mins > 120:
                is_in_window = False

        if not is_in_window:
            continue

        # Find representative point coordinates
        src_lon, src_lat = _source_representative_point(src, session)

        # Evaluate against all stations
        for station in stations:
            sta_lon, sta_lat = _get_station_coords(session, station)
            
            # Fetch wind data
            wind_speed, wind_dir = _get_station_wind(session, station, sta_lon, sta_lat)
            
            alert_payload = generate_pre_alert(
                source=src,
                wind_speed_kmh=wind_speed,
                wind_direction_deg=wind_dir,
                station=station,
                station_lon=sta_lon,
                station_lat=sta_lat,
                source_lon=src_lon,
                source_lat=src_lat,
            )
            if alert_payload is not None:
                pre_alerts.append(alert_payload)

    # Sort by estimated AQI increase descending
    pre_alerts.sort(key=lambda x: x["estimated_aqi_increase"], reverse=True)
    return pre_alerts
