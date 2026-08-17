"""
Database Session Management

This module provides SQLAlchemy session factory, connection pooling configuration,
and FastAPI dependency injection for database session management.

Uses synchronous SQLAlchemy for compatibility with Celery workers.

WP1 hardening (2026-08-16):

- All pool parameters are configurable (``DB_POOL_SIZE``, ``DB_MAX_OVERFLOW``,
  ``DB_POOL_TIMEOUT``, ``DB_POOL_RECYCLE``, ``DB_POOL_PRE_PING``) with
  conservative production defaults.
- An application guard mirrors PostgreSQL's
  ``idle_in_transaction_session_timeout``: every PostgreSQL connection is
  configured at connect time to abort transactions idle too long. This is a
  backstop; long worker transactions are also restructured so no session
  idles in a transaction across network work.
- Pool metrics (checked-out, wait, timeout) are tracked via SQLAlchemy pool
  events and exposed by the metrics endpoint.
- ``health_check`` accepts a ``timeout`` so readiness probes stay bounded and
  never compete indefinitely for a saturated pool.
- ``db_session`` context manager for short-lived, explicitly closed sessions
  (media authorization, WP1).
"""

import logging
import os
import threading
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.pool import QueuePool

from ..core.config import get_settings

logger = logging.getLogger(__name__)


def _inc(name: str, delta: int = 1) -> None:
    """Lazy metrics increment (avoids the app.services package cycle at
    import time: services/__init__ imports auth -> models -> session)."""
    try:
        from app.services.metrics import inc

        inc(name, delta)
    except Exception:  # pragma: no cover - metrics must never break the pool
        pass


# ==============================================================================
# DECLARATIVE BASE
# ==============================================================================

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    All model classes should inherit from this Base class.
    """
    pass


# ==============================================================================
# DATABASE ENGINE INITIALIZATION
# ==============================================================================

def _get_engine():
    """
    Create and configure SQLAlchemy engine with connection pooling.

    Pool parameters come from settings so production can be tuned without a
    code change:

    - pool_size: Minimum number of connections to maintain (default 20)
    - max_overflow: Maximum additional connections beyond pool_size (default 40)
    - pool_timeout: Seconds to wait for a connection before raising (default 30)
    - pool_recycle: Recycle connections after this many seconds (default 3600)
    - pool_pre_ping: Verify connection is alive before using it

    Returns:
        Engine: Configured SQLAlchemy engine instance
    """
    settings = get_settings()
    db = settings.database
    engine = create_engine(
        db.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
        pool_recycle=db.pool_recycle,
        pool_pre_ping=db.pool_pre_ping,
        echo=settings.environment.value == "development",  # Log SQL in dev
    )

    # Event listener for connection lifecycle
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_conn, connection_record):
        """SQLite pragmas and PostgreSQL idle-in-transaction guard."""
        if "sqlite" in db.DATABASE_URL:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        elif "postgresql" in db.DATABASE_URL:
            # Application-level mirror of idle_in_transaction_session_timeout.
            # Aborts transactions that sit idle too long, so a wedged request
            # cannot pin a pool connection indefinitely. Configurable, off by
            # default (0) so deployments adopting the new pool settings can
            # phase the guard in deliberately.
            timeout_ms = db.idle_in_transaction_timeout_ms
            if timeout_ms and timeout_ms > 0:
                cursor = dbapi_conn.cursor()
                cursor.execute(
                    f"SET idle_in_transaction_session_timeout = {int(timeout_ms)}"
                )
                cursor.close()

    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_conn, connection_record, connection_proxy):
        _inc("pool_checked_out", 1)
        _inc("pool_checkout_total", 1)

    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        _inc("pool_checked_out", -1)

    @event.listens_for(engine, "close")
    def receive_close(dbapi_conn, connection_record):
        # A closed connection was never returned via checkin; keep the gauge
        # consistent without double-decrementing (Review Round 2 F10).
        pass

    return engine


# Create engine instance (module-level singleton)
engine = _get_engine()


# Dedicated probe engine for readiness checks (WP1). One connection, short
# pool timeout: readiness never competes indefinitely with the saturated
# application pool — it either gets a connection quickly or reports not-ready.
_probe_engine = None
_probe_lock = threading.Lock()


def _get_probe_engine():
    global _probe_engine
    with _probe_lock:
        if _probe_engine is None:
            settings = get_settings()
            kwargs = {}
            if "postgresql" in settings.database.DATABASE_URL:
                kwargs["connect_args"] = {"connect_timeout": 3}
            _probe_engine = create_engine(
                settings.database.DATABASE_URL,
                poolclass=QueuePool,
                pool_size=1,
                max_overflow=0,
                pool_timeout=2.0,
                pool_recycle=300,
                pool_pre_ping=True,
                **kwargs,
            )
    return _probe_engine


# ==============================================================================
# SESSION FACTORY
# ==============================================================================

# Create session factory bound to engine
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,  # Don't expire objects after commit (useful for background jobs)
)


def _session_local_with_metrics() -> Session:
    """SessionLocal() wrapper that records checkout timeouts.

    SessionLocal() is lazy — the actual pool checkout happens on the first
    statement — so we force an eager checkout (``session.connection()``)
    inside the try so a QueuePool timeout is observed and counted here
    (Review Round 2 F10).
    """
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    try:
        session = SessionLocal()
        session.connection()  # eager checkout
        return session
    except PoolTimeoutError:
        _inc("pool_timeout_total")
        raise


# ==============================================================================
# FASTAPI DEPENDENCY
# ==============================================================================

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database session management.

    Provides a database session to route handlers with automatic
    commit/rollback and cleanup.

    Usage in FastAPI routes:
        from fastapi import Depends
        from app.db import get_db

        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    Yields:
        Session: SQLAlchemy database session
    """
    db = _session_local_with_metrics()
    try:
        yield db
        # Auto-commit if no exceptions
        db.commit()
    except Exception:
        # Rollback on any exception
        db.rollback()
        raise
    finally:
        # Always close session
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Short-lived explicit session context manager (WP1).

    Used where the caller needs full control over when the transaction ends
    and the session closes — e.g. media authorization, where the session must
    be closed BEFORE the response body starts streaming. The caller commits
    explicitly if it wrote; read-only scopes just roll back and close.
    """
    db = _session_local_with_metrics()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ==============================================================================
# HEALTH CHECK
# ==============================================================================

def health_check(timeout: Optional[float] = None) -> bool:
    """
    Check database connectivity.

    Uses a dedicated single-connection probe engine with a short pool
    timeout (2s), so a saturated application pool reports "not ready"
    quickly instead of blocking the probe indefinitely (Review Round 1
    Finding 4).

    Returns:
        bool: True if database is reachable, False otherwise
    """
    try:
        with _get_probe_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return False
