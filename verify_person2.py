"""Verify all new Person 2 endpoints work correctly."""
from fastapi.testclient import TestClient
from app.api import app

c = TestClient(app)

print("=" * 60)
print("PERSON 2 — NEW ENDPOINT VERIFICATION")
print("=" * 60)

# 1. Cone endpoint
print("\n--- /api/v1/cone/Shivajinagar ---")
r = c.get("/api/v1/cone/Shivajinagar")
assert r.status_code == 200
cone = r.json()
print(f"  Type: {cone['type']}")
print(f"  Pasquill: {cone['properties']['pasquill_class']}")
print(f"  Half angle: {cone['properties']['half_angle_deg']}°")
print(f"  Reach: {cone['properties']['reach_km']} km")
print(f"  Stability: {cone['properties'].get('stability', {}).get('label', 'N/A')}")

# 2. Cone with custom wind params
print("\n--- /api/v1/cone/Swargate?wind_dir=180&wind_speed=5 ---")
r = c.get("/api/v1/cone/Swargate?wind_dir=180&wind_speed=5")
assert r.status_code == 200
cone2 = r.json()
print(f"  Bearing: {cone2['properties']['bearing_deg']}° (should be 180)")
print(f"  Pasquill: {cone2['properties']['pasquill_class']} (should be B for low wind)")

# 3. Sources endpoint
print("\n--- /api/v1/sources ---")
r = c.get("/api/v1/sources")
assert r.status_code == 200
sources = r.json()
print(f"  Total sources: {sources['count']}")
curated = [s for s in sources['sources'] if s['source_origin'] == 'curated']
osm = [s for s in sources['sources'] if s['source_origin'] == 'osm']
print(f"  Curated: {len(curated)}")
print(f"  OSM: {len(osm)}")
for s in curated[:3]:
    print(f"    - {s['name']} ({s['source_type']})")

# 4. Trigger-spike endpoint
print("\n--- POST /api/v1/simulation/trigger-spike ---")
r = c.post("/api/v1/simulation/trigger-spike?station_name=Shivajinagar&spike_aqi=400")
assert r.status_code == 200
spike = r.json()
print(f"  Event ID: {spike['event_id'][:8]}...")
print(f"  Simulation: {spike['simulation']}")
print(f"  Requested AQI: {spike['simulation_params']['requested_aqi']}")
print(f"  Actual AQI: {spike['trigger_station']['reading']['total_aqi']}")
print(f"  Dominant: {spike['trigger_station']['reading']['dominant_pollutant']}")
print(f"  Severity: {spike['event_severity']}")
print(f"  Candidates: {len(spike['ranked_candidates'])}")
print(f"  Pre-alert: {spike['pre_alerts']['source']}")

# 5. Trigger spike on different station with custom AQI
print("\n--- POST /api/v1/simulation/trigger-spike (Swargate, AQI=500) ---")
r = c.post("/api/v1/simulation/trigger-spike?station_name=Swargate&spike_aqi=500")
assert r.status_code == 200
spike2 = r.json()
print(f"  Actual AQI: {spike2['trigger_station']['reading']['total_aqi']}")
print(f"  Dominant: {spike2['trigger_station']['reading']['dominant_pollutant']}")
print(f"  Severity: {spike2['event_severity']}")

# 6. City config loading
print("\n--- City Config ---")
from app.config import load_city_config
cfg = load_city_config()
print(f"  City: {cfg['city']['name']}")
print(f"  Stations: {[s['name'] for s in cfg['stations']]}")
print(f"  Spike threshold: AQI >= {cfg['thresholds']['spike_aqi']}")
print(f"  UTM SRID: {cfg['city']['utm_srid']}")

print("\n" + "=" * 60)
print("✅ ALL PERSON 2 ENDPOINTS VERIFIED SUCCESSFULLY!")
print("=" * 60)
