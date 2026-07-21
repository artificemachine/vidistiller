"""Squashed baseline schema.

The previous migration chain was unrunnable from a fresh clone: several
revisions (001, 007, 009, 011) were committed as empty stubs and later deleted,
leaving dangling down_revision references, and env.py was removed. Both the dev
quickstart and production actually build the schema from the SQLAlchemy models
via Base.metadata.create_all at startup, so alembic had drifted into a broken,
decorative state.

This baseline consolidates all prior migrations into one. It builds the full
current schema directly from the models, which are the real source of truth.
create_all uses checkfirst semantics, so applying this to a database that
already has the tables (e.g. production) is a safe no-op; on a fresh database it
creates everything.

Revision ID: 0001_squashed_baseline
Revises:
Create Date: 2026-07-21
"""
from alembic import op

from app.db.models import Base
import app.db.models  # noqa: F401  (import side effect: registers all tables)

revision = "0001_squashed_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
