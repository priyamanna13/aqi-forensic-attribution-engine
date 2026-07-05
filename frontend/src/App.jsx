import React, { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import dataContract from '../../data_contract_sample.json';
import { API } from './api_client';
import { MapRenderer } from './map_layers';

// ─── LEAFLET DEFAULT ICON FIX (Vite asset pipeline) ──────────────────────────
// Without this, Vite can't resolve the default marker PNG paths and throws.
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl:       'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl:     'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// ─── GLOBAL KEYFRAMES ─────────────────────────────────────────────────────────
// Injected via document.createElement('style') — NOT via <style> JSX tag.
// Reason: @import is illegal inside runtime-injected <style> tags and causes
// Vite to throw or silently drop the entire block → blank screen.
// Keyframes must live here so Leaflet divIcon HTML strings can reference them
// without Shadow DOM restrictions.
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

  /* ── Reset ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  /* ── Root layout ── */
  html, body, #root { width: 100%; height: 100%; overflow: hidden; background: #08080a; }

  .aq-root {
    width: 100vw; height: 100vh; display: flex;
    background: #08080a;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #f4f4f5; overflow: hidden;
  }

  /* ── Map panel ── */
  .map-panel { width: 72%; height: 100%; position: relative; background: #0c0c10; flex-shrink: 0; }
  .map-panel .leaflet-container { width: 100%; height: 100%; background: #0c0c10; }
  /* NO filter on tile-pane: Stadia Smooth Dark roads are already sharp silver.
     Any brightness/saturation filter turns them muddy. */
  .leaflet-tile-pane { filter: none; }

  /* ── Leaflet popup overrides ── */
  .leaflet-popup-content-wrapper {
    background: rgba(10,10,14,0.96) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 13px !important;
    backdrop-filter: blur(24px);
    padding: 0 !important;
  }
  .leaflet-popup-tip-container { display: none !important; }
  .leaflet-popup-content { margin: 0 !important; }
  .popup-inner        { padding: 13px 17px; }
  .popup-station-name { font-size: 12px; font-weight: 700; color: #f4f4f5; }
  .popup-aqi-badge    { display:inline-flex;align-items:center;gap:5px;margin-top:6px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.22);border-radius:6px;padding:2px 9px;font-size:11px;font-weight:700;color:#f87171; }
  .popup-source-name  { font-size: 12px; font-weight: 500; color: #e4e4e7; margin-top: 5px; }
  .popup-rank-label   { font-size: 10px; font-weight: 700; color: #fbbf24; letter-spacing: 0.12em; text-transform: uppercase; }

  /* ── Map overlay badges ── */
  .live-badge {
    position:absolute; top:20px; left:20px; z-index:1000;
    background:rgba(8,8,10,0.80); border:1px solid rgba(255,255,255,0.08);
    backdrop-filter:blur(22px); border-radius:9px; padding:7px 13px;
    display:flex; align-items:center; gap:7px;
  }
  .live-dot  { width:7px;height:7px;background:#22c55e;border-radius:50%;box-shadow:0 0 6px #22c55e;animation:livePulse 2s ease-in-out infinite; }
  .live-text { font-size:10px;font-weight:700;letter-spacing:0.16em;color:#d4d4d8;text-transform:uppercase; }

  .met-badge {
    position:absolute; bottom:24px; left:24px; z-index:1000;
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
    flex:1; overflow-y:auto; padding:28px 22px 16px;
    display:flex; flex-direction:column; gap:22px;
    scrollbar-width:none;
  }
  .sidebar-scroll::-webkit-scrollbar { display:none; }

  .header-row   { display:flex;align-items:flex-start;justify-content:space-between;gap:12px; }
  .header-meta  { font-size:10px;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#d4d4d8;margin-bottom:6px; }
  .header-title { font-size:22px;font-weight:800;color:#fafafa;line-height:1.1; }
  .header-sub   { font-size:13px;font-weight:500;color:#a1a1aa;margin-top:5px; }

  .aqi-pill      { display:inline-flex;align-items:center;gap:7px;background:rgba(239,68,68,0.10);border:1px solid rgba(239,68,68,0.22);border-radius:999px;padding:7px 13px 7px 9px;flex-shrink:0; }
  .aqi-pulse-dot { width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 7px #ef4444;animation:livePulse 1.5s ease-in-out infinite; }
  .aqi-number    { font-size:14px;font-weight:700;color:#f87171;font-family:monospace; }
  .aqi-label     { font-size:9px;font-weight:700;color:#991b1b;text-transform:uppercase;letter-spacing:0.06em; }

  .rule { height:1px;background:linear-gradient(to right, rgba(255,255,255,0.06), transparent); }

  .section-label { font-size:10px;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#d4d4d8; }

  .advisory-header { display:flex;align-items:center;justify-content:space-between;margin-bottom:12px; }
  .lang-switcher   { display:flex;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:9px;padding:3px;gap:2px; }
  .lang-btn        { padding:5px 11px;border-radius:7px;border:none;cursor:pointer;font-size:11px;font-weight:700;background:transparent;color:#a1a1aa;transition:background 0.15s,color 0.15s; }
  .lang-btn.active { background:rgba(255,255,255,0.09);color:#fafafa; }

  .advisory-card         { background:rgba(255,255,255,0.018);border:1px solid rgba(255,255,255,0.055);border-radius:15px;padding:16px;position:relative;overflow:hidden; }
  .advisory-card::before { content:'';position:absolute;top:0;left:0;right:0;height:1.5px;background:linear-gradient(to right, rgba(239,68,68,0.4), transparent); }
  .advisory-text         { font-size:14px;font-weight:400;line-height:1.9;color:#d4d4d8; }

  .sources-list { display:flex;flex-direction:column;gap:8px; }
  .source-card  { background:rgba(255,255,255,0.016);border:1px solid rgba(255,255,255,0.045);border-radius:14px;padding:13px 14px;cursor:pointer;display:flex;align-items:center;gap:12px;transition:background 0.15s,border-color 0.15s,box-shadow 0.15s; }
  .source-card:hover  { background:rgba(255,255,255,0.032); }
  .source-card.active { background:rgba(251,191,36,0.05);border-color:rgba(251,191,36,0.20);box-shadow:0 0 0 1px rgba(251,191,36,0.08) inset; }

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

  .sidebar-footer { padding:14px 22px;border-top:1px solid rgba(255,255,255,0.035);display:flex;align-items:center;justify-content:space-between; }
  .footer-engine  { font-size:9px;font-weight:700;color:#52525b;font-family:monospace;letter-spacing:0.12em; }
  .footer-version { font-size:9px;color:#52525b;font-family:monospace; }

  /* Leaflet marker wrapper resets */
  .custom-leaflet-marker-trigger,
  .custom-leaflet-marker-source { background:transparent !important; border:none !important; }
`;

// Inject all global styles + keyframes once at module load time.
// Using a module-level flag so HMR re-runs don't double-inject.
let stylesInjected = false;
function injectGlobalStyles() {
  if (stylesInjected) return;
  const el = document.createElement('style');
  el.id = 'aq-intel-global';
  el.textContent = GLOBAL_STYLES;
  document.head.appendChild(el);
  stylesInjected = true;
}
// Call immediately at module evaluation time (not inside useEffect)
// so styles exist before any component renders.
injectGlobalStyles();

// ─── LOCALISATION DICTIONARY ──────────────────────────────────────────────────
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
    live_feed:          'लाइव फ़ीड',
    attributed_sources: 'संभावित प्रदूषक स्रोत',
    action_advisory:    'कार्य योजना सलाह',
    wind_label:         'हवा गति',
    met_label:          'मौसम डेटा',
    match:              'समानता',
    rank_prefix:        '#',
    maharashtra:        'महाराष्ट्र',
    footer_engine:      'वायु_बुद्धि_इंजन',
    source_types: {
      construction: 'निर्माण कार्य',
      industrial:   'औद्योगिक क्षेत्र',
      traffic:      'यातायात / सड़क',
      waste:        'कचरा / ज्वलनशील',
    },
  },
  mr: {
    live_feed:          'थेट फीड',
    attributed_sources: 'संभाव्य प्रदूषण स्रोत',
    action_advisory:    'कृती सल्ला प्रणाली',
    wind_label:         'वारा दिशा',
    met_label:          'हवामान डेटा',
    match:              'जुळणी',
    rank_prefix:        '#',
    maharashtra:        'महाराष्ट्र',
    footer_engine:      'वायु_बुद्धी_इंजिन',
    source_types: {
      construction: 'बांधकाम क्षेत्र',
      industrial:   'औद्योगिक क्षेत्र',
      traffic:      'वाहतूक / रस्ता',
      waste:        'कचरा / जाळणे',
    },
  },
};

const LANG_LABELS = { en: 'EN', hi: 'हि', mr: 'म' };

function translateSourceType(typeStr, lang) {
  const lower = typeStr?.toLowerCase() ?? '';
  const dict  = I18N[lang]?.source_types ?? I18N.en.source_types;
  if (lower.includes('construction'))                              return dict.construction;
  if (lower.includes('industrial') || lower.includes('emission')) return dict.industrial;
  if (lower.includes('traffic')    || lower.includes('road'))     return dict.traffic;
  if (lower.includes('waste')      || lower.includes('burn'))     return dict.waste;
  return typeStr ?? '—';
}

// ─── SOURCE NAME LOCALISATION ─────────────────────────────────────────────────
// Fix #2: Inline fallback dictionary for Pune source entity names.
// Backend returns English names; this layer translates for HI/MR display.
const SOURCE_NAME_I18N = {
  'Hinjewadi Phase-III Construction Cluster': {
    hi: 'हिंजवडी फेज-३ कन्स्ट्रक्शन क्लस्टर',
    mr: 'हिंजवडी फेज-३ बांधकाम क्षेत्र',
  },
  'Pimpri-Chinchwad Industrial Zone': {
    hi: 'पिंपरी चिंचवड औद्योगिक क्षेत्र',
    mr: 'पिंपरी चिंचवड औद्योगिक क्षेत्र',
  },
  'Mumbai–Pune Expressway Entry Corridor': {
    hi: 'मुंबई-पुणे एक्सप्रेसवे एंट्री कॉरिडोर',
    mr: 'मुंबई-पुणे द्रुतगती मार्ग प्रवेश कॉरिडोर',
  },
  'Mula-Mutha Riverbank Open Waste Burning Site': {
    hi: 'मुळा-मुठा नदी किनारे खुले में कचरा जलाने का स्थल',
    mr: 'मुळा-मुठा नदीकाठ उघड्यावर कचरा जाळण्याची जागा',
  },
};

/**
 * translateSourceName
 * Attempts an exact-key match first, then a fuzzy substring match
 * for names with special characters (em-dashes, suffixes, etc.).
 * Falls back to the raw English name if no translation exists.
 */
function translateSourceName(name, lang) {
  if (!name || lang === 'en') return name;
  // Exact match
  if (SOURCE_NAME_I18N[name]?.[lang]) return SOURCE_NAME_I18N[name][lang];
  // Fuzzy: check if any dictionary key is a substring of the backend name
  for (const [key, translations] of Object.entries(SOURCE_NAME_I18N)) {
    if (name.includes(key) || key.includes(name)) {
      if (translations[lang]) return translations[lang];
    }
  }
  // Fallback: match on first significant word (e.g. "Hinjewadi", "Pimpri")
  for (const [key, translations] of Object.entries(SOURCE_NAME_I18N)) {
    const firstWord = key.split(/[\s-]/)[0];
    if (firstWord.length > 3 && name.includes(firstWord) && translations[lang]) {
      return translations[lang];
    }
  }
  return name;
}

// ─── PRE-ALERT & ADVISORY LOCALISATION ────────────────────────────────────────
// Fix: Translates pre-alert description text and cleans English source names
// leaked into LLM-generated advisory paragraphs.

const PRE_ALERT_ADVISORIES_I18N = {
  'Construction schedule active. Heavy dust dispersion predicted.': {
    hi: 'निर्माण कार्य अनुसूची सक्रिय है। भारी धूल फैलने का अनुमान है।',
    mr: 'बांधकाम वेळापत्रक सुरू आहे. मोठ्या प्रमाणावर धूळ पसरण्याचा अंदाज आहे.',
  },
};

function translatePreAlertAdvisory(advText, lang) {
  if (!advText || lang === 'en') return advText;
  return PRE_ALERT_ADVISORIES_I18N[advText]?.[lang] ?? advText;
}

/**
 * getCleanAdvisory
 * Replaces any English source names embedded inside the LLM-generated
 * advisory paragraph with their localised equivalents.
 */
function getCleanAdvisory(rawAdvisory, lang) {
  if (!rawAdvisory || lang === 'en') return rawAdvisory;
  let cleaned = rawAdvisory;
  for (const [engName] of Object.entries(SOURCE_NAME_I18N)) {
    const localised = translateSourceName(engName, lang);
    if (localised !== engName) {
      cleaned = cleaned.replaceAll(engName, localised);
    }
  }
  return cleaned;
}

// ─── THE OPTIMIZED AUDIO FORENSIC SPEECH ENGINE ────────────────────────────────
// Sentence-chunking approach: each sentence is its own utterance chained via onend.

// Chrome loads voices async — ensure they're ready before first use.
if (typeof window !== 'undefined' && window.speechSynthesis) {
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged = () => { window.speechSynthesis.getVoices(); };
}

function getLangCode(lang) {
  if (lang === 'hi') return 'hi-IN';
  if (lang === 'mr') return 'mr-IN';
  return 'en-IN'; // Indian English accent (Microsoft Ravi/Heera on Windows)
}

function findBestVoice(lang) {
  const voices = window.speechSynthesis.getVoices();
  const langCode = getLangCode(lang);

  // 1. Exact match (e.g. "hi-IN")
  let voice = voices.find(v => v.lang === langCode);
  if (voice) return voice;

  // 2. Prefix match (e.g. any voice starting with "hi")
  const prefix = langCode.split('-')[0];
  voice = voices.find(v => v.lang.startsWith(prefix));
  if (voice) return voice;

  // 3. For Hindi/Marathi: fall back to en-IN so at least something plays
  if (lang === 'hi' || lang === 'mr') {
    voice = voices.find(v => v.lang === 'en-IN')
      || voices.find(v => v.lang.startsWith('en-IN'));
    if (voice) {
      console.warn(`[AQ Voice] No ${langCode} voice installed. Using Indian English fallback. Install ${langCode} from Windows Settings > Time & Language > Speech.`);
      return voice;
    }
  }

  // 4. Last resort: any en voice
  voice = voices.find(v => v.lang.startsWith('en'));
  if (voice) return voice;

  console.warn(`[AQ Voice] No suitable voice found for ${langCode}. Available:`, voices.map(v => v.lang));
  return null;
}

const playVoiceReport = (rawAdvisory, lang) => {
  if (!window.speechSynthesis || !rawAdvisory) return;

  // 1. Kill any ongoing speech
  window.speechSynthesis.cancel();

  // 2. Clean English leaks
  const cleanText = getCleanAdvisory(rawAdvisory, lang);
  if (!cleanText) return;

  // 3. Split into sentences on period, purna viram, !, ?
  const sentences = cleanText
    .split(/(?<=[.!?।])/)
    .map(s => s.trim())
    .filter(s => s.length > 0);

  if (sentences.length === 0) return;

  // 4. Resolve voice once
  const langCode = getLangCode(lang);
  const matchedVoice = findBestVoice(lang);

  // 5. Chain utterances — no artificial delay, natural onend gap is enough
  function speakChain(index) {
    if (index >= sentences.length) return;

    const utt = new SpeechSynthesisUtterance(sentences[index]);
    utt.lang = langCode;
    utt.rate = 0.88;
    utt.pitch = 1.0;
    if (matchedVoice) utt.voice = matchedVoice;

    utt.onend = () => speakChain(index + 1);
    utt.onerror = () => speakChain(index + 1);

    window.speechSynthesis.speak(utt);
  }

  speakChain(0);
};

// ─── ICON FACTORIES ───────────────────────────────────────────────────────────

/**
 * createTriggerIcon
 * FIX #1: Attribution mode — cone points UPWIND (toward pollution source).
 *
 * Meteorological convention: windDeg = direction wind comes FROM.
 * SVG arrow naturally points right (East = 0°).
 * To point toward geographic North (0°), we need -90° CSS offset.
 *
 * For UPWIND (toward source): we want the cone pointing in the
 * windDeg direction (where wind originates = where source is).
 * cssRotate = windDeg - 90  (equivalently: (windDeg + 270) % 360)
 *
 * Previous (downwind): cssRotate = (windDeg + 90) % 360
 * Fixed    (upwind):   cssRotate = (windDeg + 270) % 360
 */
const createTriggerIcon = (windDeg = 0) => {
  const cssRotate = (windDeg + 270) % 360;

  // Each icon instance needs a unique gradient id to avoid cross-marker SVG
  // defs collisions when multiple markers share the same SVG namespace.
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

        <!-- Main fluid plume body with blur for smoke cloud effect -->
        <path
          filter="url(#sf_${cssRotate})"
          d="M0,18
             C16,18 28,11 52,9
             C76,7 100,4 130,2
             L130,38
             C100,36 76,33 52,31
             C28,29 16,22 0,22 Z"
          fill="url(#${gradId})"
        />

        <!-- Secondary wispy tendril -->
        <path
          d="M2,18 C20,15 40,9 70,8 C98,7 115,6 130,5
             L130,9 C115,10 98,11 70,12 C40,13 20,19 2,22 Z"
          fill="#f97316" opacity="0.18"
        />

        <!-- Animated smoke particles -->
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
        <!-- Outer ring: 6x expansion -->
        <div style="position:absolute;width:100%;height:100%;background:rgba(239,68,68,0.07);border-radius:50%;animation:ping3 2.8s cubic-bezier(0,0,0.2,1) infinite 0.8s;"></div>
        <!-- Mid ring: 4x expansion -->
        <div style="position:absolute;width:70%;height:70%;background:rgba(239,68,68,0.14);border-radius:50%;animation:ping2 2.3s cubic-bezier(0,0,0.2,1) infinite 0.4s;"></div>
        <!-- Inner ring: 2.8x expansion -->
        <div style="position:absolute;width:44%;height:44%;background:rgba(239,68,68,0.24);border-radius:50%;animation:ping 1.8s cubic-bezier(0,0,0.2,1) infinite;"></div>
        <!-- Neon crimson core -->
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

// ─── HELPERS ──────────────────────────────────────────────────────────────────

const confidenceColor = (score) => {
  if (score >= 0.88) return '#34d399';
  if (score >= 0.75) return '#fbbf24';
  return '#f87171';
};

const sourceEmoji = (typeStr) => {
  const s = typeStr?.toLowerCase() ?? '';
  if (s.includes('construction'))                 return '🏗️';
  if (s.includes('industrial') || s.includes('emission')) return '🏭';
  if (s.includes('traffic')    || s.includes('road'))     return '🚗';
  if (s.includes('waste')      || s.includes('burn'))     return '🔥';
  return '📍';
};

// ─── MAP CAMERA CONTROLLER ────────────────────────────────────────────────────
// Must live inside <MapContainer> to use useMap().
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
    const src = ranked_candidates?.find((s) => s?.id === activeSource);
    if (!src?.coordinates || src.coordinates.length < 2) return;
    map.flyTo([src.coordinates[1], src.coordinates[0]], 14, { animate: true, duration: 1.5 });
    prevRef.current = activeSource;
  }, [activeSource, ranked_candidates, map, mapCenter]);

  return null;
}

// ─── MAP INSTANCE TRACKER ─────────────────────────────────────────────────────
// Captures the Leaflet map object from React-Leaflet's context so imperative
// MapRenderer calls (stations, sources, wind cone) can operate on it.
function MapInstanceTracker({ setMapRef }) {
  const map = useMap();
  useEffect(() => {
    if (map) setMapRef(map);
  }, [map, setMapRef]);
  return null;
}

// ─── WIND COMPASS ─────────────────────────────────────────────────────────────
// Large floating 72×72 premium compass.
// windDeg = meteorological "FROM" direction. Needle points into the wind source.
// When activeSource has its own weather_snapshot, compass reflects that location.
function WindCompass({ windDeg, cardinal, label }) {
  const rot = windDeg ?? 0;
  const ticks = [0, 45, 90, 135, 180, 225, 270, 315];

  return (
    <div style={{
      position: 'absolute', bottom: 90, left: 24, zIndex: 1000,
      background: 'rgba(8,8,10,0.82)', border: '1px solid rgba(255,255,255,0.09)',
      backdropFilter: 'blur(28px)', borderRadius: 20,
      padding: '16px 18px', display: 'flex', flexDirection: 'column',
      alignItems: 'center', gap: 10, minWidth: 96,
    }}>
      <svg width="72" height="72" viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg">
        {/* Rings */}
        <circle cx="36" cy="36" r="34" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1.5"/>
        <circle cx="36" cy="36" r="25" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="1"/>
        {/* Tick marks */}
        {ticks.map((deg) => {
          const rad = (deg * Math.PI) / 180;
          const isCard = deg % 90 === 0;
          const r1 = isCard ? 27 : 30;
          return (
            <line key={deg}
              x1={36 + r1 * Math.sin(rad)} y1={36 - r1 * Math.cos(rad)}
              x2={36 + 34 * Math.sin(rad)} y2={36 - 34 * Math.cos(rad)}
              stroke={isCard ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.08)'}
              strokeWidth={isCard ? 1.5 : 0.8}
            />
          );
        })}
        {/* Cardinal labels */}
        {[
          { l: 'N', x: 36, y: 11  },
          { l: 'S', x: 36, y: 63  },
          { l: 'E', x: 62, y: 38  },
          { l: 'W', x: 10, y: 38  },
        ].map(({ l, x, y }) => (
          <text key={l} x={x} y={y}
            textAnchor="middle" dominantBaseline="middle"
            fontSize="7" fontWeight="700" fontFamily="-apple-system, sans-serif"
            fill={l === 'N' ? '#ef4444' : 'rgba(255,255,255,0.24)'}
            letterSpacing="0.06em"
          >{l}</text>
        ))}
        {/* Rotating needle — Fix #4: CSS inline transform for smooth animation */}
        <g
          style={{
            transform: `rotate(${rot}deg)`,
            transformOrigin: '36px 36px',
            transition: 'transform 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
          }}
        >
          {/* Red north tip */}
          <polygon points="36,10 33,36 36,31 39,36" fill="#ef4444" opacity="0.95"
            style={{ animation: 'needleSway 2.6s ease-in-out infinite' }}/>
          {/* Muted south tail */}
          <polygon points="36,62 33,36 36,41 39,36" fill="rgba(255,255,255,0.18)"/>
          {/* Hub */}
          <circle cx="36" cy="36" r="3.5" fill="#fafafa" opacity="0.7"/>
          <circle cx="36" cy="36" r="1.5" fill="#0a0a0e"/>
        </g>
      </svg>

      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#a1a1aa', letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 3 }}>
          {label}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#f4f4f5', fontFamily: 'monospace', letterSpacing: '0.04em' }}>
          {cardinal ?? '—'}
        </div>
        <div style={{ fontSize: 11, fontWeight: 500, color: '#a1a1aa', fontFamily: 'monospace', marginTop: 2 }}>
          {rot}°
        </div>
      </div>
    </div>
  );
}

// ─── APP ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [activeLang,   setActiveLang]   = useState('en');
  const [activeSource, setActiveSource] = useState(null);
  const [currentStation, setCurrentStation] = useState('Shivajinagar');
  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mapRef, setMapRef] = useState(null);
  const [currentConeLayer, setCurrentConeLayer] = useState(null);

  // ─── MapRenderer: Bootstrap station grid + source inventory on map ready ──
  useEffect(() => {
    if (!mapRef) return;

    const bootMapLayers = async () => {
      console.log('🗺️ Bootstrapping forensic map layers...');

      // 1. Station grid: all 4 monitoring points with AQI-aware pulse
      await MapRenderer.renderStations(mapRef, (stationName) => {
        setCurrentStation(stationName);
      });

      // 2. Source inventory: curated (solid red) + OSM-discovered (dashed amber)
      await MapRenderer.renderSources(mapRef);
    };

    bootMapLayers();
  }, [mapRef]);

  // ─── MapRenderer: Wind cone update on station change ──────────────────────
  useEffect(() => {
    if (!mapRef || !currentStation) return;

    const updateCone = async () => {
      const newConeLayer = await MapRenderer.updateWindConeLayer(
        mapRef,
        currentConeLayer,
        currentStation
      );
      setCurrentConeLayer(newConeLayer);
    };

    updateCone();
  }, [currentStation, mapRef]);

  useEffect(() => {
    setLoading(true);
    setActiveSource(null); // Reset selected source when switching stations
    API.getAttribution(currentStation)
      .then(data => {
        setDashboardData(data);
        setLoading(false);
      })
      .catch(err => {
        console.error("Scenario Integration Failed:", err);
        setLoading(false);
      });
  }, [currentStation]);

  // Auto-trigger speech stream on station swap or language toggle
  // Debounced to prevent rapid re-fires during React render cycles
  const speechTimerRef = useRef(null);
  useEffect(() => {
    // Cleanup: cancel pending speech and timer
    return () => {
      if (speechTimerRef.current) clearTimeout(speechTimerRef.current);
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    };
  }, []);

  useEffect(() => {
    if (loading || !dashboardData?.actionable_intelligence?.localized_advisory) return;

    // Clear any pending debounce from previous trigger
    if (speechTimerRef.current) clearTimeout(speechTimerRef.current);

    // Debounce: wait 600ms for state to settle before speaking
    speechTimerRef.current = setTimeout(() => {
      const advisoryObj = dashboardData.actionable_intelligence.localized_advisory;
      const targetSpeechText = activeLang === 'en' ? advisoryObj.en : activeLang === 'hi' ? advisoryObj.hi : advisoryObj.mr;

      if (targetSpeechText && targetSpeechText.trim() !== '') {
        playVoiceReport(targetSpeechText, activeLang);
      }
    }, 600);
  }, [dashboardData, activeLang, loading]);

  // Loading guard — show connecting screen until live data arrives
  if (loading || !dashboardData) {
    return (
      <div className="aq-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100vw', height: '100vh', background: '#08080a' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '24px', marginBottom: '10px' }}>🛰️</div>
          <div style={{ fontSize: '14px', fontFamily: 'monospace', color: '#a1a1aa' }}>Connecting to Live Intelligence Pipeline via Ngrok...</div>
        </div>
      </div>
    );
  }

  const {
    trigger_station,
    weather_snapshot,
    ranked_candidates,
    actionable_intelligence,
  } = dashboardData || {};

  // Guard: if coordinates are missing, fall back to Mumbai centre.
  const rawLat = trigger_station?.coordinates?.[1];
  const rawLng = trigger_station?.coordinates?.[0];
  const mapCenter = [
    (typeof rawLat === 'number' && !isNaN(rawLat)) ? rawLat : 19.076,
    (typeof rawLng === 'number' && !isNaN(rawLng)) ? rawLng : 72.877,
  ];

  const windDeg  = weather_snapshot?.wind_direction_deg ?? 0;
  const advisory = actionable_intelligence?.localized_advisory?.[activeLang] ?? '';
  const t        = I18N[activeLang] ?? I18N.en;

  // Compass reflects the selected source's local met data if available,
  // else falls back to the global weather_snapshot.
  const selSrc        = ranked_candidates?.find((s) => s?.id === activeSource) ?? null;
  const compassDeg    = selSrc?.weather_snapshot?.wind_direction_deg    ?? windDeg;
  const compassCard   = selSrc?.weather_snapshot?.wind_direction_cardinal ?? weather_snapshot?.wind_direction_cardinal ?? '—';

  return (
    <div className="aq-root">

      {/* ── MAP PANEL ───────────────────────────────────────────────────── */}
      <div className="map-panel">
        <MapContainer
          center={mapCenter}
          zoom={13}
          style={{ width: '100%', height: '100%' }}
          zoomControl={false}
          attributionControl={false}
        >
          {/* Stadia Alidade Smooth Dark: sharp silver roads on charcoal matte */}
          <TileLayer
            url="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png"
            maxZoom={20}
          />

          {/* MapRenderer: capture Leaflet instance for imperative layer control */}
          <MapInstanceTracker setMapRef={setMapRef} />

          {/* Cinematic flyTo controller */}
          <MapCameraController
            activeSource={activeSource}
            ranked_candidates={ranked_candidates}
            mapCenter={mapCenter}
          />

          {/* Wind Cone GeoJSON Overlay */}
          {dashboardData?.wind_cone_geometry && (
            <GeoJSON
              key={currentStation}
              data={dashboardData.wind_cone_geometry}
              style={(feature) => {
                const s = feature?.properties?.style;
                return {
                  color: s?.stroke_color || '#fb923c',
                  weight: s?.stroke_width || 1.5,
                  fillColor: s?.fill_color || '#fb923c',
                  fillOpacity: s?.fill_opacity || 0.08,
                  dashArray: '5, 5'
                };
              }}
            />
          )}

          {/* Trigger station: neon crimson core + fluid smoky plume */}
          <Marker position={mapCenter} icon={createTriggerIcon(windDeg)}>
            <Popup>
              <div className="popup-inner">
                <div className="popup-station-name">{trigger_station?.name ?? 'Trigger Station'}</div>
                <div className="popup-aqi-badge">
                  <span style={{ width:6, height:6, borderRadius:'50%', background:'#ef4444', display:'inline-block' }}/>
                  CRITICAL · {trigger_station?.reading?.total_aqi ?? '—'} AQI
                </div>
              </div>
            </Popup>
          </Marker>

          {/* Attributed source markers */}
          {ranked_candidates?.map((src) => {
            if (!src?.coordinates || src.coordinates.length < 2) return null;
            return (
              <Marker
                key={src.id}
                position={[src.coordinates[1], src.coordinates[0]]}
                icon={createSourceIcon(src.rank)}
              >
                <Popup>
                  <div className="popup-inner">
                    <div className="popup-rank-label">
                      Rank {src?.rank} · {translateSourceType(src?.type, activeLang)}
                    </div>
                    <div className="popup-source-name">{translateSourceName(src?.name, activeLang)}</div>
                  </div>
                </Popup>
              </Marker>
            );
          })}
        </MapContainer>

        {/* Live feed badge */}
        <div className="live-badge">
          <div className="live-dot"/>
          <span className="live-text">{t.live_feed}</span>
        </div>

        {/* ── DEMO SCENARIO SELECTOR CAPSULE BAR ── */}
        <div style={{
          position: 'absolute', top: '20px', left: '160px', zIndex: 1000,
          display: 'flex', gap: '6px', background: 'rgba(8,8,10,0.85)',
          padding: '4px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(20px)'
        }}>
          {[
            { id: 'Shivajinagar', en: 'Construction', hi: 'निर्माण कार्य', mr: 'बांधकाम' },
            { id: 'Swargate', en: 'Traffic', hi: 'यातायात क्षेत्र', mr: 'वाहतूक' },
            { id: 'Hadapsar', en: 'Industrial', hi: 'औद्योगिक क्षेत्र', mr: 'औद्योगिक' },
            { id: 'Kothrud', en: 'Ambiguity', hi: 'अस्पष्ट घटना', mr: 'अस्पष्ट घटना' }
          ].map((scen) => (
            <button
              key={scen.id}
              onClick={() => setCurrentStation(scen.id)}
              style={{
                padding: '6px 12px', borderRadius: '7px', border: 'none', cursor: 'pointer',
                fontSize: '11px', fontWeight: 700, fontFamily: 'monospace',
                letterSpacing: '0.05em', textTransform: 'uppercase',
                background: currentStation === scen.id ? 'rgba(251,146,60,0.15)' : 'transparent',
                color: currentStation === scen.id ? '#fb923c' : '#a1a1aa',
                border: currentStation === scen.id ? '1px solid rgba(251,146,60,0.3)' : '1px solid transparent',
                transition: 'all 0.2s ease'
              }}
            >
              {scen[activeLang] || scen.en}
            </button>
          ))}
        </div>

        {/* MET strip */}
        <div className="met-badge">
          <span className="met-icon">🛰️</span>
          <span className="met-label">{t.met_label}</span>
          <div className="met-dot"/>
          <span className="met-value">{weather_snapshot?.wind_speed_kmh ?? '—'} km/h</span>
          <div className="met-dot"/>
          <span className="met-value">
            {weather_snapshot?.wind_direction_cardinal ?? '—'} · {weather_snapshot?.wind_direction_deg ?? '—'}°
          </span>
        </div>

        {/* Large floating wind compass — needle pivots when source is selected */}
        <WindCompass
          windDeg={compassDeg}
          cardinal={compassCard}
          label={t.wind_label}
        />
      </div>

      {/* ── SIDEBAR ───────────────────────────────────────────────────────── */}
      <div className="sidebar">
        <div className="sidebar-scroll">

          {/* Header */}
          <div className="header-row">
            <div style={{ flex: 1 }}>
              <div className="header-meta">{trigger_station?.network ?? 'CPCB'}</div>
              <div className="header-title">{trigger_station?.name ?? '—'}</div>
              <div className="header-sub">{trigger_station?.city ?? '—'}, {t.maharashtra}</div>
            </div>
            <div className="aqi-pill">
              <div className="aqi-pulse-dot"/>
              <div>
                <div className="aqi-number">{trigger_station?.reading?.total_aqi ?? '—'}</div>
                <div className="aqi-label">AQI</div>
              </div>
            </div>
          </div>

          <div className="rule"/>

          {/* Action Advisory + language switcher */}
          <div>
            <div className="advisory-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span className="section-label" style={{ letterSpacing: '0.15em' }}>
                  {activeLang === 'en' ? 'ACTION ADVISORY' : activeLang === 'hi' ? 'कार्य योजना सलाह' : 'कृती सल्ला'}
                </span>
                
                {/* Dynamic Forensic Voice Dispatch Trigger */}
                <button
                  onClick={() => {
                    const advObj = dashboardData?.actionable_intelligence?.localized_advisory;
                    const targetText = activeLang === 'en' ? advObj?.en : activeLang === 'hi' ? advObj?.hi : advObj?.mr;
                    if (targetText) playVoiceReport(targetText, activeLang);
                  }}
                  style={{
                    background: 'rgba(251,146,60,0.1)',
                    border: '1px solid rgba(251,146,60,0.25)',
                    borderRadius: '6px',
                    color: '#fb923c',
                    padding: '4px 10px',
                    fontSize: '11px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.2s ease'
                  }}
                  onMouseEnter={(e) => e.target.style.background = 'rgba(251,146,60,0.2)'}
                  onMouseLeave={(e) => e.target.style.background = 'rgba(251,146,60,0.1)'}
                >
                  🔊 {activeLang === 'en' ? 'Listen' : activeLang === 'hi' ? 'सुनें' : 'ऐका'}
                </button>
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

            {/* Ambiguity Alert Banner */}
            {dashboardData?.pre_alerts?.source?.includes('AMBIGUITY') && (
              <div style={{
                background: 'rgba(245,158,11,0.08)',
                border: '1px solid rgba(245,158,11,0.25)',
                borderRadius: '12px',
                padding: '12px 16px',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px'
              }}>
                <span style={{ fontSize: '16px', animation: 'livePulse 2s infinite' }}>⚠️</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '11px', fontWeight: 800, color: '#f59e0b', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                    {activeLang === 'en' ? 'Ambiguity Warning' : activeLang === 'hi' ? 'अस्पष्टता चेतावनी' : 'अस्पष्टता चेतावणी'}
                  </div>
                  <div style={{ fontSize: '12px', color: '#fbbf24', marginTop: '2px', fontWeight: 500 }}>
                    {activeLang === 'en'
                      ? 'Multiple potential sources identified. On-field verification is recommended.'
                      : activeLang === 'hi'
                      ? 'कई संभावित स्रोत मिले हैं। जमीनी सत्यापन की सिफारिश की जाती है।'
                      : 'अनेक संभाव्य स्रोत आढळले आहेत. प्रत्यक्ष तपासणीची शिफारस केली जाते.'}
                  </div>
                </div>
              </div>
            )}

            <div className="advisory-card">
              <p className="advisory-text">
                {(() => {
                  const advisoryObj = dashboardData?.actionable_intelligence?.localized_advisory;
                  const currentText = advisoryObj
                    ? (activeLang === 'en' ? advisoryObj.en : activeLang === 'hi' ? advisoryObj.hi : advisoryObj.mr)
                    : '';
                  return currentText ? getCleanAdvisory(currentText, activeLang) : 'विवरण लोड हो रहा है...';
                })()}
              </p>
            </div>
          </div>

          {/* ── TASK 2: PRE-ALERT FORECASTING PANEL ─────────────────────── */}
          {dashboardData?.pre_alerts && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="section-label" style={{ color: '#fb923c', letterSpacing: '0.2em' }}>
                  {activeLang === 'en' ? 'PRE-EMPTIVE FORECAST' : activeLang === 'hi' ? 'आगामी पूर्वानुमान' : 'आगामी अंदाज'}
                </span>
                <span style={{ fontSize: '10px', background: 'rgba(251,146,60,0.12)', border: '1px solid rgba(251,146,60,0.22)', color: '#fb923c', padding: '2px 8px', borderRadius: '50px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  {activeLang === 'en' ? 'Predictive' : 'अनुमानित'}
                </span>
              </div>

              <div style={{
                background: 'rgba(251,146,60,0.025)',
                border: '1px solid rgba(251,146,60,0.12)',
                borderRadius: '14px',
                padding: '14px',
                position: 'relative',
                overflow: 'hidden'
              }}>
                {/* Decorative top bar matching the predictive theme */}
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '1.5px', background: 'linear-gradient(to right, #fb923c, transparent)' }} />

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f4f4f5' }}>
                    {translateSourceName(dashboardData.pre_alerts.source, activeLang)}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#fb923c', fontFamily: 'monospace' }}>
                      +{dashboardData.pre_alerts.estimated_aqi_increase} AQI
                    </div>
                    <div style={{ fontSize: '9px', color: '#a1a1aa', fontWeight: 600, textTransform: 'uppercase', marginTop: '2px' }}>
                      {activeLang === 'en' ? 'Est. Impact' : 'संभावित प्रभाव'}
                    </div>
                  </div>
                </div>

                <p style={{ fontSize: '12px', color: '#d4d4d8', lineHeight: '1.6', marginBottom: '10px', fontWeight: 500 }}>
                  {translatePreAlertAdvisory(dashboardData.pre_alerts.advisory, activeLang)}
                </p>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(255,255,255,0.03)', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.04)' }}>
                  <span style={{ fontSize: '12px', animation: 'livePulse 1.5s ease-in-out infinite' }}>⏳</span>
                  <span style={{ fontSize: '11px', fontWeight: 600, color: '#a1a1aa' }}>
                    {activeLang === 'en'
                      ? `Impact ETA: `
                      : activeLang === 'hi'
                      ? `प्रभाव का समय: `
                      : `प्रभाव वेळ: `}
                    <span style={{ color: '#fb923c', fontFamily: 'monospace', fontWeight: 700 }}>
                      ~{dashboardData.pre_alerts.eta_minutes} mins
                    </span>
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Attributed Sources list */}
          <div>
            <div style={{ marginBottom: 12 }}>
              <span className="section-label">{t.attributed_sources}</span>
            </div>
            <div className="sources-list">
              {ranked_candidates?.map((src) => {
                const score    = src?.score_breakdown?.confidence_score ?? 0;
                const color    = confidenceColor(score);
                const pct      = (score * 100).toFixed(0);
                const emoji    = sourceEmoji(src?.type);
                const isActive = activeSource === src?.id;
                const typeLabel = translateSourceType(src?.type, activeLang);

                return (
                  <div
                    key={src?.id}
                    className={`source-card${isActive ? ' active' : ''}`}
                    onClick={() => setActiveSource(isActive ? null : src?.id)}
                  >
                    <div className="source-icon-box">{emoji}</div>
                    <div className="source-info">
                      <div className="source-top">
                        <span className="rank-badge">{t.rank_prefix}{src?.rank}</span>
                        <span className="source-type-tag">{typeLabel}</span>
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
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="sidebar-footer">
          <span className="footer-engine">{t.footer_engine}</span>
          <span className="footer-version">v{actionable_intelligence?.enforcement_priority ?? '1'}.04</span>
        </div>
      </div>

    </div>
  );
}