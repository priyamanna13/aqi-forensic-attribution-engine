/**
 * api_config.js — Central client configuration module for the AQI Forensic Attribution Platform.
 * Supports both local development (http://localhost:8000) and Ngrok/production tunnels.
 */

export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

export const NGROK_HEADERS = {
  'ngrok-skip-browser-warning': 'true',
  'Accept': 'application/json'
};

export const ENDPOINTS = {
  attribution:    (station) => `${BASE_URL}/api/v1/attribution/${encodeURIComponent(station)}?live=true`,
  timeline:       (station) => `${BASE_URL}/api/v1/timeline/${encodeURIComponent(station)}`,
  replay:         (station, ts) => `${BASE_URL}/api/v1/replay/${encodeURIComponent(station)}?timestamp=${encodeURIComponent(ts)}`,
  spikeSimulate:  ()         => `${BASE_URL}/api/v1/simulation/trigger-spike`,
  liveWebSocket:  ()         => `${WS_BASE_URL}/api/v1/simulation/ws`,
};

export const getAttributionLive = (stationName) => {
  return fetch(`${BASE_URL}/api/v1/attribution/${encodeURIComponent(stationName)}?live=true`, {
    headers: { ...NGROK_HEADERS }
  }).then(res => {
    if (!res.ok) throw new Error(`Network error ${res.status}`);
    return res.json();
  });
};
