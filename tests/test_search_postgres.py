"""Full-text transcript search against real Postgres.

The main test suite runs on in-memory SQLite (tests/conftest.py's test_engine
fixture), so it exercises the ILIKE fallback branch of
app/routes/jobs.py's _search_filter -- never the Postgres-only
to_tsvector/websearch_to_tsquery path against the generated full_text_tsv
column (see migrations/versions/0002_transcript_fulltext_search.py). This
module is the only place that path gets real coverage.

Requires a real Postgres reachable via TEST_DATABASE_URL (or DATABASE_URL) --
start one with:

    docker compose -f docker-compose.test.yml up -d

If no Postgres is reachable, this module skips rather than failing -- but it
runs for real in CI (see .github/workflows/test.yml's migration-drift job),
so skipping locally never masks a real regression on a PR.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

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
def pg_session():
    """A real Postgres session, migrated via the Alembic CLI, wiped after."""
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

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    engine.dispose()


def _make_user(session, username="pguser"):
    from app.db.models import User
    from app.services.auth import AuthService

    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=AuthService.hash_password("TestPass123"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _make_job_with_transcript(session, user, job_id, full_text):
    from app.db.models import ProcessingJob, ProcessingStatus, Transcript

    job = ProcessingJob(
        job_id=job_id,
        status=ProcessingStatus.COMPLETED,
        video_url=f"https://www.youtube.com/watch?v={job_id}",
        user_id=user.id,
    )
    session.add(job)
    session.flush()
    session.add(Transcript(job_id=job.id, full_text=full_text, language="en", source="youtube_captions"))
    session.commit()
    session.refresh(job)
    return job


def test_generated_tsvector_column_populates(pg_session):
    """The generated column derives from full_text without any app write."""
    user = _make_user(pg_session)
    _make_job_with_transcript(
        pg_session, user, "job-tsv-1",
        "This tutorial explains how to configure a Kubernetes ingress controller.",
    )

    row = pg_session.execute(
        text("SELECT full_text_tsv FROM transcripts WHERE job_id = (SELECT id FROM processing_jobs WHERE job_id = 'job-tsv-1')")
    ).first()
    assert row is not None
    assert row[0] is not None
    assert "kubernet" in row[0]  # tsvector stores the stemmed lexeme


def test_search_matches_transcript_keyword_via_tsvector(pg_session):
    from app.routes.jobs import _search_filter
    from app.db.models import ProcessingJob

    user = _make_user(pg_session)
    matching = _make_job_with_transcript(
        pg_session, user, "job-tsv-match",
        "This tutorial explains how to configure a Kubernetes ingress controller.",
    )
    _make_job_with_transcript(
        pg_session, user, "job-tsv-nomatch",
        "A completely unrelated video about baking sourdough bread.",
    )

    results = (
        pg_session.query(ProcessingJob)
        .filter(ProcessingJob.user_id == user.id, _search_filter(pg_session, "kubernetes"))
        .all()
    )
    job_ids = [j.job_id for j in results]
    assert matching.job_id in job_ids
    assert "job-tsv-nomatch" not in job_ids


def test_search_matches_stemmed_variant(pg_session):
    """websearch_to_tsquery normalizes plurals/verb forms via the stemmer."""
    from app.routes.jobs import _search_filter
    from app.db.models import ProcessingJob

    user = _make_user(pg_session)
    job = _make_job_with_transcript(
        pg_session, user, "job-tsv-stem",
        "We are configuring several ingress controllers today.",
    )

    results = (
        pg_session.query(ProcessingJob)
        .filter(ProcessingJob.user_id == user.id, _search_filter(pg_session, "controller"))
        .all()
    )
    assert job.job_id in [j.job_id for j in results]
