#!/usr/bin/env python3
"""Grant or revoke the operator role for a user (WP4).

Auditable, one-time operational tool. No username is hardcoded as
authorization: the acting operator (or the owner, for the first grant)
resolves the target by numeric user id and the grant is recorded in
``user_roles`` with actor metadata.

Usage:
    python scripts/grant-operator.py grant <user_id> --actor <name> [--reason <text>]
    python scripts/grant-operator.py revoke <user_id> --actor <name> [--reason <text>]
    python scripts/grant-operator.py list

Requires DATABASE_URL to be set (production .env). Idempotent.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROLE = "operator"


def _engine():
    from sqlalchemy import create_engine

    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL is not set")
        sys.exit(2)
    return create_engine(url)


def _grant(db, user_id: int, actor: str, reason: str | None) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    row = db.execute(
        text(
            "SELECT id, revoked_at FROM user_roles "
            "WHERE user_id = :uid AND role = :role"
        ),
        {"uid": user_id, "role": ROLE},
    ).first()
    if row is not None and row.revoked_at is None:
        logger.info("user %s already has an active %s grant (row %s)", user_id, ROLE, row.id)
        return False
    db.execute(
        text(
            "INSERT INTO user_roles (user_id, role, granted_by, granted_at, revoked_at) "
            "VALUES (:uid, :role, :actor, :now, NULL)"
        ),
        {"uid": user_id, "role": ROLE, "actor": actor, "now": now},
    )
    db.commit()
    logger.info("granted %s to user %s by %s (reason: %s)", ROLE, user_id, actor, reason or "-")
    return True


def _revoke(db, user_id: int, actor: str, reason: str | None) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    result = db.execute(
        text(
            "UPDATE user_roles SET revoked_at = :now, revoked_by = :actor "
            "WHERE user_id = :uid AND role = :role AND revoked_at IS NULL"
        ),
        {"uid": user_id, "role": ROLE, "actor": actor, "now": now},
    )
    db.commit()
    if result.rowcount:
        logger.info("revoked %s from user %s by %s (reason: %s)", ROLE, user_id, actor, reason or "-")
        return True
    logger.info("user %s has no active %s grant to revoke", user_id, ROLE)
    return False


def _list(db) -> None:
    rows = db.execute(
        text(
            "SELECT user_id, granted_by, granted_at, revoked_by, revoked_at "
            "FROM user_roles WHERE role = :role ORDER BY granted_at DESC"
        ),
        {"role": ROLE},
    ).all()
    if not rows:
        print("no operator grants")
        return
    for r in rows:
        state = "revoked" if r.revoked_at else "active"
        print(
            f"user={r.user_id} {state} granted_by={r.granted_by} "
            f"at={r.granted_at} revoked_by={r.revoked_by}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the operator role")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant", help="grant operator to a user id")
    grant.add_argument("user_id", type=int)
    grant.add_argument("--actor", required=True, help="acting identity (audit)")
    grant.add_argument("--reason", default=None)
    revoke = sub.add_parser("revoke", help="revoke operator from a user id")
    revoke.add_argument("user_id", type=int)
    revoke.add_argument("--actor", required=True)
    revoke.add_argument("--reason", default=None)
    sub.add_parser("list", help="list operator grants")

    args = parser.parse_args()
    engine = _engine()
    with engine.connect() as conn:
        if args.command == "grant":
            _grant(conn, args.user_id, args.actor, args.reason)
        elif args.command == "revoke":
            _revoke(conn, args.user_id, args.actor, args.reason)
        else:
            _list(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
