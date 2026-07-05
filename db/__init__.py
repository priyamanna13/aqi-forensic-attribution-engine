"""Database package for the AI-Powered Urban Air Quality Intelligence platform.

Public submodules:
    config     — environment-driven settings + URL builder
    connection — SQLAlchemy engine, SessionLocal, get_session(), ping()
    models     — ORM table definitions (SQLAlchemy 2.0 + GeoAlchemy2)
    geo_utils  — geometry builders + GeoJSON serialization helpers
    init_db    — idempotent schema initialization entry point
    seed_data  — Pune stations + pollution-source seeder
"""

__all__ = ["config", "connection", "models", "geo_utils", "init_db", "seed_data"]
