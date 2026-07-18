/**
 * api_config.js — Central client configuration module for the AQI Intelligence Platform.
 *
 * ALL backend URL references in the frontend must import from here.
 * To switch environments (local Docker ↔ Ngrok ↔ production), change only this file.
 *
 * Current active backend: Ngrok tunnel → person1-backend Docker container (port 5000)
 */

// ─── BASE URL ─────────────────────────────────────────────────────────────────
// HTTP/S base for all REST API calls.
export const BASE_URL = 'https://vocalize-oncoming-wolf.ngrok-free.dev';

// ─── WEBSOCKET URL ────────────────────────────────────────────────────────────
// WSS endpoint for live spike broadcast stream.
// Ngrok tunnels HTTP → HTTPS and WS → WSS automatically on the same hostname.
export const WS_BASE_URL = 'wss://vocalize-oncoming-wolf.ngrok-free.dev';

// ─── ENDPOINT BUILDERS ────────────────────────────────────────────────────────
export const ENDPOINTS = {
  attribution:    (station) => `${BASE_URL}/api/v1/attribution/${station}`,
  timeline:       (station) => `${BASE_URL}/api/v1/timeline?station=${station}`,
  replay:         (station, ts) => `${BASE_URL}/api/v1/replay?station=${station}&timestamp=${ts}`,
  spikeSimulate:  ()         => `${BASE_URL}/api/v1/simulation/trigger-spike`,
  liveWebSocket:  ()         => `${WS_BASE_URL}/ws/live`,
};

// ─── SHARED HEADERS ───────────────────────────────────────────────────────────
// Ngrok requires this header to bypass the browser interstitial warning page.
export const NGROK_HEADERS = {
  'ngrok-skip-browser-warning': 'true',
  'Accept': 'application/json',
};
