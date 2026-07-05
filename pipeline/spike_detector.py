"""Spike detection engine (Task 2, Part 1 + Part 3).

``SpikeDetector.check_and_trigger_spike(session, station_id, current_reading)``
runs two independent detection rules:

  Rule A (threshold)  — total AQI >= 150, OR any exceedance factor > 1.5
  Rule B (rate-of-change) — AQI rose by >= 50 within a 1-hour window
                            (proportionally scaled if the gap differs)

When a spike fires, it packages the event into the **top half** of
``data_contract_sample.json`` (``event_id`` … end of ``weather_snapshot``),
strictly conforming to those keys, nesting, and value types. The lower half
(wind cone, ranked candidates, actionable intelligence) is produced by later
attribution tasks.

Design notes:
  - Detection and payload-building are kept pure (no DB writes) so the unit
    test can exercise them offline. The ``check_and_trigger_spike`` wrapper
    performs the DB read (previous reading) and returns the payload.
  - ``current_reading`` is a plain dict to keep the detector decoupled from
    ORM objects (the poller may build it from JSON).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from geoalchemy2 import functions as gfunc
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AqiReading, Station
from . import naaqs
from .naaqs import POLLUTANT_KEYS
from .station_meta import get_station_meta
from .weather_client import WeatherClient, WeatherSnapshot

PIPELINE_VERSION = "3.1.0"

# Tunable thresholds (Task 2, Part 1).
THRESHOLD_TOTAL_AQI = 150.0
THRESHOLD_EXCEEDANCE = 1.5
ROC_AQI_DELTA = 50.0           # rate-of-change AQI jump
ROC_WINDOW_SECONDS = 3600.0    # reference 1-hour window


@dataclass
class ChemicalFingerprint:
    """Output of the chemical-fingerprint analysis (Part 1)."""

    pm25_pm10_ratio: Optional[float]
    no2_so2_ratio: Optional[float]
    signature_class: str
    notes: str


# --------------------------------------------------------------------------
# Pure helpers — chemical fingerprint
# --------------------------------------------------------------------------
def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Safe division -> float rounded to 3 decimals, or None if undefined."""
    if num is None or den is None or den == 0:
        return None
    return round(num / den, 3)


def compute_chemical_fingerprint(
    values: dict[str, Optional[float]],
    factors: dict[str, Optional[float]],
) -> ChemicalFingerprint:
    """Classify the pollutant signature (Part 1: Chemical Fingerprint Analysis).

    Decision order (first match wins):
      1. pm10 highest-exceedance + pm25/pm10 < 0.4  -> crustal_dominant
      2. pm25 highest-exceedance + no2 exceedance high  -> combustion_vehicular
      3. so2 highest-exceedance  -> industrial_sulfur
      4. pm25 highest-exceedance + co exceedance high  -> biomass_burning
      else -> mixed
    """
    pm25_pm10_ratio = _ratio(values.get("pm25"), values.get("pm10"))
    no2_so2_ratio = _ratio(values.get("no2"), values.get("so2"))

    def f(p: str) -> float:
        return factors.get(p) or 0.0

    # Identify the highest-exceedance pollutant (ignoring Nones).
    present = {p: f(p) for p in POLLUTANT_KEYS}
    dominant_key = max(present, key=present.get)
    dominant_factor = present[dominant_key]

    signature = "mixed"
    notes = "No single dominant source signature; mixed contributions."

    high_threshold = 1.0  # an exceedance factor above NAAQS counts as "high"

    if dominant_key == "pm10" and pm25_pm10_ratio is not None and pm25_pm10_ratio < 0.4:
        signature = "crustal_dominant"
        notes = (
            "High PM coarse fraction with moderate NO\u2082 suggests combined "
            "dust + vehicular contribution"
        )
    elif dominant_key == "pm25" and f("no2") >= high_threshold:
        signature = "combustion_vehicular"
        notes = (
            "Fine PM dominance with elevated NO\u2082 indicates vehicular / "
            "diesel combustion sources"
        )
    elif dominant_key == "so2":
        signature = "industrial_sulfur"
        notes = "SO\u2082 dominance points to industrial sulfur emissions (stacks)"
    elif dominant_key == "pm25" and f("co") >= high_threshold:
        signature = "biomass_burning"
        notes = "Fine PM with elevated CO is characteristic of biomass / waste burning"
    else:
        # Keep a slightly more informative note when something dominated.
        if dominant_factor >= high_threshold:
            notes = (
                f"Dominant pollutant {dominant_key.upper()} (EF {dominant_factor:.2f}) "
                "without a distinguishing co-pollutant signal"
            )

    return ChemicalFingerprint(
        pm25_pm10_ratio=pm25_pm10_ratio,
        no2_so2_ratio=no2_so2_ratio,
        signature_class=signature,
        notes=notes,
    )


# --------------------------------------------------------------------------
# Pure helpers — detection rules
# --------------------------------------------------------------------------
@dataclass
class DetectionResult:
    """Outcome of running the rules against a single reading."""

    triggered: bool
    reasons: list[str]
    factors: dict[str, Optional[float]]
    dominant_pollutant_key: Optional[str]
    dominant_pollutant_factor: Optional[float]
    fingerprint: ChemicalFingerprint


def evaluate_rules(
    current_aqi: float,
    values: dict[str, Optional[float]],
    previous_aqi: Optional[float],
    gap_seconds: Optional[float],
) -> DetectionResult:
    """Run Rule A (threshold) and Rule B (rate-of-change) and return the verdict.

    Pure function — no DB. ``gap_seconds`` is the time since the previous
    reading; used to proportionally scale the rate-of-change delta.
    """
    factors = naaqs.compute_exceedance_factors(values)
    dom_key, dom_factor = naaqs.dominant_pollutant(values)
    fingerprint = compute_chemical_fingerprint(values, factors)

    reasons: list[str] = []

    # ---- Rule A: threshold ------------------------------------------------
    if current_aqi >= THRESHOLD_TOTAL_AQI:
        reasons.append(
            f"threshold_total_aqi: {current_aqi:.1f} >= {THRESHOLD_TOTAL_AQI:.0f}"
        )
    exceeded = [
        p for p in POLLUTANT_KEYS
        if (factors.get(p) or 0.0) > THRESHOLD_EXCEEDANCE
    ]
    if exceeded:
        names = ", ".join(p.upper() for p in exceeded)
        reasons.append(
            f"threshold_exceedance: {names} > {THRESHOLD_EXCEEDANCE:.1f}x NAAQS"
        )

    # ---- Rule B: rate-of-change ------------------------------------------
    if previous_aqi is not None and gap_seconds is not None and gap_seconds > 0:
        # Scale: a delta that occurred over a longer window is more significant
        # per unit time the *shorter* it is. We normalize to the 1-hour window:
        # required_delta = ROC_AQI_DELTA * (gap_seconds / ROC_WINDOW_SECONDS).
        # This means a faster jump needs a smaller absolute delta to fire.
        scaled_threshold = ROC_AQI_DELTA * (gap_seconds / ROC_WINDOW_SECONDS)
        # But we never let the scaled threshold drop below a floor of 25 to
        # avoid noise triggering on tiny gaps.
        scaled_threshold = max(scaled_threshold, 25.0)
        delta = current_aqi - previous_aqi
        if delta >= scaled_threshold:
            reasons.append(
                f"rate_of_change: +{delta:.1f} AQI over {gap_seconds/60:.0f} min "
                f"(threshold {scaled_threshold:.0f})"
            )

    triggered = bool(reasons)
    return DetectionResult(
        triggered=triggered,
        reasons=reasons,
        factors=factors,
        dominant_pollutant_key=dom_key,
        dominant_pollutant_factor=dom_factor,
        fingerprint=fingerprint,
    )


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------
def _fetch_previous_reading(
    session: Session, station_id: str, before: datetime
) -> Optional[AqiReading]:
    """Most recent aqi_readings row for this station strictly before ``before``."""
    stmt = (
        select(AqiReading)
        .where(AqiReading.station_id == station_id, AqiReading.timestamp < before)
        .order_by(AqiReading.timestamp.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _station_coordinates(session: Session, station: Station) -> tuple[float, float]:
    """Return ``(lon, lat)`` from a station's PostGIS POINT geometry."""
    # ST_X / ST_Y return lon / lat respectively for a POINT.
    stmt = select(gfunc.ST_X(station.geom), gfunc.ST_Y(station.geom))
    lon, lat = session.execute(stmt).one()
    return float(lon), float(lat)


# --------------------------------------------------------------------------
# Payload builder — produces the contract's top half
# --------------------------------------------------------------------------
def _iso_utcnow() -> str:
    """ISO-8601 UTC timestamp with a trailing ``Z`` (contract: generated_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _iso_with_offset(dt: datetime) -> str:
    """ISO-8601 with offset, e.g. ``2026-06-25T08:30:00+05:30``.

    If ``dt`` is naive we assume the contract's IST convention (+05:30).
    """
    if dt.tzinfo is None:
        from datetime import timedelta

        dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return dt.isoformat()


def _build_sub_pollutants(
    values: dict[str, Optional[float]],
    factors: dict[str, Optional[float]],
) -> dict[str, Any]:
    """Build the ``reading.sub_pollutants`` block per the contract."""
    out: dict[str, Any] = {}
    for p in POLLUTANT_KEYS:
        std = naaqs.NAAQS[p]
        out[p] = {
            "value": values.get(p),
            "unit": std.unit,
            "averaging_period": std.averaging_period,
            "naaqs_limit": std.limit,
            "exceedance_factor": factors.get(p),
        }
    return out


def _build_fingerprint_block(fp: ChemicalFingerprint) -> dict[str, Any]:
    """Build the ``reading.chemical_fingerprint`` block."""
    return {
        "pm25_pm10_ratio": fp.pm25_pm10_ratio,
        "no2_so2_ratio": fp.no2_so2_ratio,
        "signature_class": fp.signature_class,
        "notes": fp.notes,
    }


def _build_weather_block(snap: WeatherSnapshot) -> dict[str, Any]:
    """Build the ``weather_snapshot`` block from a WeatherSnapshot."""
    return snap.to_dict()


def build_event_payload(
    *,
    station: Station,
    coordinates: tuple[float, float],
    reading: dict[str, Any],
    detection: DetectionResult,
    weather: WeatherSnapshot,
) -> dict[str, Any]:
    """Assemble the **top half** of the data contract payload.

    Returns a dict shaped exactly like ``data_contract_sample.json`` from
    ``event_id`` through the end of ``weather_snapshot``. The lower half
    (wind_cone_geometry, ranked_candidates, actionable_intelligence) is left
    to the attribution task.
    """
    meta = get_station_meta(station.name)
    values = {p: reading.get(p) for p in POLLUTANT_KEYS}
    total_aqi = float(reading["aqi"])
    ts = reading["timestamp"]
    timestamp_iso = _iso_with_offset(ts) if isinstance(ts, datetime) else ts

    dom_display = (
        naaqs.POLLUTANT_DISPLAY[detection.dominant_pollutant_key]
        if detection.dominant_pollutant_key
        else None
    )

    payload = {
        "event_id": str(uuid.uuid4()),
        "event_severity": naaqs.event_severity(total_aqi),
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": _iso_utcnow(),
        "trigger_station": {
            "id": str(station.id),
            "name": station.name,
            "network": meta.network,
            "city": meta.city,
            "state": meta.state,
            "coordinates": [coordinates[0], coordinates[1]],   # [lon, lat]
            "elevation_m": meta.elevation_m,
            "reading": {
                "timestamp": timestamp_iso,
                "total_aqi": total_aqi,
                "aqi_category": naaqs.aqi_category(total_aqi),
                "dominant_pollutant": dom_display,
                "sub_pollutants": _build_sub_pollutants(values, detection.factors),
                "chemical_fingerprint": _build_fingerprint_block(detection.fingerprint),
            },
        },
        "weather_snapshot": _build_weather_block(weather),
    }
    return payload


# --------------------------------------------------------------------------
# Public class
# --------------------------------------------------------------------------
class SpikeDetector:
    """Detects AQI spikes and emits contract-conformant event payloads."""

    def __init__(self, weather_client: Optional[WeatherClient] = None) -> None:
        # Lazy default so tests can inject a stub and offline runs don't fail.
        self.weather = weather_client or WeatherClient()

    def check_and_trigger_spike(
        self,
        session: Session,
        station_id: str,
        current_reading: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Evaluate one reading; return a payload if a spike fired, else None.

        ``current_reading`` shape::

            {
                "timestamp": datetime,          # tz-aware preferred
                "aqi": float,
                "pm25": float | None, "pm10": ..., "no2": ...,
                "so2": ..., "co": ..., "o3": ...,
            }

        Side effects: none. The poller is responsible for persisting the
        reading to ``aqi_readings`` and (if a payload is returned) writing the
        alert. This keeps the detector testable in isolation.
        """
        station = session.get(Station, station_id)
        if station is None:
            raise ValueError(f"Unknown station_id: {station_id}")

        ts = current_reading["timestamp"]
        if not isinstance(ts, datetime):
            raise TypeError("current_reading['timestamp'] must be a datetime")

        values = {p: current_reading.get(p) for p in POLLUTANT_KEYS}
        total_aqi = float(current_reading["aqi"])

        prev = _fetch_previous_reading(session, station_id, ts)
        prev_aqi = prev.aqi if prev else None
        gap_seconds = (ts - prev.timestamp).total_seconds() if prev else None

        detection = evaluate_rules(total_aqi, values, prev_aqi, gap_seconds)
        if not detection.triggered:
            return None

        lon, lat = _station_coordinates(session, station)
        weather = self.weather.get_weather(lat=lat, lon=lon)

        return build_event_payload(
            station=station,
            coordinates=(lon, lat),
            reading=current_reading,
            detection=detection,
            weather=weather,
        )


__all__ = [
    "ChemicalFingerprint",
    "DetectionResult",
    "SpikeDetector",
    "evaluate_rules",
    "compute_chemical_fingerprint",
    "build_event_payload",
    "PIPELINE_VERSION",
]
