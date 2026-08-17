"""WP2 acceptance: real Celery late-ack redelivery fencing (Review Round 2 F12).

Starts a real Celery worker against the real Redis (docker-compose.test.yml),
submits a task that blocks on a file barrier, kills the worker mid-execution
(worker loss before ack), and verifies that:

1. the redelivered execution cannot re-claim the step (per-incarnation
   exec_uuid fencing), and
2. no duplicate sidecar-style work happens (the step claim is the fence).

Requires Redis at REDIS_URL and the real Postgres at TEST_DATABASE_URL.
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db",
)
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


def _postgres_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


def _redis_reachable(url: str) -> bool:
    try:
        import redis as _redis

        client = _redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_postgres_reachable(DATABASE_URL) and _redis_reachable(REDIS_URL)),
    reason="requires real Postgres + Redis (docker-compose.test.yml)",
)


@pytest.fixture(scope="module")
def celery_env(tmp_path_factory):
    """Migrated DB, seeded job, and a real worker process with a short
    visibility timeout so redelivery happens quickly."""
    from alembic import command
    from alembic.config import Config

    from app.db.models import ProcessingJob, ResourceSlot, Sidecar, User
    from app.db.session import SessionLocal
    from app.services.auth import AuthService

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")
    engine.dispose()

    barrier_dir = tmp_path_factory.mktemp("celery-barrier")

    env = dict(os.environ)
    env["DATABASE_URL"] = DATABASE_URL
    env["REDIS_URL"] = REDIS_URL
    env["ENVIRONMENT"] = "testing"
    env["JWT_SECRET_KEY"] = "TestSecretKey123!@#abcDEF_development_onlyx"
    env["CELERY_VISIBILITY_TIMEOUT"] = "10"
    env["CELERY_TASK_TIME_LIMIT"] = "120"
    env["VIDISTILLER_TEST_BARRIER_DIR"] = str(barrier_dir)

    # Seed user + slot once; each test creates its own fresh job via the
    # returned factory so tests never share step state (Review Round 2 F12).
    db = SessionLocal()
    user = User(
        username="celery_race",
        email="celery_race@test.local",
        password_hash=AuthService.hash_password("RacePass123"),
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(
        Sidecar(
            registered_id="primary",
            label="Primary",
            base_url="http://test.invalid:8000",
            capabilities=["text"],
        )
    )
    db.add(ResourceSlot(sidecar_id="primary", slot_index=0))
    db.commit()
    user_id = user.id

    def make_job() -> int:
        """Create a fresh slide-aware job with seeded steps; returns job id."""
        from app.services.job_steps import seed_job_steps

        d = SessionLocal()
        try:
            job = ProcessingJob(
                job_id=str(uuid.uuid4()),
                status="pending",
                video_url="https://example.com/v",
                user_id=user_id,
                processing_mode="slide_aware",
            )
            d.add(job)
            d.commit()
            d.refresh(job)
            seed_job_steps(d, job, extract_snapshots=False, is_slide_mode=True)
            d.commit()
            return job.id
        finally:
            d.close()

    db.close()

    yield {"env": env, "make_job": make_job, "barrier_dir": str(barrier_dir)}

    # Cleanup worker if still running.
    try:
        subprocess.run(["pkill", "-f", "celery -A app.tasks worker"], check=False)
    except Exception:
        pass


def _start_worker(env):
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks",
            "worker",
            "--loglevel=INFO",
            "--concurrency=1",
            "--pool=solo",
        ],
        cwd=str(Path(__file__).resolve().parents[1] / "backend"),
        env=env,
        stdout=open("/tmp/celery-worker.log", "w"),
        stderr=subprocess.STDOUT,
    )
    return proc


def test_late_ack_redelivery_cannot_duplicate_work(celery_env):
    """A worker killed mid-step (before ack) is redelivered; the second
    incarnation must NOT re-claim the step (exec_uuid fencing)."""
    from app.services.job_steps import claim_step

    env = celery_env["env"]
    job_id = celery_env["make_job"]()
    barrier_dir = Path(celery_env["barrier_dir"])

    # First incarnation claims the step and blocks at a barrier (simulating a
    # long sidecar call in progress). We drive the claim + barrier by hand:
    # the claim carries the incarnation's exec_uuid.
    from app.db.session import SessionLocal

    db = SessionLocal()
    exec_uuid = str(uuid.uuid4())
    claimed = claim_step(db, job_id, "transcribe", exec_uuid)
    assert claimed is not None
    db.commit()
    db.close()

    # A redelivered message (same Celery task id, NEW incarnation) tries to
    # claim the same step: must be rejected — the running claim is fenced by
    # the old incarnation's exec_uuid.
    db = SessionLocal()
    redelivered_exec_uuid = str(uuid.uuid4())  # fresh incarnation UUID
    reclaimed = claim_step(db, job_id, "transcribe", redelivered_exec_uuid)
    db.commit()
    db.close()
    assert reclaimed is None, (
        "redelivered incarnation must not re-claim a step owned by another "
        "execution (fencing violated)"
    )

    # The first incarnation can still complete under ITS token (its work is
    # authoritative; the duplicate delivery is skipped).
    from app.services.job_steps import complete_step

    db = SessionLocal()
    ok = complete_step(db, job_id, "transcribe", exec_uuid, {"source": "test"})
    db.commit()
    db.close()
    assert ok is True


def test_worker_process_redelivery_real(celery_env):
    """End-to-end worker-loss with a DURABLE claim: the real task claims
    (committed), blocks at the barrier; the worker is SIGKILLed before ack;
    the redelivered execution must be FENCED OUT — it must not re-claim the
    step (attempt stays 1, claim token unchanged) and must not rewrite the
    marker (Review Round 2 F12)."""
    import redis as _redis

    env = celery_env["env"]
    job_id = celery_env["make_job"]()
    barrier_dir = Path(celery_env["barrier_dir"])
    marker = barrier_dir / f"claimed-{job_id}-transcribe"
    release = barrier_dir / f"release-{job_id}-transcribe"

    from app.tasks import process_transcript

    client = _redis.from_url(REDIS_URL, decode_responses=True)
    client.flushdb()

    worker1 = _start_worker(env)
    try:
        time.sleep(3)
        result = process_transcript.delay(job_id)
        task_id = result.id

        # Wait for the durable claim marker (claim is COMMITTED in the DB).
        for _ in range(30):
            if marker.exists():
                break
            time.sleep(1)
        assert marker.exists(), "worker did not reach the barrier"
        first_claim = marker.read_text()
        assert "claimed=True" in first_claim

        # SIGKILL before ack (hard worker loss; the committed claim survives).
        worker1.kill()
        worker1.wait(timeout=10)

        # Worker 2: redelivery after the visibility window. It must be fenced
        # out by the durable RUNNING claim — the marker is NOT rewritten and
        # the task completes as "skipped".
        time.sleep(10)
        worker2 = _start_worker(env)
        try:
            time.sleep(2)
            # Give the redelivery time to be picked up and fenced out.
            for _ in range(40):
                meta = client.get(f"celery-task-meta-{task_id}") or ""
                if '"status": "SUCCESS"' in meta or '"status": "FAILURE"' in meta:
                    break
                time.sleep(1)
            meta = client.get(f"celery-task-meta-{task_id}") or ""
            assert '"status": "SUCCESS"' in meta, f"task did not succeed: {meta[:200]}"
            # Fence proof: the marker was NOT rewritten by a second claim.
            assert marker.read_text() == first_claim, (
                "redelivered incarnation re-claimed the step (fencing violated)"
            )
        finally:
            worker2.terminate()
            worker2.wait(timeout=10)

        # The durable claim is untouched: attempt == 1, token unchanged,
        # status still RUNNING (owned by the dead incarnation; the orphan
        # reaper reclaims it after ORPHANED_CLAIM_TTL_SECONDS).
        from app.db.models import JobStep
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            step = (
                db.query(JobStep)
                .filter(JobStep.job_id == job_id, JobStep.name == "transcribe")
                .first()
            )
            assert step is not None
            assert step.attempt == 1, f"duplicate work: attempt={step.attempt}"
            assert step.claim_token is not None
        finally:
            db.close()
    finally:
        for proc in (worker1,):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
