"""Offline verification for the spike detection pipeline (Task 2, Part 4).

This script verifies, WITHOUT a database or network:

  1. The detection algorithm fires exactly once on the Shivajinagar replay
     sequence (AQI 90 -> 310), at the spike timestamp (08:30 IST).
  2. The NAAQS math matches the data contract's worked example:
     pm25=148.6 -> EF 2.48, pm10=387.2 -> EF 3.87, etc.
  3. The chemical fingerprint classifies the spike as ``crustal_dominant``
     (PM10-dominant with pm25/pm10 < 0.4).
  4. **The emitted payload's ``trigger_station`` and ``weather_snapshot``
     sections match the keys, nesting, and value types of
     data_contract_sample.json EXACTLY** (structural conformance).

Run::

    python scripts/test_spike_detection.py

Exit code 0 = pass.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as `python scripts/test_spike_detection.py` from project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import naaqs  # noqa: E402
from pipeline.spike_detector import (  # noqa: E402
    PIPELINE_VERSION,
    SpikeDetector,
    build_event_payload,
    evaluate_rules,
)
from pipeline.weather_client import WeatherSnapshot  # noqa: E402
from pipeline.pasquill import classify_stability, wind_direction_cardinal  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = PROJECT_ROOT / "data_contract_sample.json"
REPLAY_PATH = PROJECT_ROOT / "data" / "replay_shivajinagar.json"

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    flag = "ok  " if cond else "FAIL"
    print(f"  [{flag}] {msg}")
    if not cond:
        FAILURES.append(msg)


# --------------------------------------------------------------------------
# Contract schema extraction
# --------------------------------------------------------------------------
def _shape(value: Any) -> Any:
    """Reduce a JSON value to a structural shape: type + nesting + keys.

    Lists -> shape of first element (we only need to know it's a list of
    numbers/strings for the contract; lengths are checked separately).
    """
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return ["empty"]
        return [_shape(value[0])]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def assert_conforms(actual: Any, expected_shape: Any, path: str) -> None:
    """Recursively assert ``actual`` has the keys/types described by ``expected_shape``.

    ``expected_shape`` is the output of ``_shape`` on the contract sample.
    Numbers are allowed to be int-or-float (``"int"/"float"`` both accept either)
    because JSON round-trips 310 as int but the pipeline may produce 310.0.
    """
    if isinstance(expected_shape, dict):
        if not isinstance(actual, dict):
            check(False, f"{path}: expected object, got {type(actual).__name__}")
            return
        # Every contract key must be present.
        missing = [k for k in expected_shape if k not in actual]
        check(not missing, f"{path}: all contract keys present (missing={missing})")
        # No structural surprises in keys that exist.
        extra = [k for k in actual if k not in expected_shape]
        check(not extra, f"{path}: no extra keys (extra={extra})")
        for k, sub in expected_shape.items():
            if k in actual:
                assert_conforms(actual[k], sub, f"{path}.{k}")
        return
    if isinstance(expected_shape, list):
        if not isinstance(actual, list):
            check(False, f"{path}: expected list, got {type(actual).__name__}")
            return
        if expected_shape == ["empty"]:
            return
        if not actual:
            check(False, f"{path}: expected non-empty list")
            return
        assert_conforms(actual[0], expected_shape[0], f"{path}[0]")
        return
    # Leaf: type check.
    num_types = {"int", "float"}
    if expected_shape in num_types:
        ok = isinstance(actual, (int, float)) and not isinstance(actual, bool)
        check(ok, f"{path}: expected number, got {type(actual).__name__} = {actual!r}")
    elif expected_shape == "bool":
        check(isinstance(actual, bool), f"{path}: expected bool, got {actual!r}")
    elif expected_shape == "str":
        check(isinstance(actual, str), f"{path}: expected str, got {actual!r}")
    elif expected_shape == "null":
        check(actual is None, f"{path}: expected null, got {actual!r}")


# --------------------------------------------------------------------------
# Stub weather snapshot (deterministic, offline)
# --------------------------------------------------------------------------
def make_stub_weather(ts: datetime) -> WeatherSnapshot:
    """A fixed weather snapshot matching the contract's structural shape.

    Uses the contract's sample wind (290 deg, 14.5 km/h) so the cardinal
    resolves to "WNW" exactly as the sample shows.
    """
    wind_speed = 14.5
    wind_deg = 290.0
    stability = classify_stability(wind_speed, ts.hour)
    return WeatherSnapshot(
        source="OpenWeatherMap (stub)",
        observed_at=ts.isoformat(),
        wind_speed_kmh=wind_speed,
        wind_direction_deg=wind_deg,
        wind_direction_cardinal=wind_direction_cardinal(wind_deg),
        temperature_c=31.4,
        relative_humidity_pct=62.0,
        pressure_hpa=1006.3,
        cloud_cover_oktas=3,
        precipitation_mm_last_1h=0.0,
        visibility_km=4.2,
        mixing_layer_height_m=850,
        atmospheric_stability={
            "pasquill_class": stability.pasquill_class,
            "label": stability.label,
            "description": stability.description,
            "dispersion_coefficient": {
                "sigma_y": stability.sigma_y,
                "sigma_z": stability.sigma_z,
            },
        },
    )


# --------------------------------------------------------------------------
# Fake station (no DB) for build_event_payload
# --------------------------------------------------------------------------
class FakeStation:
    """Minimal stand-in for db.models.Station used by build_event_payload."""

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_naaqs_math() -> None:
    print("\n[Test] NAAQS exceedance math matches contract worked example")
    values = {"pm25": 148.6, "pm10": 387.2, "no2": 72.4, "so2": 54.8, "co": 3.2, "o3": 42.1}
    factors = naaqs.compute_exceedance_factors(values)
    # Expected values straight from data_contract_sample.json.
    expected = {"pm25": 2.48, "pm10": 3.87, "no2": 0.91, "so2": 0.69, "co": 0.80, "o3": 0.42}
    for p, want in expected.items():
        got = factors[p]
        check(got == want, f"EF[{p}] = {got} (contract: {want})")
    dom_key, dom_factor = naaqs.dominant_pollutant(values)
    check(dom_key == "pm10", f"dominant pollutant = {dom_key} (expected pm10)")
    check(dom_factor == 3.87, f"dominant EF = {dom_factor} (expected 3.87)")


def test_detection_fires_once() -> None:
    print("\n[Test] Detection fires exactly once, at 08:30 IST spike")
    seq = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))["sequence"]

    fired_ts: list[str] = []
    prev_aqi = None
    prev_ts = None
    for entry in seq:
        ts = datetime.fromisoformat(entry["timestamp"])
        values = {p: entry.get(p) for p in naaqs.POLLUTANT_KEYS}
        gap = (ts - prev_ts).total_seconds() if prev_ts else None
        result = evaluate_rules(float(entry["aqi"]), values, prev_aqi, gap)
        if result.triggered:
            fired_ts.append(entry["timestamp"])
        prev_aqi, prev_ts = float(entry["aqi"]), ts

    check(len(fired_ts) == 1, f"exactly one spike fired (got {len(fired_ts)}: {fired_ts})")
    if fired_ts:
        check(
            fired_ts[0] == "2026-06-25T08:30:00+05:30",
            f"spike at 08:30 IST (got {fired_ts[0]})",
        )


def test_fingerprint_is_crustal() -> None:
    print("\n[Test] Chemical fingerprint classifies as crustal_dominant")
    values = {"pm25": 148.6, "pm10": 387.2, "no2": 72.4, "so2": 54.8, "co": 3.2, "o3": 42.1}
    factors = naaqs.compute_exceedance_factors(values)
    from pipeline.spike_detector import compute_chemical_fingerprint

    fp = compute_chemical_fingerprint(values, factors)
    check(fp.signature_class == "crustal_dominant",
          f"signature_class = {fp.signature_class} (expected crustal_dominant)")
    # 148.6 / 387.2 = 0.3838... -> 0.384 (3 decimals), matches contract.
    check(fp.pm25_pm10_ratio == 0.384,
          f"pm25_pm10_ratio = {fp.pm25_pm10_ratio} (expected 0.384)")
    # 72.4 / 54.8 = 1.32116... -> 1.321 (3 decimals), matches contract exactly.
    check(fp.no2_so2_ratio == 1.321,
          f"no2_so2_ratio = {fp.no2_so2_ratio} (expected 1.321)")


def test_payload_conforms_to_contract() -> None:
    print("\n[Test] Payload trigger_station + weather_snapshot conform to contract")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_ts_shape = _shape(contract["trigger_station"])
    expected_ws_shape = _shape(contract["weather_snapshot"])

    # Build a payload using the contract's own spike reading.
    spike_reading = {
        "timestamp": datetime.fromisoformat("2026-06-25T08:30:00+05:30"),
        "aqi": 310.0,
        "pm25": 148.6, "pm10": 387.2, "no2": 72.4, "so2": 54.8, "co": 3.2, "o3": 42.1,
    }
    values = {p: spike_reading[p] for p in naaqs.POLLUTANT_KEYS}
    detection = evaluate_rules(310.0, values, previous_aqi=128.0, gap_seconds=1800.0)
    station = FakeStation(id="d4e8f1a2-6b3c-4f9d-8e7a-1c2d5f0b9a63", name="Shivajinagar")
    weather = make_stub_weather(spike_reading["timestamp"])

    payload = build_event_payload(
        station=station,
        coordinates=(73.8440, 18.5308),
        reading=spike_reading,
        detection=detection,
        weather=weather,
    )

    # --- Top-level scalar fields ---
    check(isinstance(payload["event_id"], str), "event_id is a string")
    check(payload["event_severity"] == "critical", f"event_severity=critical (got {payload['event_severity']})")
    check(payload["pipeline_version"] == PIPELINE_VERSION, "pipeline_version matches module constant")
    check(isinstance(payload["generated_at"], str) and payload["generated_at"].endswith("Z"),
          "generated_at is ISO-UTC ending with Z")

    # --- Structural conformance to the contract ---
    print("  -- trigger_station structural conformance --")
    assert_conforms(payload["trigger_station"], expected_ts_shape, "trigger_station")
    print("  -- weather_snapshot structural conformance --")
    assert_conforms(payload["weather_snapshot"], expected_ws_shape, "weather_snapshot")

    # --- A few key value-level assertions ---
    check(payload["trigger_station"]["reading"]["total_aqi"] == 310.0, "total_aqi = 310")
    check(payload["trigger_station"]["reading"]["aqi_category"] == "Very Poor",
          f"aqi_category=Very Poor (got {payload['trigger_station']['reading']['aqi_category']})")
    check(payload["trigger_station"]["reading"]["dominant_pollutant"] == "PM10",
          f"dominant_pollutant=PM10 (got {payload['trigger_station']['reading']['dominant_pollutant']})")
    check(payload["trigger_station"]["coordinates"] == [73.8440, 18.5308],
          f"coordinates [lon,lat] = {payload['trigger_station']['coordinates']}")
    check(payload["weather_snapshot"]["wind_direction_cardinal"] == "WNW",
          f"wind cardinal=WNW for 290deg (got {payload['weather_snapshot']['wind_direction_cardinal']})")
    # The atmospheric_stability block must have the 4 expected keys.
    stab = payload["weather_snapshot"]["atmospheric_stability"]
    check(set(stab.keys()) == {"pasquill_class", "label", "description", "dispersion_coefficient"},
          f"atmospheric_stability keys = {sorted(stab.keys())}")
    check(set(stab["dispersion_coefficient"].keys()) == {"sigma_y", "sigma_z"},
          "dispersion_coefficient keys = {sigma_y, sigma_z}")


def main() -> int:
    print("=" * 70)
    print("Task 2 — spike detection offline verification")
    print("=" * 70)
    test_naaqs_math()
    test_detection_fires_once()
    test_fingerprint_is_crustal()
    test_payload_conforms_to_contract()

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} assertion(s) FAILED:")
        for f in FAILURES:
            print(f"   - {f}")
        return 1
    print("RESULT: all assertions passed. Payload conforms to data_contract_sample.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
