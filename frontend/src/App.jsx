import React, { useState, useEffect, useRef, useCallback, startTransition } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import dataContract from '../../data_contract_sample.json';
import { API } from './api_client';
import { MapRenderer } from './map_layers';
import { WebSocketClient } from './ws_client';

// ─── LEAFLET DEFAULT ICON FIX (Vite asset pipeline) ────────────────────────────
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl:       'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl:     'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// ─── ALL 4 PUNE CPCB STATIONS (static reference — always shown on map) ──────────
// Coordinates are [lon, lat] GeoJSON order; swapped to [lat, lon] when passed to Leaflet.
const PUNE_STATIONS = [
  { name: 'Shivajinagar', coordinates: [73.8553, 18.5308] },
  { name: 'Swargate',     coordinates: [73.8604, 18.5018] },
  { name: 'Hadapsar',     coordinates: [73.9315, 18.5089] },
  { name: 'Kothrud',      coordinates: [73.8076, 18.5074] },
];

// ─── POLL INTERVAL matches server-side 30 s attribution cache TTL ──────────────
const POLL_INTERVAL_MS = 30_000;
// Number of consecutive poll failures before the emergency spike button appears.
const SPIKE_FAILURE_THRESHOLD = 3;

// ─── GLOBAL KEYFRAMES & BASE CSS ─────────────────────────────────────────────────
// Injected via document.createElement('style') — NOT via <style> JSX tag.
// Reason: @import is illegal inside runtime-injected <style> tags.
const GLOBAL_STYLES = `
  /* ── Keyframes ── */
  @keyframes ping {
    0%   { transform: scale(0.95); opacity: 0.85; }
    70%  { transform: scale(2.8);  opacity: 0;    }
    100% { transform: scale(0.95); opacity: 0;    }
  }
  @keyframes ping2 {
    0%   { transform: scale(0.95); opacity: 0.6; }
    70%  { transform: scale(4.2);  opacity: 0;   }
    100% { transform: scale(0.95); opacity: 0;   }
  }
  @keyframes ping3 {
    0%   { transform: scale(0.95); opacity: 0.35; }
    70%  { transform: scale(6.0);  opacity: 0;    }
    100% { transform: scale(0.95); opacity: 0;    }
  }
  @keyframes pulse {
    0%, 100% { opacity: 1;    transform: scale(1);    }
    50%       { opacity: 0.5;  transform: scale(0.88); }
  }
  @keyframes livePulse {
    0%, 100% { opacity: 1;    transform: scale(1);    }
    50%       { opacity: 0.4;  transform: scale(0.82); }
  }
  @keyframes plumeFlow {
    0%   { opacity: 0;    }
    15%  { opacity: 0.92; }
    65%  { opacity: 0.75; }
    100% { opacity: 0;    }
  }
  @keyframes needleSway {
    0%, 100% { filter: drop-shadow(0 0 4px rgba(239,68,68,0.7)); }
    50%       { filter: drop-shadow(0 0 9px rgba(239,68,68,1.0)); }
  }
  @keyframes slideInRight {
    from { transform: translateX(120%); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
  @keyframes yellowGlow {
    0%, 100% { opacity: 1;   transform: scale(1);   }
    50%       { opacity: 0.6; transform: scale(0.9); }
  }
  @keyframes playbackPulse {
    0%, 100% { box-shadow: 0 0 0 2px rgba(251,191,36,0.35), 0 0 12px rgba(251,191,36,0.5); }
    50%       { box-shadow: 0 0 0 5px rgba(251,191,36,0.15), 0 0 28px rgba(251,191,36,0.85); }
  }

  /* ── Reset ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  /* ── Root layout ── */
  html, body, #root { width: 100%; height: 100%; overflow: hidden; background: #08080a; }

  .aq-root {
    width: 100vw; height: 100vh; display: flex;
    background: #08080a;
    font-family: 'Inter', 'Noto Sans Devanagari', 'Noto Sans', 'Segoe UI Emoji',
                 'Apple Color Emoji', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #f4f4f5; overflow: hidden;
  }

  /* ── Map panel ── */
  .map-panel { width: 72%; height: 100%; position: relative; background: #0c0c10; flex-shrink: 0; }
  .map-panel .leaflet-container { width: 100%; height: 100%; background: #0c0c10; }
  .leaflet-tile-pane { filter: none; }

  /* ── Leaflet popup overrides ── */
  .leaflet-popup-content-wrapper {
    background: rgba(10,10,14,0.96) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 13px !important;
    backdrop-filter: blur(24px);
    padding: 0 !important;
    font-family: 'Inter','Noto Sans Devanagari','Noto Sans',sans-serif !important;
  }
  .leaflet-popup-tip-container { display: none !important; }
  .leaflet-popup-content { margin: 0 !important; }
  .popup-inner        { padding: 13px 17px; }
  .popup-station-name { font-size: 12px; font-weight: 700; color: #f4f4f5; }
  .popup-aqi-badge    { display:inline-flex;align-items:center;gap:5px;margin-top:6px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.22);border-radius:6px;padding:2px 9px;font-size:11px;font-weight:700;color:#f87171; }
  .popup-source-name  { font-size: 12px; font-weight: 500; color: #e4e4e7; margin-top: 5px; }
  .popup-rank-label   { font-size: 10px; font-weight: 700; color: #fbbf24; letter-spacing: 0.12em; text-transform: uppercase; }
  .popup-yellow-aqi   { font-size: 11px; color: #a1a1aa; margin-top: 4px; }

  /* ── Map overlay badges ── */
  .live-badge {
    position:absolute; top:20px; left:20px; z-index:1000;
    background:rgba(8,8,10,0.80); border:1px solid rgba(255,255,255,0.08);
    backdrop-filter:blur(22px); border-radius:9px; padding:7px 13px;
    display:flex; align-items:center; gap:7px;
  }
  .live-dot               { width:7px;height:7px;border-radius:50%;box-shadow:0 0 6px currentColor;animation:livePulse 2s ease-in-out infinite; }
  .live-dot.status-live   { background:#22c55e;color:#22c55e; }
  .live-dot.status-refresh{ background:#fbbf24;color:#fbbf24; }
  .live-dot.status-stale  { background:#f59e0b;color:#f59e0b; }
  .live-dot.status-offline{ background:#ef4444;color:#ef4444; }
  .live-text { font-size:10px;font-weight:700;letter-spacing:0.16em;color:#d4d4d8;text-transform:uppercase; }

  .met-badge {
    position:absolute; bottom:80px; left:24px; z-index:1000;
    background:rgba(8,8,10,0.80); border:1px solid rgba(255,255,255,0.08);
    backdrop-filter:blur(24px); border-radius:13px; padding:11px 18px;
    display:flex; align-items:center; gap:10px;
  }
  .met-icon  { font-size:14px;opacity:0.7; }
  .met-label { font-size:10px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#d4d4d8; }
  .met-value { font-size:13px;font-weight:600;color:#f4f4f5;font-family:monospace; }
  .met-dot   { width:3px;height:3px;background:rgba(255,255,255,0.18);border-radius:50%; }

  /* ── Sidebar ── */
  .sidebar {
    width:28%; height:100%; flex-shrink:0;
    background:rgba(9,9,12,0.92);
    border-left:1px solid rgba(255,255,255,0.045);
    backdrop-filter:blur(40px);
    display:flex; flex-direction:column;
    position:relative; z-index:10;
  }
  .sidebar-scroll {
    flex:1; overflow-y:auto; padding:20px 22px 12px;
    display:flex; flex-direction:column; gap:16px;
    scrollbar-width:none;
  }
  .sidebar-scroll::-webkit-scrollbar { display:none; }

  .header-row   { display:flex;align-items:flex-start;justify-content:space-between;gap:12px; }
  .header-meta  { font-size:10px;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#d4d4d8;margin-bottom:6px; }
  .header-title { font-size:21px;font-weight:800;color:#fafafa;line-height:1.1; }
  .header-sub   { font-size:13px;font-weight:500;color:#a1a1aa;margin-top:5px; }

  .aqi-pill      { display:inline-flex;align-items:center;gap:7px;background:rgba(239,68,68,0.10);border:1px solid rgba(239,68,68,0.22);border-radius:999px;padding:7px 13px 7px 9px;flex-shrink:0; }
  .aqi-pulse-dot { width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 7px #ef4444;animation:livePulse 1.5s ease-in-out infinite; }
  .aqi-number    { font-size:14px;font-weight:700;color:#f87171;font-family:monospace; }
  .aqi-label     { font-size:9px;font-weight:700;color:#991b1b;text-transform:uppercase;letter-spacing:0.06em; }

  .rule { height:1px;background:linear-gradient(to right, rgba(255,255,255,0.06), transparent); }

  .section-label { font-size:10px;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#d4d4d8; }

  .advisory-header { display:flex;align-items:center;justify-content:space-between;margin-bottom:12px; }
  .lang-switcher   { display:flex;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:9px;padding:3px;gap:2px; }
  .lang-btn        { padding:5px 11px;border-radius:7px;border:none;cursor:pointer;font-size:11px;font-weight:700;background:transparent;color:#a1a1aa;transition:background 0.15s,color 0.15s;font-family:'Inter','Noto Sans Devanagari','Noto Sans',sans-serif; }
  .lang-btn.active { background:rgba(255,255,255,0.09);color:#fafafa; }

  .advisory-card         { background:rgba(255,255,255,0.018);border:1px solid rgba(255,255,255,0.055);border-radius:15px;padding:16px;position:relative;overflow:hidden; }
  .advisory-card::before { content:'';position:absolute;top:0;left:0;right:0;height:1.5px;background:linear-gradient(to right, rgba(239,68,68,0.4), transparent); }
  .advisory-text         { font-size:13px;font-weight:400;line-height:1.9;color:#d4d4d8; }

  .sources-list { display:flex;flex-direction:column;gap:8px; }
  .source-card  { background:rgba(255,255,255,0.016);border:1px solid rgba(255,255,255,0.045);border-radius:14px;padding:13px 14px;cursor:pointer;display:flex;align-items:center;gap:12px;transition:background 0.15s,border-color 0.15s,box-shadow 0.15s; }
  .source-card:hover  { background:rgba(255,255,255,0.032); }
  .source-card.active { background:rgba(251,191,36,0.05);border-color:rgba(251,191,36,0.20);box-shadow:0 0 0 1px rgba(251,191,36,0.08) inset; }
  .source-card.playback-highlight { border-color:rgba(251,191,36,0.5);animation:playbackPulse 1.8s ease-in-out infinite; }

  .source-icon-box { width:36px;height:36px;border-radius:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.055);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0; }
  .source-info     { flex:1;min-width:0; }
  .source-top      { display:flex;align-items:center;gap:6px;margin-bottom:5px; }
  .rank-badge      { font-size:10px;font-weight:800;color:#d4d4d8;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.07);border-radius:5px;padding:1px 7px;letter-spacing:0.04em; }
  .source-type-tag { font-size:10px;color:#d4d4d8;font-family:monospace;text-transform:uppercase;letter-spacing:0.08em;font-weight:600; }
  .source-name     { font-size:13px;font-weight:700;color:#e4e4e7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }

  .confidence-block  { text-align:right;flex-shrink:0; }
  .confidence-number { font-size:14px;font-weight:700;font-family:monospace; }
  .confidence-sub    { font-size:10px;color:#d4d4d8;font-weight:600;letter-spacing:0.06em;margin-top:2px; }
  .conf-bar-wrap     { height:2px;background:rgba(255,255,255,0.06);border-radius:1px;margin-top:8px;overflow:hidden; }
  .conf-bar-fill     { height:100%;border-radius:1px;transition:width 0.5s ease; }

  .sidebar-footer { padding:12px 22px;border-top:1px solid rgba(255,255,255,0.035);display:flex;align-items:center;justify-content:space-between; }
  .footer-engine  { font-size:9px;font-weight:700;color:#52525b;font-family:monospace;letter-spacing:0.12em; }
  .footer-version { font-size:9px;color:#52525b;font-family:monospace; }

  /* Leaflet marker wrapper resets */
  .custom-leaflet-marker-trigger,
  .custom-leaflet-marker-source,
  .custom-leaflet-marker-yellow { background:transparent !important; border:none !important; }
`;

let stylesInjected = false;
function injectGlobalStyles() {
  if (stylesInjected) return;
  const el = document.createElement('style');
  el.id = 'aq-intel-global';
  el.textContent = GLOBAL_STYLES;
  document.head.appendChild(el);
  stylesInjected = true;
}
injectGlobalStyles();

// ─── LOCALISATION DICTIONARY ──────────────────────────────────────────────────────
// All non-ASCII strings stored as explicit Unicode escapes so the file's encoding
// is irrelevant — the JS engine always produces the correct codepoints.
const I18N = {
  en: {
    live_feed:          'Live Feed',
    attributed_sources: 'Attributed Sources',
    action_advisory:    'Action Advisory',
    wind_label:         'Wind',
    met_label:          'MET Feed',
    match:              'match',
    rank_prefix:        '#',
    maharashtra:        'Maharashtra',
    footer_engine:      'AQ_INTEL_ENGINE',
    source_types: {
      construction: 'Construction',
      industrial:   'Industrial',
      traffic:      'Traffic',
      waste:        'Waste / Burn',
    },
  },
  hi: {
    // Hindi (Devanagari) — all codepoints explicit
    live_feed:          '\u0932\u093E\u0907\u0935 \u092B\u093C\u0940\u0921',
    attributed_sources: '\u0938\u0902\u092D\u093E\u0935\u093F\u0924 \u092A\u094D\u0930\u0926\u0942\u0937\u0915 \u0938\u094D\u0930\u094B\u0924',
    action_advisory:    '\u0915\u093E\u0930\u094D\u092F \u092F\u094B\u091C\u0928\u093E \u0938\u0932\u093E\u0939',
    wind_label:         '\u0939\u0935\u093E \u0917\u0924\u093F',
    met_label:          '\u092E\u094C\u0938\u092E \u0921\u0947\u091F\u093E',
    match:              '\u0938\u092E\u093E\u0928\u0924\u093E',
    rank_prefix:        '#',
    maharashtra:        '\u092E\u0939\u093E\u0930\u093E\u0937\u094D\u091F\u094D\u0930',
    footer_engine:      '\u0935\u093E\u092F\u0941_\u092C\u0941\u0926\u094D\u0927\u093F_\u0907\u0902\u091C\u0928',
    source_types: {
      construction: '\u0928\u093F\u0930\u094D\u092E\u093E\u0923 \u0915\u093E\u0930\u094D\u092F',
      industrial:   '\u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915 \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
      traffic:      '\u092F\u093E\u0924\u093E\u092F\u093E\u0924 / \u0938\u095C\u0915',
      waste:        '\u0915\u091A\u0930\u093E / \u091C\u094D\u0935\u0932\u0928\u0936\u0940\u0932',
    },
  },
  mr: {
    // Marathi (Devanagari) — all codepoints explicit
    live_feed:          '\u0925\u0947\u091F \u092B\u0940\u0921',
    attributed_sources: '\u0938\u0902\u092D\u093E\u0935\u094D\u092F \u092A\u094D\u0930\u0926\u0942\u0937\u0923 \u0938\u094D\u0930\u094B\u0924',
    action_advisory:    '\u0915\u0943\u0924\u0940 \u0938\u0932\u094D\u0932\u093E \u092A\u094D\u0930\u0923\u093E\u0932\u0940',
    wind_label:         '\u0935\u093E\u0930\u093E \u0926\u093F\u0936\u093E',
    met_label:          '\u0939\u0935\u093E\u092E\u093E\u0928 \u0921\u0947\u091F\u093E',
    match:              '\u091C\u0941\u0933\u0923\u0940',
    rank_prefix:        '#',
    maharashtra:        '\u092E\u0939\u093E\u0930\u093E\u0937\u094D\u091F\u094D\u0930',
    footer_engine:      '\u0935\u093E\u092F\u0942_\u092C\u0941\u0926\u094D\u0927\u0940_\u0907\u0902\u091C\u093F\u0928',
    source_types: {
      construction: '\u092C\u093E\u0902\u0927\u0915\u093E\u092E \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
      industrial:   '\u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915 \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
      traffic:      '\u0935\u093E\u0939\u0924\u0942\u0915 / \u0930\u0938\u094D\u0924\u093E',
      waste:        '\u0915\u091A\u0930\u093E / \u091C\u093E\u0933\u0923\u0947',
    },
  },
};

// Language switcher button labels
const LANG_LABELS = {
  en: 'EN',
  hi: '\u0939\u093F',   // हि
  mr: '\u092E',          // म
};

// Station selector — each entry carries translated name + scenario type subtitle
const STATION_SCENARIOS = [
  {
    id: 'Shivajinagar',
    en: 'Shivajinagar', sub_en: 'Construction',
    hi: '\u0936\u093F\u0935\u093E\u091C\u0940\u0928\u0917\u0930', sub_hi: '\u0928\u093F\u0930\u094D\u092E\u093E\u0923',
    mr: '\u0936\u093F\u0935\u093E\u091C\u0940\u0928\u0917\u0930', sub_mr: '\u092C\u093E\u0902\u0927\u0915\u093E\u092E',
  },
  {
    id: 'Swargate',
    en: 'Swargate', sub_en: 'Traffic',
    hi: '\u0938\u094D\u0935\u093E\u0930\u0917\u0947\u091F', sub_hi: '\u092F\u093E\u0924\u093E\u092F\u093E\u0924',
    mr: '\u0938\u094D\u0935\u093E\u0930\u0917\u0947\u091F', sub_mr: '\u0935\u093E\u0939\u0924\u0942\u0915',
  },
  {
    id: 'Hadapsar',
    en: 'Hadapsar', sub_en: 'Industrial',
    hi: '\u0939\u0921\u092A\u0938\u0930', sub_hi: '\u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915',
    mr: '\u0939\u0921\u092A\u0938\u0930', sub_mr: '\u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915',
  },
  {
    id: 'Kothrud',
    en: 'Kothrud', sub_en: 'Ambiguity',
    hi: '\u0915\u094B\u0925\u0930\u0942\u0921', sub_hi: '\u0905\u0938\u094D\u092A\u0937\u094D\u091F',
    mr: '\u0915\u094B\u0925\u0930\u0942\u0921', sub_mr: '\u0905\u0938\u094D\u092A\u0937\u094D\u091F',
  },
];

// ─── SOURCE NAME LOCALISATION ─────────────────────────────────────────────────────
const SOURCE_NAME_I18N = {
  'Hinjewadi Phase-III Construction Cluster': {
    hi: '\u0939\u093F\u0902\u091C\u0935\u0921\u0940 \u092B\u0947\u091C-3 \u0928\u093F\u0930\u094D\u092E\u093E\u0923 \u0915\u094D\u0932\u0938\u094D\u091F\u0930',
    mr: '\u0939\u093F\u0902\u091C\u0935\u0921\u0940 \u092B\u0947\u091C-3 \u092C\u093E\u0902\u0927\u0915\u093E\u092E \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
  },
  'Pimpri-Chinchwad Industrial Zone': {
    hi: '\u092A\u093F\u0902\u092A\u0930\u0940 \u091A\u093F\u0902\u091A\u0935\u0921 \u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915 \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
    mr: '\u092A\u093F\u0902\u092A\u0930\u0940 \u091A\u093F\u0902\u091A\u0935\u0921 \u0909\u0926\u094D\u092F\u094B\u0917\u093F\u0915 \u0915\u094D\u0937\u0947\u0924\u094D\u0930',
  },
  'Mumbai\u2013Pune Expressway Entry Corridor': {
    hi: '\u092E\u0941\u0902\u092C\u0908-\u092A\u0941\u0923\u0947 \u090F\u0915\u094D\u0938\u092A\u094D\u0930\u0947\u0938\u0935\u0947 \u090F\u0902\u091F\u094D\u0930\u0940 \u0915\u0949\u0930\u093F\u0921\u094B\u0930',
    mr: '\u092E\u0941\u0902\u092C\u0908-\u092A\u0941\u0923\u0947 \u0926\u094D\u0930\u0941\u0924\u0917\u0924\u0940 \u092E\u093E\u0930\u094D\u0917 \u092A\u094D\u0930\u0935\u0947\u0936 \u0915\u0949\u0930\u093F\u0921\u094B\u0930',
  },
  'Mula-Mutha Riverbank Open Waste Burning Site': {
    hi: '\u092E\u0941\u0933\u093E-\u092E\u0941\u0920\u093E \u0928\u0926\u0940 \u0915\u093F\u0928\u093E\u0930\u0947 \u0916\u0941\u0932\u0947 \u092E\u0947\u0902 \u0915\u091A\u0930\u093E \u091C\u0932\u093E\u0928\u0947 \u0915\u093E \u0938\u094D\u0925\u0932',
    mr: '\u092E\u0941\u0933\u093E-\u092E\u0941\u0920\u093E \u0928\u0926\u0940\u0915\u093E\u0920 \u0909\u0918\u0921\u094D\u092F\u093E\u0935\u0930 \u0915\u091A\u0930\u093E \u091C\u093E\u0933\u0923\u094D\u092F\u093E\u091A\u0940 \u091C\u093E\u0917\u093E',
  },
};

function translateSourceName(name, lang) {
  if (!name || lang === 'en') return name;
  if (SOURCE_NAME_I18N[name]?.[lang]) return SOURCE_NAME_I18N[name][lang];
  for (const [key, translations] of Object.entries(SOURCE_NAME_I18N)) {
    if (name.includes(key) || key.includes(name)) {
      if (translations[lang]) return translations[lang];
    }
  }
  for (const [key, translations] of Object.entries(SOURCE_NAME_I18N)) {
    const firstWord = key.split(/[\s-]/)[0];
    if (firstWord.length > 3 && name.includes(firstWord) && translations[lang]) {
      return translations[lang];
    }
  }
  return name;
}

// ─── PRE-ALERT ADVISORY LOCALISATION ─────────────────────────────────────────────
const PRE_ALERT_ADVISORIES_I18N = {
  'Construction schedule active. Heavy dust dispersion predicted.': {
    hi: '\u0928\u093F\u0930\u094D\u092E\u093E\u0923 \u0915\u093E\u0930\u094D\u092F \u0905\u0928\u0941\u0938\u0942\u091A\u0940 \u0938\u0915\u094D\u0930\u093F\u092F \u0939\u0948\u0964 \u092D\u093E\u0930\u0940 \u0927\u0942\u0932 \u092B\u0948\u0932\u0928\u0947 \u0915\u093E \u0905\u0928\u0941\u092E\u093E\u0928 \u0939\u0948\u0964',
    mr: '\u092C\u093E\u0902\u0927\u0915\u093E\u092E \u0935\u0947\u0933\u093E\u092A\u0924\u094D\u0930\u0915 \u0938\u0941\u0930\u0942 \u0906\u0939\u0947. \u092E\u094B\u0920\u094D\u092F\u093E \u092A\u094D\u0930\u092E\u093E\u0923\u093E\u0935\u0930 \u0927\u0942\u0933 \u092A\u0938\u0930\u0923\u094D\u092F\u093E\u091A\u093E \u0905\u0902\u0926\u093E\u091C \u0906\u0939\u0947.',
  },
};

function translateSourceType(typeStr, lang) {
  const lower = typeStr?.toLowerCase() ?? '';
  const dict  = I18N[lang]?.source_types ?? I18N.en.source_types;
  if (lower.includes('construction'))                              return dict.construction;
  if (lower.includes('industrial') || lower.includes('emission')) return dict.industrial;
  if (lower.includes('traffic')    || lower.includes('road'))     return dict.traffic;
  if (lower.includes('waste')      || lower.includes('burn'))     return dict.waste;
  return typeStr ?? '\u2014';
}

function translatePreAlertAdvisory(advText, lang) {
  if (!advText || lang === 'en') return advText;
  return PRE_ALERT_ADVISORIES_I18N[advText]?.[lang] ?? advText;
}

// ─── ICON FACTORIES ───────────────────────────────────────────────────────────────

/**
 * Trigger station: neon crimson core + animated smoky plume pointing upwind.
 * windDeg = meteorological "FROM" direction; cone points toward source.
 */
const createTriggerIcon = (windDeg = 0) => {
  const cssRotate = (windDeg + 270) % 360;
  const gradId = `pg_${cssRotate}`;

  const plumeHtml = `
    <div style="
      position:absolute;left:50%;top:50%;
      width:130px;height:40px;margin-top:-20px;
      transform-origin:0% 50%;transform:rotate(${cssRotate}deg);
      pointer-events:none;
    ">
      <svg width="130" height="40" viewBox="0 0 130 40"
           xmlns="http://www.w3.org/2000/svg"
           style="overflow:visible;animation:plumeFlow 3.2s cubic-bezier(0.4,0,0.2,1) infinite;">
        <defs>
          <linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stop-color="#f97316" stop-opacity="0.88"/>
            <stop offset="30%"  stop-color="#fb923c" stop-opacity="0.52"/>
            <stop offset="68%"  stop-color="#fbbf24" stop-opacity="0.22"/>
            <stop offset="100%" stop-color="#fde68a" stop-opacity="0"/>
          </linearGradient>
          <filter id="sf_${cssRotate}" x="-15%" y="-40%" width="130%" height="180%">
            <feGaussianBlur stdDeviation="3.5"/>
          </filter>
        </defs>
        <path
          filter="url(#sf_${cssRotate})"
          d="M0,18 C16,18 28,11 52,9 C76,7 100,4 130,2 L130,38 C100,36 76,33 52,31 C28,29 16,22 0,22 Z"
          fill="url(#${gradId})"
        />
        <path
          d="M2,18 C20,15 40,9 70,8 C98,7 115,6 130,5 L130,9 C115,10 98,11 70,12 C40,13 20,19 2,22 Z"
          fill="#f97316" opacity="0.18"
        />
        <circle cx="4" cy="20" r="2.8" fill="#f97316" opacity="0.75">
          <animate attributeName="cx"      from="4"   to="125" dur="2.3s" repeatCount="indefinite"/>
          <animate attributeName="opacity" from="0.75" to="0"  dur="2.3s" repeatCount="indefinite"/>
          <animate attributeName="r"       from="2"   to="6"   dur="2.3s" repeatCount="indefinite"/>
        </circle>
        <circle cx="8" cy="15" r="2" fill="#fbbf24" opacity="0.55">
          <animate attributeName="cx"      from="8"   to="125" dur="3s"   begin="0.6s" repeatCount="indefinite"/>
          <animate attributeName="opacity" from="0.55" to="0"  dur="3s"   begin="0.6s" repeatCount="indefinite"/>
          <animate attributeName="r"       from="1.5" to="5"   dur="3s"   begin="0.6s" repeatCount="indefinite"/>
        </circle>
        <circle cx="6" cy="24" r="1.5" fill="#fb923c" opacity="0.4">
          <animate attributeName="cx"      from="6"   to="120" dur="2.7s" begin="1.2s" repeatCount="indefinite"/>
          <animate attributeName="opacity" from="0.4"  to="0"  dur="2.7s" begin="1.2s" repeatCount="indefinite"/>
          <animate attributeName="r"       from="1"   to="4"   dur="2.7s" begin="1.2s" repeatCount="indefinite"/>
        </circle>
      </svg>
    </div>
  `;

  return L.divIcon({
    className: 'custom-leaflet-marker-trigger',
    html: `
      <div style="position:relative;display:flex;align-items:center;justify-content:center;width:56px;height:56px;">
        ${plumeHtml}
        <div style="position:absolute;width:100%;height:100%;background:rgba(239,68,68,0.07);border-radius:50%;animation:ping3 2.8s cubic-bezier(0,0,0.2,1) infinite 0.8s;"></div>
        <div style="position:absolute;width:70%;height:70%;background:rgba(239,68,68,0.14);border-radius:50%;animation:ping2 2.3s cubic-bezier(0,0,0.2,1) infinite 0.4s;"></div>
        <div style="position:absolute;width:44%;height:44%;background:rgba(239,68,68,0.24);border-radius:50%;animation:ping 1.8s cubic-bezier(0,0,0.2,1) infinite;"></div>
        <div style="
          width:15px;height:15px;
          background:radial-gradient(circle at 33% 33%, #ff8080, #dc2626);
          border-radius:50%;
          border:2px solid rgba(255,255,255,0.88);
          box-shadow:0 0 0 3px rgba(239,68,68,0.28), 0 0 20px rgba(239,68,68,0.95), 0 0 40px rgba(239,68,68,0.45);
          z-index:2;position:relative;
        "></div>
      </div>
    `,
    iconSize:   [56, 56],
    iconAnchor: [28, 28],
  });
};

/** Ranked source marker — amber tone, intensity varies with rank. */
const createSourceIcon = (rank) => {
  const palette = ['#f59e0b', '#f59e0b', '#d97706', '#b45309'];
  const color   = palette[Math.max(0, (rank ?? 1) - 1)] ?? '#f59e0b';
  return L.divIcon({
    className: 'custom-leaflet-marker-source',
    html: `
      <div style="position:relative;display:flex;align-items:center;justify-content:center;width:24px;height:24px;">
        <div style="position:absolute;width:100%;height:100%;background:${color}22;border-radius:50%;animation:pulse 2s cubic-bezier(0.4,0,0.6,1) infinite;"></div>
        <div style="width:9px;height:9px;background:${color};border-radius:50%;border:1.5px solid rgba(0,0,0,0.45);box-shadow:0 0 8px ${color}99;"></div>
      </div>
    `,
    iconSize:   [24, 24],
    iconAnchor: [12, 12],
  });
};

/**
 * Playback top-rank source — larger amber ring, extra pulse for visibility.
 * Used for the #1 candidate during 24H replay mode.
 */
const createPlaybackTopSourceIcon = () => {
  const color = '#fbbf24';
  return L.divIcon({
    className: 'custom-leaflet-marker-source',
    html: `
      <div style="position:relative;display:flex;align-items:center;justify-content:center;width:32px;height:32px;">
        <div style="position:absolute;width:100%;height:100%;background:${color}18;border-radius:50%;animation:ping 1.6s cubic-bezier(0,0,0.2,1) infinite;"></div>
        <div style="position:absolute;width:70%;height:70%;background:${color}28;border-radius:50%;animation:pulse 1.3s ease-in-out infinite;"></div>
        <div style="width:12px;height:12px;background:${color};border-radius:50%;border:2px solid rgba(0,0,0,0.5);box-shadow:0 0 14px ${color}cc;z-index:2;position:relative;"></div>
      </div>
    `,
    iconSize:   [32, 32],
    iconAnchor: [16, 16],
  });
};

/**
 * Yellow dot — shown for non-trigger CPCB monitoring stations.
 * Small, distinct; ensures every data point is visible on the map.
 */
const createYellowDotIcon = () => L.divIcon({
  className: 'custom-leaflet-marker-yellow',
  html: `
    <div style="position:relative;display:flex;align-items:center;justify-content:center;width:18px;height:18px;">
      <div style="position:absolute;width:100%;height:100%;background:rgba(250,204,21,0.18);border-radius:50%;animation:yellowGlow 2.4s ease-in-out infinite;"></div>
      <div style="
        width:8px;height:8px;
        background:radial-gradient(circle at 35% 35%, #fde047, #ca8a04);
        border-radius:50%;
        border:1.5px solid rgba(255,255,255,0.55);
        box-shadow:0 0 6px rgba(250,204,21,0.7);
      "></div>
    </div>
  `,
  iconSize:   [18, 18],
  iconAnchor: [9, 9],
  popupAnchor:[0, -10],
});

// ─── HELPERS ──────────────────────────────────────────────────────────────────────

/**
 * Extract a [lat, lng] centroid suitable for Leaflet from a GeoJSON geometry object.
 * ranked_candidates have geometry.type = "Polygon" with coord arrays (or occasionally Point).
 * Returns null if the geometry is missing or malformed.
 */
function getCentroid(geometry) {
  if (!geometry) return null;
  if (geometry.type === 'Point') {
    const [lon, lat] = geometry.coordinates;
    return [lat, lon];
  }
  if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
    const ring = geometry.type === 'Polygon'
      ? geometry.coordinates?.[0]
      : geometry.coordinates?.[0]?.[0];
    if (!ring || ring.length === 0) return null;
    let sumLon = 0, sumLat = 0, count = 0;
    for (const coord of ring) {
      // Coords may be [lon, lat] numbers OR "lon lat" strings (backend quirk on some versions)
      if (Array.isArray(coord) && coord.length >= 2) {
        sumLon += Number(coord[0]); sumLat += Number(coord[1]); count++;
      } else if (typeof coord === 'string') {
        const [lo, la] = coord.split(' ').map(Number);
        if (!isNaN(lo) && !isNaN(la)) { sumLon += lo; sumLat += la; count++; }
      }
    }
    if (count === 0) return null;
    return [sumLat / count, sumLon / count];
  }
  return null;
}

const confidenceColor = (score) => {
  if (score >= 0.88) return '#34d399';
  if (score >= 0.75) return '#fbbf24';
  return '#f87171';
};

const sourceEmoji = (typeStr) => {
  const s = typeStr?.toLowerCase() ?? '';
  if (s.includes('construction'))                          return '\uD83C\uDFD7\uFE0F'; // 🏗️
  if (s.includes('industrial') || s.includes('emission')) return '\uD83C\uDFED';       // 🏭
  if (s.includes('traffic')    || s.includes('road'))     return '\uD83D\uDE97';       // 🚗
  if (s.includes('waste')      || s.includes('burn'))     return '\uD83D\uDD25';       // 🔥
  return '\uD83D\uDCCC'; // 📌
};

const fmt = (d) => d ? new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

// ─── MAP CAMERA CONTROLLER ────────────────────────────────────────────────────────
function MapCameraController({ activeSource, ranked_candidates, mapCenter }) {
  const map     = useMap();
  const prevRef = useRef(null);

  useEffect(() => {
    if (activeSource === null) {
      if (prevRef.current !== null) {
        map.flyTo(mapCenter, 13, { animate: true, duration: 1.2 });
      }
      prevRef.current = null;
      return;
    }
    const src      = ranked_candidates?.find((s) => s?.id === activeSource);
    const centroid = getCentroid(src?.geometry);
    if (!centroid) return;
    map.flyTo(centroid, 14, { animate: true, duration: 1.5 });
    prevRef.current = activeSource;
  }, [activeSource, ranked_candidates, map, mapCenter]);

  return null;
}

// ─── MAP INSTANCE TRACKER ─────────────────────────────────────────────────────────
function MapInstanceTracker({ setMapRef }) {
  const map = useMap();
  useEffect(() => {
    if (map) setMapRef(map);
  }, [map, setMapRef]);
  return null;
}

// ─── WIND COMPASS ─────────────────────────────────────────────────────────────────
function WindCompass({ windDeg, cardinal, label }) {
  const rot  = windDeg ?? 0;
  const ticks = [0, 45, 90, 135, 180, 225, 270, 315];

  return (
    <div style={{
      position: 'absolute', bottom: 140, left: 24, zIndex: 1000,
      background: 'rgba(8,8,10,0.82)', border: '1px solid rgba(255,255,255,0.09)',
      backdropFilter: 'blur(28px)', borderRadius: 20,
      padding: '16px 18px', display: 'flex', flexDirection: 'column',
      alignItems: 'center', gap: 10, minWidth: 96,
    }}>
      <svg width="72" height="72" viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg">
        <circle cx="36" cy="36" r="34" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1.5"/>
        <circle cx="36" cy="36" r="25" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="1"/>
        {ticks.map((deg) => {
          const rad    = (deg * Math.PI) / 180;
          const isCard = deg % 90 === 0;
          const r1     = isCard ? 27 : 30;
          return (
            <line key={deg}
              x1={36 + r1 * Math.sin(rad)}   y1={36 - r1 * Math.cos(rad)}
              x2={36 + 34 * Math.sin(rad)}    y2={36 - 34 * Math.cos(rad)}
              stroke={isCard ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.08)'}
              strokeWidth={isCard ? 1.5 : 0.8}
            />
          );
        })}
        {[
          { l: 'N', x: 36, y: 11 },
          { l: 'S', x: 36, y: 63 },
          { l: 'E', x: 62, y: 38 },
          { l: 'W', x: 10, y: 38 },
        ].map(({ l, x, y }) => (
          <text key={l} x={x} y={y}
            textAnchor="middle" dominantBaseline="middle"
            fontSize="7" fontWeight="700" fontFamily="Inter, sans-serif"
            fill={l === 'N' ? '#ef4444' : 'rgba(255,255,255,0.24)'}
            letterSpacing="0.06em"
          >{l}</text>
        ))}
        <g style={{
          transform: `rotate(${rot}deg)`,
          transformOrigin: '36px 36px',
          transition: 'transform 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
        }}>
          <polygon points="36,10 33,36 36,31 39,36" fill="#ef4444" opacity="0.95"
            style={{ animation: 'needleSway 2.6s ease-in-out infinite' }}/>
          <polygon points="36,62 33,36 36,41 39,36" fill="rgba(255,255,255,0.18)"/>
          <circle cx="36" cy="36" r="3.5" fill="#fafafa" opacity="0.7"/>
          <circle cx="36" cy="36" r="1.5" fill="#0a0a0e"/>
        </g>
      </svg>

      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#a1a1aa', letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 3 }}>
          {label}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#f4f4f5', fontFamily: 'monospace', letterSpacing: '0.04em' }}>
          {cardinal ?? '\u2014'}
        </div>
        <div style={{ fontSize: 11, fontWeight: 500, color: '#a1a1aa', fontFamily: 'monospace', marginTop: 2 }}>
          {rot}&deg;
        </div>
      </div>
    </div>
  );
}

// ─── CONNECTION STATUS BANNER (sidebar) ──────────────────────────────────────────
function ConnectionBanner({ status, lastUpdated }) {
  if (status === 'live') return null;

  const configs = {
    refreshing: { bg: 'rgba(251,191,36,0.06)', border: 'rgba(251,191,36,0.18)', color: '#fbbf24',
                  icon: '\u23F3', text: 'Refreshing data\u2026' },
    stale:      { bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.25)', color: '#f59e0b',
                  icon: '\u26A0\uFE0F', text: 'Live feed degraded \u2014 showing last known data' },
    offline:    { bg: 'rgba(239,68,68,0.07)', border: 'rgba(239,68,68,0.22)', color: '#f87171',
                  icon: '\uD83D\uDCE1', text: 'Backend offline \u2014 cached snapshot shown' },
  };
  const cfg = configs[status] ?? configs.stale;

  return (
    <div style={{
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      borderRadius: 10, padding: '8px 12px',
      display: 'flex', alignItems: 'center', gap: 8,
    }}>
      <span style={{ fontSize: 13 }}>{cfg.icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: cfg.color, letterSpacing: '0.04em' }}>
          {cfg.text}
        </div>
        {lastUpdated && (
          <div style={{ fontSize: 10, color: '#71717a', marginTop: 2 }}>
            Last update: {fmt(lastUpdated)}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── SIMULATION ACTIVE BANNER (sidebar) ──────────────────────────────────────────
function SimulationBanner({ onRevert, loading }) {
  return (
    <div style={{
      background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.30)',
      borderRadius: 10, padding: '10px 14px',
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <span style={{ fontSize: 14, animation: 'livePulse 1.2s ease-in-out infinite' }}>&#x26A1;</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: '#f87171', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          SIMULATED DATA ACTIVE
        </div>
        <div style={{ fontSize: 10, color: '#a1a1aa', marginTop: 2 }}>
          Emergency fallback \u2014 not real sensor readings
        </div>
      </div>
      <button
        onClick={onRevert}
        disabled={loading}
        style={{
          padding: '4px 10px', borderRadius: 6,
          border: '1px solid rgba(239,68,68,0.35)',
          background: 'rgba(239,68,68,0.12)', color: '#f87171',
          fontSize: 10, fontWeight: 700, cursor: loading ? 'wait' : 'pointer',
          fontFamily: 'monospace', letterSpacing: '0.05em', textTransform: 'uppercase',
          opacity: loading ? 0.6 : 1,
        }}
      >
        {loading ? 'Reverting\u2026' : 'Revert'}
      </button>
    </div>
  );
}

// ─── PLAYBACK BANNER (sidebar) ────────────────────────────────────────────────────
function PlaybackBanner({ timestamp, isLoading, isGap }) {
  if (isGap) {
    return (
      <div style={{
        background: 'rgba(99,102,241,0.07)', border: '1px solid rgba(99,102,241,0.22)',
        borderRadius: 10, padding: '10px 14px',
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#818cf8', letterSpacing: '0.05em', marginBottom: 4 }}>
          &#x26A0;&#xFE0F;&nbsp; HISTORICAL DATA UNAVAILABLE
        </div>
        <div style={{ fontSize: 10, color: '#6366f1', lineHeight: 1.5 }}>
          Backend replay endpoint returned no data for this timestamp.
          Showing live attribution as reference.
        </div>
      </div>
    );
  }
  return (
    <div style={{
      background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.22)',
      borderRadius: 10, padding: '8px 14px',
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <span style={{ fontSize: 13 }}>
        {isLoading ? '\u23F3' : '\u23EE\uFE0F'}
      </span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#fbbf24', letterSpacing: '0.05em' }}>
          {isLoading ? 'Loading historical frames\u2026' : 'REPLAY MODE'}
        </div>
        {timestamp && !isLoading && (
          <div style={{ fontSize: 10, color: '#a1a1aa', marginTop: 2, fontFamily: 'monospace' }}>
            {new Date(timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            &nbsp;&middot;&nbsp;<span style={{ color: '#78716c', fontSize: 9 }}>mock historical</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── APP ──────────────────────────────────────────────────────────────────────────

export default function App() {
  // ── UI state
  const [activeLang,   setActiveLang]   = useState('en');
  const [activeSource, setActiveSource] = useState(null);
  const [currentStation, setCurrentStation] = useState('Shivajinagar');

  // ── Data state
  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading]             = useState(true);

  // ── Map
  const [mapRef, setMapRef]                     = useState(null);
  const [stationCones, setStationCones]          = useState({});   // { stationName: GeoJSON }
  const [stationsData, setStationsData]          = useState([]);   // from /api/v1/stations
  // Ref so the poll-error handler can check data availability without stale closure
  const hasDataRef = useRef(false);

  // ── Connection health
  // 'live' | 'refreshing' | 'stale' | 'offline'
  const [connectionStatus, setConnectionStatus] = useState('live');
  const [lastUpdated, setLastUpdated]           = useState(null);
  const [isFetching, setIsFetching]             = useState(false);
  const pollFailureCount = useRef(0);          // raw counter — no re-render per failure

  // ── Spike / simulation (emergency fallback only)
  const [spikeActive, setSpikeActive]   = useState(false);
  const [spikeLoading, setSpikeLoading] = useState(false);
  const spikeActiveRef = useRef(false);        // for access inside async closures
  // Reveal the spike button only when live data has failed ≥ SPIKE_FAILURE_THRESHOLD times
  const showSpikeButton = connectionStatus === 'stale' || connectionStatus === 'offline';

  // ── 24H Timeline / Playback
  const [isAnimating, setIsAnimating]           = useState(false);
  const [currentHourIndex, setCurrentHourIndex] = useState(23);
  const [timelineTimestamps, setTimelineTimestamps] = useState([]);
  const [replayCache, setReplayCache]           = useState({});  // { timestamp: fullAttribution }
  const [replayLoading, setReplayLoading]       = useState(false);
  const [timelineGap, setTimelineGap]           = useState(false);

  // ── WebSocket alert toast
  const [websocketAlert, setWebsocketAlert] = useState(null);

  // ── Derived: what data to actually show ──────────────────────────────────────
  // During playback at a past frame, show that frame's data; otherwise live.
  const isInPlayback      = isAnimating || currentHourIndex < 23;
  const currentTimestamp  = timelineTimestamps[currentHourIndex];
  const playbackFrame     = currentTimestamp ? replayCache[currentTimestamp] : null;

  // activeData is the single source of truth for all rendering downstream.
  // Priority: playbackFrame (during replay) → dashboardData (live) → dataContract (true offline fallback)
  const usingCachedFallback = !dashboardData && !loading;
  const activeData = (() => {
    if (isInPlayback && playbackFrame) return playbackFrame;
    if (dashboardData) return dashboardData;
    if (!loading) return dataContract;   // hard offline — static JSON, labelled in UI
    return null;
  })();

  const {
    trigger_station,
    weather_snapshot,
    ranked_candidates,
    actionable_intelligence,
  } = activeData || {};

  const rawLat   = trigger_station?.coordinates?.[1];
  const rawLng   = trigger_station?.coordinates?.[0];
  const mapCenter = [
    (typeof rawLat === 'number' && !isNaN(rawLat)) ? rawLat : 18.5204,
    (typeof rawLng === 'number' && !isNaN(rawLng)) ? rawLng : 73.8567,
  ];

  const windDeg     = weather_snapshot?.wind_direction_deg ?? 0;
  const t           = I18N[activeLang] ?? I18N.en;
  const selSrc      = ranked_candidates?.find((s) => s?.id === activeSource) ?? null;
  const compassDeg  = selSrc?.weather_snapshot?.wind_direction_deg    ?? windDeg;
  const compassCard = selSrc?.weather_snapshot?.wind_direction_cardinal ?? weather_snapshot?.wind_direction_cardinal ?? '\u2014';

  // ── POLLING: primary real-time data channel (30 s, matches server TTL) ───────
  useEffect(() => {
    let intervalId = null;
    let mounted    = true;

    const fetchLive = async () => {
      if (!mounted) return;
      if (spikeActiveRef.current) { console.log('[Poll] Skipped — spike active'); return; }

      console.log(`[Poll] Fetching /attribution/${currentStation} at`, new Date().toLocaleTimeString());

      // Abort after 8 s so a slow backend never blocks the UI indefinitely
      const controller = new AbortController();
      const abortTimer = setTimeout(() => controller.abort(), 8000);

      setIsFetching(true);
      try {
        if (pollFailureCount.current > 0) setConnectionStatus('refreshing');
        const data = await fetch(
          `${API.BASE_URL}/api/v1/attribution/${encodeURIComponent(currentStation)}?live=true`,
          { headers: { Accept: 'application/json' }, signal: controller.signal }
        ).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });

        if (!mounted) return;
        clearTimeout(abortTimer);
        pollFailureCount.current = 0;
        console.log('[Poll] ✅ Success — AQI:', data?.trigger_station?.reading?.total_aqi,
                    '| candidates:', data?.ranked_candidates?.length,
                    '| station:', data?.trigger_station?.name);
        startTransition(() => {
          setDashboardData(data);
        });
        hasDataRef.current = true;
        setLastUpdated(new Date());
        setConnectionStatus('live');
        if (spikeActiveRef.current) { spikeActiveRef.current = false; setSpikeActive(false); }
      } catch (err) {
        clearTimeout(abortTimer);
        if (!mounted) return;
        pollFailureCount.current += 1;
        const reason = err.name === 'AbortError' ? 'timed-out (8 s)' : err.message;
        console.error(`[Poll] ❌ Failure #${pollFailureCount.current} — ${reason}`);
        if (pollFailureCount.current >= SPIKE_FAILURE_THRESHOLD) setConnectionStatus('stale');
        if (!hasDataRef.current) {
          setConnectionStatus('offline');
          // Show static contract data so UI is never completely blank
          startTransition(() => {
            setDashboardData(dataContract);
          });
        }
      }
    };

    // Immediate first fetch on station switch
    spikeActiveRef.current = false;
    setSpikeActive(false);
    setLoading(true);
    setActiveSource(null);
    setCurrentHourIndex(23);
    setIsAnimating(false);
    pollFailureCount.current = 0;
    console.log('[Poll] Starting poll loop for station:', currentStation);

    fetchLive().finally(() => { if (mounted) setLoading(false); });

    // Recurring poll every 30 s
    intervalId = setInterval(() => {
      console.log('[Poll] ⏱ Interval at', new Date().toLocaleTimeString());
      fetchLive();
    }, POLL_INTERVAL_MS);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStation]);

  // ── WEBSOCKET: spike-alert toast channel only ─────────────────────────────────
  useEffect(() => {
    const ws = new WebSocketClient();
    ws.connect((msg) => {
      if (msg?.type === 'SPIKE_ALERT') {
        const { station_name, timestamp, pre_alerts, actionable_intelligence: ai } = msg.payload || {};
        setWebsocketAlert({ station: station_name, timestamp, pre_alerts, actionable_intelligence: ai });
        setTimeout(() => {
          setWebsocketAlert((prev) => {
            if (prev?.station === station_name) return null;
            return prev;
          });
        }, 12000);
      }
    });
    return () => ws.disconnect();
  }, []); // ws connection is station-independent

  // ── STATIONS: load immediately on mount, independent of mapRef ──────────────
  // CRITICAL: must NOT depend on mapRef — yellow dot <Marker> elements are
  // inside <MapContainer> and re-render when stationsData state changes.
  // Tying this to mapRef introduces a race where dots never appear.
  useEffect(() => {
    console.log('[App] Fetching stations for yellow dots...');
    API.getStations()
      .then(res => {
        const arr = Array.isArray(res) ? res : (res.stations ?? []);
        console.log('[App] stationsData set:', arr.map(s => s.name));
        setStationsData(arr);
      })
      .catch(() => {
        console.warn('[App] getStations failed — using PUNE_STATIONS fallback');
        setStationsData(PUNE_STATIONS.map(s => ({ name: s.name, coordinates: s.coordinates })));
      });
  }, []); // run once on mount

  // ── MAP BOOTSTRAP: imperative Leaflet layers (mapRef required) ───────────────
  useEffect(() => {
    if (!mapRef) return;
    console.log('[App] mapRef ready');
  }, [mapRef]);

  // ── WIND CONES: fetch for ALL 4 stations in parallel (task 3) ────────────────
  useEffect(() => {
    const ALL_STATIONS = ['Shivajinagar', 'Swargate', 'Hadapsar', 'Kothrud'];
    API.getAllWindCones(ALL_STATIONS)
      .then(cones => setStationCones(cones))
      .catch(err => console.warn('[Cones] Failed to fetch all cones:', err));
  }, []); // fetch once on mount; cones are per-station, not per-minute

  // ── TIMELINE: fetch 24h tick list when station changes ───────────────────────
  useEffect(() => {
    if (!currentStation) return;
    setReplayCache({});
    setTimelineGap(false);

    const fetchTimeline = async () => {
      try {
        const ticks = await API.getTimeline(currentStation);
        if (ticks && ticks.length > 0) {
          setTimelineTimestamps(ticks.map(tick => tick.timestamp));
          setCurrentHourIndex(ticks.length - 1);
        } else {
          throw new Error('Empty timeline');
        }
      } catch (err) {
        // Regenerate fallback timestamps so scrubber still works
        const hours = [];
        const now   = new Date();
        for (let i = 23; i >= 0; i--) {
          hours.push(new Date(now - i * 3600_000).toISOString());
        }
        setTimelineTimestamps(hours);
        setCurrentHourIndex(23);
      }
    };

    fetchTimeline();
  }, [currentStation]);

  // ── ON-DEMAND REPLAY FRAME FETCH: fetch historical frame only when scrubbing ──
  useEffect(() => {
    if (!isInPlayback || !currentTimestamp || replayCache[currentTimestamp]) return;

    let cancelled = false;
    setReplayLoading(true);
    API.getReplay(currentStation, currentTimestamp)
      .then((data) => {
        if (cancelled) return;
        setReplayCache((prev) => ({ ...prev, [currentTimestamp]: data }));
      })
      .catch((err) => {
        console.warn(`[Replay] Failed for timestamp ${currentTimestamp}:`, err);
      })
      .finally(() => {
        if (!cancelled) setReplayLoading(false);
      });

    return () => { cancelled = true; };
  }, [isInPlayback, currentTimestamp, currentStation, replayCache]);

  // ── PLAYBACK ANIMATION FRAME ENGINE ──────────────────────────────────────────
  useEffect(() => {
    if (!isAnimating) return;
    const id = setInterval(() => {
      setCurrentHourIndex((prev) => {
        if (prev >= 23) { setIsAnimating(false); return 23; }
        return prev + 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [isAnimating]);

  // ── SPIKE / SIMULATION ACTIONS ────────────────────────────────────────────────
  const triggerSpike = useCallback(async () => {
    setSpikeLoading(true);
    try {
      const res = await fetch(
        `${API.BASE_URL}/api/v1/simulation/trigger-spike?station_name=${currentStation}&spike_aqi=310`,
        { method: 'POST' }
      );
      if (res.ok) {
        const data = await res.json();
        startTransition(() => {
          setDashboardData(data);
        });
        spikeActiveRef.current = true;
        setSpikeActive(true);
        setIsAnimating(false);
        setCurrentHourIndex(23);
      } else {
        console.warn('[Spike] Trigger returned non-OK status:', res.status);
      }
    } catch (err) {
      console.warn('[Spike] Trigger failed — backend unreachable:', err);
      // Do NOT set spikeActive: we cannot fake data silently
    } finally {
      setSpikeLoading(false);
    }
  }, [currentStation]);

  const revertFromSpike = useCallback(async () => {
    setSpikeLoading(true);
    spikeActiveRef.current = false;
    setSpikeActive(false);
    try {
      const data = await API.getAttributionLive(currentStation);
      startTransition(() => {
        setDashboardData(data);
      });
      setLastUpdated(new Date());
      setConnectionStatus('live');
      pollFailureCount.current = 0;
    } catch (err) {
      console.warn('[Spike] Revert fetch failed:', err);
      // Keep whatever data we have; polling will recover
    } finally {
      setSpikeLoading(false);
    }
  }, [currentStation]);

  // ── RENDER ────────────────────────────────────────────────────────────────────
  return (
    <div className="aq-root">

      {/* ── REAL-TIME WEBSOCKET ALERT TOAST ── */}
      {websocketAlert && (
        <div style={{
          position: 'fixed', top: '24px', right: '24px', zIndex: 9999,
          width: '380px', background: 'rgba(15,10,10,0.92)',
          border: '1px solid rgba(239,68,68,0.3)', borderRadius: '16px',
          boxShadow: '0 10px 30px rgba(0,0,0,0.5), 0 0 20px rgba(239,68,68,0.15)',
          backdropFilter: 'blur(20px)', padding: '16px',
          color: '#ffffff', fontFamily: 'Inter, sans-serif',
          animation: 'slideInRight 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ display: 'inline-block', width: '8px', height: '8px', background: '#ef4444', borderRadius: '50%', boxShadow: '0 0 10px #ef4444', animation: 'livePulse 1.2s infinite' }} />
              <span style={{ fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', color: '#ef4444', letterSpacing: '0.1em', fontFamily: 'monospace' }}>
                Live Spike Alert
              </span>
            </div>
            <button onClick={() => setWebsocketAlert(null)}
              style={{ background: 'none', border: 'none', color: '#a1a1aa', cursor: 'pointer', fontSize: '16px', padding: '0 4px', lineHeight: 1 }}
            >&times;</button>
          </div>

          <div style={{ fontSize: '14px', fontWeight: 700, color: '#f4f4f5', marginBottom: '4px' }}>
            &#x1F6A8; Spike detected at {websocketAlert.station}
          </div>
          <div style={{ fontSize: '12px', color: '#a1a1aa', marginBottom: '12px', lineHeight: '1.4' }}>
            {activeLang === 'hi'
              ? '\u0935\u093E\u0938\u094D\u0924\u0935\u093F\u0915 \u0938\u092E\u092F \u0938\u0947\u0902\u0938\u0930 \u0928\u0947\u091F\u0935\u0930\u094D\u0915 \u0928\u0947 \u0905\u0932\u0930\u094D\u091F \u091F\u094D\u0930\u093F\u0917\u0930 \u0915\u093F\u092F\u093E'
              : activeLang === 'mr'
              ? '\u0930\u093F\u0905\u0932-\u091F\u093E\u0907\u092E \u0938\u0947\u0928\u094D\u0938\u0930 \u0928\u0947\u091F\u0935\u0930\u094D\u0915\u0928\u0947 \u0905\u0932\u0930\u094D\u091F \u091F\u094D\u0930\u093F\u0917\u0930 \u0915\u0947\u0932\u093E'
              : `Real-time sensor network triggered an alert at ${new Date(websocketAlert.timestamp).toLocaleTimeString()}`}
          </div>

          {websocketAlert.pre_alerts && (
            <div style={{ background: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.15)', borderRadius: '8px', padding: '8px 10px', marginBottom: '12px', fontSize: '11px' }}>
              <div style={{ fontWeight: 700, color: '#fb923c', marginBottom: '2px' }}>
                Forecasted Impact: +{websocketAlert.pre_alerts.estimated_aqi_increase} AQI
              </div>
              <div style={{ color: '#d4d4d8', lineHeight: '1.4' }}>
                {websocketAlert.pre_alerts.advisory}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px' }}>
            <button onClick={() => { setCurrentStation(websocketAlert.station); setWebsocketAlert(null); }}
              style={{ flex: 1, padding: '8px 12px', borderRadius: '8px', border: 'none', background: '#ef4444', color: '#ffffff', fontSize: '11px', fontWeight: 700, cursor: 'pointer', fontFamily: 'monospace', textTransform: 'uppercase' }}>
              View Radar
            </button>
            <button onClick={() => setWebsocketAlert(null)}
              style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: '#d4d4d8', fontSize: '11px', fontWeight: 700, cursor: 'pointer', fontFamily: 'monospace', textTransform: 'uppercase' }}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* ── MAP PANEL ── */}
      <div className="map-panel">
        <MapContainer
          center={mapCenter}
          zoom={13}
          style={{ width: '100%', height: '100%' }}
          zoomControl={false}
          attributionControl={false}
        >
          <TileLayer
            url="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png"
            maxZoom={20}
          />

          <MapInstanceTracker setMapRef={setMapRef} />
          <MapCameraController
            activeSource={activeSource}
            ranked_candidates={ranked_candidates}
            mapCenter={mapCenter}
          />

          {/* ── ALL-STATION WIND CONES (task 3) ── */}
          {/* Key includes whether data is loaded so React-Leaflet remounts on first arrival.
              GeoJSON ignores data prop changes without a key change (React-Leaflet limitation). */}
          {Object.entries(stationCones).map(([stationName, coneData]) => {
            const isActive = stationName === currentStation;
            const geoData = (isActive && isInPlayback && playbackFrame?.wind_cone_geometry)
              ? playbackFrame.wind_cone_geometry
              : coneData;
            if (!geoData) return null;
            // Include a content hash so the key changes when playback cone updates
            const coneKey = `cone-${stationName}-${isActive ? `pb${currentHourIndex}` : 'ok'}`;
            return (
              <GeoJSON
                key={coneKey}
                data={geoData}
                style={() => ({
                  color:       isActive ? '#fb923c' : '#0ea5e9',
                  weight:      isActive ? 1.5 : 0.8,
                  fillColor:   isActive ? '#fb923c' : '#0ea5e9',
                  fillOpacity: isActive ? 0.07 : 0.025,
                  opacity:     isActive ? 0.8  : 0.3,
                  dashArray:   '5, 5',
                })}
              />
            );
          })}

          {/* ── TRIGGER STATION MARKER ── */}
          <Marker position={mapCenter} icon={createTriggerIcon(windDeg)}>
            <Popup>
              <div className="popup-inner">
                <div className="popup-station-name">{trigger_station?.name ?? 'Trigger Station'}</div>
                <div className="popup-aqi-badge">
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', display: 'inline-block' }}/>
                  CRITICAL &middot; {trigger_station?.reading?.total_aqi ?? '\u2014'} AQI
                </div>
                {spikeActive && (
                  <div style={{ fontSize: 10, color: '#f87171', marginTop: 5, fontWeight: 700 }}>
                    &#x26A1; Simulated data
                  </div>
                )}
              </div>
            </Popup>
          </Marker>

          {/* ── YELLOW DOTS: non-trigger CPCB monitoring stations (task 2) ── */}
          {stationsData
            .filter(st => st.name !== (trigger_station?.name ?? currentStation))
            .map(st => {
              if (!st.coordinates || st.coordinates.length < 2) return null;
              return (
                <Marker
                  key={`ydot-${st.name}`}
                  position={[st.coordinates[1], st.coordinates[0]]}
                  icon={createYellowDotIcon()}
                >
                  <Popup>
                    <div className="popup-inner">
                      <div className="popup-station-name">{st.name}</div>
                      <div className="popup-yellow-aqi">
                        CPCB CAAQMS &middot; {st.city ?? 'Pune'}<br/>
                        {st.spike_aqi ? `AQI ${st.spike_aqi}` : 'Click station to load'}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              );
            })
          }

          {/* ── RANKED SOURCE MARKERS ── */}
          {/* ranked_candidates have a geometry object, NOT a top-level coordinates field.
              Use getCentroid() to extract a [lat, lng] from geometry.coordinates. */}
          {ranked_candidates?.map((src, idx) => {
            const centroid = getCentroid(src?.geometry);
            if (!centroid) return null;          // skip if geometry missing/unreadable
            const isTop = idx === 0 && isInPlayback;
            const icon  = isTop ? createPlaybackTopSourceIcon() : createSourceIcon(src.rank);
            return (
              <Marker
                key={src.id ?? idx}
                position={centroid}
                icon={icon}
              >
                <Popup>
                  <div className="popup-inner">
                    <div className="popup-rank-label">
                      Rank {src?.rank} &middot; {translateSourceType(src?.type, activeLang)}
                    </div>
                    <div className="popup-source-name">{translateSourceName(src?.name, activeLang)}</div>
                  </div>
                </Popup>
              </Marker>
            );
          })}
        </MapContainer>

        {/* ── LIVE BADGE ── */}
        <div className="live-badge" style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          background: (isFetching || loading || connectionStatus === 'refreshing') ? 'rgba(59, 130, 246, 0.2)' : 'rgba(8, 8, 10, 0.85)',
          border: (isFetching || loading || connectionStatus === 'refreshing') ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid rgba(255,255,255,0.08)',
          transition: 'all 0.3s ease'
        }}>
          <div className={`live-dot status-${(isFetching || loading || connectionStatus === 'refreshing') ? 'refreshing' : connectionStatus}`}/>
          <span className="live-text" style={{ fontFamily: 'monospace', fontSize: '11px', letterSpacing: '0.02em' }}>
            {(isFetching || loading || connectionStatus === 'refreshing')
              ? '⏳ FETCHING BACKGROUND DATA (OWM / WAQI / CPCB)...'
              : connectionStatus === 'live'
              ? '● LIVE BACKGROUND SYNC ACTIVE (OWM, WAQI, CPCB)'
              : connectionStatus === 'stale'
              ? 'Stale Telemetry'
              : 'Offline'}
          </span>
          {lastUpdated && connectionStatus === 'live' && !isFetching && !loading && (
            <span style={{ fontSize: 9, color: '#71717a', fontFamily: 'monospace', marginLeft: 4 }}>
              {fmt(lastUpdated)}
            </span>
          )}
        </div>

        {/* ── STATION SELECTOR BAR ── */}
        <div style={{
          position: 'absolute', top: '20px', left: '160px', zIndex: 1000,
          display: 'flex', gap: '6px', background: 'rgba(8,8,10,0.85)',
          padding: '4px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(20px)',
        }}>
          {STATION_SCENARIOS.map((scen) => {
            const label    = scen[activeLang] || scen.en;
            const sublabel = scen[`sub_${activeLang}`] || scen.sub_en;
            const isActive = currentStation === scen.id;
            return (
              <button
                key={scen.id}
                onClick={() => setCurrentStation(scen.id)}
                style={{
                  padding: '5px 12px', borderRadius: '7px', border: 'none', cursor: 'pointer',
                  background: isActive ? 'rgba(251,146,60,0.15)' : 'transparent',
                  border: isActive ? '1px solid rgba(251,146,60,0.3)' : '1px solid transparent',
                  transition: 'all 0.2s ease', textAlign: 'center',
                }}
              >
                <div style={{
                  fontSize: '11px', fontWeight: 700, fontFamily: "'Inter','Noto Sans Devanagari',monospace",
                  color: isActive ? '#fb923c' : '#a1a1aa',
                  letterSpacing: '0.02em',
                }}>
                  {label}
                </div>
                <div style={{
                  fontSize: '9px', fontWeight: 600, color: isActive ? 'rgba(251,146,60,0.6)' : '#52525b',
                  textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: '1px',
                }}>
                  {sublabel}
                </div>
              </button>
            );
          })}
        </div>

        {/* ── MET STRIP ── */}
        <div className="met-badge">
          <span className="met-icon">&#x1F321;&#xFE0F;</span>
          <span className="met-label">{t.met_label}</span>
          <div className="met-dot"/>
          <span className="met-value">{weather_snapshot?.wind_speed_kmh ?? '\u2014'} km/h</span>
          <div className="met-dot"/>
          <span className="met-value">
            {weather_snapshot?.wind_direction_cardinal ?? '\u2014'} &middot; {weather_snapshot?.wind_direction_deg ?? '\u2014'}&deg;
          </span>
        </div>

        {/* ── WIND COMPASS ── */}
        <WindCompass windDeg={compassDeg} cardinal={compassCard} label={t.wind_label} />

        {/* ── 24H PLAYBACK CONTROLLER ── */}
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 1000,
          display: 'flex', alignItems: 'center', gap: 0,
          background: 'rgba(9,9,12,0.95)', borderTop: '1px solid rgba(255,255,255,0.05)',
          backdropFilter: 'blur(24px)', padding: '10px 20px',
        }}>
          {/* Left: MET indicator */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
            borderRight: '1px solid rgba(255,255,255,0.07)', paddingRight: 16, marginRight: 16,
            fontSize: 11, fontFamily: 'monospace', color: '#71717a',
          }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#a855f7', animation: 'livePulse 2s infinite', display: 'inline-block' }}/>
            <span style={{ fontWeight: 700, color: '#d4d4d8' }}>MET</span>
            <span>&middot;</span>
            <span>{weather_snapshot?.wind_speed_kmh ?? '\u2014'} km/h</span>
            <span>&middot;</span>
            <span style={{ color: '#a855f7' }}>{weather_snapshot?.wind_direction_cardinal ?? '\u2014'}</span>
          </div>

          {/* Play / Pause button */}
          <button
            onClick={() => {
              if (currentHourIndex >= 23 && !isAnimating) setCurrentHourIndex(0);
              setIsAnimating(!isAnimating);
            }}
            style={{
              flexShrink: 0, width: 96, height: 32,
              borderRadius: 8, border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
              fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
              background: isAnimating ? '#f59e0b' : '#10b981',
              color: '#0a0a0a',
              marginRight: 16,
              boxShadow: isAnimating ? '0 4px 14px rgba(245,158,11,0.3)' : '0 4px 14px rgba(16,185,129,0.3)',
            }}
          >
            {isAnimating ? (
              <>
                <span style={{ display: 'inline-flex', gap: 2 }}>
                  <span style={{ width: 3, height: 12, background: '#0a0a0a', borderRadius: 1, display: 'inline-block' }}/>
                  <span style={{ width: 3, height: 12, background: '#0a0a0a', borderRadius: 1, display: 'inline-block' }}/>
                </span>
                Pause
              </>
            ) : (
              <>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="#0a0a0a"><path d="M8 5v14l11-7z"/></svg>
                Play 24h
              </>
            )}
          </button>

          {/* Scrubber + timestamps */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {replayLoading ? (
              <div style={{ fontSize: 10, color: '#71717a', fontFamily: 'monospace', textAlign: 'center', padding: '4px 0' }}>
                <span style={{ display: 'inline-block', width: 10, height: 10, border: '1.5px solid #71717a', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite', marginRight: 6, verticalAlign: 'middle' }}/>
                Loading replay frames&#x2026;
              </div>
            ) : (
              <>
                <input
                  type="range"
                  min="0"
                  max={Math.max(0, timelineTimestamps.length - 1)}
                  value={currentHourIndex}
                  onChange={(e) => {
                    setIsAnimating(false);
                    setCurrentHourIndex(parseInt(e.target.value));
                  }}
                  style={{
                    width: '100%', accentColor: isInPlayback ? '#fbbf24' : '#10b981',
                    background: 'rgba(255,255,255,0.06)', borderRadius: 4,
                    appearance: 'none', height: 4, cursor: 'pointer',
                  }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontFamily: 'monospace', color: '#52525b' }}>
                  <span>&minus;24h</span>
                  <span style={{ color: isInPlayback ? '#fbbf24' : '#a1a1aa', fontWeight: 600 }}>
                    {currentTimestamp
                      ? new Date(currentTimestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                      : '\u2014'}
                    {isInPlayback && currentHourIndex < 23 ? ' \u25C4 replay' : ' \u25C4 live'}
                  </span>
                  <span>Now</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── SIDEBAR ── */}
      <div className="sidebar">
        <div className="sidebar-scroll">

          {/* Telemetry Loader Banner */}
          {(connectionStatus === 'refreshing' || spikeLoading || loading || isFetching) && (
            <div style={{
              background: 'rgba(59, 130, 246, 0.12)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: '8px',
              padding: '10px 14px',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '10px',
              fontSize: '11px',
              color: '#60a5fa',
              fontWeight: 700,
              fontFamily: 'monospace',
              letterSpacing: '0.05em',
              boxShadow: '0 4px 14px rgba(59, 130, 246, 0.15)'
            }}>
              <span className="spinner" style={{
                display: 'inline-block',
                width: '14px',
                height: '14px',
                border: '2px solid currentColor',
                borderTopColor: 'transparent',
                borderRadius: '50%',
                animation: 'spin 0.8s linear infinite'
              }}/>
              FETCHING LIVE TELEMETRY (OWM / WAQI / CPCB)... PLEASE WAIT
            </div>
          )}

          {/* Header */}
          <div className="header-row">
            <div style={{ flex: 1 }}>
              <div className="header-meta">{trigger_station?.network ?? 'CPCB_CAAQMS'}</div>
              <div className="header-title">{trigger_station?.name ?? currentStation}</div>
              <div className="header-sub">{trigger_station?.city ?? 'Pune'}, {t.maharashtra}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
              {/* AQI pill */}
              <div className="aqi-pill">
                <div className="aqi-pulse-dot"/>
                <div>
                  <div className="aqi-number">{trigger_station?.reading?.total_aqi ?? '\u2014'}</div>
                  <div className="aqi-label">AQI</div>
                </div>
              </div>

              {/* ── EMERGENCY SPIKE BUTTON ──
                  Only rendered when live feed has failed ≥ SPIKE_FAILURE_THRESHOLD polls.
                  Hidden completely during normal operation. */}
              {!spikeActive && (
                <button
                  id="spike-fallback-btn"
                  onClick={triggerSpike}
                  disabled={spikeLoading}
                  title="Trigger a simulated pollution spike for this station"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '5px 10px', borderRadius: 8,
                    border: '1px solid rgba(239,68,68,0.45)',
                    background: 'rgba(239,68,68,0.10)',
                    color: '#ef4444',
                    fontSize: 10, fontWeight: 800, fontFamily: 'monospace',
                    letterSpacing: '0.05em', textTransform: 'uppercase',
                    cursor: spikeLoading ? 'wait' : 'pointer',
                    opacity: spikeLoading ? 0.6 : 1,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {spikeLoading ? (
                    <>
                      <span style={{ display: 'inline-block', width: 8, height: 8, border: '1.5px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }}/>
                      Loading&hellip;
                    </>
                  ) : (
                    <>⚡ Spike</>
                  )}
                </button>
              )}
            </div>
          </div>

          <div className="rule"/>

          {/* ── STATUS BANNERS (ordered by priority) ── */}
          {spikeActive && (
            <SimulationBanner onRevert={revertFromSpike} loading={spikeLoading} />
          )}
          {!spikeActive && connectionStatus !== 'live' && (
            <ConnectionBanner status={connectionStatus} lastUpdated={lastUpdated} />
          )}
          {usingCachedFallback && !spikeActive && connectionStatus === 'live' && (
            <div style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.18)', borderRadius: 10, padding: '8px 12px', fontSize: 11, color: '#f87171', fontWeight: 700 }}>
              &#x1F4E1; OFFLINE \u2014 cached snapshot
            </div>
          )}
          {(isInPlayback && currentHourIndex < 23) && (
            <PlaybackBanner
              timestamp={currentTimestamp}
              isLoading={replayLoading}
              isGap={timelineGap && !playbackFrame}
            />
          )}

          {/* ── ACTION ADVISORY ── */}
          <div>
            <div className="advisory-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span className="section-label" style={{ letterSpacing: '0.15em' }}>
                  {activeLang === 'en' ? t.action_advisory.toUpperCase() : t.action_advisory}
                </span>
              </div>
              <div className="lang-switcher">
                {['en', 'hi', 'mr'].map((lang) => (
                  <button
                    key={lang}
                    onClick={() => setActiveLang(lang)}
                    className={`lang-btn${activeLang === lang ? ' active' : ''}`}
                  >
                    {LANG_LABELS[lang]}
                  </button>
                ))}
              </div>
            </div>

            {/* Ambiguity alert */}
            {activeData?.pre_alerts?.source?.includes('AMBIGUITY') && (
              <div style={{
                background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
                borderRadius: '12px', padding: '12px 16px', marginBottom: '12px',
                display: 'flex', alignItems: 'center', gap: '10px',
              }}>
                <span style={{ fontSize: '16px', animation: 'livePulse 2s infinite' }}>&#x26A0;&#xFE0F;</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '11px', fontWeight: 800, color: '#f59e0b', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                    {activeLang === 'en' ? 'Ambiguity Warning'
                    : activeLang === 'hi' ? '\u0905\u0938\u094D\u092A\u0937\u094D\u091F\u0924\u093E \u091A\u0947\u0924\u093E\u0935\u0928\u0940'
                    : '\u0905\u0938\u094D\u092A\u0937\u094D\u091F\u0924\u093E \u091A\u0947\u0924\u093E\u0935\u0923\u0940'}
                  </div>
                  <div style={{ fontSize: '12px', color: '#fbbf24', marginTop: '2px', fontWeight: 500 }}>
                    {activeLang === 'en'
                      ? 'Multiple potential sources identified. On-field verification recommended.'
                      : activeLang === 'hi'
                      ? '\u0915\u0908 \u0938\u0902\u092D\u093E\u0935\u093F\u0924 \u0938\u094D\u0930\u094B\u0924 \u092E\u093F\u0932\u0947 \u0939\u0948\u0902\u0964 \u091C\u092E\u0940\u0928\u0940 \u0938\u0924\u094D\u092F\u093E\u092A\u0928 \u0915\u0940 \u0938\u093F\u092B\u093E\u0930\u093F\u0936 \u0915\u0940 \u091C\u093E\u0924\u0940 \u0939\u0948\u0964'
                      : '\u0905\u0928\u0947\u0915 \u0938\u0902\u092D\u093E\u0935\u094D\u092F \u0938\u094D\u0930\u094B\u0924 \u0906\u0922\u0933\u0932\u0947 \u0906\u0939\u0947\u0924. \u092A\u094D\u0930\u0924\u094D\u092F\u0915\u094D\u0937 \u0924\u092A\u093E\u0938\u0923\u0940\u091A\u0940 \u0936\u093F\u092B\u093E\u0930\u0938 \u0915\u0947\u0932\u0940 \u091C\u093E\u0924\u0947.'}
                  </div>
                </div>
              </div>
            )}

            <div className="advisory-card">
              <p className="advisory-text">
                {(() => {
                  const advisoryObj = activeData?.actionable_intelligence?.localized_advisory;
                  const text = advisoryObj
                    ? (activeLang === 'hi' ? advisoryObj.hi : activeLang === 'mr' ? advisoryObj.mr : advisoryObj.en)
                    : '';
                  return text || (loading ? 'Loading advisory\u2026' : 'No advisory available.');
                })()}
              </p>
            </div>
          </div>

          {/* ── PRE-EMPTIVE FORECAST ── */}
          {activeData?.pre_alerts && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="section-label" style={{ color: '#fb923c', letterSpacing: '0.2em' }}>
                  {activeLang === 'en' ? 'PRE-EMPTIVE FORECAST'
                  : activeLang === 'hi' ? '\u0906\u0917\u093E\u092E\u0940 \u092A\u0942\u0930\u094D\u0935\u093E\u0928\u0941\u092E\u093E\u0928'
                  : '\u0906\u0917\u093E\u092E\u0940 \u0905\u0902\u0926\u093E\u091C'}
                </span>
                <span style={{ fontSize: 10, background: 'rgba(251,146,60,0.12)', border: '1px solid rgba(251,146,60,0.22)', color: '#fb923c', padding: '2px 8px', borderRadius: '50px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  {activeLang === 'en' ? 'Predictive' : '\u0905\u0928\u0941\u092E\u093E\u0928\u093F\u0924'}
                </span>
              </div>

              <div style={{ background: 'rgba(251,146,60,0.025)', border: '1px solid rgba(251,146,60,0.12)', borderRadius: 14, padding: 14, position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '1.5px', background: 'linear-gradient(to right, #fb923c, transparent)' }}/>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#f4f4f5' }}>
                    {translateSourceName(activeData.pre_alerts.source, activeLang)}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#fb923c', fontFamily: 'monospace' }}>
                      +{activeData.pre_alerts.estimated_aqi_increase} AQI
                    </div>
                    <div style={{ fontSize: 9, color: '#a1a1aa', fontWeight: 600, textTransform: 'uppercase', marginTop: 2 }}>
                      {activeLang === 'en' ? 'Est. Impact' : '\u0938\u0902\u092D\u093E\u0935\u093F\u0924 \u092A\u094D\u0930\u092D\u093E\u0935'}
                    </div>
                  </div>
                </div>
                <p style={{ fontSize: 12, color: '#d4d4d8', lineHeight: 1.6, marginBottom: 10, fontWeight: 500 }}>
                  {translatePreAlertAdvisory(activeData.pre_alerts.advisory, activeLang)}
                </p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(255,255,255,0.03)', padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.04)' }}>
                  <span style={{ fontSize: 12, animation: 'livePulse 1.5s ease-in-out infinite' }}>&#x23F1;</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: '#a1a1aa' }}>
                    {activeLang === 'en' ? 'Impact ETA: '
                    : activeLang === 'hi' ? '\u092A\u094D\u0930\u092D\u093E\u0935 \u0915\u093E \u0938\u092E\u092F: '
                    : '\u092A\u094D\u0930\u092D\u093E\u0935 \u0935\u0947\u0933: '}
                    <span style={{ color: '#fb923c', fontFamily: 'monospace', fontWeight: 700 }}>
                      ~{activeData.pre_alerts.eta_minutes} mins
                    </span>
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* ── ATTRIBUTED SOURCES ── */}
          <div>
            <div style={{ marginBottom: 12 }}>
              <span className="section-label">{t.attributed_sources}</span>
              {isInPlayback && currentHourIndex < 23 && (
                <span style={{ marginLeft: 8, fontSize: 9, color: '#fbbf24', fontFamily: 'monospace', background: 'rgba(251,191,36,0.1)', padding: '1px 6px', borderRadius: 4, border: '1px solid rgba(251,191,36,0.2)' }}>
                  REPLAY
                </span>
              )}
            </div>
            <div className="sources-list">
              {ranked_candidates?.map((src, idx) => {
                const score    = src?.score_breakdown?.confidence_score ?? 0;
                const color    = confidenceColor(score);
                const pct      = (score * 100).toFixed(0);
                const emoji    = sourceEmoji(src?.type);
                const isActive = activeSource === src?.id;
                const isTop    = idx === 0 && isInPlayback && currentHourIndex < 23;
                const typeLabel = translateSourceType(src?.type, activeLang);

                return (
                  <div
                    key={src?.id ?? idx}
                    className={`source-card${isActive ? ' active' : ''}${isTop ? ' playback-highlight' : ''}`}
                    onClick={() => setActiveSource(isActive ? null : src?.id)}
                  >
                    <div className="source-icon-box">{emoji}</div>
                    <div className="source-info">
                      <div className="source-top">
                        <span className="rank-badge">{t.rank_prefix}{src?.rank}</span>
                        <span className="source-type-tag">{typeLabel}</span>
                        {isTop && (
                          <span style={{ fontSize: 9, color: '#fbbf24', fontFamily: 'monospace', marginLeft: 2 }}>&#x25B2; DOMINANT</span>
                        )}
                      </div>
                      <div className="source-name">{translateSourceName(src?.name, activeLang)}</div>
                      <div className="conf-bar-wrap">
                        <div className="conf-bar-fill" style={{ width: `${pct}%`, background: color }}/>
                      </div>
                    </div>
                    <div className="confidence-block">
                      <div className="confidence-number" style={{ color }}>{pct}%</div>
                      <div className="confidence-sub">{t.match}</div>
                    </div>
                  </div>
                );
              })}
              {(!ranked_candidates || ranked_candidates.length === 0) && !loading && (
                <div style={{ fontSize: 12, color: '#52525b', textAlign: 'center', padding: '20px 0' }}>
                  No sources attributed
                </div>
              )}
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="sidebar-footer">
          <span className="footer-engine">{t.footer_engine}</span>
          <span className="footer-version">
            v{actionable_intelligence?.enforcement_priority ?? '1'}.04
            {spikeActive && <span style={{ color: '#f87171', marginLeft: 6 }}>[SIM]</span>}
            {usingCachedFallback && <span style={{ color: '#71717a', marginLeft: 6 }}>[cached]</span>}
          </span>
        </div>
      </div>

    </div>
  );
}
