"""Admission control, resource leases, and dispatch outbox.

Additive schema for WP2 (explicit admission control and resource leases):

- ``admission_counters`` — durable global/per-user active-job counters whose
  rows are locked in deterministic order (global, then user) inside the
  admission transaction. ``active`` counts admitted-but-unfinished work;
  ``limit`` is the operator-configured cap.
- ``job_admissions`` — one row per job recording its admission state
  (queued / admitted / finished / failed), the visible queue reason, and the
  policy version that admitted it. A job in ``queued`` state is not yet
  dispatched to Celery.
- ``resource_slots`` — per-sidecar slot table. A slot is the unit of scarce
  sidecar capacity (LLM/vision requests). Rows carry the fencing data
  required by Review Round 1 Finding 5: a per-incarnation execution UUID
  (``claim_exec_uuid``, never the Celery task id), a monotonic
  ``generation``, a database-time ``heartbeat_at``, and an ``expires_at``.
  State machine: free -> leased -> expired/free. Reclamation never moves a
  slot straight from leased to free while an old external request may still
  be running; it goes through ``expired`` and a quarantine window.
- ``lease_events`` — append-only audit trail of acquire / heartbeat /
  release / reclaim / expire events.
- ``task_outbox`` — durable at-least-once dispatch records. A stage is
  written ``pending`` in the admission transaction and only published to
  Redis after commit; the API startup sweep re-publishes pending rows after
  a crash.

The ``processingstatus`` enum is intentionally NOT extended with a queued
value (Review Round 1 Finding 17): queue state lives in ``job_admissions``,
keeping the processing lifecycle enum additive-safe for rollback.

Revision ID: 0004_admission_leases
Revises: 0003_job_steps
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_admission_leases"
down_revision: Union[str, Sequence[str], None] = "0003_job_steps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


admission_state = postgresql.ENUM(
    "queued", "admitted", "finished", "failed",
    name="admissionstate",
    create_type=False,
)
slot_state = postgresql.ENUM(
    "free", "leased", "expired",
    name="slotstate",
    create_type=False,
)


def upgrade() -> None:
    admission_state.create(op.get_bind(), checkfirst=True)
    slot_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admission_counters",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "job_admissions",
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("state", admission_state, nullable=False, server_default="queued"),
        sa.Column("queue_reason", sa.String(length=512), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("admitted_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_job_admissions_state_queued_at", "job_admissions", ["state", "queued_at"])

    op.create_table(
        "resource_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sidecar_id", sa.String(length=64), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("state", slot_state, nullable=False, server_default="free"),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("claim_exec_uuid", sa.String(length=64), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sidecar_id", "slot_index", name="uq_resource_slots_sidecar_slot"),
    )
    op.create_index("ix_resource_slots_state_expires", "resource_slots", ["state", "expires_at"])
    op.create_index("ix_resource_slots_sidecar_state", "resource_slots", ["sidecar_id", "state"])

    op.create_table(
        "lease_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("sidecar_id", sa.String(length=64), nullable=True),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("exec_uuid", sa.String(length=64), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["resource_slots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lease_events_slot_created", "lease_events", ["slot_id", "created_at"])
    op.create_index("ix_lease_events_job_created", "lease_events", ["job_id", "created_at"])

    op.create_table(
        "task_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_outbox_state_created", "task_outbox", ["state", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_task_outbox_state_created", table_name="task_outbox")
    op.drop_table("task_outbox")
    op.drop_index("ix_lease_events_job_created", table_name="lease_events")
    op.drop_index("ix_lease_events_slot_created", table_name="lease_events")
    op.drop_table("lease_events")
    op.drop_index("ix_resource_slots_sidecar_state", table_name="resource_slots")
    op.drop_index("ix_resource_slots_state_expires", table_name="resource_slots")
    op.drop_table("resource_slots")
    op.drop_index("ix_job_admissions_state_queued_at", table_name="job_admissions")
    op.drop_table("job_admissions")
    op.drop_table("admission_counters")
    slot_state.drop(op.get_bind(), checkfirst=True)
    admission_state.drop(op.get_bind(), checkfirst=True)
