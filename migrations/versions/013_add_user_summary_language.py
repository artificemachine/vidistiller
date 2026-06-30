"""
Add summary_language column to users table.

Allows users to specify a preferred output language for LLM summaries,
independent of the detected transcript language.

Revision ID: 013
Revises: 012
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('summary_language', sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'summary_language')
