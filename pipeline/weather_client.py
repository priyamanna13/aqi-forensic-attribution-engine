"""OpenWeatherMap weather client with offline caching and contract-shaped output.

Responsibilities (Task 2, Part 2):
  - Fetch current weather for a lat/lon from the OpenWeatherMap "Current
    Weather Data" API (``/data/2.5/weather``) via ``requests``.
  - **Resilience caching (Improvement #8):** every successful response is
    persisted to ``api_cache/<cache_key>.json``. If the network call fails,
    times out, or is rate-limited (HTTP 429), the last good cached snapshot
    for that location is returned silently — never raises to the caller.
  - Convert OWM wind speed (m/s) -> km/h (``* 3.6``).
  - Map wind direction degrees -> 16-point cardinal (delegated to pasquill).
  - Estimate Pasquill-Gifford stability from wind speed + hour-of-day.
  - Produce a ``WeatherSnapshot`` dataclass that mirrors the contract's
    ``weather_snapshot`` block (keys, nesting, value types).

OWM does not return mixing-layer height, cloud cover in oktas, or visibility
in km directly in the free "current" tier; we map what OWM gives us (visibility
in meters -> km; cloud cover % -> oktas; a simple MLH heuristic) and clearly
mark the heuristic origins in code.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

from .pasquill import StabilityProfile, classify_stability, wind_direction_cardinal

log = logging.getLogger(__name__)

# Resolve the cache dir relative to the project root (parent of pipeline/).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = _PROJECT_ROOT / "api_cache"

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"

# Tunables (overridable via env). Read lazily through helpers for testability.
_DEFAULT_TIMEOUT = float(os.getenv("OWM_API_TIMEOUT", "10"))


@dataclass
class WeatherSnapshot:
    """Mirrors the contract's ``weather_snapshot`` object (top-level keys)."""

    source: str
    observed_at: str                       # ISO 8601 with offset, e.g. +05:30
    wind_speed_kmh: float
    wind_direction_deg: float              # 0–360
    wind_direction_cardinal: str           # 16-point, e.g. "WNW"
    temperature_c: float
    relative_humidity_pct: float
    pressure_hpa: float
    cloud_cover_oktas: int                 # 0–8
    precipitation_mm_last_1h: float
    # Always numeric per the data contract (missing/unknown -> clear-sky 10 km).
    visibility_km: float
    mixing_layer_height_m: int             # heuristic estimate
    atmospheric_stability: dict[str, Any]  # contract-shaped sub-object

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# OWM response parsing
# --------------------------------------------------------------------------
def _round(v: Any, ndigits: int = 1) -> float:
    """Round defensively; None passes through."""
    if v is None:
        return 0.0
    return round(float(v), ndigits)


def _to_oktas(cloud_pct: Optional[float]) -> int:
    """Convert OWM cloud ``all`` (0–100 percent) to eighths (0–8 oktas)."""
    if cloud_pct is None:
        return 0
    return max(0, min(8, round(cloud_pct / 12.5)))


def _wind_from_origin_deg(owm_deg: Optional[float]) -> float:
    """OWM reports the direction wind is coming FROM. Keep it as-is (0–360).

    The contract's ``wind_direction_deg`` (sample value 290 -> WNW) uses the
    meteorological convention (direction the wind blows FROM), so we pass the
    OWM value through unchanged.
    """
    if owm_deg is None:
        return 0.0
    return round(owm_deg % 360, 1)


def _estimate_mixing_layer_height(
    stability: StabilityProfile,
    hour: int,
    cloud_oktas: int,
) -> int:
    """Heuristic daytime/nighttime mixing-layer height (m).

    OWM's free current-weather tier does not expose MLH. We use a simple
    proxy: unstable classes + midday + clear skies -> taller boundary layer;
    stable nighttime + clear -> shallow. Values are bounded to a plausible
    50–2500 m range and rounded to the nearest 10 m.

    This is intentionally a coarse estimator — sufficient for ranking source
    dispersion potential, which is the only role MLH plays in the pipeline.
    """
    day = 6 <= hour < 18
    base = {
        "A": 1800, "B": 1500, "C": 1200,
        "D": 800,
        "E": 300, "F": 150,
    }[stability.pasquill_class]
    if day:
        # Midday peak (11–14h) and clearer skies raise the boundary layer.
        solar_boost = max(0.0, 1.0 - abs(hour - 12.5) / 6.0)
        clear_boost = max(0.0, (8 - cloud_oktas) / 8.0)
        mlh = base * (0.7 + 0.6 * solar_boost * clear_boost)
    else:
        mlh = base * (0.5 + 0.1 * (cloud_oktas / 8.0))
    return int(max(50, min(2500, round(mlh / 10.0) * 10)))


def parse_owm_response(
    payload: dict[str, Any],
    *,
    source: str = "OpenWeatherMap",
) -> WeatherSnapshot:
    """Convert a raw OWM ``/data/2.5/weather`` JSON payload into a snapshot.

    Pure function — no I/O — so it is directly unit-testable.
    """
    wind = payload.get("wind", {}) or {}
    main = payload.get("main", {}) or {}
    clouds = payload.get("clouds", {}) or {}
    rain = payload.get("rain", {}) or {}

    wind_speed_ms = wind.get("speed")
    wind_speed_kmh = _round((wind_speed_ms or 0.0) * 3.6, 1)
    wind_deg = _wind_from_origin_deg(wind.get("deg"))

    # OWM ``dt`` is unix UTC; build an offset-aware ISO string in local tz.
    dt_unix = payload.get("dt") or int(time.time())
    tz_offset_sec = int(payload.get("timezone") or 0)
    observed_iso = _unix_to_iso_with_offset(int(dt_unix), tz_offset_sec)
    hour_local = _hour_of_local_time(int(dt_unix), tz_offset_sec)

    stability = classify_stability(wind_speed_kmh, hour_local)

    visibility_m = payload.get("visibility")
    # Contract requires visibility_km to be numeric. OWM omits it sometimes;
    # treat a missing value as clear-sky (10 km) rather than null.
    visibility_km = _round(visibility_m / 1000.0, 1) if visibility_m else 10.0

    cloud_oktas = _to_oktas(clouds.get("all"))
    mlh = _estimate_mixing_layer_height(stability, hour_local, cloud_oktas)

    precip = rain.get("1h")
    precipitation = _round(precip, 2) if precip is not None else 0.0

    snapshot = WeatherSnapshot(
        source=source,
        observed_at=observed_iso,
        wind_speed_kmh=wind_speed_kmh,
        wind_direction_deg=wind_deg,
        wind_direction_cardinal=wind_direction_cardinal(wind_deg),
        temperature_c=_round((main.get("temp") or 0.0) - 273.15, 1),  # K -> C
        relative_humidity_pct=round(float(main.get("humidity") or 0.0)),
        pressure_hpa=_round(main.get("pressure"), 1),
        cloud_cover_oktas=cloud_oktas,
        precipitation_mm_last_1h=precipitation,
        visibility_km=visibility_km,
        mixing_layer_height_m=mlh,
        atmospheric_stability=_stability_to_dict(stability),
    )
    return snapshot


def _stability_to_dict(stab: StabilityProfile) -> dict[str, Any]:
    """Shape the StabilityProfile into the contract's ``atmospheric_stability``."""
    return {
        "pasquill_class": stab.pasquill_class,
        "label": stab.label,
        "description": stab.description,
        "dispersion_coefficient": {
            "sigma_y": stab.sigma_y,
            "sigma_z": stab.sigma_z,
        },
    }


def _unix_to_iso_with_offset(dt_unix: int, tz_offset_sec: int) -> str:
    """Build an ISO-8601 string with a ``+HH:MM`` offset from unix UTC + offset."""
    import datetime as _dt

    utc = _dt.datetime.fromtimestamp(dt_unix, tz=_dt.timezone.utc)
    local = utc.astimezone(_dt.timezone(_dt.timedelta(seconds=tz_offset_sec)))
    # ``isoformat()`` already yields e.g. "2026-06-25T08:30:00+05:30".
    return local.isoformat()


def _hour_of_local_time(dt_unix: int, tz_offset_sec: int) -> int:
    import datetime as _dt

    utc = _dt.datetime.fromtimestamp(dt_unix, tz=_dt.timezone.utc)
    local = utc.astimezone(_dt.timezone(_dt.timedelta(seconds=tz_offset_sec)))
    return local.hour


# --------------------------------------------------------------------------
# Cache layer (Improvement #8: resilience caching)
# --------------------------------------------------------------------------
def _cache_key(lat: float, lon: float) -> str:
    """Stable cache key from rounded coordinates (0.01 deg ~ 1.1 km grid)."""
    return f"owm_{round(lon, 2)}_{round(lat, 2)}"


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _read_cache(cache_dir: Path, key: str) -> Optional[dict[str, Any]]:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt cache file — ignore, treat as miss
        log.warning("Corrupt cache file %s: %s", path, exc)
        return None


def _write_cache(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, key)
    # We cache the RAW OWM payload (not the parsed snapshot) so future schema
    # tweaks can re-parse the original response.
    wrapped = {"cached_at_unix": int(time.time()), "owm": payload}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(wrapped, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic-ish on most filesystems


# --------------------------------------------------------------------------
# Public client
# --------------------------------------------------------------------------
class WeatherClient:
    """OpenWeatherMap client with transparent offline caching.

    Usage::

        client = WeatherClient(api_key=os.getenv("OWM_API_KEY"))
        snap = client.get_weather(lat=18.5308, lon=73.8440)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        cache_dir: Optional[Path] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("OWM_API_KEY") or "").strip() or None
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.timeout = timeout
        self._session = session or requests.Session()

    def _fetch_open_meteo(self, lat: float, lon: float) -> Optional[WeatherSnapshot]:
        """Fetch current weather from Open-Meteo (free, no API key required)."""
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation",
            "timezone": "auto"
        }
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                
                temp_c = current.get("temperature_2m", 25.0)
                rh = current.get("relative_humidity_2m", 60.0)
                wind_speed_kmh = current.get("wind_speed_10m", 0.0)
                wind_direction_deg = current.get("wind_direction_10m", 0.0)
                pressure_hpa = current.get("surface_pressure", 1013.25)
                precip = current.get("precipitation", 0.0)
                
                # stability classification
                from .pasquill import classify_stability, wind_direction_cardinal
                from datetime import datetime, timezone, timedelta
                IST = timezone(timedelta(hours=5, minutes=30))
                now_ist = datetime.now(IST)
                stability = classify_stability(wind_speed_kmh, now_ist.hour)
                
                return WeatherSnapshot(
                    source="Open-Meteo",
                    observed_at=now_ist,
                    temperature_c=float(temp_c),
                    relative_humidity_pct=float(rh),
                    wind_speed_kmh=float(wind_speed_kmh),
                    wind_direction_deg=float(wind_direction_deg),
                    wind_direction_cardinal=wind_direction_cardinal(wind_direction_deg),
                    pressure_hpa=float(pressure_hpa),
                    precipitation_mm_last_1h=float(precip),
                    atmospheric_stability=stability,
                    mixing_layer_height_m=800,
                    visibility_km=10.0,
                )
        except Exception as e:
            log.warning("Open-Meteo request failed: %s", e)
        return None

    def get_weather(
        self,
        lat: float,
        lon: float,
        *,
        source: str = "OpenWeatherMap",
    ) -> WeatherSnapshot:
        """Return a weather snapshot, falling back to Open-Meteo or cache on failure."""
        key = _cache_key(lat, lon)

        if not self.api_key:
            log.info("OWM_API_KEY not set — trying Open-Meteo fallback...")
            om_snap = self._fetch_open_meteo(lat, lon)
            if om_snap:
                return om_snap
            log.info("Open-Meteo failed — using cached weather (offline mode).")
            return self._snapshot_from_cache_or_fallback(
                key, lat, lon, source=source
            )

        try:
            payload = self._fetch_live(lat, lon)
        except Exception as exc:
            log.warning("OWM request failed (%s); falling back to cache.", exc)
            return self._snapshot_from_cache_or_fallback(
                key, lat, lon, source=source
            )

        # Persist the good response, then parse.
        try:
            _write_cache(self.cache_dir, key, payload)
        except Exception as exc:  # caching must never break the pipeline
            log.warning("Could not write weather cache: %s", exc)

        return parse_owm_response(payload, source=source)

    # ---- internals --------------------------------------------------------
    def _fetch_live(self, lat: float, lon: float) -> dict[str, Any]:
        """Perform a live OWM current-weather request and return JSON.

        Raises on any non-2xx status, including rate-limiting (429).
        """
        params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "standard"}
        resp = self._session.get(
            OWM_CURRENT_URL, params=params, timeout=self.timeout
        )
        if resp.status_code == 429:
            # Rate-limited: deliberately fall through to the cache path.
            resp.raise_for_status()
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp.json()

    def _snapshot_from_cache_or_fallback(
        self,
        key: str,
        lat: float,
        lon: float,
        *,
        source: str,
    ) -> WeatherSnapshot:
        cached = _read_cache(self.cache_dir, key)
        if cached and "owm" in cached:
            try:
                # Mark provenance so consumers know this was a cache hit.
                snap = parse_owm_response(cached["owm"], source=f"{source} (cached)")
                return snap
            except Exception as exc:  # corrupt cached payload — fall through
                log.warning("Failed to parse cached OWM payload: %s", exc)
        # Absolute last resort: a zero-wind snapshot so attribution logic can
        # still proceed (with neutral stability D).
        return self._fallback_snapshot(lat, lon, source=source)

    @staticmethod
    def _fallback_snapshot(lat: float, lon: float, *, source: str) -> WeatherSnapshot:
        """Synthesize a calm-weather snapshot when no data is available at all."""
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc).astimezone()
        stability = classify_stability(0.0, now.hour)
        return WeatherSnapshot(
            source=f"{source} (unavailable — calm fallback)",
            observed_at=now.isoformat(),
            wind_speed_kmh=0.0,
            wind_direction_deg=0.0,
            wind_direction_cardinal=wind_direction_cardinal(0.0),
            temperature_c=0.0,
            relative_humidity_pct=0.0,
            pressure_hpa=0.0,
            cloud_cover_oktas=0,
            precipitation_mm_last_1h=0.0,
            visibility_km=10.0,
            mixing_layer_height_m=_estimate_mixing_layer_height(stability, now.hour, 0),
            atmospheric_stability=_stability_to_dict(stability),
        )


__all__ = ["WeatherSnapshot", "WeatherClient", "parse_owm_response"]
