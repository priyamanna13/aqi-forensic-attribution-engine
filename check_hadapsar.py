from app.api import app
from fastapi.testclient import TestClient

c = TestClient(app)
d = c.get("/api/v1/attribution/Hadapsar").json()
sp = d["trigger_station"]["reading"]["sub_pollutants"]
print("Hadapsar sub-pollutant values:")
for k, v in sp.items():
    print(f"  {k}: value={v['value']}, exceedance={v['exceedance_factor']}")
print(f"  dominant: {d['trigger_station']['reading']['dominant_pollutant']}")
print(f"  total_aqi: {d['trigger_station']['reading']['total_aqi']}")
