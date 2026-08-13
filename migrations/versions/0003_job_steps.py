"""Persist independently resumable processing stages for each job.

Revision ID: 0003_job_steps
Revises: 0002_transcript_fulltext_search
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_job_steps"
down_revision: Union[str, Sequence[str], None] = "0002_transcript_fulltext_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


job_step_status = sa.Enum(
    "pending", "running", "completed", "failed", "skipped", "cancelled",
    name="jobstepstatus",
)


def upgrade() -> None:
    job_step_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "job_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("status", job_step_status, nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("claim_token", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "name", name="uq_job_steps_job_id_name"),
    )
    op.create_index("ix_job_steps_job_id_status", "job_steps", ["job_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_job_steps_job_id_status", table_name="job_steps")
    op.drop_table("job_steps")
    job_step_status.drop(op.get_bind(), checkfirst=True)
