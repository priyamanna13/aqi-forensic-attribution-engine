"""Application configuration via pydantic-settings (reads .env / environment).

Everything is overridable by env vars so the same code runs locally (mock),
in tests (no DB), and against PostGIS (docker-compose).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database -------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://aq:aq@localhost:5432/aqdb",
        description="SQLAlchemy URL. PostGIS in prod; SQLite (no PostGIS) for tests/dry-run.",
    )

    # --- Ingestion source ----------------------------------------------
    aq_source: str = Field(
        default="mock",
        description='"mock" (deterministic, offline) or "live" (real CPCB adapter).',
    )
    cpcb_api_base: str = Field(default="https://app.cpcbccr.com/aqi_dashboard")

    # --- Target station defaults (seed) --------------------------------
    tz: str = Field(default="Asia/Kolkata")
    station_name: str = Field(default="Shivajinagar")
    station_city: str = Field(default="Pune")
    station_state: str = Field(default="Maharashtra")
    station_network: str = Field(default="CPCB_CAAQMS")
    # GeoJSON order: [longitude, latitude]
    station_coordinates: tuple[float, float] = Field(default=(73.8567, 18.5308))
    station_elevation_m: int = Field(default=560)

    # --- Spike scenario (data contract) --------------------------------
    spike_aqi: int = Field(default=310)
    spike_local_time: str = Field(default="08:30")  # HH:MM, in `tz`

    # --- City config file path -----------------------------------------
    city_config: str = Field(
        default="city_config.yml",
        description="Path to city_config.yml (geographic-agnostic keystone).",
    )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_city_config(path: str | None = None) -> dict:
    """Load the geographic-agnostic city configuration from YAML.

    Resolution order:
        1. Explicit ``path`` argument
        2. ``CITY_CONFIG`` env var / pydantic setting
        3. ``city_config.yml`` in the project root

    Returns
    -------
    dict
        The parsed YAML as a plain dict.

    Raises
    ------
    FileNotFoundError
        When no config file is found at the resolved path.
    """
    import yaml  # lazy import — only needed when this function is called

    if path is None:
        path = get_settings().city_config

    # Resolve relative paths from the project root (parent of app/).
    config_path = Path(path)
    if not config_path.is_absolute():
        project_root = Path(__file__).resolve().parent.parent
        config_path = project_root / config_path

    if not config_path.exists():
        raise FileNotFoundError(
            f"City config not found at {config_path}. "
            f"Set CITY_CONFIG env var or create {config_path}."
        )

    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)

