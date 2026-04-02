"""
Database Session Management

This module provides SQLAlchemy session factory, connection pooling configuration,
and FastAPI dependency injection for database session management.

Uses synchronous SQLAlchemy for compatibility with Celery workers.
"""

import logging
from typing import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.pool import QueuePool

from ..core.config import get_settings

logger = logging.getLogger(__name__)


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

    Connection pooling configuration:
    - pool_size: Minimum number of connections to maintain (20)
    - max_overflow: Maximum additional connections beyond pool_size (40)
    - pool_recycle: Recycle connections after this many seconds (3600 = 1 hour)
    - pool_pre_ping: Verify connection is still alive before using it

    Returns:
        Engine: Configured SQLAlchemy engine instance
    """
    settings = get_settings()
    engine = create_engine(
        settings.database.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=settings.environment.value == "development",  # Log SQL in dev
    )

    # Add event listener to handle connection before use
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_conn, connection_record):
        """Enable foreign key constraints for SQLite (if used)."""
        if "sqlite" in settings.database.DATABASE_URL:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# Create engine instance (module-level singleton)
engine = _get_engine()


# ==============================================================================
# SESSION FACTORY
# ==============================================================================

# Create session factory bound to engine
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,  # Don't expire objects after commit (useful for background jobs)
)


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
    db = SessionLocal()
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


# ==============================================================================
# HEALTH CHECK
# ==============================================================================

def health_check() -> bool:
    """
    Check database connectivity.

    Useful for startup health checks or monitoring.

    Returns:
        bool: True if database is reachable, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return False
