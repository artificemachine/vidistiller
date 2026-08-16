"""Sidecar registry and operator RBAC grants.

Additive schema for WP3 (selectable sidecars) and WP4 (operator RBAC):

- ``sidecars`` — the server-side registry of trusted sidecar endpoints.
  ``registered_id`` is the stable, allowlisted identifier users may select
  as ``sidecar_preference``; it is never a client-supplied URL. Capabilities
  (text/vision) are declared by the operator; the live inventory probe
  separately verifies health and the served model.
- ``processing_jobs.sidecar_preference`` — nullable; ``auto`` is the default
  when NULL (see the application layer), otherwise a registered sidecar id.
- ``user_roles`` — durable, auditable role grants. ``role`` is a string
  (``operator`` today); ``granted_by``/``revoked_by`` record the actor;
  grants are revoked by setting ``revoked_at`` (rows are never deleted, so
  audit history is preserved). No username is hardcoded as authorization:
  the grant tool resolves a user id and records it here.

Revision ID: 0005_sidecars_rbac
Revises: 0004_admission_leases
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_sidecars_rbac"
down_revision: Union[str, Sequence[str], None] = "0004_admission_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sidecars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registered_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("declared_model", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registered_id", name="uq_sidecars_registered_id"),
    )

    op.add_column(
        "processing_jobs",
        sa.Column("sidecar_preference", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_processing_jobs_sidecar_preference",
        "processing_jobs",
        ["sidecar_preference"],
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("granted_by", sa.String(length=128), nullable=True),
        sa.Column("granted_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_by", sa.String(length=128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role", name="uq_user_roles_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role", "user_roles", ["role"])


def downgrade() -> None:
    op.drop_index("ix_user_roles_role", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_processing_jobs_sidecar_preference", table_name="processing_jobs")
    op.drop_column("processing_jobs", "sidecar_preference")
    op.drop_table("sidecars")
