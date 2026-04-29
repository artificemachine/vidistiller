"""
API Key Authentication for Machine-to-Machine Clients

Provides a FastAPI dependency that accepts either:
- X-API-Key header (machine-to-machine, e.g. Semblar calling vidistiller)
- JWT Bearer token (standard user login, existing behavior)

When VIDISTILLER_API_KEY is not configured, API key auth is silently skipped
and only JWT auth is used. This ensures backward compatibility.
"""

import secrets
import logging
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings, ApiKeySettings
from app.db.session import get_db
from app.db.models import User
from app.exceptions import AuthenticationException

logger = logging.getLogger(__name__)

# Username for the synthetic service user created on first API key call
SEMBLAR_SERVICE_USERNAME = "semblar"


def _get_or_create_service_user(db: Session, username: str) -> User:
    """Return the service user, creating it on first use if it does not exist."""
    user = db.query(User).filter(User.username == username).first()
    if user is not None:
        return user

    logger.info("Creating service user '%s' (first API key call)", username)
    user = User(
        username=username,
        email=f"{username}@internal",
        password_hash="",  # no password — only API key auth
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


async def get_current_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Authenticate a request via X-API-Key header or JWT Bearer token.

    Priority:
    1. X-API-Key header → compare against VIDISTILLER_API_KEY, return service user
    2. Authorization: Bearer <token> → standard JWT validation, return real user

    If VIDISTILLER_API_KEY is not configured (empty string), API key auth is
    silently skipped and only JWT auth is attempted.
    """
    settings = get_settings()
    configured_key = settings.api_key.vidistiller_api_key

    # Option A: API key header (machine-to-machine)
    if x_api_key and configured_key:
        if not secrets.compare_digest(x_api_key, configured_key):
            raise AuthenticationException("Invalid API key")
        return _get_or_create_service_user(db, SEMBLAR_SERVICE_USERNAME)

    # Option B: standard JWT (user login)
    # Import here to avoid circular dependency — the route module
    # wires this dependency, so we delegate to the existing JWT flow.
    from app.routes.auth import get_current_user_from_token

    return get_current_user_from_token(authorization=authorization, db=db)
