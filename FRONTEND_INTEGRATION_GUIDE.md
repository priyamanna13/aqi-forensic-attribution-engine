# 🚀 Backend API — Integration Guide for Frontend (Person 3)

> **Status:** All 4 Demo Scenarios are LIVE and ready for integration.
> **CORS:** Enabled (`allow_origins=["*"]`), no browser blocks.
> **Coordinates:** GeoJSON order `[longitude, latitude]` (EPSG:4326).

---

## 🔗 Base URL

```
https://vocalize-oncoming-wolf.ngrok-free.dev
```

> ⚠️ This URL is live as long as Person 2's laptop is ON and `start_dev.bat` is running.
> If URL changes after restart, Person 2 will share the new one.

---

## 📌 4 Demo Endpoints

| # | Station | Endpoint | Scenario | Dominant | AQI |
|---|---------|----------|----------|----------|-----|
| 1 | Shivajinagar | `/api/v1/attribution/Shivajinagar` | Construction Dust Spike | PM10 | 310 |
| 2 | Swargate | `/api/v1/attribution/Swargate` | Heavy Traffic Corridor | NO2 | 285 |
| 3 | Hadapsar | `/api/v1/attribution/Hadapsar` | Industrial / Factory Emission | SO2 | 340 |
| 4 | Kothrud | `/api/v1/attribution/Kothrud` | Ambiguity — Multiple Sources | PM2.5 | 265 |

### Full URLs (copy-paste ready)

```
https://vocalize-oncoming-wolf.ngrok-free.dev/api/v1/attribution/Shivajinagar
https://vocalize-oncoming-wolf.ngrok-free.dev/api/v1/attribution/Swargate
https://vocalize-oncoming-wolf.ngrok-free.dev/api/v1/attribution/Hadapsar
https://vocalize-oncoming-wolf.ngrok-free.dev/api/v1/attribution/Kothrud
```

---

## 📌 Station List Endpoint (For Dropdown)

```
GET /api/v1/stations
```

Use this to **dynamically populate** a dropdown or button group.

**Response:**

```json
{
  "stations": [
    {
      "name": "Shivajinagar",
      "city": "Pune",
      "state": "Maharashtra",
      "coordinates": [73.8567, 18.5308],
      "elevation_m": 560,
      "spike_aqi": 310,
      "dominant_pollutant": "pm10",
      "scenario_type": "Construction Spike (PM10)"
    },
    {
      "name": "Swargate",
      "coordinates": [73.8553, 18.5018],
      "spike_aqi": 285,
      "dominant_pollutant": "no2",
      "scenario_type": "Heavy Traffic Corridor (NO2)"
    },
    {
      "name": "Hadapsar",
      "coordinates": [73.926, 18.5089],
      "spike_aqi": 340,
      "dominant_pollutant": "so2",
      "scenario_type": "Industrial Emission (SO2)"
    },
    {
      "name": "Kothrud",
      "coordinates": [73.8077, 18.5074],
      "spike_aqi": 265,
      "dominant_pollutant": "pm25",
      "scenario_type": "Ambiguity — Multi-Source (PM2.5)"
    }
  ]
}
```

---

## 🗺️ Frontend Integration Steps

### Step 1: Station Selector (Dropdown / Buttons)

Add a UI element (dropdown or 4 buttons) so the user can pick a station.
You can hardcode the 4 names or fetch them dynamically from `/api/v1/stations`.

---

### Step 2: Fetch Attribution Data

When user selects a station, make a fetch call:

```js
const station = "Swargate"; // or whichever is selected
const BASE = "https://vocalize-oncoming-wolf.ngrok-free.dev";
const res = await fetch(`${BASE}/api/v1/attribution/${station}`);
const data = await res.json();
```

---

### Step 3: Response JSON Structure

Every endpoint returns the **same JSON structure** with 6 blocks:

```
data.event_id                    → Unique event UUID
data.event_severity              → "critical" or "moderate"
data.pipeline_version            → "3.1.0"
data.generated_at                → ISO timestamp

data.trigger_station             → Station info + AQI reading
data.weather_snapshot            → Weather conditions at spike time
data.wind_cone_geometry          → GeoJSON Polygon (upwind cone)
data.ranked_candidates           → Array of pollution sources with scores
data.actionable_intelligence     → Enforcement actions + trilingual advisory
data.pre_alerts                  → Early warning panel data
```

#### Key Fields for Map:

```js
// Station marker position
data.trigger_station.coordinates           // [lon, lat] → flip for L.marker([lat, lon])
data.trigger_station.reading.total_aqi     // e.g. 310
data.trigger_station.reading.aqi_category  // e.g. "Very Poor"
data.trigger_station.reading.dominant_pollutant // e.g. "pm10", "no2", "so2", "pm25"
```

#### Key Fields for Weather Panel:

```js
data.weather_snapshot.wind_speed_kmh       // e.g. 14.5
data.weather_snapshot.wind_direction_deg   // e.g. 290
data.weather_snapshot.temperature_c        // e.g. 31.4
data.weather_snapshot.relative_humidity_pct // e.g. 62
data.weather_snapshot.visibility_km        // e.g. 4.2
data.weather_snapshot.pasquill_class       // e.g. "B" (stability class)
```

#### Key Fields for Wind Cone (GeoJSON → Leaflet):

```js
// This is a standard GeoJSON Polygon — add directly to Leaflet!
L.geoJSON(data.wind_cone_geometry).addTo(map);

// Properties available:
data.wind_cone_geometry.properties.station_name
data.wind_cone_geometry.properties.half_angle_deg
data.wind_cone_geometry.properties.reach_km
```

#### Key Fields for Source Candidates:

```js
data.ranked_candidates   // Array, sorted by score (highest first)

// Each candidate has:
candidate.name                              // e.g. "Swargate ST Bus Depot"
candidate.type                              // "construction", "traffic", "industrial", "waste_burning"
candidate.geometry                          // GeoJSON (Point/Polygon/LineString) → add to map
candidate.score_breakdown.confidence_score  // 0.0 to 1.0
candidate.compliance_profile.near_school    // true/false
candidate.compliance_profile.school_name    // e.g. "Vibgyor High School"
candidate.compliance_profile.violation_count_90d  // e.g. 3
```

#### Key Fields for Intelligence Panel:

```js
data.actionable_intelligence.enforcement_priority      // 0.0 to 1.0
data.actionable_intelligence.recommended_actions       // Array of action codes
data.actionable_intelligence.localized_advisory.en     // English advisory text
data.actionable_intelligence.localized_advisory.hi     // Hindi advisory text
data.actionable_intelligence.localized_advisory.mr     // Marathi advisory text
data.actionable_intelligence.field_team_assignment.team_lead  // Inspector name
data.actionable_intelligence.field_team_assignment.eta_minutes // ETA in minutes
```

#### Key Fields for Pre-Alert Panel:

```js
data.pre_alerts.source                   // e.g. "Swargate ST Bus Depot & Diesel Terminal"
data.pre_alerts.eta_minutes              // e.g. 22
data.pre_alerts.estimated_aqi_increase   // e.g. 38
data.pre_alerts.advisory                 // e.g. "Peak bus dispatch hour. 400+ diesel vehicles..."
```

---

### Step 4: Map Rendering Tips

1. **Auto-center map** on the selected station's coordinates.
2. **Station marker:** Use `data.trigger_station.coordinates` (remember to flip `[lon,lat]` → `[lat,lon]` for `L.marker`, but `L.geoJSON` handles it automatically).
3. **Wind cone:** `L.geoJSON(data.wind_cone_geometry)` — each station has a **different wind direction**, so the cone will visually rotate on the map. Very impressive for judges!
4. **Source candidates:** Loop through `data.ranked_candidates` and add each `candidate.geometry` to the map with color-coded markers based on `candidate.type`.
5. **Color coding suggestion:**
   - `construction` → Orange 🟠
   - `traffic` → Red 🔴
   - `industrial` → Purple 🟣
   - `waste_burning` → Brown 🟤

---

### Step 5: What Makes Each Scenario Unique (For Judges)

| Station | What judges will see differently |
|---------|----------------------------------|
| **Shivajinagar** | Wind cone points NW, 4 candidates, construction dust dominates, school alert |
| **Swargate** | Wind cone points SW, 3 candidates, NO2 from diesel buses, traffic-heavy area |
| **Hadapsar** | Wind cone points SE, 3 candidates, SO2 from factory furnaces, industrial zone |
| **Kothrud** | Wind cone points S, 4 candidates, **multiple sources flagged (AMBIGUITY)**, low visibility, stagnation zone — this is the WOW scenario |

---

## ⚡ Quick Test

Open this in your browser to verify the API is live:

```
https://vocalize-oncoming-wolf.ngrok-free.dev/health
```

Expected response: `{"status": "ok", "version": "3.1.0"}`

---

## 📞 Need Help?

If any endpoint returns an error or the URL stops working, ping Person 2 (Anish) immediately.
He just needs to re-run `start_dev.bat` on his laptop to bring it back up.
