"""Database engine, session factory, and schema bootstrap.

`init_db()` creates all tables. On PostGIS it also enables the ``postgis``
extension so the Geometry columns compile. The same call is a no-op extra on
SQLite (used by tests / dry-run) where geometry is stored as EWKT text.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_settings = get_settings()

engine: Engine = create_engine(
    _settings.database_url,
    future=True,
    # SQLite needs check_same_thread=False for the test/demo session pattern.
    **({"connect_args": {"check_same_thread": False}} if _settings.is_sqlite else {}),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


# Enforce foreign keys on SQLite for realistic cascade behaviour in tests.
if _settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session that commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create the PostGIS extension (if applicable) and all tables."""
    if not _settings.is_sqlite:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop and recreate all tables. Used by `seed.py --reset`."""
    Base.metadata.drop_all(bind=engine)
    init_db()
