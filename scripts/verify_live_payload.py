"""Verify a LIVE pipeline payload conforms to data_contract_sample.json (top half).

Runs the same structural conformance check used by the offline test, but
against a real payload emitted by `python -m pipeline.poller` against the live
database. Proves the full DB + weather path produces contract-conformant
output, not just the pure detector path.

Usage:
    python scripts/verify_live_payload.py [path/to/payloads.json]

Defaults to data/live_spike_payloads.json (the output of `pipeline.poller --out`).
Exit code 0 = conformant.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = PROJECT_ROOT / "data_contract_sample.json"
DEFAULT_PAYLOAD = PROJECT_ROOT / "data" / "live_spike_payloads.json"

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    flag = "ok  " if cond else "FAIL"
    print(f"  [{flag}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- Structural shape extraction (mirrors scripts/test_spike_detection.py) ----
def _shape(value: Any) -> Any:
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
    if isinstance(expected_shape, dict):
        if not isinstance(actual, dict):
            check(False, f"{path}: expected object, got {type(actual).__name__}")
            return
        missing = [k for k in expected_shape if k not in actual]
        check(not missing, f"{path}: all contract keys present (missing={missing})")
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


def main() -> int:
    payload_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PAYLOAD
    print("=" * 70)
    print("Live payload contract conformance check")
    print("=" * 70)
    print(f"Contract : {CONTRACT_PATH}")
    print(f"Payload  : {payload_path}")

    if not payload_path.exists():
        print(f"\nFAIL: payload file not found: {payload_path}")
        print("      Run: python -m pipeline.poller --out data/live_spike_payloads.json")
        return 2

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    payloads = json.loads(payload_path.read_text(encoding="utf-8"))
    if not payloads:
        print("\nFAIL: payload file contains no events.")
        return 2

    expected_ts_shape = _shape(contract["trigger_station"])
    expected_ws_shape = _shape(contract["weather_snapshot"])

    for i, p in enumerate(payloads, 1):
        print(f"\n--- Event {i}/{len(payloads)} (event_id={p.get('event_id')}) ---")
        check(isinstance(p.get("event_id"), str), "event_id is a string")
        check(p.get("pipeline_version") == "3.1.0", "pipeline_version = 3.1.0")
        check(
            isinstance(p.get("generated_at"), str) and p["generated_at"].endswith("Z"),
            "generated_at is ISO-UTC ending with Z",
        )
        sev = p.get("event_severity")
        check(sev in {"critical", "high", "warning", "low"},
              f"event_severity in allowed set (got {sev!r})")

        print("  -- trigger_station conformance --")
        assert_conforms(p["trigger_station"], expected_ts_shape, "trigger_station")
        print("  -- weather_snapshot conformance --")
        assert_conforms(p["weather_snapshot"], expected_ws_shape, "weather_snapshot")

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"   - {f}")
        return 1
    print(f"RESULT: live payload conforms to data_contract_sample.json "
          f"({len(payloads)} event(s), top half).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
