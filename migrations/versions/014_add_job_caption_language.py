"""
Add caption_language column to processing_jobs.

Lets a user pick which caption language a job should transcribe, so an
auto-dubbed video is not transcribed in the first available dub track. Null
means the pipeline defaults to English.

Revision ID: 014
Revises: 013
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'processing_jobs',
        sa.Column('caption_language', sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('processing_jobs', 'caption_language')
