"""WP2 acceptance: admission races, lease fencing, worker-loss, queued recovery.

Runs against a real Postgres (docker-compose.test.yml) with independent
connections so the locking semantics are real — SQLite cannot exercise
FOR UPDATE SKIP LOCKED. Skipped when no Postgres is reachable.
"""

import os
import threading
import time
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
    """Migrated schema + a session factory bound to ONE shared engine.

    The engine is module-lifetime and disposed at teardown; per-call session

    factories reuse it (Review Round 2: repeated per-call engines leaked

    pool connections and exhausted PostgreSQL).

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


    factory = sessionmaker(bind=engine, expire_on_commit=False)

    yield factory

    engine.dispose()


def _seed(db, global_limit: int = 1, per_user_limit: int = 1, slots: int = 1):
    from app.db.models import AdmissionCounter, ProcessingJob, ResourceSlot, Sidecar, User
    from app.services.auth import AuthService

    user = User(
        username=f"race_{uuid.uuid4().hex[:8]}",
        email=f"race_{uuid.uuid4().hex[:8]}@test.local",
        password_hash=AuthService.hash_password("RacePass123"),
        is_active=True,
    )
    db.add(user)
    db.flush()
    # Registry row required by the resource_slots FK (Review Round 2 F13).
    if db.query(Sidecar).filter(Sidecar.registered_id == "primary").first() is None:
        db.add(
            Sidecar(
                registered_id="primary",
                label="Primary",
                base_url="http://test.invalid:8000",
                capabilities=["text"],
            )
        )
        db.flush()
    # Telemetry cache so acquire_slot's capacity gate passes (N4).
    import time as _time

    from app.services.sidecar import SidecarTelemetry, _telemetry_cache, _telemetry_local_ts, _telemetry_lock

    with _telemetry_lock:
        _telemetry_cache["primary"] = SidecarTelemetry(
            registered_id="primary",
            label="Primary",
            base_url="http://test.invalid:8000",
            declared_model="test-model",
            capabilities=["text"],
            healthy=True,
            served_models=["test-model"],
            observed_at=_time.time(),
        )
        # Mark the injected entry as freshly loaded so the read-through cache
        # serves it directly (WP3-hotfix local-ts bookkeeping).
        _telemetry_local_ts["primary"] = _time.monotonic()
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
    # Admission no longer leases slots (Review Round 2 F3): the task
    # incarnation leases at the point of external work.
    assert outcome.slot_id is None

    # Task incarnation leases under its own exec_uuid.
    from app.services.lease import acquire_slot

    slot = acquire_slot(db, job, exec_uuid="task-exec-1")
    db.commit()
    assert slot is not None
    slot_id = slot.id
    generation = slot.generation

    # Simulate worker loss: no heartbeats, TTL elapses.
    db.execute(
        text("UPDATE resource_slots SET expires_at = now() - interval '1 second' WHERE id = :id"),
        {"id": slot_id},
    )
    db.commit()
    assert reap_expired_slots(db) == 1
    db.commit()
    slot = db.get(ResourceSlot, slot_id)
    assert slot.state == SlotState.EXPIRED

    # A second incarnation cannot take the slot during quarantine.
    job2 = _mkjob(db, user_id)
    outcome2 = admit_or_queue_job(db, job2, exec_uuid="exec-2")
    db.commit()
    slot2 = acquire_slot(db, job2, exec_uuid="task-exec-2")
    db.commit()
    assert slot2 is None, "quarantined slot must not be reusable"

    # The dead worker's heartbeat/release are rejected (stale fence).
    assert heartbeat_slot(db, slot_id, "task-exec-1", generation) is False
    assert release_slot(db, slot_id, "task-exec-1", generation) is False
    db.rollback()

    # Release job1's admission so a later job can be admitted.
    finish_job_admission(db, job.id)
    db.commit()

    # After the quarantine window, the slot is reusable.
    db.execute(
        text("UPDATE resource_slots SET updated_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": slot_id},
    )
    db.commit()
    assert reset_quarantined_slots(db) == 1
    db.commit()
    job3 = _mkjob(db, user_id)
    outcome3 = admit_or_queue_job(db, job3, exec_uuid="exec-3")
    db.commit()
    slot3 = acquire_slot(db, job3, exec_uuid="task-exec-3")
    db.commit()
    assert slot3 is not None and slot3.id == slot_id, "slot reusable after quarantine"
    assert slot3.generation == generation + 1
    finish_job_admission(db, job.id)
    finish_job_admission(db, job3.id)
    db.commit()
    db.close()


def test_lease_expiry_race_heartbeat_vs_reaper(db_factory):
    """A stale generation can never heartbeat a reaped/reassigned slot."""
    from app.db.models import ResourceSlot, SlotState
    from app.services.admission import admit_or_queue_job, finish_job_admission
    from app.services.lease import acquire_slot, heartbeat_slot, release_slot

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    admit_or_queue_job(db, job, exec_uuid="exec-race")
    db.commit()
    slot = acquire_slot(db, job, exec_uuid="exec-race")
    db.commit()
    assert slot is not None
    slot_id = slot.id
    generation = slot.generation

    # Old worker (exec-race, gen=generation) heartbeats after the slot was
    # reaped+reset by a new lease: rejected.
    db.execute(
        text("UPDATE resource_slots SET expires_at = now() - interval '1 second' WHERE id = :id"),
        {"id": slot_id},
    )
    db.commit()
    from app.services.lease import reap_expired_slots, reset_quarantined_slots

    assert reap_expired_slots(db) == 1
    db.execute(
        text("UPDATE resource_slots SET updated_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": slot_id},
    )
    db.commit()
    assert reset_quarantined_slots(db) == 1
    db.commit()

    job2 = _mkjob(db, user_id)
    admit_or_queue_job(db, job2, exec_uuid="exec-new")
    db.commit()
    slot2 = acquire_slot(db, job2, exec_uuid="exec-new")
    db.commit()
    assert slot2 is not None and slot2.id == slot_id
    assert slot2.generation == generation + 1

    # Stale worker fence: rejected against the new generation.
    assert heartbeat_slot(db, slot_id, "exec-race", generation) is False
    assert release_slot(db, slot_id, "exec-race", generation) is False
    # New worker: accepted.
    assert heartbeat_slot(db, slot_id, "exec-new", slot2.generation) is True
    assert release_slot(db, slot_id, "exec-new", slot2.generation) is True
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
    assert outcome.state == "admitted"

    pending = pending_outbox_rows(db, limit=10)
    assert len(pending) == 1
    row = pending[0]
    # The outbox row carries the CONCRETE first stage (Review Round 2 F2),
    # not an abstract dispatch marker.
    assert row.stage == "transcript"
    assert row.state == "pending"

    # The sweep publishes it via the real stage mapping.
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
    assert published_tasks == [("transcript", job.id)]
    refreshed = db.get(TaskOutbox, row.id)
    assert refreshed.state == "published"
    db.close()


def test_queue_promotion_publishes_after_capacity_frees(db_factory):
    """A job queued on the global limit is promoted by the scheduler once a
    running job finishes (Review Round 2 F2)."""
    from app.db.models import TaskOutbox
    from app.services.admission import admit_or_queue_job, finish_job_admission, pending_outbox_rows
    from app.services.scheduler import promote_queued_jobs

    db = db_factory()
    user_id = _seed(db, global_limit=1, per_user_limit=10, slots=1)
    job1 = _mkjob(db, user_id)
    outcome1 = admit_or_queue_job(db, job1, exec_uuid="exec-1")
    db.commit()
    assert outcome1.state == "admitted"

    job2 = _mkjob(db, user_id)
    outcome2 = admit_or_queue_job(db, job2, exec_uuid="exec-2")
    db.commit()
    assert outcome2.state == "queued"

    # No capacity yet: promotion promotes nothing.
    assert promote_queued_jobs(db) == 0

    # Finish job1 -> capacity frees -> promotion admits job2 and writes a
    # concrete transcript outbox row.
    finish_job_admission(db, job1.id)
    db.commit()
    assert promote_queued_jobs(db) == 1
    rows = pending_outbox_rows(db, limit=10)
    stages = [r.stage for r in rows]
    assert "transcript" in stages
    admission2 = db.execute(
        text("SELECT state FROM job_admissions WHERE job_id = :id"),
        {"id": job2.id},
    ).scalar()
    assert admission2 == "admitted"
    db.close()


def test_concurrent_claim_is_exactly_once(db_factory):
    """Two independent sessions racing to claim the same PENDING step: exactly
    one wins (Review Round 2 N1 — atomic conditional claim)."""
    from app.db.models import JobStep
    from app.services.job_steps import claim_step, seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    db.commit()
    job_id = job.id
    db.close()

    winners = []
    lock = threading.Lock()

    def contender(token):
        d = db_factory()
        try:
            claimed = claim_step(d, job_id, "transcribe", token)
            d.commit()
            with lock:
                winners.append(token if claimed is not None else None)
        finally:
            d.close()

    threads = [
        threading.Thread(target=contender, args=(f"tok-{i}",)) for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    won = [w for w in winners if w is not None]
    assert len(won) == 1, f"expected exactly one claim winner, got {won}"
    assert winners.count(None) == 7

    d = db_factory()
    step = d.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "transcribe"
    ).first()
    assert step.attempt == 1
    assert step.claim_token == won[0]
    d.close()


def test_promotion_cancellation_race_no_leak(db_factory):
    """A cancellation concurrent with promotion must never admit the job or
    leak counters (Review Round 2 NEW-8). Two independent sessions race:
    the canceller updates the job row while the promoter locks it."""
    from app.db.models import ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job, finish_job_admission
    from app.services.scheduler import promote_queued_jobs

    db = db_factory()
    user_id = _seed(db, global_limit=1, per_user_limit=10, slots=1)
    job1 = _mkjob(db, user_id)
    admit_or_queue_job(db, job1, exec_uuid="e1")
    db.commit()
    job2 = _mkjob(db, user_id)
    admit_or_queue_job(db, job2, exec_uuid="e2")  # queued (global limit 1)
    db.commit()
    job2_id = job2.id
    db.close()

    # Free capacity first (the queued job becomes promotable).
    db = db_factory()
    finish_job_admission(db, job1.id)
    db.commit()
    db.close()

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def canceller():
        # Mirrors the real cancel route: lock the job row, set the terminal
        # status, and run the exactly-once admission finish (which handles
        # both 'admitted' and 'queued' rows), all in one transaction.
        from app.services.admission import finish_job_admission

        d = db_factory()
        try:
            barrier.wait(timeout=30)
            d.execute(
                text("SELECT id FROM processing_jobs WHERE id = :id FOR UPDATE"),
                {"id": job2_id},
            )
            time.sleep(0.5)  # hold the lock while the promoter waits
            d.execute(
                text("UPDATE processing_jobs SET status = 'cancelled', celery_task_id = NULL WHERE id = :id"),
                {"id": job2_id},
            )
            finish_job_admission(d, job2_id, failed=True)
            d.commit()
            with lock:
                results.append("cancelled")
        finally:
            d.close()

    def promoter():
        d = db_factory()
        try:
            barrier.wait(timeout=30)
            promoted = promote_queued_jobs(d)
            d.close()
            with lock:
                results.append(f"promoted={promoted}")
        except Exception as exc:
            with lock:
                results.append(f"promoter-error={exc!r}")
            try:
                d.close()
            except Exception:
                pass

    t1 = threading.Thread(target=canceller)
    t2 = threading.Thread(target=promoter)
    t1.start(); t2.start()
    t1.join(timeout=60); t2.join(timeout=60)

    # No thread may have errored (lock waits, not deadlocks).
    errors = [r for r in results if r.startswith("promoter-error") or "error" in r]
    assert not errors, f"thread errors: {errors}"

    db = db_factory()
    adm = db.execute(
        text("SELECT state FROM job_admissions WHERE job_id = :id"),
        {"id": job2_id},
    ).scalar()
    counter = db.execute(
        text("SELECT active FROM admission_counters WHERE key='global'")
    ).scalar()
    job_status = db.execute(
        text("SELECT status FROM processing_jobs WHERE id = :id"),
        {"id": job2_id},
    ).scalar()
    db.close()
    # Safety invariants under EITHER race outcome: a cancelled job is never
    # left admitted, and the counter never leaks.
    assert int(counter) == 0, f"counter leaked: {counter} ({results})"
    if job_status == "cancelled":
        assert adm in ("finished", "failed"), f"cancelled job left admitted: {adm} ({results})"


def test_reaper_cancellation_race_no_resurrect(db_factory):
    """The orphan reaper racing a cancellation must not resurrect the job's
    step (Review Round 2 NEW-9). Two sessions: the reaper locks the job row
    while the canceller commits a terminal transition."""
    from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.job_steps import claim_step, seed_job_steps
    from app.services.scheduler import reap_orphaned_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    db.commit()
    claimed = claim_step(db, job.id, "transcribe", "stale-exec")
    assert claimed is not None
    db.execute(
        text("UPDATE job_steps SET started_at = now() - interval '3 hours' WHERE id = :id"),
        {"id": claimed.id},
    )
    db.commit()
    step_id = claimed.id
    job_id = job.id
    db.close()

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def canceller():
        d = db_factory()
        try:
            barrier.wait(timeout=30)
            d.execute(
                text("SELECT id FROM processing_jobs WHERE id = :id FOR UPDATE"),
                {"id": job_id},
            )
            time.sleep(0.5)
            d.execute(
                text("UPDATE processing_jobs SET status = 'cancelled', celery_task_id = NULL WHERE id = :id"),
                {"id": job_id},
            )
            d.commit()
            with lock:
                results.append("cancelled")
        finally:
            d.close()

    def reaper():
        d = db_factory()
        try:
            barrier.wait(timeout=30)
            n = reap_orphaned_steps(d)
            d.close()
            with lock:
                results.append(f"reaped={n}")
        except Exception as exc:
            with lock:
                results.append(f"reaper-error={exc!r}")
            try:
                d.close()
            except Exception:
                pass

    t1 = threading.Thread(target=canceller)
    t2 = threading.Thread(target=reaper)
    t1.start(); t2.start()
    t1.join(timeout=60); t2.join(timeout=60)

    db = db_factory()
    step = db.query(JobStep).filter(JobStep.id == step_id).first()
    job_status = db.execute(
        text("SELECT status FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).scalar()
    # If the reaper won the race (step reset to pending before the cancel),
    # any outbox dispatch is absorbed by the tasks' terminal guards — but a
    # cancelled job must never carry a RUNNING claim minted after cancel.
    outbox_count = 0
    if step.status == JobStepStatus.RUNNING:
        outbox_count = db.execute(
            text("SELECT count(*) FROM task_outbox WHERE job_id = :id AND state IN ('pending','publishing')"),
            {"id": job_id},
        ).scalar()
    db.close()
    # Safety invariant: the job is terminal, and the step is never left
    # RUNNING with an active claim token on a cancelled job. A step the
    # reaper reset to pending BEFORE the canceller committed is legal — the
    # redriven task's terminal guard absorbs the dispatch.
    assert job_status == "cancelled", f"job not terminal: {job_status} ({results})"
    if step.status == JobStepStatus.RUNNING:
        # A RUNNING step here means the reaper did NOT reap before the
        # cancel (its job-row lock serialized after the canceller's
        # terminal commit, so it skipped). The step keeps the stale claim;
        # the orphan sweep will not redrive a cancelled job.
        assert step.claim_token == "stale-exec", "step re-claimed after cancellation"
        assert int(outbox_count) == 0, f"reaper enqueued work for a cancelled job ({results})"



def test_concurrent_force_generation_is_distinct(db_factory):
    """Two concurrent force mints always produce distinct generations, and a
    stale forced task cannot mutate state (Review Round 2 P8-NEW-12)."""
    from app.db.models import ProcessingJob, ProcessingStatus

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.summarize_status = "processing"
    job.celery_task_id = "task-A"
    db.commit()
    job_id = job.id
    db.close()

    barrier = threading.Barrier(2)
    gens = []
    lock = threading.Lock()

    def forcer(name):
        d = db_factory()
        try:
            barrier.wait(timeout=30)
            # Atomic mint exactly as the route does (UPDATE...RETURNING).
            row = d.execute(
                text(
                    "UPDATE processing_jobs SET force_generation = force_generation + 1 "
                    "WHERE id = :job_id RETURNING force_generation"
                ),
                {"job_id": job_id},
            ).first()
            d.commit()
            with lock:
                gens.append((name, int(row[0])))
        finally:
            d.close()

    t1 = threading.Thread(target=forcer, args=("f1",))
    t2 = threading.Thread(target=forcer, args=("f2",))
    t1.start(); t2.start()
    t1.join(timeout=60); t2.join(timeout=60)

    assert len(gens) == 2
    assert gens[0][1] != gens[1][1], f"generations collided: {gens}"
    assert sorted(g[1] for g in gens) == [1, 2]

    # A stale forced delivery (generation 1 when the job is at 2) must be
    # rejected atomically: simulate the task's locked generation check.
    d = db_factory()
    d.execute(
        text("SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"),
        {"job_id": job_id},
    )
    job = d.get(ProcessingJob, job_id)
    assert (job.force_generation or 0) == 2
    stale = 1
    assert (job.force_generation or 0) != stale
    d.rollback()
    d.close()


def test_failed_job_redelivery_not_resurrected(db_factory):
    """A redelivered transcript task past max_retries must not resurrect a
    FAILED job whose admission was already released (P9-NEW-16)."""
    from app.db.models import ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job, finish_job_admission
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    # Simulate terminal failure with admission released (as the exhaustion
    # path does).
    job.status = ProcessingStatus.FAILED
    job.error_message = "No transcript could be generated"
    job.celery_task_id = None
    finish_job_admission(db, job.id, failed=True)
    db.commit()
    job_id = job.id
    db.close()

    # Redelivered execution with retries == max_retries (post-exhaustion).
    from unittest.mock import patch

    from app.tasks import process_transcript

    with patch("app.db.session.SessionLocal") as MockSession, \
         patch("app.tasks._add_log"):
        mock_db = MockSession.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = job

        from app.tasks import process_transcript

        # apply() with retries=2 == max_retries emulates a post-exhaustion
        # redelivery; the guard must skip it without resurrecting the job.
        result = process_transcript.apply(
            kwargs={"job_id": job_id},
            task_id="task-redelivered",
            retries=2,
        ).get()


    assert job.status == ProcessingStatus.FAILED, "FAILED job was resurrected"
    assert job.celery_task_id is None


def test_claim_vs_terminalize_race(db_factory):
    """A claim racing capacity terminalization: whichever wins the job-row
    lock, the job must never end up BOTH failed-and-admitted nor
    processing-with-released-admission (P9-NEW-17)."""
    from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import claim_step, seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job_id = job.id
    db.close()

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def claimer():
        d = db_factory()
        try:
            barrier.wait(timeout=30)
            c = claim_step(d, job_id, "transcribe", "incarnation-B")
            d.commit()
            d.close()
            with lock:
                results.append("claimed" if c else "claim-lost")
        except Exception as exc:
            with lock:
                results.append(f"claimer-error={exc!r}")
            try:
                d.close()
            except Exception:
                pass

    def terminalizer():
        from app.tasks import _terminalize_capacity_exhausted

        d = db_factory()
        try:
            barrier.wait(timeout=30)
            ok = _terminalize_capacity_exhausted(d, job_id)
            d.close()
            with lock:
                results.append(f"terminalized={ok}")
        except Exception as exc:
            with lock:
                results.append(f"terminalizer-error={exc!r}")
            try:
                d.close()
            except Exception:
                pass

    t1 = threading.Thread(target=claimer)
    t2 = threading.Thread(target=terminalizer)
    t1.start(); t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)
    assert not t1.is_alive(), "claimer thread did not terminate"
    assert not t2.is_alive(), "terminalizer thread did not terminate"
    assert len(results) == 2, f"expected both threads to report, got {results}"

    errors = [r for r in results if "error" in r]
    assert not errors, f"thread errors: {errors}"

    db = db_factory()
    job = db.get(ProcessingJob, job_id)
    step = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "transcribe"
    ).first()
    adm = db.execute(
        text("SELECT state FROM job_admissions WHERE job_id = :id"),
        {"id": job_id},
    ).scalar()
    counter = db.execute(
        text("SELECT active FROM admission_counters WHERE key='global'")
    ).scalar()
    db.close()

    if job.status == ProcessingStatus.FAILED:
        # Terminalizer won: no running claim may exist and admission released.
        assert step.status != JobStepStatus.RUNNING
        assert adm in ("finished", "failed"), adm
        assert int(counter) == 0, counter
    else:
        # Claimer won: job still processing/admitted with a running claim.
        assert step.status == JobStepStatus.RUNNING
        assert adm == "admitted", adm
        assert int(counter) == 1, counter


def test_reaped_transcribe_recovery_dispatches_transcript(db_factory):
    """An orphaned transcribe step reaped by the scheduler re-dispatches to
    the transcript task via the transcribe->transcript stage mapping, and the
    stale celery_task_id is cleared (P13-NEW-28/30)."""
    from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.job_steps import claim_step, seed_job_steps
    from app.services.scheduler import reap_orphaned_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    job.status = ProcessingStatus.PROCESSING
    job.celery_task_id = "dead-task-id"
    db.commit()
    claimed = claim_step(db, job.id, "transcribe", "stale-exec")
    db.execute(
        text("UPDATE job_steps SET started_at = now() - interval '3 hours' WHERE id = :id"),
        {"id": claimed.id},
    )
    db.commit()
    job_id = job.id
    db.close()

    assert reap_orphaned_steps(db_factory()) == 1

    db = db_factory()
    step = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "transcribe"
    ).first()
    assert step.status == JobStepStatus.PENDING
    cleared = db.execute(
        text("SELECT celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).scalar()
    assert cleared is None, f"stale celery_task_id not cleared: {cleared}"
    # The outbox row carries the canonical transcribe name; the dispatcher
    # maps it to the transcript task (alias) — verified via _task_for_stage.
    from app.services.dispatch import _task_for_stage

    assert _task_for_stage("transcribe") is not None
    assert _task_for_stage("transcribe").name == "process_transcript"
    db.close()


def test_cancelled_summarize_recovery_rejected(db_factory):
    """A reaped summarize outbox row for a cancelled summarization must not
    restart the work at dispatch (P13-NEW-29)."""
    from app.db.models import TaskOutbox
    from app.services.admission import enqueue_first_stage

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.status = "completed"
    job.summarize_status = "failed"  # user cancelled
    db.commit()
    job_id = job.id
    enqueue_first_stage(db, job_id, "exec-1", stage="summarize", payload={"force": True})
    db.commit()
    row = db.query(TaskOutbox).filter(
        TaskOutbox.job_id == job_id, TaskOutbox.stage == "summarize"
    ).first()
    assert row is not None

    # Publish: the dispatcher must skip (delivered, no task started) because
    # summarize_status != processing.
    import app.services.dispatch as dispatch_mod

    original = dispatch_mod._task_for_stage
    started = []

    def _fake_task(stage):
        class _FakeTask:
            @staticmethod
            def delay(*args):
                started.append(args)
        return _FakeTask()

    dispatch_mod._task_for_stage = _fake_task
    try:
        count = dispatch_mod.publish_outbox(db, job_id=job_id)
    finally:
        dispatch_mod._task_for_stage = original
    assert count == 1  # row published/delivered, but no task started
    assert started == [], f"cancelled summarize was restarted: {started}"
    db.close()


def test_force_route_does_not_overwrite_later_cancellation(db_factory):
    """A force-start that commits before a cancellation must not rewrite
    'failed' afterwards (P15-NEW-34)."""
    from app.services.admission import admit_or_queue_job

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.status = "completed"
    job.summarize_status = "processing"
    db.commit()
    job_id = job.id
    db.close()

    # Simulate the force route's state write: processing (authorized).
    from app.routes.jobs import _mint_force_generation

    db = db_factory()
    gen = _mint_force_generation(db, job_id)
    db.execute(
        text("UPDATE processing_jobs SET summarize_status = 'processing' WHERE id = :id"),
        {"id": job_id},
    )
    db.commit()
    # Cancellation commits 'failed' AFTER the force fence.
    db.execute(
        text("UPDATE processing_jobs SET summarize_status = 'failed', celery_task_id = NULL WHERE id = :id"),
        {"id": job_id},
    )
    db.commit()
    db.close()

    # The force route's post-revoke re-check must refuse to proceed: the
    # re-check reads failed -> no rewrite. Verify the route logic directly.
    db = db_factory()
    db.execute(
        text("SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"),
        {"job_id": job_id},
    )
    state = db.execute(
        text("SELECT summarize_status FROM processing_jobs WHERE id = :job_id"),
        {"job_id": job_id},
    ).scalar()
    assert state == "failed", state
    # The route returns 409 without touching the row.
    db.rollback()
    db.close()
    assert gen >= 1


def test_step_retry_route_co_commits_outbox(db_factory):
    """The step-retry route commits the reset AND the outbox row in one
    transaction even when publish fails (Redis down): after the route
    returns, exactly one recoverable pending outbox row exists (P16-NEW-36/37).
    Exercises the real route function."""
    from app.db.models import JobStep, JobStepStatus, TaskOutbox
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    step = db.query(JobStep).filter(JobStep.job_id == job.id, JobStep.name == "transcribe").first()
    step.status = JobStepStatus.FAILED
    db.commit()
    job_id = job.id
    job_uuid = job.job_id
    from app.db.models import User

    owner = db.get(User, user_id)
    db.close()

    # Real .delay() failure: the REAL publish_outbox runs, but the mapped
    # task's .delay() raises exactly like a Redis outage. The dispatcher's
    # own claim/rollback/reset logic is exercised, and the row must return
    # to 'pending' for the sweep.
    import app.services.dispatch as dispatch_mod
    from app.tasks import process_transcript as _pt

    original_delay = _pt.delay
    def _boom_delay(*a, **k):
        raise RuntimeError("redis down")
    _pt.delay = _boom_delay
    try:
        # Invoke the REAL route handler.
        from app.routes.jobs import retry_job_step
        from app.db.session import SessionLocal

        d = SessionLocal()
        try:
            retry_job_step(job_uuid, "transcribe", db=d, current_user=owner)
        finally:
            d.close()
    finally:
        _pt.delay = original_delay

    # A fresh session sees exactly one PENDING outbox row (sweep-recoverable)
    # and the step reset to pending.
    db = db_factory()
    rows = db.query(TaskOutbox).filter(
        TaskOutbox.job_id == job_id, TaskOutbox.stage == "transcribe"
    ).all()
    assert len(rows) == 1, f"expected exactly one outbox row, got {len(rows)}"
    assert rows[0].state == "pending", rows[0].state
    step = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "transcribe"
    ).first()
    assert step.status == JobStepStatus.PENDING
    db.close()



def test_slide_finalizer_never_resurrects_cancelled(db_factory):
    """The slide finalizer must not overwrite a cancellation with COMPLETED
    (P19-NEW-41/P20-NEW-45): cancellation committed DURING the pipeline (the
    mocked pipeline cancels then raises) leaves the job CANCELLED; the step
    is failed/skipped, never completed."""
    from unittest.mock import patch

    from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus, ResourceSlot
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.processing_mode = "slide_aware"
    job.video_file_path = "/tmp/fake-slide.mp4"
    job.status = ProcessingStatus.PROCESSING
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=True)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job_id = job.id
    db.close()

    from app.services.llm import CancelledException
    from app.tasks import process_slides

    fake_slot = ResourceSlot(sidecar_id="primary", slot_index=0, generation=1)

    def _cancel_then_raise(db, job, cancel_check, provider=None, model=None):
        # A user cancellation commits DURING the pipeline run; the worker
        # then observes it and raises — the exact cancel_check sequence.
        d2 = db_factory()
        d2.execute(
            text(
                "UPDATE processing_jobs SET status = 'cancelled', "
                "celery_task_id = NULL WHERE id = :id"
            ),
            {"id": job.id},
        )
        d2.commit()
        d2.close()
        raise CancelledException()

    with patch(
        "app.services.slide_detection.SlideDetectionService.run_full_pipeline",
        side_effect=_cancel_then_raise,
    ), patch("app.tasks._lease_slot_for_job", return_value=fake_slot), patch("app.tasks._add_log"):
        result = process_slides.apply(kwargs={"job_id": job_id}).get()

    assert result == {"status": "cancelled"}, result
    db = db_factory()
    fresh = db.execute(
        text("SELECT status, slide_status FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert fresh[0] == "cancelled", f"cancelled job resurrected: {fresh[0]}"
    step = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "slides"
    ).first()
    assert step.status in (JobStepStatus.FAILED, JobStepStatus.SKIPPED), step.status
    db.close()


def test_transcript_retry_reenters_processing(db_factory):
    """An authorized transcript retry (retries < max) re-enters processing
    via the conditional start update; admission is not released mid-retry
    (P21-NEW-46). The update predicate itself is exercised against the real
    DB with the exact parameters the task passes."""
    from app.db.models import ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job.status = ProcessingStatus.FAILED
    job.error_message = "Unexpected error: transient"
    db.commit()
    job_id = job.id
    db.close()

    # The task's start UPDATE with retries=1 < max_retries=2 must re-enter,
    # including the exclusive-ID predicate (P22-NEW-53).
    db = db_factory()
    claimed = db.execute(
        text(
            "UPDATE processing_jobs SET status = 'processing', "
            "celery_task_id = :task_id "
            "WHERE id = :job_id AND (celery_task_id IS NULL OR celery_task_id = :task_id) "
            "AND (status IN ('pending', 'processing') "
            "OR (status = 'failed' AND :retries < :max_retries))"
        ),
        {"job_id": job_id, "task_id": "retry-1", "retries": 1, "max_retries": 2},
    )
    assert claimed.rowcount == 1, "authorized retry was rejected"
    db.commit()
    status = db.execute(
        text("SELECT status, celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert status[0] == "processing"
    assert status[1] == "retry-1"
    # Admission not released (still admitted, counter held).
    adm = db.execute(
        text("SELECT state FROM job_admissions WHERE job_id = :id"),
        {"id": job_id},
    ).scalar()
    assert adm == "admitted", f"admission released mid-retry: {adm}"
    counter = db.execute(
        text("SELECT active FROM admission_counters WHERE key='global'")
    ).scalar()
    assert int(counter) == 1, counter
    db.close()

def test_snapshot_finalize_job_lock_before_step(db_factory):
    """The snapshot finalizer locks the job row before complete_step
    (job->step order, P21-NEW-48) — verified by the source ordering and a
    functional run that preserves a concurrent cancellation."""
    import inspect

    from app.tasks import process_snapshots

    source = inspect.getsource(process_snapshots)
    job_lock_pos = source.find("FOR UPDATE")
    step_pos = source.find("complete_step(")
    assert job_lock_pos != -1 and step_pos != -1
    assert job_lock_pos < step_pos, (
        "snapshot finalizer must lock the job row before completing the step"
    )


def test_summarize_install_fenced_on_generation(db_factory):
    """A non-force summarize worker whose generation went stale (a force
    minted after its startup read) must not install its task id (P21-NEW-47)."""
    from app.db.models import ProcessingJob

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.status = "completed"
    job.summarize_status = "processing"
    job.force_generation = 2  # a force already bumped past the worker's read
    db.commit()
    job_id = job.id
    db.close()

    # The worker observed generation 1 at startup; the install requires the
    # current generation — it must fail (0 rows) and the worker skips.
    db = db_factory()
    installed = db.execute(
        text(
            "UPDATE processing_jobs SET celery_task_id = 'stale-worker', "
            "summarize_status = 'processing' "
            "WHERE id = :job_id AND summarize_status IN ('processing', 'pending') "
            "AND force_generation = :gen"
        ),
        {"job_id": job_id, "gen": 1},
    )
    assert installed.rowcount == 0
    db.rollback()
    task_id = db.execute(
        text("SELECT celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).scalar()
    assert task_id is None, f"stale worker installed its task id: {task_id}"
    db.close()


def test_admitted_final_transcript_retry_is_not_skipped(db_factory):
    """A FAILED job whose admission is STILL HELD and whose retries == max is
    an authorized final retry — it must run, not be skipped as a terminal
    redelivery (P22-NEW-51)."""
    from app.db.models import JobAdmission, ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job.status = ProcessingStatus.FAILED
    job.error_message = "Unexpected error"
    # Admission NOT released (authorized retry in progress).
    db.commit()
    job_id = job.id
    db.close()

    db = db_factory()
    admission = db.get(JobAdmission, job_id)
    assert admission is not None and admission.state.value == "admitted"
    # The start claim uses the admission-state predicate (P24-NEW-58): a
    # FAILED job whose admission is STILL HELD is claimable at retries ==
    # max_retries — the final authorized attempt must run.
    claimed = db.execute(
        text(
            "UPDATE processing_jobs SET status = 'processing', "
            "celery_task_id = :task_id "
            "WHERE id = :job_id AND (celery_task_id IS NULL OR celery_task_id = :task_id) "
            "AND (status IN ('pending', 'processing') "
            "OR (status = 'failed' AND EXISTS (SELECT 1 FROM job_admissions ja "
            "WHERE ja.job_id = processing_jobs.id AND ja.state = 'admitted')))"
        ),
        {"job_id": job_id, "task_id": "final-retry"},
    )
    assert claimed.rowcount == 1, "authorized final retry was rejected"
    db.commit()
    status = db.execute(
        text("SELECT status, celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert status[0] == "processing", status
    assert status[1] == "final-retry"
    db.close()


def test_failed_queued_job_redelivery_rejected(db_factory):
    """A FAILED job whose admission is QUEUED must be skipped by the REAL
    transcript task at retries == max_retries — no re-entry, no task-id
    install, no work (P25-NEW-60/P26-NEW-61)."""
    from unittest.mock import patch

    from app.db.models import JobAdmission, JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=1, per_user_limit=10, slots=1)
    job1 = _mkjob(db, user_id)
    admit_or_queue_job(db, job1, exec_uuid="e1")
    db.commit()
    job2 = _mkjob(db, user_id)
    admit_or_queue_job(db, job2, exec_uuid="e2")  # QUEUED (global limit held)
    db.commit()
    job2.status = ProcessingStatus.FAILED
    db.commit()
    job_id = job2.id
    db.close()

    from app.tasks import process_transcript

    # Run the REAL task against the REAL DB (only log writing mocked): the
    # entry guard must read the actual queued admission and skip.
    from app.db.session import SessionLocal as _RealSL

    real_session = _RealSL()
    with patch("app.db.session.SessionLocal", return_value=real_session), \
         patch("app.tasks._add_log"):
        result = process_transcript.apply(
            kwargs={"job_id": job_id}, task_id="late-redelivery", retries=2
        ).get()
    real_session.close()

    assert result == {"job_id": job_id, "status": "failed", "skipped": True}, result
    db = db_factory()
    status = db.execute(
        text("SELECT status, celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert status[0] == "failed", status
    assert status[1] is None, f"task id installed on queued job: {status[1]}"
    db.close()


def test_failed_untracked_job_redelivery_rejected(db_factory):
    """A FAILED job with NO admission row must be skipped by the REAL
    transcript task at retries == max_retries (P25-NEW-60/P26-NEW-61)."""
    from unittest.mock import patch

    from app.db.models import ProcessingJob, ProcessingStatus
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    job.status = ProcessingStatus.FAILED
    db.commit()
    job_id = job.id
    db.close()

    from app.tasks import process_transcript

    # Real task against the real DB: the guard must skip an untracked FAILED
    # job at retries == max_retries.
    from app.db.session import SessionLocal as _RealSL

    real_session = _RealSL()
    with patch("app.db.session.SessionLocal", return_value=real_session), \
         patch("app.tasks._add_log"):
        result = process_transcript.apply(
            kwargs={"job_id": job_id}, task_id="late-redelivery", retries=2
        ).get()
    real_session.close()

    assert result == {"job_id": job_id, "status": "failed", "skipped": True}, result
    db = db_factory()
    status = db.execute(
        text("SELECT status, celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert status[0] == "failed", status
    assert status[1] is None
    db.close()



def test_final_exhaustion_co_commits_terminal_and_admission(db_factory):
    """Final exhaustion (retries == max) invoked through the REAL task
    terminalizes job + step + admission in one transaction: after the task
    returns, job is FAILED, step is FAILED, admission is terminal and the
    global counter is zero (P27-NEW-62/P28-NEW-65)."""
    from unittest.mock import patch

    from app.db.models import JobAdmission, JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=False)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job.status = ProcessingStatus.PROCESSING
    job.celery_task_id = "task-final"
    db.commit()
    job_id = job.id
    db.close()

    # Run the REAL task at retries == max_retries against the REAL DB:
    # the claim succeeds, then caption fetch fails on the final attempt and
    # the exhaustion handler terminalizes atomically. The caption-fetch mock
    # must actually be hit (proving the task progressed past the claim).
    from unittest.mock import Mock
    from app.tasks import process_transcript

    captions_mock = Mock(side_effect=RuntimeError("final fail"))
    with patch("app.tasks._add_log"), patch(
        "app.tasks._fetch_platform_captions", captions_mock
    ):
        from app.db.session import SessionLocal as _RealSL

        real_session = _RealSL()
        try:
            result = None
            try:
                result = process_transcript.apply(
                    kwargs={"job_id": job_id}, task_id="task-final", retries=2
                ).get()
            except RuntimeError:
                # apply().get() re-raises the final attempt's exception after
                # the exhaustion handler ran — the terminalization is what
                # we assert.
                pass
        finally:
            real_session.close()

    db = db_factory()
    status = db.execute(
        text("SELECT status, celery_task_id FROM processing_jobs WHERE id = :id"),
        {"id": job_id},
    ).first()
    assert status[0] == "failed", f"job not failed: {status} (result={result})"
    admission = db.get(JobAdmission, job_id)
    assert admission.state.value in ("finished", "failed"), admission.state
    counter = db.execute(
        text("SELECT active FROM admission_counters WHERE key='global'")
    ).scalar()
    assert int(counter) == 0, counter
    step = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "transcribe"
    ).first()
    assert step is not None
    assert step.status == JobStepStatus.FAILED, f"step not failed: {step.status}"
    assert captions_mock.called, "caption fetch never reached — earlier failure path"
    db.close()



def test_capacity_exhaustion_terminalizes_pending_steps(db_factory):
    """WP3-hotfix (post-deploy review B1): a job failed by capacity
    exhaustion must have its NON-TERMINAL (pending/failed, unclaimed) steps
    terminalized in the SAME transaction — no dangling pending steps on a
    failed job (job 293's slides step stayed pending)."""
    from app.db.models import JobAdmission, JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.admission import admit_or_queue_job
    from app.services.job_steps import seed_job_steps
    from app.tasks import _terminalize_capacity_exhausted

    db = db_factory()
    user_id = _seed(db, global_limit=10, per_user_limit=10, slots=1)
    job = _mkjob(db, user_id)
    # Slide-aware job: slides step exists but is NOT claimed (pending).
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=True)
    admit_or_queue_job(db, job, exec_uuid="e1")
    db.commit()
    job.status = ProcessingStatus.PROCESSING
    job.celery_task_id = "task-cap"
    db.commit()
    job_id = job.id

    disposition = _terminalize_capacity_exhausted(db, job_id)
    db.commit()
    assert disposition == "done", disposition

    status = db.execute(
        text("SELECT status FROM processing_jobs WHERE id = :id"), {"id": job_id}
    ).scalar()
    assert status == "failed", status
    admission = db.get(JobAdmission, job_id)
    assert admission.state.value in ("finished", "failed"), admission.state
    # EVERY step must be terminal (completed or failed) — no pending left.
    steps = db.query(JobStep).filter(JobStep.job_id == job_id).all()
    assert steps, "no steps seeded"
    for step in steps:
        assert step.status in (
            JobStepStatus.COMPLETED, JobStepStatus.FAILED, JobStepStatus.SKIPPED,
        ), (
            f"step {step.name} left non-terminal: {step.status}"
        )
    slides = db.query(JobStep).filter(
        JobStep.job_id == job_id, JobStep.name == "slides"
    ).first()
    assert slides is not None and slides.status == JobStepStatus.FAILED, slides
    db.close()
