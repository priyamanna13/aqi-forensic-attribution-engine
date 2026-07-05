"""Structured Pipeline Logger — Task 5 (Gap 5).

Generates JSON formatted log entries to `pipeline.log` for auditable tracing
of every attribution run and its performance timings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

# Configure structured logging to pipeline.log
_file_handler = logging.FileHandler("pipeline.log", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s'))

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s'))

logger = logging.getLogger("aq_pipeline")
logger.setLevel(logging.INFO)
logger.addHandler(_file_handler)
logger.addHandler(_console_handler)


def log_pipeline_run(spike_data: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    """Create and write a structured log entry representing a complete pipeline run."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "trigger": {
            "station_id": spike_data.get("station_id"),
            "station_name": spike_data.get("station_name"),
            "aqi_value": spike_data.get("aqi"),
            "dominant_pollutant": spike_data.get("dominant_pollutant"),
        },
        "wind": {
            "speed_kmh": spike_data.get("wind_speed"),
            "direction_deg": spike_data.get("wind_direction"),
            "cone_angle_used": results.get("cone_angle"),
            "search_radius_used": results.get("search_radius_m"),
        },
        "funnel": {
            "total_sources_in_db": results.get("total_sources"),
            "after_spatial_filter": results.get("spatial_count"),
            "after_wind_cone": results.get("cone_count"),
            "after_chemical_match": results.get("chemical_count"),
            "final_candidates": results.get("candidate_count"),
        },
        "attribution": {
            "primary_source": results.get("primary_source"),
            "confidence": results.get("confidence"),
            "ambiguous": results.get("ambiguous", False),
        },
        "performance": {
            "total_ms": results.get("total_ms"),
            "spatial_filter_ms": results.get("spatial_ms"),
            "cone_filter_ms": results.get("cone_ms"),
            "scoring_ms": results.get("scoring_ms"),
        },
        "validation_warnings": results.get("warnings", []),
    }
    logger.info("PIPELINE_RUN | %s", json.dumps(log_entry, ensure_ascii=False))
    return log_entry
