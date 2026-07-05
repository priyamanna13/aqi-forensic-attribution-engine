"""Quick test: verify all 4 demo station endpoints return distinct data."""
from app.api import app
from fastapi.testclient import TestClient

client = TestClient(app)

for name in ["Shivajinagar", "Swargate", "Hadapsar", "Kothrud"]:
    r = client.get(f"/api/v1/attribution/{name}")
    assert r.status_code == 200, f"{name} failed: {r.status_code}"
    d = r.json()
    ts = d["trigger_station"]
    reading = ts["reading"]
    pre = d["pre_alerts"]
    print(f"--- {name} ---")
    print(f"  AQI:        {reading['total_aqi']}")
    print(f"  Category:   {reading['aqi_category']}")
    print(f"  Dominant:   {reading['dominant_pollutant']}")
    print(f"  Severity:   {d['event_severity']}")
    print(f"  Coords:     {ts['coordinates']}")
    print(f"  Wind:       {d['weather_snapshot']['wind_speed_kmh']} km/h @ {d['weather_snapshot']['wind_direction_deg']}deg")
    print(f"  Pre-alert:  {pre['source'][:50]}")
    print(f"  Candidates: {len(d['ranked_candidates'])}")
    print()

# Also test /api/v1/stations
r2 = client.get("/api/v1/stations")
print("--- Station List ---")
for s in r2.json()["stations"]:
    print(f"  {s['name']:15s} | {s['scenario_type']:35s} | AQI target: {s['spike_aqi']}")
