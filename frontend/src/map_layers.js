/**
 * AeroTrace AI ΓÇö Map Layer Renderer Module
 * ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
 * Modular Leaflet rendering engine for 3 core forensic layers:
 *   1. Station Grid Layer (monitoring stations with AQI-aware pulse)
 *   2. Pollution Source Layer (curated vs. OSM-discovered differentiation)
 *   3. Upwind Wind Cone GeoJSON Overlay (dynamic polygon mesh)
 *
 * All coordinate handling follows GeoJSON convention: [longitude, latitude].
 * Backend API returns coordinates in this order; Leaflet expects [lat, lon].
 * Every coordinate access swaps accordingly.
 *
 * Designed to integrate with App.jsx's React-Leaflet lifecycle.
 * Can also be used standalone with vanilla Leaflet via initMap().
 */
import L from 'leaflet';
import { API } from './api_client';

// ——— CONSTANTS ————————————————————————————————————————————————————————————————————————————————————————
const PUNE_CENTER = [18.5204, 73.8567]; // [lat, lon] for Leaflet
const AQI_SEVERE_THRESHOLD = 200;

// Source type → emoji mapping (matches App.jsx sourceEmoji)
const SOURCE_EMOJI = {
  construction: '\uD83C\uDFD7\uFE0F', // 🏗️
  industrial:   '\uD83C\uDFED',       // 🏭
  traffic:      '\uD83D\uDE97',       // 🚗
  waste_burning:'\uD83D\uDD25',       // 🔥
};

const getSourceEmoji = (typeStr) => {
  const s = (typeStr ?? '').toLowerCase();
  if (s.includes('construction'))                         return SOURCE_EMOJI.construction;
  if (s.includes('industrial') || s.includes('emission')) return SOURCE_EMOJI.industrial;
  if (s.includes('traffic')    || s.includes('road'))     return SOURCE_EMOJI.traffic;
  if (s.includes('waste')      || s.includes('burn'))     return SOURCE_EMOJI.waste_burning;
  return '\uD83D\uDCCC'; // 📌
};


// ——— ICON FACTORIES —————————————————————————————————————————————————————————————————————————————————————

/**
 * Station marker: pulsing circle whose animation class changes based on AQI.
 * Normal state — steady glow. AQI > 200 — aggressive crimson pulse.
 */
const createStationIcon = (station) => {
  const aqi = station.spike_aqi ?? 0;
  const isSevere = aqi > AQI_SEVERE_THRESHOLD;

  const coreColor  = isSevere ? '#ef4444' : '#3b82f6';
  const glowColor  = isSevere ? 'rgba(239,68,68,0.35)' : 'rgba(59,130,246,0.25)';
  const pulseAnim  = isSevere
    ? 'animation:stationPulseSevere 1.4s ease-in-out infinite;'
    : 'animation:stationPulseNormal 2.8s ease-in-out infinite;';
  const ringAnim   = isSevere
    ? 'animation:stationRingExpand 2s cubic-bezier(0,0,0.2,1) infinite;'
    : '';

  return L.divIcon({
    className: 'map-layer-station-icon',
    html: `
      <div style="position:relative;display:flex;align-items:center;justify-content:center;width:36px;height:36px;">
        ${isSevere ? `<div style="position:absolute;width:100%;height:100%;background:${glowColor};border-radius:50%;${ringAnim}"></div>` : ''}
        <div style="position:absolute;width:75%;height:75%;background:${glowColor};border-radius:50%;${pulseAnim}"></div>
        <div style="
          width:14px;height:14px;
          background:radial-gradient(circle at 35% 35%, ${isSevere ? '#ff8080' : '#60a5fa'}, ${coreColor});
          border-radius:50%;
          border:2px solid rgba(255,255,255,0.85);
          box-shadow:0 0 0 2px ${glowColor}, 0 0 12px ${coreColor}88;
          z-index:2;position:relative;
        "></div>
      </div>
    `,
    iconSize:   [36, 36],
    iconAnchor: [18, 18],
    popupAnchor:[0, -18],
  });
};


/**
 * Source marker: differentiated by origin (curated vs. OSM).
 * Curated — solid red circle. OSM — amber dashed outline.
 */
const createSourceIcon = (source) => {
  const isOSM = source.source_origin === 'osm';
  const fillColor   = isOSM ? '#f59e0b' : '#ef4444';
  const borderStyle = isOSM ? 'border:2px dashed #d97706;' : 'border:2px solid #dc2626;';
  const glowColor   = isOSM ? 'rgba(245,158,11,0.2)' : 'rgba(239,68,68,0.2)';
  const emoji = getSourceEmoji(source.source_type);

  return L.divIcon({
    className: 'map-layer-source-icon',
    html: `
      <div style="position:relative;display:flex;align-items:center;justify-content:center;width:28px;height:28px;">
        <div style="position:absolute;width:100%;height:100%;background:${glowColor};border-radius:50%;animation:pulse 2.4s ease-in-out infinite;"></div>
        <div style="
          width:12px;height:12px;
          background:radial-gradient(circle at 35% 35%, ${isOSM ? '#fbbf24' : '#f87171'}, ${fillColor});
          border-radius:50%;
          ${borderStyle}
          box-shadow:0 0 8px ${fillColor}66;
          z-index:2;position:relative;
        "></div>
      </div>
    `,
    iconSize:   [28, 28],
    iconAnchor: [14, 14],
    popupAnchor:[0, -14],
  });
};


// ——— POPUP BUILDERS ———————————————————————————————————————————————————————————————————————————————————

const buildStationPopup = (station) => `
  <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-width:180px;">
    <div style="font-weight:700;font-size:13px;color:#f8fafc;margin-bottom:4px;">
      \uD83D\uDCCD ${station.name}
    </div>
    <div style="font-size:11px;color:#94a3b8;line-height:1.5;">
      <div>Network: <span style="color:#cbd5e1;">${station.network}</span></div>
      <div>City: <span style="color:#cbd5e1;">${station.city}, ${station.state}</span></div>
      <div>Elevation: <span style="color:#cbd5e1;">${station.elevation_m}m</span></div>
      <div>Scenario: <span style="color:#fbbf24;">${station.scenario_type}</span></div>
      <div style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,0.08);">
        Spike AQI: <span style="color:${station.spike_aqi > 300 ? '#ef4444' : '#fbbf24'};font-weight:700;">${station.spike_aqi}</span>
        &middot; <span style="color:#cbd5e1;text-transform:uppercase;font-size:10px;">${station.dominant_pollutant}</span>
      </div>
    </div>
  </div>
`;

const buildSourcePopup = (source) => {
  const emoji = getSourceEmoji(source.source_type);
  const originBadge = source.source_origin === 'osm'
    ? '<span style="background:#f59e0b22;color:#f59e0b;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;border:1px dashed #d97706;">OSM DISCOVERED</span>'
    : '<span style="background:#ef444422;color:#ef4444;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;border:1px solid #dc2626;">CURATED</span>';

  return `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-width:200px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="font-size:16px;">${emoji}</span>
        <span style="font-weight:700;font-size:12px;color:#f8fafc;">${source.name || 'Unidentified Source'}</span>
      </div>
      <div style="font-size:11px;color:#94a3b8;line-height:1.6;">
        <div>Type: <span style="color:#cbd5e1;text-transform:capitalize;">${source.source_type}</span></div>
        <div style="margin-top:3px;">${originBadge}</div>
        ${source.description ? `<div style="margin-top:4px;font-style:italic;color:#64748b;font-size:10px;">${source.description}</div>` : ''}
      </div>
    </div>
  `;
};


// ΓöÇΓöÇΓöÇ GEOMETRY HELPERS ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

/**
 * Extract a [lat, lon] position from a GeoJSON geometry object.
 * Handles Point, Polygon (centroid of first ring), and LineString (midpoint).
 */
const extractLatLng = (geometry) => {
  if (!geometry || !geometry.coordinates) return null;

  switch (geometry.type) {
    case 'Point':
      // GeoJSON: [lon, lat] ΓåÆ Leaflet: [lat, lon]
      return [geometry.coordinates[1], geometry.coordinates[0]];

    case 'Polygon': {
      // Use centroid of outer ring
      const ring = geometry.coordinates[0];
      if (!ring || ring.length === 0) return null;
      const sumLon = ring.reduce((s, c) => s + c[0], 0);
      const sumLat = ring.reduce((s, c) => s + c[1], 0);
      return [sumLat / ring.length, sumLon / ring.length];
    }

    case 'LineString': {
      // Use midpoint
      const coords = geometry.coordinates;
      if (!coords || coords.length === 0) return null;
      const mid = coords[Math.floor(coords.length / 2)];
      return [mid[1], mid[0]];
    }

    default:
      return null;
  }
};


// ΓöÇΓöÇΓöÇ WIND CONE STYLE ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

const windConeStyle = (feature) => {
  const s = feature?.properties?.style;
  return {
    color:       s?.stroke_color || '#fb923c',
    weight:      s?.stroke_width || 1.5,
    fillColor:   s?.fill_color   || '#fb923c',
    fillOpacity: s?.fill_opacity || 0.08,
    opacity:     0.8,
    dashArray:   '5, 5',
    className:   'wind-cone-sweep',
  };
};


// ΓöÇΓöÇΓöÇ KEYFRAME INJECTION ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
// Inject additional keyframes for station pulse animations.
// These complement the existing GLOBAL_STYLES in App.jsx.

let _stylesInjected = false;
const injectLayerStyles = () => {
  if (_stylesInjected) return;
  _stylesInjected = true;

  const style = document.createElement('style');
  style.textContent = `
    @keyframes stationPulseNormal {
      0%, 100% { transform: scale(1);    opacity: 0.7; }
      50%       { transform: scale(1.25); opacity: 0.3; }
    }
    @keyframes stationPulseSevere {
      0%, 100% { transform: scale(1);   opacity: 0.9; }
      50%       { transform: scale(1.4); opacity: 0.35; }
    }
    @keyframes stationRingExpand {
      0%   { transform: scale(0.9); opacity: 0.6; }
      70%  { transform: scale(2.8); opacity: 0;   }
      100% { transform: scale(0.9); opacity: 0;   }
    }
    .wind-cone-sweep {
      transition: fill-opacity 0.6s ease, opacity 0.6s ease;
    }
    /* Ensure map layer icons have no default Leaflet styling conflicts */
    .map-layer-station-icon,
    .map-layer-source-icon {
      background: transparent !important;
      border: none !important;
    }
  `;
  document.head.appendChild(style);
};


// ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
// MAP RENDERER ΓÇö Public API
// ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ

export const MapRenderer = {

  // ΓöÇΓöÇΓöÇ 1. CORE MAP INIT (Vanilla Leaflet ΓÇö standalone mode) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
  /**
   * Initialise a vanilla Leaflet map centred on Pune.
   * Use this only if NOT using React-Leaflet's <MapContainer>.
   */
  initMap(containerId) {
    injectLayerStyles();

    const map = L.map(containerId, {
      zoomControl: false,
      attributionControl: false,
    }).setView(PUNE_CENTER, 13);

    L.tileLayer(
      'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png',
      { maxZoom: 20 }
    ).addTo(map);

    return map;
  },


  // ΓöÇΓöÇΓöÇ 2. STATION GRID LAYER ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
  /**
   * Fetch stations from API and render as pulsing circle markers.
   * AQI > 200 ΓåÆ crimson pulse animation. Otherwise ΓåÆ calm blue glow.
   *
   * @param {L.Map} map - The Leaflet map instance.
   * @param {Function} onStationSelect - Callback(stationName) on click.
   * @returns {L.LayerGroup} The station layer group (for later removal).
   */
  async renderStations(map, onStationSelect) {
    injectLayerStyles();

    try {
      const response = await API.getStations();
      // API returns { stations: [...] }
      const stations = response.stations ?? response;
      const stationLayer = L.layerGroup().addTo(map);

      stations.forEach((station) => {
        // Backend coordinates: [lon, lat] (GeoJSON) ΓåÆ Leaflet [lat, lon]
        const coords = station.coordinates;
        if (!coords || coords.length < 2) return;
        const latLng = [coords[1], coords[0]];

        const marker = L.marker(latLng, {
          icon: createStationIcon(station),
          zIndexOffset: 1000,
        });

        marker.bindPopup(buildStationPopup(station), {
          className: 'forensic-popup',
          maxWidth: 280,
        });

        marker.on('click', () => {
          if (onStationSelect) onStationSelect(station.name);
        });

        marker.addTo(stationLayer);
      });

      console.log(`[MapRenderer] Rendered ${stations.length} station markers`);
      return stationLayer;

    } catch (err) {
      console.error('[MapRenderer] Failed to render station grid:', err);
      return null;
    }
  },


  // ΓöÇΓöÇΓöÇ 3. POLLUTION SOURCE LAYER ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
  /**
   * Fetch all pollution sources and render with origin-based differentiation.
   * curated ΓåÆ solid red marker. osm ΓåÆ dashed amber outline.
   *
   * Also renders Polygon/LineString geometries as GeoJSON overlays
   * in addition to point markers at centroids.
   *
   * @param {L.Map} map - The Leaflet map instance.
   * @returns {{ markerLayer: L.LayerGroup, geoJsonLayer: L.LayerGroup }} Layers.
   */
  async renderSources(map) {
    injectLayerStyles();

    try {
      const response = await API.getSources();
      // API returns { count, sources: [...] }
      const sources = response.sources ?? response;
      const markerLayer  = L.layerGroup().addTo(map);
      const geoJsonLayer = L.layerGroup().addTo(map);

      let curatedCount = 0;
      let osmCount = 0;

      sources.forEach((source) => {
        const latLng = extractLatLng(source.geometry);
        if (!latLng) return;

        // Track origin counts
        if (source.source_origin === 'osm') osmCount++;
        else curatedCount++;

        // Point marker at centroid
        const marker = L.marker(latLng, {
          icon: createSourceIcon(source),
          zIndexOffset: source.source_origin === 'curated' ? 500 : 200,
        });

        marker.bindPopup(buildSourcePopup(source), {
          className: 'forensic-popup',
          maxWidth: 300,
        });

        marker.addTo(markerLayer);

        // If geometry is Polygon or LineString, render as GeoJSON overlay
        if (source.geometry && source.geometry.type !== 'Point') {
          const isOSM = source.source_origin === 'osm';
          const geoFeature = {
            type: 'Feature',
            geometry: source.geometry,
            properties: { name: source.name, origin: source.source_origin },
          };

          L.geoJSON(geoFeature, {
            style: () => ({
              color:       isOSM ? '#f59e0b' : '#ef4444',
              weight:      isOSM ? 1.5 : 2,
              fillColor:   isOSM ? '#f59e0b' : '#ef4444',
              fillOpacity: isOSM ? 0.06 : 0.10,
              dashArray:   isOSM ? '6, 4' : null,
            }),
          }).addTo(geoJsonLayer);
        }
      });

      console.log(`[MapRenderer] Rendered ${sources.length} sources (${curatedCount} curated, ${osmCount} OSM)`);
      return { markerLayer, geoJsonLayer };

    } catch (err) {
      console.error('[MapRenderer] Failed to render source matrix:', err);
      return null;
    }
  },


  // ΓöÇΓöÇΓöÇ 4. WIND CONE GEOJSON LAYER ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
  /**
   * Fetch and render the upwind wind cone for a given station.
   * Removes the previous cone layer to prevent stacking.
   *
   * @param {L.Map} map - The Leaflet map instance.
   * @param {L.Layer|null} currentLayer - Previous cone layer to remove.
   * @param {string} stationName - Target station (e.g. 'Shivajinagar').
   * @param {string|null} timestamp - Optional ISO timestamp for replay.
   * @returns {L.GeoJSON|null} The new cone layer.
   */
  async updateWindConeLayer(map, currentLayer, stationName, timestamp = null) {
    // Purge old cone to prevent overlapping visual artefacts
    if (currentLayer) {
      map.removeLayer(currentLayer);
    }

    try {
      const coneGeoJSON = await API.getWindCone(stationName, timestamp);

      const newLayer = L.geoJSON(coneGeoJSON, {
        style: windConeStyle,
      }).addTo(map);

      const props = coneGeoJSON?.properties ?? {};
      console.log(
        `[MapRenderer] Wind cone rendered: ${stationName}`,
        `| Half-angle: ${props.half_angle_deg}┬░`,
        `| Reach: ${props.reach_km} km`,
        `| Pasquill: ${props.pasquill_class}`
      );

      return newLayer;

    } catch (err) {
      console.error(`[MapRenderer] Failed to render wind cone for ${stationName}:`, err);
      return null;
    }
  },


  // ΓöÇΓöÇΓöÇ UTILITIES ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

  /** Clear all custom layers from the map. */
  clearLayers(map, ...layers) {
    layers.forEach((layer) => {
      if (layer && map.hasLayer(layer)) {
        map.removeLayer(layer);
      }
    });
  },

  /** Get Pune center coordinates for Leaflet [lat, lon]. */
  getPuneCenter() {
    return [...PUNE_CENTER];
  },

  /** Swap GeoJSON [lon, lat] ΓåÆ Leaflet [lat, lon]. */
  geoToLatLng(coords) {
    if (!coords || coords.length < 2) return null;
    return [coords[1], coords[0]];
  },
};

export default MapRenderer;
