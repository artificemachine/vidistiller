"""Migration drift guard.

Asserts that running `alembic upgrade head` against a real, empty Postgres
database produces exactly the schema `models.py` declares. This is the test
the 2026-07-22 architecture audit found missing: schema management had
drifted into a state where the app's own startup lifespan built the schema
directly from the models (Base.metadata.create_all + a hand-written
ALTER-loop), Alembic's migration existed but was never actually invoked
anywhere, and real drift accumulated on production silently -- a missing
enum value, a narrower-than-declared column, and five foreign keys missing
their ON DELETE CASCADE. See migrations/versions/0001_squashed_baseline.py
for the incident writeup.

This test requires a real Postgres reachable via TEST_DATABASE_URL (or
DATABASE_URL) -- SQLite (used by the rest of the suite via conftest.py's
test_engine fixture) can't exercise Postgres-specific DDL like the enum
types and ON DELETE CASCADE this guard exists to protect. Start one with:

    docker compose -f docker-compose.test.yml up -d

If no Postgres is reachable, this test skips rather than failing -- but it
runs for real in CI (see .github/workflows/test.yml's migration-drift job),
so skipping locally never masks a real regression on a PR.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db"
)


def _postgres_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(DATABASE_URL),
    reason=(
        "No Postgres reachable at TEST_DATABASE_URL/DATABASE_URL -- "
        "start one with `docker compose -f docker-compose.test.yml up -d`"
    ),
)


@pytest.fixture()
def migrated_engine():
    """The test database, wiped to empty and migrated via the real Alembic CLI
    (not create_all) -- this is the same DB docker-compose.test.yml provides,
    reset to a clean slate so this test owns its own state.
    """
    from alembic import command
    from alembic.config import Config

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")

    yield engine

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    engine.dispose()



# transcripts.full_text_tsv (+ its GIN index) is a Postgres-only generated
# column added in 0002_transcript_fulltext_search.py, deliberately NOT
# declared on the Transcript model: SQLAlchemy would emit the same DDL for
# the SQLite test engine (Base.metadata.create_all), and SQLite has no
# to_tsvector() -- declaring it there would break every test in the suite.
# It's queried via a raw text() clause (app/routes/jobs.py's _search_filter)
# instead of an ORM column. Expected drift, not a missed migration.
_EXPECTED_DRIFT_TABLES_COLUMNS = {("transcripts", "full_text_tsv")}


def _is_expected_drift(item) -> bool:
    kind = item[0]
    if kind == "remove_column":
        _, table, column = item[0], item[2], item[3]
        return (table, column.name) in _EXPECTED_DRIFT_TABLES_COLUMNS
    if kind == "remove_index":
        index = item[1]
        table = index.table.name
        # An index's columns are on the Column objects it indexes.
        return any((table, c.name) in _EXPECTED_DRIFT_TABLES_COLUMNS for c in index.columns)
    return False


def test_alembic_head_matches_models(migrated_engine):
    """The migrated schema must exactly match what the models declare.

    A non-empty diff means someone changed a model without writing a
    migration for it -- exactly the drift that let `videos.url`, the
    `processingstatus` enum, and five FK ON DELETE clauses silently
    diverge from production for an unknown length of time.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    import app.db.models as m

    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diff = compare_metadata(context, m.Base.metadata)

    unexpected = [item for item in diff if not _is_expected_drift(item)]

    assert unexpected == [], (
        f"alembic upgrade head produced a schema that differs from models.py "
        f"({len(unexpected)} unexpected item(s)): {unexpected}\n"
        f"Run `alembic revision --autogenerate` and commit the result."
    )


def test_downgrade_reupgrade_rehearsal(migrated_engine):
    """Upgrade → downgrade → re-upgrade with representative data (Review
    Round 1 Finding 18 / plan §4: migration upgrade/rollback rehearsal).

    Seeds users, jobs, queue rows, active/expired leases and role grants,
    then downgrades to 0003 and back to head, asserting both directions
    succeed and the re-upgraded schema still holds the seeded rows.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    with migrated_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (username, email, password_hash, is_active, token_version) "
                "VALUES ('rehearsal', 'rehearsal@test.local', 'x', true, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO processing_jobs (job_id, status, user_id) "
                "VALUES ('rehearsal-job-1', 'pending', "
                "(SELECT id FROM users WHERE username='rehearsal'))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO admission_counters (key, active, \"limit\") VALUES ('global', 1, 4)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO resource_slots (sidecar_id, slot_index, enabled, state, generation) "
                "VALUES ('primary', 0, true, 'leased', 3)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO user_roles (user_id, role, granted_by) "
                "VALUES ((SELECT id FROM users WHERE username='rehearsal'), 'operator', 'tests')"
            )
        )
        conn.commit()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    command.downgrade(cfg, "0003_job_steps")
    # The downgrade must drop the new tables (their rows are scheduler
    # ephemera; destructive downgrade is a documented separate action).
    with migrated_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.resource_slots')")
        ).scalar()
        assert exists is None
        # 0003-era data survives the downgrade.
        user_count = conn.execute(
            text("SELECT count(*) FROM users WHERE username='rehearsal'")
        ).scalar()
        assert user_count == 1

    command.upgrade(cfg, "head")
    with migrated_engine.connect() as conn:
        # 0003-era data still present after re-upgrade.
        job_count = conn.execute(
            text("SELECT count(*) FROM processing_jobs WHERE job_id='rehearsal-job-1'")
        ).scalar()
        assert job_count == 1
        # New tables recreated empty and usable.
        conn.execute(
            text(
                "INSERT INTO admission_counters (key, active, \"limit\") VALUES ('global', 1, 4)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO resource_slots (sidecar_id, slot_index, enabled, state, generation) "
                "VALUES ('primary', 0, true, 'leased', 3)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO user_roles (user_id, role, granted_by) "
                "VALUES ((SELECT id FROM users WHERE username='rehearsal'), 'operator', 'tests')"
            )
        )
        conn.commit()
        slot_state = conn.execute(
            text("SELECT state FROM resource_slots WHERE sidecar_id='primary'")
        ).scalar()
        assert slot_state == "leased"
        active = conn.execute(
            text("SELECT active FROM admission_counters WHERE key='global'")
        ).scalar()
        assert active == 1
        role = conn.execute(
            text("SELECT role FROM user_roles WHERE role='operator'")
        ).scalar()
        assert role == "operator"
