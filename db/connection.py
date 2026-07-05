"""SQLAlchemy engine, session factory, and connection helpers.

Centralizes engine creation so every other module (init_db, seed_data,
verify_spatial, future API code) shares one connection pool and one
``SessionLocal`` factory.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import config


def _make_engine() -> Engine:
    """Create the global engine.

    - ``future=True`` is implicit on SQLAlchemy 2.x engines.
    - ``pool_pre_ping`` issues a lightweight SELECT 1 before reusing a pooled
      connection so a stale/idle connection (e.g. after DB restart) is dropped
      instead of raising.
    """
    return create_engine(
        config.database_url(),
        echo=config.DB_ECHO,
        pool_pre_ping=True,
        future=True,
    )


# Module-level singleton engine + session factory.
engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_engine() -> Engine:
    """Return the shared engine (useful for explicit connections / DDL)."""
    return engine


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session that commits on success, rolls back on error.

    Usage::

        with get_session() as s:
            s.add(obj)
        # committed here, session closed automatically
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    """Return True if the database answers ``SELECT 1`` and PostGIS is usable.

    Used by init_db / verify scripts as a connectivity + extension sanity check.
    """
    try:
        with engine.connect() as conn:
            one = conn.execute(text("SELECT 1")).scalar()
            has_postgis = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis')")
            ).scalar()
        return bool(one == 1 and has_postgis)
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[connection.ping] failed: {exc}")
        return False
