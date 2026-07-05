"""Demo Scenario Seeding Script — Task 8.

Clears existing runtime telemetry and seeds 4 clean demo scenario alerts
representing high-confidence attribution, ambiguity flags, countdown pre-alerts,
and trilingual advisories.
"""
from __future__ import annotations

import sys
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---- path bootstrap -------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import SessionLocal, ping
from db.models import Alert, AqiReading, Station, WindData, PollutionSource
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from pipeline.attribution import run_attribution
from pipeline.forecasting import predict_upcoming_impacts

IST = timezone(timedelta(hours=5, minutes=30))


def _get_station_coords(session: SessionLocal, station: Station) -> tuple[float, float]:
    from geoalchemy2 import functions as gfunc
    lon, lat = session.execute(
        select(gfunc.ST_X(station.geom), gfunc.ST_Y(station.geom))
    ).one()
    return float(lon), float(lat)


def _seed_custom_sources(session: SessionLocal) -> None:
    """Seed custom sources specifically to trigger Scenario 2 (Ambiguity)."""
    # We add two identical construction sites at similar distance/bearing near Karve Road
    sources = [
        {
            "name": "Kothrud Metro Phase-II Yard",
            "type": "construction",
            "geom": WKTElement(
                "POLYGON((73.8180 18.5080, 73.8210 18.5080, 73.8210 18.5050, 73.8180 18.5050, 73.8180 18.5080))",
                srid=4326
            ),
            "schedule_start": dtime(9, 0),
            "schedule_end": dtime(18, 0),
            "near_school": False,
            "near_hospital": False,
        },
        {
            "name": "Kothrud Flyover Construction Site",
            "type": "construction",
            "geom": WKTElement(
                "POLYGON((73.8180 18.5140, 73.8210 18.5140, 73.8210 18.5110, 73.8180 18.5110, 73.8180 18.5140))",
                srid=4326
            ),
            "schedule_start": dtime(9, 0),
            "schedule_end": dtime(18, 0),
            "near_school": False,
            "near_hospital": False,
        }
    ]

    for data in sources:
        exists = session.execute(
            select(PollutionSource).where(PollutionSource.name == data["name"])
        ).scalars().first()
        if not exists:
            src = PollutionSource(**data)
            session.add(src)
    session.flush()


def main() -> int:
    if not ping():
        print("Error: Database not reachable. Start Docker first.")
        return 1

    print("=" * 60)
    print("SEEDING DEMO SCENARIOS FOR FRONTEND VISUALIZATION")
    print("=" * 60)

    session = SessionLocal()
    try:
        # Clear existing logs for a clean demo experience
        print("Clearing past alerts, wind data, and AQI readings...")
        session.execute(delete(Alert))
        session.execute(delete(WindData))
        session.execute(delete(AqiReading))
        session.commit()

        # Seed Kothrud ambiguity construction sites
        _seed_custom_sources(session)

        # Lookup Pune CPCB stations
        stations = {
            s.name: s for s in session.execute(select(Station)).scalars().all()
        }

        # ------------------------------------------------------------------
        # SCENARIO 1: Clear Single-Source Attribution (Shivajinagar)
        # ------------------------------------------------------------------
        print("\nSeeding Scenario 1: Clear Single-Source (Shivajinagar)...")
        sta_s1 = stations["Shivajinagar"]
        lon, lat = _get_station_coords(session, sta_s1)
        ts_s1 = datetime(2026, 6, 25, 10, 0, tzinfo=IST)

        # Add corresponding WindData
        w1 = WindData(
            station_id=str(sta_s1.id),
            timestamp=ts_s1,
            wind_speed_kmh=12.0,
            wind_direction_deg=310.0,
            temperature=28.5
        )
        session.add(w1)
        session.flush()

        res_s1 = run_attribution(
            session=session,
            station_lon=lon,
            station_lat=lat,
            station_name=sta_s1.name,
            spike_ts=ts_s1,
            aqi_value=310.0,
            dominant_pollutant="PM10",
            signature_class="crustal_dominant",
            wind_direction_deg=310.0,
            wind_speed_kmh=12.0,
        )

        # Build full contract payload structure
        payload_s1 = {
            "event_id": "demo-event-s1-uuid-1111",
            "event_severity": "critical",
            "pipeline_version": "3.1.0",
            "generated_at": ts_s1.isoformat(),
            "trigger_station": {
                "id": str(sta_s1.id),
                "name": sta_s1.name,
                "network": "CPCB_CAAQMS",
                "city": "Pune",
                "state": "Maharashtra",
                "elevation_m": 560,
                "coordinates": [lon, lat],
                "reading": {
                    "timestamp": ts_s1.isoformat(),
                    "total_aqi": 310.0,
                    "aqi_category": "Severe",
                    "dominant_pollutant": "PM10",
                    "chemical_fingerprint": {
                        "pm25_pm10_ratio": 0.384,
                        "so2_no2_ratio": 1.321,
                        "signature_class": "crustal_dominant"
                    }
                }
            },
            "weather_snapshot": {
                "source": "OpenWeatherMap",
                "observed_at": ts_s1.isoformat(),
                "wind_speed_kmh": 12.0,
                "wind_direction_deg": 310.0,
                "wind_direction_cardinal": "NW",
                "temperature_c": 28.5,
                "relative_humidity_pct": 65.0,
                "pressure_hpa": 1008.0,
                "cloud_cover_oktas": 4,
                "precipitation_mm_last_1h": 0.0,
                "visibility_km": 10.0,
                "mixing_layer_height_m": 850,
                "atmospheric_stability": {
                    "pasquill_class": "C",
                    "stability_label": "Slightly Unstable"
                }
            },
            **res_s1
        }

        alert_s1 = Alert(
            station_id=str(sta_s1.id),
            spike_time=ts_s1,
            aqi_value=310.0,
            dominant_pollutant="PM10",
            attribution_details=payload_s1,
            enforcement_priority=float(payload_s1["actionable_intelligence"]["enforcement_priority"])
        )
        session.add(alert_s1)

        # Update station summary
        sta_s1.last_aqi = 310.0; sta_s1.last_updated = ts_s1

        # ------------------------------------------------------------------
        # SCENARIO 2: Ambiguity Scenario (Karve Road)
        # ------------------------------------------------------------------
        print("Seeding Scenario 2: Ambiguity Flag (Karve Road)...")
        sta_s2 = stations["Karve Road"]
        lon2, lat2 = _get_station_coords(session, sta_s2)
        ts_s2 = datetime(2026, 6, 25, 10, 0, tzinfo=IST)

        w2 = WindData(
            station_id=str(sta_s2.id),
            timestamp=ts_s2,
            wind_speed_kmh=8.0,
            wind_direction_deg=280.0,
            temperature=27.0
        )
        session.add(w2)
        session.flush()

        res_s2 = run_attribution(
            session=session,
            station_lon=lon2,
            station_lat=lat2,
            station_name=sta_s2.name,
            spike_ts=ts_s2,
            aqi_value=220.0,
            dominant_pollutant="PM25",
            signature_class="mixed",
            wind_direction_deg=280.0,
            wind_speed_kmh=8.0,
        )

        payload_s2 = {
            "event_id": "demo-event-s2-uuid-2222",
            "event_severity": "high",
            "pipeline_version": "3.1.0",
            "generated_at": ts_s2.isoformat(),
            "trigger_station": {
                "id": str(sta_s2.id),
                "name": sta_s2.name,
                "network": "CPCB_CAAQMS",
                "city": "Pune",
                "state": "Maharashtra",
                "elevation_m": 560,
                "coordinates": [lon2, lat2],
                "reading": {
                    "timestamp": ts_s2.isoformat(),
                    "total_aqi": 220.0,
                    "aqi_category": "Very Poor",
                    "dominant_pollutant": "PM25",
                    "chemical_fingerprint": {
                        "pm25_pm10_ratio": 0.512,
                        "so2_no2_ratio": 0.812,
                        "signature_class": "mixed"
                    }
                }
            },
            "weather_snapshot": {
                "source": "OpenWeatherMap",
                "observed_at": ts_s2.isoformat(),
                "wind_speed_kmh": 8.0,
                "wind_direction_deg": 280.0,
                "wind_direction_cardinal": "W",
                "temperature_c": 27.0,
                "relative_humidity_pct": 70.0,
                "pressure_hpa": 1009.0,
                "cloud_cover_oktas": 5,
                "precipitation_mm_last_1h": 0.0,
                "visibility_km": 8.0,
                "mixing_layer_height_m": 600,
                "atmospheric_stability": {
                    "pasquill_class": "B",
                    "stability_label": "Moderately Unstable"
                }
            },
            **res_s2
        }

        alert_s2 = Alert(
            station_id=str(sta_s2.id),
            spike_time=ts_s2,
            aqi_value=220.0,
            dominant_pollutant="PM25",
            attribution_details=payload_s2,
            enforcement_priority=float(payload_s2["actionable_intelligence"]["enforcement_priority"])
        )
        session.add(alert_s2)

        sta_s2.last_aqi = 220.0; sta_s2.last_updated = ts_s2

        # ------------------------------------------------------------------
        # SCENARIO 3: Pre-Alert Countdown Trigger (Hadapsar)
        # ------------------------------------------------------------------
        print("Seeding Scenario 3: Pre-Alert Countdown (Hadapsar)...")
        # We seed a WindData record for Hadapsar at 8:30 AM.
        # This will trigger Hadapsar Magarpatta Flyover Works (starts at 9:00 AM) to alert
        sta_s3 = stations["Hadapsar"]
        lon3, lat3 = _get_station_coords(session, sta_s3)
        ts_s3 = datetime(2026, 6, 25, 8, 30, tzinfo=IST)

        w3 = WindData(
            station_id=str(sta_s3.id),
            timestamp=ts_s3,
            wind_speed_kmh=15.0,
            wind_direction_deg=310.0,   # wind from NW carrying flyover works emissions
            temperature=26.0
        )
        session.add(w3)

        sta_s3.last_aqi = 90.0; sta_s3.last_updated = ts_s3

        # ------------------------------------------------------------------
        # SCENARIO 4: Multi-Language Advisories (Katraj)
        # ------------------------------------------------------------------
        print("Seeding Scenario 4: Multi-Language Advisories (Katraj)...")
        sta_s4 = stations["Katraj"]
        lon4, lat4 = _get_station_coords(session, sta_s4)
        ts_s4 = datetime(2026, 6, 25, 10, 0, tzinfo=IST)

        # Seed wind from 180 degrees (South) so Katraj Hillock (waste burning) is upwind
        w4 = WindData(
            station_id=str(sta_s4.id),
            timestamp=ts_s4,
            wind_speed_kmh=10.0,
            wind_direction_deg=180.0,
            temperature=29.0
        )
        session.add(w4)
        session.flush()

        res_s4 = run_attribution(
            session=session,
            station_lon=lon4,
            station_lat=lat4,
            station_name=sta_s4.name,
            spike_ts=ts_s4,
            aqi_value=340.0,
            dominant_pollutant="CO",
            signature_class="biomass_burning",
            wind_direction_deg=180.0,
            wind_speed_kmh=10.0,
        )

        payload_s4 = {
            "event_id": "demo-event-s4-uuid-4444",
            "event_severity": "critical",
            "pipeline_version": "3.1.0",
            "generated_at": ts_s4.isoformat(),
            "trigger_station": {
                "id": str(sta_s4.id),
                "name": sta_s4.name,
                "network": "CPCB_CAAQMS",
                "city": "Pune",
                "state": "Maharashtra",
                "elevation_m": 560,
                "coordinates": [lon4, lat4],
                "reading": {
                    "timestamp": ts_s4.isoformat(),
                    "total_aqi": 340.0,
                    "aqi_category": "Severe",
                    "dominant_pollutant": "CO",
                    "chemical_fingerprint": {
                        "pm25_pm10_ratio": 0.712,
                        "so2_no2_ratio": 0.512,
                        "signature_class": "biomass_burning"
                    }
                }
            },
            "weather_snapshot": {
                "source": "OpenWeatherMap",
                "observed_at": ts_s4.isoformat(),
                "wind_speed_kmh": 10.0,
                "wind_direction_deg": 180.0,
                "wind_direction_cardinal": "S",
                "temperature_c": 29.0,
                "relative_humidity_pct": 58.0,
                "pressure_hpa": 1010.0,
                "cloud_cover_oktas": 3,
                "precipitation_mm_last_1h": 0.0,
                "visibility_km": 10.0,
                "mixing_layer_height_m": 900,
                "atmospheric_stability": {
                    "pasquill_class": "B",
                    "stability_label": "Moderately Unstable"
                }
            },
            **res_s4
        }

        alert_s4 = Alert(
            station_id=str(sta_s4.id),
            spike_time=ts_s4,
            aqi_value=340.0,
            dominant_pollutant="CO",
            attribution_details=payload_s4,
            enforcement_priority=float(payload_s4["actionable_intelligence"]["enforcement_priority"])
        )
        session.add(alert_s4)

        sta_s4.last_aqi = 340.0; sta_s4.last_updated = ts_s4

        session.commit()
        print("\nAll 4 scenarios seeded successfully! DB is ready for live demo.")

    except Exception as e:
        session.rollback()
        print(f"Error seeding demo scenarios: {e}")
        import traceback; traceback.print_exc()
        return 1
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
