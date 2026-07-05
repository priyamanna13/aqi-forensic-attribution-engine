"""Pytest config: force an in-memory SQLite DB and rebuild the schema per test.

Tests run entirely without PostGIS so they execute anywhere. The production
Geometry path is exercised separately via docker-compose (see README).
"""
from __future__ import annotations

import os

# Force SQLite BEFORE any app module imports the engine.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    """Re-import the app under an isolated in-memory SQLite engine per test."""
    import importlib

    import app.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    yield db_mod
    db_mod.Base.metadata.drop_all(bind=db_mod.engine)
