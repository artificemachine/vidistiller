"""
Add LLM provider preference columns to users table.

Revision ID: 008
Revises: 007
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add LLM preference fields to users table."""
    op.add_column(
        'users',
        sa.Column('llm_provider', sa.String(20), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('llm_model', sa.String(100), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('llm_api_key_encrypted', sa.Text, nullable=True),
    )


def downgrade() -> None:
    """Remove LLM preference fields from users table."""
    op.drop_column('users', 'llm_api_key_encrypted')
    op.drop_column('users', 'llm_model')
    op.drop_column('users', 'llm_provider')
