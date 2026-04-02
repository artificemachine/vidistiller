"""
Fix Video.video_id unique constraint — replace column-level unique with composite unique(video_id, job_id).

Previously, video_id had a global unique constraint which forced a synthetic-key workaround when
multiple jobs processed the same YouTube video. This migration drops that constraint and adds
a composite unique on (video_id, job_id) so each job gets its own clean Video record.

Revision ID: 010
Revises: 009
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa


revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop global unique on video_id; add composite unique(video_id, job_id)."""
    # Drop the old column-level unique index
    op.drop_index('ix_videos_video_id', table_name='videos')
    op.drop_constraint('videos_video_id_key', 'videos', type_='unique')

    # Add composite unique constraint
    op.create_unique_constraint('uq_videos_video_id_job_id', 'videos', ['video_id', 'job_id'])

    # Re-create the non-unique index for lookup performance
    op.create_index('ix_videos_video_id', 'videos', ['video_id'])


def downgrade() -> None:
    """Restore global unique on video_id."""
    op.drop_constraint('uq_videos_video_id_job_id', 'videos', type_='unique')
    op.drop_index('ix_videos_video_id', table_name='videos')
    op.create_index('ix_videos_video_id', 'videos', ['video_id'], unique=True)
