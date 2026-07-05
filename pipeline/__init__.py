"""Spike detection + telemetry ingestion pipeline (Task 2).

Submodules:
    naaqs        — Indian NAAQS limits + exceedance-factor + AQI category logic
    pasquill     — Pasquill-Gifford atmospheric stability classification
    station_meta — metadata not stored in the stations table (network/city/...)
    weather_client — OpenWeatherMap client with offline JSON caching
    spike_detector — SpikeDetector class + event payload builder
    poller       — mock CPCB telemetry replay driver
"""
