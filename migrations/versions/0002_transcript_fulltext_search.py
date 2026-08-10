"""Add a generated tsvector column + GIN index on transcripts.full_text.

Backs the job search feature (GET /jobs?q=...): title/URL matches are cheap
ILIKE scans, but transcripts can run 60K+ chars, so a plain ILIKE full-table
scan on that column doesn't hold up. Postgres' GENERATED ALWAYS AS ... STORED
keeps the tsvector in sync with full_text automatically (no app-side upkeep,
no trigger to maintain), and the GIN index makes @@ websearch_to_tsquery(...)
lookups index-scans instead of table-scans.

SQLite (used by the rest of the test suite) has no tsvector/GIN equivalent —
the search query falls back to a plain ILIKE on full_text for that dialect,
so this migration and the generated column are Postgres-only.

Revision ID: 0002_transcript_fulltext_search
Revises: 0001_squashed_baseline
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0002_transcript_fulltext_search'
down_revision: Union[str, Sequence[str], None] = '0001_squashed_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE transcripts ADD COLUMN full_text_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_transcripts_full_text_tsv ON transcripts USING GIN (full_text_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcripts_full_text_tsv")
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS full_text_tsv")
