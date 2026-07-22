"""Environment-driven configuration and Postgres URL builder.

Reads values from a local ``.env`` file (loaded with python-dotenv) and falls
back to defaults that match ``docker-compose.yml``. The same values are also
available as plain environment variables, so the code works in CI/containers
without a ``.env`` file present.
"""
from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

try:
    # Optional: load .env from project root if present. Harmless if missing.
    from dotenv import load_dotenv

    _ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    load_dotenv(_ENV_PATH)
except Exception:  # pragma: no cover - dotenv not strictly required
    pass


def _get(name: str, default: str) -> str:
    """Return an env value, treating empty string as unset."""
    val = os.getenv(name)
    return val if val not in (None, "") else default


# Individual connection parameters (also used directly by some tooling).
POSTGRES_USER = _get("POSTGRES_USER", "aqi")
POSTGRES_PASSWORD = _get("POSTGRES_PASSWORD", "aqi_pass")
POSTGRES_DB = _get("POSTGRES_DB", "aqi")
POSTGRES_HOST = _get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = _get("POSTGRES_PORT", "5432")

# Whether SQLAlchemy should echo emitted SQL (dev debugging).
DB_ECHO = _get("DB_ECHO", "0") == "1"

# ML Model URL (defaults to http://ml-model-container:8000 if not set)
ML_MODEL_URL = _get("ML_MODEL_URL", "http://ml-model-container:8000")


# WGS 84 — every spatial column in the schema uses this SRID.
SRID_WGS84 = 4326


@lru_cache(maxsize=1)
def database_url() -> str:
    """Build a ``postgresql://`` DSN from the individual env vars.

    Password is URL-quoted so special characters don't break the DSN.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        if env_url.startswith("postgres://"):
            return env_url.replace("postgres://", "postgresql://", 1)
        return env_url

    password = quote_plus(POSTGRES_PASSWORD)
    return (
        f"postgresql://{POSTGRES_USER}:{password}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


def describe() -> dict:
    """Return a dict of the active settings (password masked) for logging."""
    return {
        "host": POSTGRES_HOST,
        "port": POSTGRES_PORT,
        "user": POSTGRES_USER,
        "db": POSTGRES_DB,
        "echo": DB_ECHO,
        "url": database_url().replace(POSTGRES_PASSWORD, "********"),
        "ml_model_url": ML_MODEL_URL,
    }
