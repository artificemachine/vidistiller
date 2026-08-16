"""WP2 acceptance: admission races, lease fencing, worker-loss, queued recovery.

Runs against a real Postgres (docker-compose.test.yml) with independent
connections so the locking semantics are real — SQLite cannot exercise
FOR UPDATE SKIP LOCKED. Skipped when no Postgres is reachable.
"""

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db",
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
    reason="No Postgres reachable at TEST_DATABASE_URL/DATABASE_URL",
)


@pytest.fixture()
def db_factory():
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
    engine.dispose()

    factory = sessionmaker(bind=create_engine(DATABASE_URL), expire_on_commit=False)
    yield factory
    factory.kw["bind"].dispose()


def _seed(db, global_limit: int = 1, per_user_limit: int = 1, slots: int = 1):
    from app.db.models import AdmissionCounter, ProcessingJob, ResourceSlot, User
    from app.services.auth import AuthService

    user = User(
        username=f"race_{uuid.uuid4().hex[:8]}",
        email=f"race_{uuid.uuid4().hex[:8]}@test.local",
        password_hash=AuthService.hash_password("RacePass123"),
        is_active=True,
    )
    db.add(user)
    db.flush()
    existing_slots = (
        db.query(ResourceSlot)
        .filter(ResourceSlot.sidecar_id == "primary")
        .count()
    )
    for i in range(existing_slots, slots):
        db.add(ResourceSlot(sidecar_id="primary", slot_index=i))
    # Pre-create counter rows with the limits this test wants (the row is the
    # runtime authority; settings only seed it at creation).
    for key, limit in (("global", global_limit), (f"user:{user.id}", per_user_limit)):
        existing = db.get(AdmissionCounter, key)
        if existing is None:
            db.add(AdmissionCounter(key=key, active=0, limit=limit))
        else:
            existing.limit = limit
    db.commit()
    return user.id


def _mkjob(db, user_id: int):
    from app.db.models import ProcessingJob

    job = ProcessingJob(
        job_id=str(uuid.uuid4()),
        status="pending",
        video_url="https://example.com/v",
        user_id=user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_atomic_admission_race_global_limit_one(db_factory):
    """With global limit 1, exactly one of N concurrent admissions wins."""
    from app.services.admission import admit_or_queue_job

    db = db_factory()
    user_id = _seed(db, global_limit=1, per_user_limit=100, slots=4)
    db.close()

    results = []
    lock = threading.Lock()

    def contender():
        d = db_factory()
        try:
            job = _mkjob(d, user_id)
            outcome = admit_or_queue_job(d, job, exec_uuid=str(uuid.uuid4()))
            d.commit()
            with lock:
                results.append(outcome.state)
        finally:
            d.close()

    threads = [threading.Thread(target=contender) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    admitted = sum(1 for r in results if r == "admitted")
    queued = sum(1 for r in results if r == "queued")
    assert admitted == 1, f"expected exactly 1 admitted, got {results}"
    assert queued == 7, f"expected 7 queued, got {results}"

    # Counter consistency.
    d = db_factory()
    row = d.execute(text("SELECT active FROM admission_counters WHERE key='global'")).scalar()
    assert int(row) == 1, row
    d.close()


def test_atomic_admission_race_per_user_limit_one(db_factory):
    """Per-user limit 1 admits one job per user; other users are independent."""
    from app.services.admission import admit_or_queue_job

    db = db_factory()
    user_a = _seed(db, global_limit=100, per_user_limit=1, slots=8)
    user_b = _seed(db, global_limit=100, per_user_limit=1, slots=8)
    db.close()

    results = []
    lock = threading.Lock()

    def contender(user_id):
        d = db_factory()
        try:
            job = _mkjob(d, user_id)
            outcome = admit_or_queue_job(d, job, exec_uuid=str(uuid.uuid4()))
            d.commit()
            with lock:
                results.append((user_id, outcome.state))
        finally:
            d.close()

    threads = [
        threading.Thread(target=contender, args=(user_a,)) for _ in range(4)
    ] + [threading.Thread(target=contender, args=(user_b,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    a_states = [s for uid, s in results if uid == user_a]
    b_states = [s for uid, s in results if uid == user_b]
    assert a_states.count("admitted") == 1, a_states
    assert b_states.count("admitted") == 1, b_states


def test_worker_loss_lease_is_not_reusable_until_quarantine(db_factory):
    """A reaped (worker-lost) lease must NOT be reusable immediately; the
    fencing triple rejects stale completions and heartbeats."""
    from app.db.models import ResourceSlot, SlotState
    from app.services.admission import admit_or_queue_job, finish_job_admission
    from app.services.lease import (
        heartbeat_slot,
        reap_expired_slots,
        release_slot,
        reset_quarantined_slots,
    )

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    outcome = admit_or_queue_job(db, job, exec_uuid="exec-1")
    db.commit()
    assert outcome.slot_id is not None

    # Simulate worker loss: no heartbeats, TTL elapses.
    db.execute(
        text("UPDATE resource_slots SET expires_at = now() - interval '1 second' WHERE id = :id"),
        {"id": outcome.slot_id},
    )
    db.commit()
    assert reap_expired_slots(db) == 1
    db.commit()
    slot = db.get(ResourceSlot, outcome.slot_id)
    assert slot.state == SlotState.EXPIRED

    # A second job cannot take the slot during quarantine.
    job2 = _mkjob(db, user_id)
    outcome2 = admit_or_queue_job(db, job2, exec_uuid="exec-2")
    db.commit()
    assert outcome2.slot_id is None, "quarantined slot must not be reusable"

    # The dead worker's heartbeat/release are rejected (stale fence).
    assert heartbeat_slot(db, outcome.slot_id, "exec-1", outcome.slot_generation) is False
    assert release_slot(db, outcome.slot_id, "exec-1", outcome.slot_generation) is False
    db.rollback()

    # Release job1's admission so a later job can be admitted.
    finish_job_admission(db, job.id)
    db.commit()

    # After the quarantine window, the slot is reusable.
    db.execute(
        text("UPDATE resource_slots SET updated_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": outcome.slot_id},
    )
    db.commit()
    assert reset_quarantined_slots(db) == 1
    db.commit()
    job3 = _mkjob(db, user_id)
    outcome3 = admit_or_queue_job(db, job3, exec_uuid="exec-3")
    db.commit()
    assert outcome3.slot_id == outcome.slot_id, "slot reusable after quarantine"
    finish_job_admission(db, job.id)
    finish_job_admission(db, job3.id)
    db.commit()
    db.close()


def test_lease_expiry_race_heartbeat_vs_reaper(db_factory):
    """A stale generation can never heartbeat a reaped/reassigned slot."""
    from app.db.models import ResourceSlot, SlotState
    from app.services.admission import admit_or_queue_job, finish_job_admission
    from app.services.lease import heartbeat_slot, release_slot

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    outcome = admit_or_queue_job(db, job, exec_uuid="exec-race")
    db.commit()
    assert outcome.slot_id is not None
    generation = outcome.slot_generation

    # Old worker (exec-race, gen=generation) heartbeats after the slot was
    # reaped+reset by a new lease: rejected.
    db.execute(
        text("UPDATE resource_slots SET expires_at = now() - interval '1 second' WHERE id = :id"),
        {"id": outcome.slot_id},
    )
    db.commit()
    from app.services.lease import reap_expired_slots, reset_quarantined_slots

    assert reap_expired_slots(db) == 1
    db.execute(
        text("UPDATE resource_slots SET updated_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": outcome.slot_id},
    )
    db.commit()
    assert reset_quarantined_slots(db) == 1
    db.commit()

    job2 = _mkjob(db, user_id)
    outcome2 = admit_or_queue_job(db, job2, exec_uuid="exec-new")
    db.commit()
    assert outcome2.slot_id == outcome.slot_id
    assert outcome2.slot_generation == generation + 1

    # Stale worker fence: rejected against the new generation.
    assert heartbeat_slot(db, outcome.slot_id, "exec-race", generation) is False
    assert release_slot(db, outcome.slot_id, "exec-race", generation) is False
    # New worker: accepted.
    assert heartbeat_slot(db, outcome.slot_id, "exec-new", outcome2.slot_generation) is True
    assert release_slot(db, outcome.slot_id, "exec-new", outcome2.slot_generation) is True
    db.commit()
    finish_job_admission(db, job.id)
    finish_job_admission(db, job2.id)
    db.commit()
    db.close()


def test_queued_job_recovery_outbox_sweep(db_factory):
    """A queued job's pending outbox row is re-published by the sweep after a
    crash (simulated by committing the admission but never publishing)."""
    from app.db.models import TaskOutbox
    from app.services.admission import admit_or_queue_job, pending_outbox_rows

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    outcome = admit_or_queue_job(db, job, exec_uuid="exec-outbox")
    db.commit()  # committed; dispatch never ran (crash in the gap)

    pending = pending_outbox_rows(db, limit=10)
    assert len(pending) == 1
    row = pending[0]
    assert row.stage == "dispatch"
    assert row.state == "pending"

    # The sweep marks it published (task dispatch itself is mocked here by
    # asserting the outbox contract; real dispatch is covered in CI).
    from app.services.dispatch import publish_outbox
    import app.services.dispatch as dispatch_mod

    original = dispatch_mod._task_for_stage
    published_tasks = []

    def _fake_task_for_stage(stage):
        def fake_delay(job_id):
            published_tasks.append((stage, job_id))

        class _FakeTask:
            @staticmethod
            def delay(job_id):
                fake_delay(job_id)

        return _FakeTask()

    dispatch_mod._task_for_stage = _fake_task_for_stage
    try:
        count = publish_outbox(db, job_id=job.id)
    finally:
        dispatch_mod._task_for_stage = original
    assert count == 1
    assert published_tasks == [("dispatch", job.id)]
    refreshed = db.get(TaskOutbox, row.id)
    assert refreshed.state == "published"
    db.close()
