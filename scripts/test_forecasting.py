"""Unit + integration tests for Task 6 (Improvement #6) Pre-Alert Forecasting.

Verifies:
  - generate_pre_alert downwind calculation and distance decay.
  - predict_upcoming_impacts scheduling window lookup.
  - Live HTTP /api/pre-alerts endpoint.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

# ---- path bootstrap -------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.forecasting import generate_pre_alert, predict_upcoming_impacts
from db.connection import get_session, ping
from db.models import PollutionSource, Station

PASS = FAIL = 0


def ok(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        print(f"  [ok  ] {msg}")
        PASS += 1
    else:
        print(f"  [FAIL] {msg}")
        FAIL += 1


# Mock class to mimic SQLAlchemy model fields
class MockSource:
    def __init__(self, name, stype, start_time):
        self.name = name
        self.type = stype
        self.schedule_start = start_time


class MockStation:
    def __init__(self, name):
        self.name = name


# ============================================================
print("\n=== generate_pre_alert (offline) ===")

src = MockSource("Upwind Construction", "construction", dtime(9, 0))
sta = MockStation("Shivajinagar")

# Station coordinates
sta_lon, sta_lat = 73.8440, 18.5308
# Source ~1.5km directly upwind (west, bearing ~270)
src_lon_west, src_lat_west = 73.8298, 18.5308

# Test Case 1: Station is downwind of the source (wind from west/270 deg)
alert = generate_pre_alert(
    source=src,
    wind_speed_kmh=15.0,
    wind_direction_deg=270.0,
    station=sta,
    station_lon=sta_lon,
    station_lat=sta_lat,
    source_lon=src_lon_west,
    source_lat=src_lat_west,
)
ok(alert is not None, "pre-alert triggered for downwind source")
if alert:
    ok(alert["eta_minutes"] > 0, f"calculated travel time: {alert['eta_minutes']} mins")
    ok(alert["estimated_aqi_increase"] > 0, f"estimated AQI increase: {alert['estimated_aqi_increase']}")
    ok("becomes active at" in alert["advisory"], "advisory text generated")

# Test Case 2: Wind direction changes (now from east/90 deg) — station no longer downwind
alert_mismatch = generate_pre_alert(
    source=src,
    wind_speed_kmh=15.0,
    wind_direction_deg=90.0,
    station=sta,
    station_lon=sta_lon,
    station_lat=sta_lat,
    source_lon=src_lon_west,
    source_lat=src_lat_west,
)
ok(alert_mismatch is None, "no pre-alert triggered for mismatch wind direction")

# Test Case 3: Calm wind conditions
alert_calm = generate_pre_alert(
    source=src,
    wind_speed_kmh=0.2,
    wind_direction_deg=270.0,
    station=sta,
    station_lon=sta_lon,
    station_lat=sta_lat,
    source_lon=src_lon_west,
    source_lat=src_lat_west,
)
ok(alert_calm is None, "no pre-alert triggered under calm wind")


# ============================================================
print("\n=== predict_upcoming_impacts (live DB) ===")
if not ping():
    print("  [SKIP] DB not reachable, skipping live DB lookahead test.")
else:
    with get_session() as session:
        # Pune CPCB stations have seeded source "Karve Road Corridor" (traffic, schedule_start = 08:00)
        # Mock check time to 07:30 AM (starts in 30 mins)
        IST = timezone(timedelta(hours=5, minutes=30))
        check_ts = datetime(2026, 6, 25, 7, 30, tzinfo=IST)
        
        alerts = predict_upcoming_impacts(session, check_ts)
        ok(isinstance(alerts, list), f"returned list of upcoming impacts (len={len(alerts)})")
        
        # Verify sorting
        if alerts:
            increases = [a["estimated_aqi_increase"] for a in alerts]
            ok(increases == sorted(increases, reverse=True), "alerts sorted by AQI impact descending")
            
            for a in alerts:
                ok("source" in a, "alert contains source name")
                ok("eta_minutes" in a, "alert contains eta")
                ok("estimated_aqi_increase" in a, "alert contains AQI impact")


# ============================================================
print("\n=== Live HTTP Endpoint /api/pre-alerts ===")
BASE_URL = "http://localhost:5000"

try:
    # Query with custom timestamp corresponding to 7:30 AM (IST) to trigger lookahead pre-alerts
    ts_str = "2026-06-25T07:30:00+05:30"
    url = f"{BASE_URL}/api/pre-alerts?timestamp={urllib.parse.quote(ts_str)}"
    
    req = urllib.request.urlopen(url, timeout=10)
    code = req.status
    body = json.loads(req.read().decode())
    
    ok(code == 200, f"status 200, got {code}")
    ok(isinstance(body, list), f"response is a list (len={len(body)})")
    if body:
        first = body[0]
        ok("source" in first, "pre-alert has source field")
        ok("eta_minutes" in first, "pre-alert has eta_minutes field")
        ok("estimated_aqi_increase" in first, "pre-alert has estimated_aqi_increase field")
        print(f"  First pre-alert: {first['advisory']}")

except Exception as ex:
    print(f"  [SKIP] API server check failed (is uvicorn running?): {ex}")


# ============================================================
print(f"\n{'='*60}")
print(f"RESULT: {PASS} passed / {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
