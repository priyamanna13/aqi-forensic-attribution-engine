# AQI Attribution API Documentation — Task 9

The backend exposes a FastAPI REST API server to serve the Frontend visualization layer.

*   **Base URL:** `http://localhost:5000`
*   **Swagger Docs (Interactive):** `http://localhost:5000/docs`
*   **ReDoc Docs:** `http://localhost:5000/redoc`

---

## Endpoints

### 1. `GET /health`
Liveness check indicating whether the backend app and Postgres database are up and connected.
*   **Response (200 OK):**
    ```json
    {
      "status": "ok",
      "db": true,
      "pipeline_version": "3.1.0"
    }
    ```

### 2. `GET /stations`
List all seeded monitoring stations with their GeoJSON coordinates and last known telemetry.
*   **Response (200 OK):**
    ```json
    [
      {
        "id": "e0e22709-6617-48f8-b391-76813ab229bf",
        "name": "Shivajinagar",
        "coordinates": [73.844, 18.5308],
        "last_aqi": 310.0,
        "last_updated": "2026-06-25T10:00:00+05:30"
      }
    ]
    ```

### 3. `GET /stations/{station_name}/latest-spike` or `GET /api/v1/attribution/{station_name}`
Returns the complete merged data-contract payload for the most recent alert of the specified station, enriched with dynamic or fallback `pre_alerts`.
*   **URL Params:** `station_name` (e.g. `Shivajinagar`)
*   **Response (200 OK):** Exposes the complete JSON structure of `data_contract_sample.json` including the `pipeline_timings` and `pre_alerts` blocks (see `/attribution/run` for payload details).
*   **Response (404 Not Found):** `{"detail": "No spike found for station: Shivajinagar"}`

### 4. `GET /stations/{station_name}/alerts`
Returns a summary list of past alerts logged for the specified station.
*   **Query Params:** `limit` (default: 10, max: 50)
*   **Response (200 OK):**
    ```json
    [
      {
        "id": "14f08ab6-57bd-42ec-9a8c-9cbe4989adbe",
        "spike_time": "2026-06-25T10:00:00+05:30",
        "aqi_value": 310.0,
        "dominant_pollutant": "PM10",
        "enforcement_priority": 0.85,
        "created_at": "2026-07-02T20:12:18.961021+05:30"
      }
    ]
    ```

### 5. `POST /attribution/run`
Submit a live telemetry reading. The engine validates the inputs, runs spike detection, fetches current weather, queries nearby upwind sources, scores candidates, logs the result to `pipeline.log`, writes to the `alerts` database table, and returns the merged contract payload.
*   **Request Body:**
    ```json
    {
      "station_name": "Shivajinagar",
      "aqi": 310.0,
      "pm25": 148.6,
      "pm10": 387.2,
      "no2": 72.4,
      "so2": 54.8,
      "co": 3.2,
      "o3": 42.1,
      "timestamp": "2026-06-25T10:00:00+05:30"
    }
    ```
*   **Response (201 Created — Spike Detected):**
    ```json
    {
      "event_id": "a1f7c2e4-89b3-4d6e-9f12-3c8a5b7d0e41",
      "event_severity": "critical",
      "pipeline_version": "3.1.0",
      "generated_at": "2026-06-25T10:00:00+05:30",
      "trigger_station": {
        "id": "e0e22709-6617-48f8-b391-76813ab229bf",
        "name": "Shivajinagar",
        "network": "CPCB_CAAQMS",
        "city": "Pune",
        "state": "Maharashtra",
        "elevation_m": 560,
        "coordinates": [73.844, 18.5308],
        "reading": { ... }
      },
      "weather_snapshot": {
        "source": "OpenWeatherMap",
        "observed_at": "2026-06-25T10:00:00+05:30",
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
      "wind_cone_geometry": {
        "type": "Feature",
        "properties": {
          "cone_type": "upwind_source_area",
          "origin_station": "Shivajinagar",
          "bearing_deg": 310.0,
          "half_angle_deg": 30.0,
          "reach_km": 2.5,
          "pasquill_class": "C",
          "style": { ... }
        },
        "geometry": { ... }
      },
      "ranked_candidates": [
        {
          "rank": 1,
          "id": "e3a89045-8fbe-4cf4-9143-5b8cb7934661",
          "name": "Mula Road Residential Towers",
          "type": "construction",
          "distance_from_station_km": 1.42,
          "bearing_from_station_deg": 309,
          "compliance_profile": { ... },
          "score_breakdown": {
            "wind_alignment_score": 0.98,
            "chemical_match_score": 1.0,
            "temporal_match_score": 1.0,
            "proximity_score": 0.53,
            "compliance_penalty": 0.1,
            "confidence_score": 0.98
          }
        }
      ],
      "actionable_intelligence": {
        "enforcement_priority": 0.98,
        "priority_justification": "'Mula road residential towers' is located near a school.",
        "recommended_actions": ["DISPATCH_INSPECTOR", "ISSUE_SHOW_CAUSE_NOTICE", "ACTIVATE_WATER_SPRINKLERS"],
        "estimated_response_time_min": 20,
        "localized_advisory": {
          "en": "AIR QUALITY ALERT — Shivajinagar station has recorded AQI 310...",
          "hi": "वायु गुणवत्ता चेतावनी...",
          "mr": "हवा गुणवत्ता इशारा..."
        },
        "ambiguous": false
      },
      "pipeline_timings": {
        "spatial_filter_ms": 8,
        "wind_cone_ms": 5,
        "scoring_ms": 1,
        "total_ms": 14
      }
    }
    ```
*   **Response (200 OK — Telemetry normal, no spike):**
    ```json
    {
      "spike_detected": false
    }
    ```
*   **Response (422 Unprocessable Entity — Validation Failure):**
    ```json
    {
      "detail": "Negative AQI: -999.0"
    }
    ```

### 6. `GET /attribution/sources`
Returns all seeded municipal pollution sources in the Pune area formatted as a GeoJSON FeatureCollection.
*   **Response (200 OK):**
    ```json
    {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": {
            "type": "Polygon",
            "coordinates": [...]
          },
          "properties": {
            "id": "e3a89045-8fbe-4cf4-9143-5b8cb7934661",
            "name": "Mula Road Residential Towers",
            "type": "construction",
            "schedule_start": "09:00:00",
            "schedule_end": "18:00:00",
            "near_school": true,
            "near_hospital": false
          }
        }
      ]
    }
    ```

### 7. `GET /api/pre-alerts`
Returns a list of forecasted upcoming pollution impacts from scheduled upwind sources in the next 2 hours.
*   **Query Params:** `timestamp` (optional ISO-8601 string, defaults to current time).
*   **Response (200 OK):**
    ```json
    [
      {
        "source": "Kothrud Metro Phase-II Yard",
        "type": "construction",
        "station": "Karve Road",
        "distance_m": 1006.7,
        "bearing_deg": 264,
        "eta_minutes": 8,
        "estimated_aqi_increase": 53,
        "schedule_start": "09:00",
        "advisory": "Kothrud Metro Phase-II Yard becomes active at 09:00. Wind direction indicates AQI at Karve Road may increase by ~53 points in ~8 minutes. Recommend pre-emptive action."
      }
    ]
    ```
