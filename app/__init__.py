"""CPCB ingestion pipeline + PostGIS schema for the Air Quality Attribution Engine.

This package implements Person 2, Task 1: the data foundation that produces the
`trigger_station` block of the immutable data contract (see
data_contract_sample.json).

Coordinate convention everywhere: GeoJSON [longitude, latitude], EPSG:4326.
"""

__version__ = "3.1.0"
