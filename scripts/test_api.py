"""Integration tests for the Task 4 FastAPI REST API.

Runs against the live server at http://localhost:5000.
Requires the server to already be running (uvicorn api.main:app --port 5000)
and the database to be seeded.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://localhost:5000"

PASS = FAIL = 0


def ok(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        print(f"  [ok  ] {msg}")
        PASS += 1
    else:
        print(f"  [FAIL] {msg}")
        FAIL += 1


def get(path: str) -> tuple[int, dict]:
    try:
        req = urllib.request.urlopen(f"{BASE}{path}", timeout=10)
        return req.status, json.loads(req.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def post(path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# ============================================================
print("\n=== GET /health ===")
code, body = get("/health")
ok(code == 200, f"status 200, got {code}")
ok(body.get("status") == "ok", f"status == 'ok': {body.get('status')}")
ok(isinstance(body.get("db"), bool), f"db field is bool: {body.get('db')}")
ok("pipeline_version" in body, "has pipeline_version")
print(f"  DB connected: {body.get('db')}")

# ============================================================
print("\n=== GET /stations ===")
code, body = get("/stations")
ok(code == 200, f"status 200, got {code}")
ok(isinstance(body, list), f"response is a list (len={len(body)})")
ok(len(body) >= 1, f"at least 1 station returned")
if body:
    s = body[0]
    ok("id" in s, "station has id")
    ok("name" in s, "station has name")
    ok("coordinates" in s and len(s["coordinates"]) == 2, "station has [lon, lat]")

# ============================================================
print("\n=== GET /stations/BadName/latest-spike (expect 404) ===")
code, body = get("/stations/DoesNotExist/latest-spike")
ok(code == 404, f"status 404 for unknown station, got {code}")
ok("detail" in body, "404 has detail field")

# ============================================================
print("\n=== POST /attribution/run (below threshold — expect no spike) ===")
code, body = post("/attribution/run", {
    "station_name": "Shivajinagar",
    "aqi": 45.0,
    "pm25": 20.0,
    "pm10": 40.0,
    "no2": 15.0,
    "so2": 10.0,
    "co": 0.5,
    "o3": 20.0,
    "timestamp": "2026-06-25T10:00:00+05:30",
})
ok(code == 200, f"status 200 (no spike), got {code}")
ok(body.get("spike_detected") is False, f"spike_detected == False: {body.get('spike_detected')}")

# ============================================================
print("\n=== POST /attribution/run (HIGH AQI — expect spike + full payload) ===")
code, body = post("/attribution/run", {
    "station_name": "Shivajinagar",
    "aqi": 330.0,
    "pm25": 175.0,
    "pm10": 420.0,
    "no2": 78.0,
    "so2": 55.0,
    "co": 3.8,
    "o3": 45.0,
    "timestamp": "2026-06-25T08:30:00+05:30",
})

if code == 201:
    ok(True, f"status 201 (spike detected)")
    ok("event_id" in body, "payload has event_id")
    ok("event_severity" in body, "payload has event_severity")
    ok("trigger_station" in body, "payload has trigger_station")
    ok("weather_snapshot" in body, "payload has weather_snapshot")
    ok("wind_cone_geometry" in body, "payload has wind_cone_geometry")
    ok("ranked_candidates" in body, "payload has ranked_candidates")
    ok("actionable_intelligence" in body, "payload has actionable_intelligence")
    ok("pipeline_timings" in body, "payload has pipeline_timings")
    if "pipeline_timings" in body:
        ok("total_ms" in body["pipeline_timings"], "pipeline_timings has total_ms")

    ai = body.get("actionable_intelligence", {})
    ok("enforcement_priority" in ai, "actionable_intelligence has enforcement_priority")
    ok("localized_advisory" in ai, "actionable_intelligence has localized_advisory")
    ok("en" in ai.get("localized_advisory", {}), "advisory has English text")

    # Verify latest-spike now returns data
    print("\n=== GET /api/v1/attribution/Shivajinagar ===")
    code2, body2 = get("/api/v1/attribution/Shivajinagar")
    ok(code2 == 200, f"status 200 for latest-spike, got {code2}")
    ok("event_id" in body2, "latest-spike payload has event_id")
    ok("wind_cone_geometry" in body2, "latest-spike payload has wind_cone_geometry")
    ok("actionable_intelligence" in body2, "latest-spike payload has actionable_intelligence")
    ok("pre_alerts" in body2, "latest-spike payload has pre_alerts")
    if "pre_alerts" in body2:
        ok("source" in body2["pre_alerts"], "pre_alerts has source")
        ok("eta_minutes" in body2["pre_alerts"], "pre_alerts has eta_minutes")
elif code == 200:
    ok(False, "Expected spike (AQI 330), got 200 (no spike) — may need to clear history or re-seed")
else:
    ok(False, f"Expected 201, got {code}: {body}")

# ============================================================
print("\n=== GET /stations/Shivajinagar/alerts ===")
code, body = get("/stations/Shivajinagar/alerts")
ok(code == 200, f"status 200, got {code}")
ok(isinstance(body, list), f"response is a list")
if body:
    a = body[0]
    ok("id" in a, "alert has id")
    ok("spike_time" in a, "alert has spike_time")
    ok("aqi_value" in a, "alert has aqi_value")
    ok("enforcement_priority" in a, "alert has enforcement_priority")

# ============================================================
print("\n=== GET /attribution/sources ===")
code, body = get("/attribution/sources")
ok(code == 200, f"status 200, got {code}")
ok(body.get("type") == "FeatureCollection", "response is FeatureCollection")
features = body.get("features", [])
ok(len(features) >= 1, f"at least 1 source feature (got {len(features)})")

# ============================================================
print("\n=== GET /api/v1/timeline/Shivajinagar ===")
code, body = get("/api/v1/timeline/Shivajinagar")
ok(code == 200, f"status 200 for timeline, got {code}")
ok(isinstance(body, list), f"timeline response is a list (len={len(body)})")
ok(len(body) == 24, f"timeline returned 24 hourly ticks")
if body:
    t = body[0]
    ok("timestamp" in t, "tick has timestamp")
    ok("aqi" in t, "tick has aqi")
    ok("was_spike" in t, "tick has was_spike")
    ok("dominant_pollutant" in t, "tick has dominant_pollutant")
    ok("wind_dir" in t, "tick has wind_dir")
    ok("wind_speed" in t, "tick has wind_speed")

# ============================================================
print("\n=== GET /api/v1/replay/Shivajinagar ===")
code, body = get("/api/v1/replay/Shivajinagar?timestamp=2026-07-05T12:00:00+05:30")
ok(code == 200, f"status 200 for replay, got {code}")
ok("event_id" in body, "replay payload has event_id")
ok("wind_cone_geometry" in body, "replay payload has wind_cone_geometry")
ok("actionable_intelligence" in body, "replay payload has actionable_intelligence")
ok("pre_alerts" in body, "replay payload has pre_alerts")

# ============================================================
print("\n=== GET /api/v1/cone/Shivajinagar ===")
code, body = get("/api/v1/cone/Shivajinagar")
ok(code == 200, f"status 200 for cone, got {code}")
ok(body.get("type") == "Feature", "cone response is Feature")
ok("geometry" in body and body["geometry"].get("type") == "Polygon", "cone geometry is Polygon")
ok("properties" in body and body["properties"].get("cone_type") == "upwind_source_area", "cone has correct properties")

# ============================================================
print("\n=== POST /api/v1/ws/broadcast (Phase 3 WebSocket Live Push Hook) ===")
code, body = post("/api/v1/ws/broadcast", {"test_event": "spike_detected", "aqi": 340.0})
ok(code == 200, f"status 200 for ws broadcast, got {code}")
ok(body.get("status") == "broadcasted", f"status == 'broadcasted': {body.get('status')}")
ok("client_count" in body, "response has client_count")

# ============================================================
print(f"\n{'='*60}")
print(f"RESULT: {PASS} passed / {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
