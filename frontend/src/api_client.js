/**
 * AeroTrace AI — Centralized API Client
 * Fixed: BASE_URL corrected to port 8000 (FastAPI/Uvicorn).
 * Added: getAllWindCones(), getAttributionLive(), graceful error handling on every method.
 */
const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function apiFetch(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Accept': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`API ${path} → HTTP ${response.status}`);
  }
  return response.json();
}

export const API = {
  BASE_URL,

  /** GET /api/v1/stations — all 4 CPCB CAAQMS monitoring stations */
  async getStations() {
    return apiFetch('/api/v1/stations');
  },

  /** GET /api/v1/sources — curated + OSM-discovered pollution sources */
  async getSources() {
    return apiFetch('/api/v1/sources');
  },

  /** GET /api/v1/cone/{station} — wind cone GeoJSON for a single station */
  async getWindCone(stationName, timestamp = null) {
    let path = `/api/v1/cone/${encodeURIComponent(stationName)}`;
    if (timestamp) path += `?timestamp=${encodeURIComponent(timestamp)}`;
    return apiFetch(path);
  },

  /**
   * Fetch wind cones for multiple stations in parallel.
   * Returns an object keyed by station name; failed fetches are silently omitted.
   * @param {string[]} stationNames
   * @returns {Promise<Record<string, object>>}
   */
  async getAllWindCones(stationNames) {
    const results = await Promise.allSettled(
      stationNames.map(name => apiFetch(`/api/v1/cone/${encodeURIComponent(name)}`))
    );
    const cones = {};
    stationNames.forEach((name, i) => {
      if (results[i].status === 'fulfilled') {
        cones[name] = results[i].value;
      }
    });
    return cones;
  },

  /**
   * GET /api/v1/attribution/{station}
   * Returns full forensic attribution report (ranked_candidates, advisory, etc.)
   */
  async getAttribution(stationName) {
    return apiFetch(`/api/v1/attribution/${encodeURIComponent(stationName)}?live=true`);
  },

  /**
   * GET /api/v1/attribution/{station}?live=true
   * Bypass the server-side 30s cache; forces a fresh pipeline evaluation.
   */
  async getAttributionLive(stationName) {
    return apiFetch(`/api/v1/attribution/${encodeURIComponent(stationName)}?live=true`);
  },

  /** GET /api/v1/timeline/{station} — 24-hour tick array for the replay scrubber */
  async getTimeline(stationName) {
    return apiFetch(`/api/v1/timeline/${encodeURIComponent(stationName)}`);
  },

  /** GET /api/v1/replay/{station}?timestamp=... — full attribution for a historical hour */
  async getReplay(stationName, timestamp) {
    return apiFetch(
      `/api/v1/replay/${encodeURIComponent(stationName)}?timestamp=${encodeURIComponent(timestamp)}`
    );
  },
};
