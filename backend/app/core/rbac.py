"""Operator authorization (WP4).

DB-backed, audited role grants. ``require_operator`` runs after normal
authentication and fails CLOSED: missing role, revoked role, or any DB error
denies access. Usernames are never hardcoded as authorization; grants live in
``user_roles`` and are managed through the grant tool
(``scripts/grant-operator.py``) which records the acting identity.
"""

from __future__ import annotations

import logging

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.api_key_auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.exceptions import ResourceNotFoundException

logger = logging.getLogger(__name__)

OPERATOR_ROLE = "operator"


def is_operator(db: Session, user_id: int) -> bool:
    """True only when an unrevoked operator grant exists in the DB."""
    try:
        row = db.execute(
            text(
                "SELECT 1 FROM user_roles WHERE user_id = :uid AND role = :role "
                "AND revoked_at IS NULL"
            ),
            {"uid": user_id, "role": OPERATOR_ROLE},
        ).first()
        return row is not None
    except Exception as exc:
        # Fail closed: a DB error must never grant access.
        logger.error("operator role lookup failed (denying): %s", exc)
        return False


def require_operator(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: authenticated AND an unrevoked operator.

    Raises 404 (indistinguishable from absent) for non-operators so the
    operations surface is not enumerable by ordinary users.
    """
    if not is_operator(db, current_user.id):
        raise ResourceNotFoundException("Job")
    return current_user
