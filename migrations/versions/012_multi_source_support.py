"""
Multi-source video support.

- Renames processing_jobs.youtube_url → video_url
- Expands videos.video_id from String(20) to String(100)
- Adds source_type column to processing_jobs and videos
- Backfills source_type = 'youtube' for all existing rows

Revision ID: 012
Revises: 011
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename youtube_url → video_url on processing_jobs
    op.alter_column('processing_jobs', 'youtube_url', new_column_name='video_url')

    # 2. Add source_type to processing_jobs; backfill existing rows as 'youtube'
    op.add_column('processing_jobs', sa.Column('source_type', sa.String(20), nullable=True))
    op.execute("UPDATE processing_jobs SET source_type = 'youtube' WHERE video_url IS NOT NULL")

    # 3. Expand videos.video_id from String(20) to String(100)
    op.alter_column('videos', 'video_id', type_=sa.String(100), existing_nullable=False)

    # 4. Add source_type to videos; backfill existing rows as 'youtube'
    op.add_column('videos', sa.Column('source_type', sa.String(20), nullable=True))
    op.execute("UPDATE videos SET source_type = 'youtube'")


def downgrade() -> None:
    op.drop_column('videos', 'source_type')
    op.alter_column('videos', 'video_id', type_=sa.String(20), existing_nullable=False)
    op.drop_column('processing_jobs', 'source_type')
    op.alter_column('processing_jobs', 'video_url', new_column_name='youtube_url')
