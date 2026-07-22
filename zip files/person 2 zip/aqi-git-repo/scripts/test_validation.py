"""Unit + integration tests for Task 5 (Gap 5) validation and structured logging.

Validates:
  - Input telemetry validators offline (negative value, calm wind, out of range).
  - Structured pipeline runs logger appending JSON entries to pipeline.log.
  - Early-exit error handling when run_attribution is called with invalid parameters.
  - Live HTTP API returns HTTP 422 for invalid telemetry.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---- path bootstrap -------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.validators import validate_aqi, validate_wind, validate_pollutant_reading
from pipeline.pipeline_logger import log_pipeline_run
from pipeline.attribution import run_attribution
from db.connection import get_session, ping
from db.models import Station
from sqlalchemy import select

PASS = FAIL = 0


def ok(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        print(f"  [ok  ] {msg}")
        PASS += 1
    else:
        print(f"  [FAIL] {msg}")
        FAIL += 1


# ============================================================
print("\n=== Offline Telemetry Validators ===")

# AQI checks
ok(not validate_aqi(-999).is_valid, "AQI -999 (sensor error) is invalid")
ok(not validate_aqi(0).is_valid, "AQI 0 (offline) is invalid")
ok(validate_aqi(310).is_valid, "AQI 310 is valid")
res = validate_aqi(550)
ok(res.is_valid and "Severe" in res.reason, f"AQI 550 is valid but flagged: {res.reason}")
ok(not validate_aqi("corrupted").is_valid, "Non-numeric AQI is invalid")

# Wind checks
ok(not validate_wind(10, 450).is_valid, "Wind direction 450 degrees is invalid")
ok(not validate_wind(-5, 180).is_valid, "Negative wind speed is invalid")
res_calm = validate_wind(0.2, 180)
ok(res_calm.is_valid and "Calm" in res_calm.reason, f"Calm wind is valid but noted: {res_calm.reason}")
ok(validate_wind(15.5, 290).is_valid, "Normal wind (15.5 km/h, 290 deg) is valid")

# Pollutant checks
ok(validate_pollutant_reading("pm25", 80.0).is_valid, "PM2.5 80.0 is valid")
res_high = validate_pollutant_reading("pm10", 2500.0)
ok(res_high.is_valid and "Out of typical range" in res_high.reason, f"PM10 2500.0 is valid but flagged: {res_high.reason}")
ok(not validate_pollutant_reading("so2", -10).is_valid, "Negative pollutant reading is invalid")
ok(not validate_pollutant_reading("no2", "bad_data").is_valid, "Non-numeric pollutant is invalid")


# ============================================================
print("\n=== Structured Logger (pipeline.log) ===")
# Remove existing log for clean test
log_file = PROJECT_ROOT / "pipeline.log"
if log_file.exists():
    try:
        os.remove(log_file)
    except OSError:
        pass

spike_data = {
    "station_id": "test-uuid-1234",
    "station_name": "Hadapsar",
    "aqi": 340,
    "dominant_pollutant": "PM10",
    "wind_speed": 12.5,
    "wind_direction": 270,
}

results = {
    "cone_angle": 60,
    "search_radius_m": 2500,
    "total_sources": 12,
    "spatial_count": 5,
    "cone_count": 2,
    "chemical_count": 1,
    "candidate_count": 1,
    "primary_source": "Hadapsar Industrial Estate",
    "confidence": 0.85,
    "ambiguous": False,
    "total_ms": 42,
    "spatial_ms": 15,
    "cone_ms": 20,
    "scoring_ms": 7,
    "warnings": ["CO: Out of typical range — flagged"],
}

log_pipeline_run(spike_data, results)

ok(log_file.exists(), "pipeline.log was created")
if log_file.exists():
    log_content = log_file.read_text(encoding="utf-8")
    ok("PIPELINE_RUN | {" in log_content, "Log file contains structured PIPELINE_RUN prefix")
    ok("Hadapsar Industrial Estate" in log_content, "Log contains top candidate name")
    ok("total_ms" in log_content, "Log contains performance metric key")


# ============================================================
print("\n=== run_attribution early-exit check ===")
if not ping():
    print("  [SKIP] DB not reachable, skipping run_attribution unit test.")
else:
    with get_session() as session:
        # Pass invalid wind speed to trigger early exit
        res_error = run_attribution(
            session=session,
            station_lon=73.8440,
            station_lat=18.5308,
            station_name="Shivajinagar",
            spike_ts=datetime.now(timezone(timedelta(hours=5, minutes=30))),
            aqi_value=310.0,
            dominant_pollutant="PM10",
            signature_class="crustal_dominant",
            wind_direction_deg=450.0,  # invalid wind direction
            wind_speed_kmh=10.0,
        )
        ok("error" in res_error, f"run_attribution early exits with error: {res_error.get('error')}")
        ok(res_error.get("attribution") is None, "attribution is None on early exit")


# ============================================================
print("\n=== Live API validation error check (expect HTTP 422) ===")
BASE_URL = "http://localhost:5000"

try:
    # Send a POST with invalid telemetry (AQI = -999)
    req_body = {
        "station_name": "Shivajinagar",
        "aqi": -999.0, # invalid
        "pm25": 148.6,
        "timestamp": "2026-06-25T08:30:00+05:30",
    }
    data = json.dumps(req_body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/attribution/run",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        urllib.request.urlopen(req, timeout=10)
        ok(False, "API accepted invalid AQI (expected HTTP 422)")
    except urllib.error.HTTPError as e:
        ok(e.code == 422, f"API returned expected HTTP 422 validation error: {e.code}")
        body = json.loads(e.read().decode())
        detail = str(body.get("detail", ""))
        ok("greater_than" in detail or "Negative AQI" in detail, f"Error detail explains why: {detail}")

    # Send a POST with pm25 = -10.0 (bypasses Pydantic schema validation, triggers our custom validator)
    req_body_2 = {
        "station_name": "Shivajinagar",
        "aqi": 100.0,
        "pm25": -10.0,
        "timestamp": "2026-06-25T08:30:00+05:30",
    }
    data_2 = json.dumps(req_body_2).encode()
    req_2 = urllib.request.Request(
        f"{BASE_URL}/attribution/run",
        data=data_2,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req_2, timeout=10)
        ok(False, "API accepted invalid pm25 (expected HTTP 422)")
    except urllib.error.HTTPError as e:
        ok(e.code == 422, f"API returned expected HTTP 422 validation error: {e.code}")
        body_2 = json.loads(e.read().decode())
        detail_2 = str(body_2.get("detail", ""))
        ok("Negative pm25" in detail_2, f"Custom validator returned clean message: {detail_2}")

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
