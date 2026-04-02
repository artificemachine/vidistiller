"""
Database Package Initialization

Exports all database models, session management, and utilities
for clean imports throughout the application.

Usage in routes:
    from app.db import SessionLocal, get_db, Base
    from app.db.models import ProcessingJob, Video, etc.

Usage for Alembic migrations:
    from app.db.session import Base
    from app.db import models  # This registers models with Base.metadata
"""

# Export session management utilities
from .session import Base, SessionLocal, engine, get_db, health_check

__all__ = [
    # Session management
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "health_check",
]
