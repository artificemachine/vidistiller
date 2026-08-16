"""Durable admission control, sidecar slot leases, and dispatch outbox (WP2).

The scheduler authority is PostgreSQL, never Redis (Review Round 1 Findings
6-7). Everything that decides *who may run* lives in one transaction with
deterministic lock ordering:

1. lock ``admission_counters`` rows (``global`` then ``user:<id>``) FOR UPDATE
2. verify per-user and global active-job limits
3. if limits allow: admit the job, acquire a compatible sidecar slot
   (``FOR UPDATE SKIP LOCKED``), increment its generation, write the
   ``job_admissions`` row, append a ``task_outbox`` pending record, audit
   the lease event
4. if a limit is hit: write ``job_admissions(state=queued, queue_reason)``

Only after commit does the caller publish the outbox row to Redis. A sweep
re-publishes stale pending rows after a crash, closing the commit-then-crash
dispatch gap.

Fencing contract (Review Round 1 Finding 5): every lease carries a
per-incarnation ``exec_uuid`` (never the Celery task id, which is preserved
across redelivery) and a monotonic ``generation``. Heartbeats, releases and
completions are conditional updates keyed on both. Reclamation never moves a
slot straight from ``leased`` to ``free``: it passes through ``expired`` and
a quarantine window before a slot may be reused.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    AdmissionCounter,
    AdmissionState,
    JobAdmission,
    LeaseEvent,
    ProcessingJob,
    ResourceSlot,
    SlotState,
    TaskOutbox,
)

logger = logging.getLogger(__name__)

GLOBAL_COUNTER_KEY = "global"
ADMISSION_POLICY_VERSION = 1


class AdmissionDenied(Exception):
    """Raised when a job cannot be admitted and cannot be queued either."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def user_counter_key(user_id: int) -> str:
    return f"user:{user_id}"


def _audit(
    db: Session,
    event: str,
    *,
    slot_id: Optional[int] = None,
    job_id: Optional[int] = None,
    sidecar_id: Optional[str] = None,
    exec_uuid: Optional[str] = None,
    generation: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    db.add(
        LeaseEvent(
            slot_id=slot_id,
            job_id=job_id,
            sidecar_id=sidecar_id,
            event=event,
            exec_uuid=exec_uuid,
            generation=generation,
            detail=detail,
        )
    )


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

@dataclass
class AdmissionOutcome:
    state: str  # "admitted" | "queued" | "failed"
    queue_reason: Optional[str] = None
    sidecar_id: Optional[str] = None
    slot_id: Optional[int] = None
    slot_generation: Optional[int] = None


def _ensure_counter(db: Session, key: str, limit: int) -> AdmissionCounter:
    counter = db.get(AdmissionCounter, key)
    if counter is None:
        counter = AdmissionCounter(key=key, active=0, limit=limit)
        db.add(counter)
        db.flush()
    return counter


def admit_or_queue_job(
    db: Session,
    job: ProcessingJob,
    *,
    exec_uuid: Optional[str] = None,
    preferred_sidecar: Optional[str] = None,
) -> AdmissionOutcome:
    """Atomically admit a job or queue it with a visible reason.

    Must be called inside a caller-managed transaction (the route or task
    commits). Locks counters in deterministic global→user order; acquires a
    sidecar slot when the job is admitted; writes the admission row and a
    pending outbox dispatch. On limits, the job is queued with the reason —
    it is never overcommitted nor failed ambiguously.
    """
    from app.services.lease import acquire_slot

    settings = get_settings().admission
    exec_uuid = exec_uuid or str(uuid.uuid4())

    # 1. Lock counters in deterministic order (global first, then user).
    global_counter = _ensure_counter(db, GLOBAL_COUNTER_KEY, settings.global_active_limit)
    user_counter = _ensure_counter(db, user_counter_key(job.user_id or 0), settings.per_user_active_limit)
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT 1 FROM admission_counters WHERE key = :k FOR UPDATE"),
            {"k": GLOBAL_COUNTER_KEY},
        )
        db.execute(
            text("SELECT 1 FROM admission_counters WHERE key = :k FOR UPDATE"),
            {"k": user_counter.key},
        )
    else:
        # SQLite serializes writers with a database-wide lock; the counter
        # updates below are the atomic step. (Test suite runs on SQLite.)
        db.flush()

    # 2. Verify limits.
    if global_counter.limit > 0 and global_counter.active >= global_counter.limit:
        _write_admission(db, job.id, AdmissionState.QUEUED, "global active-job limit reached")
        return AdmissionOutcome(
            state="queued", queue_reason="global active-job limit reached"
        )
    if user_counter.limit > 0 and user_counter.active >= user_counter.limit:
        _write_admission(db, job.id, AdmissionState.QUEUED, "per-user active-job limit reached")
        return AdmissionOutcome(
            state="queued", queue_reason="per-user active-job limit reached"
        )

    # 3. Admit: bump counters, acquire a slot for the chosen sidecar.
    global_counter.active += 1
    user_counter.active += 1
    _write_admission(db, job.id, AdmissionState.ADMITTED)

    slot = acquire_slot(
        db, job, exec_uuid=exec_uuid, preferred_sidecar=preferred_sidecar
    )
    if slot is None:
        # No sidecar capacity yet — still admitted (counters held) but the
        # dispatch will wait on the slot sweep. This is the bounded case:
        # the job is visibly admitted and waits on capacity, never queued
        # behind the counter limits while holding a slot.
        _enqueue_outbox(db, job.id, "dispatch", exec_uuid)
        return AdmissionOutcome(
            state="admitted",
            sidecar_id=None,
            slot_id=None,
        )

    _enqueue_outbox(db, job.id, "dispatch", exec_uuid)
    return AdmissionOutcome(
        state="admitted",
        sidecar_id=slot.sidecar_id,
        slot_id=slot.id,
        slot_generation=slot.generation,
    )


def _write_admission(
    db: Session,
    job_id: int,
    state: AdmissionState,
    reason: Optional[str] = None,
) -> None:
    now = _utcnow()
    admission = db.get(JobAdmission, job_id)
    if admission is None:
        admission = JobAdmission(
            job_id=job_id,
            state=state,
            queue_reason=reason,
            policy_version=ADMISSION_POLICY_VERSION,
            queued_at=now if state == AdmissionState.QUEUED else None,
            admitted_at=now if state == AdmissionState.ADMITTED else None,
        )
        db.add(admission)
    else:
        admission.state = state
        admission.queue_reason = reason
        if state == AdmissionState.QUEUED and admission.queued_at is None:
            admission.queued_at = now
        if state == AdmissionState.ADMITTED:
            admission.admitted_at = now
            admission.queued_at = None
        if state in (AdmissionState.FINISHED, AdmissionState.FAILED):
            admission.finished_at = now


def finish_job_admission(db: Session, job_id: int, *, failed: bool = False) -> None:
    """Mark a job's admission finished/failed and decrement its counters.

    Called exactly once per job from the terminal task path. Counter
    decrements are guarded by the admission state so a duplicate call cannot
    double-release (Review Round 1 Finding 5).
    """
    admission = db.get(JobAdmission, job_id)
    if admission is None:
        return
    if admission.state in (AdmissionState.FINISHED, AdmissionState.FAILED):
        return  # already released
    job = db.get(ProcessingJob, job_id)
    user_id = job.user_id if job else 0

    for key in (GLOBAL_COUNTER_KEY, user_counter_key(user_id)):
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    "UPDATE admission_counters SET active = active - 1, updated_at = now() "
                    "WHERE key = :k AND active > 0"
                ),
                {"k": key},
            )
        else:
            db.execute(
                text(
                    "UPDATE admission_counters SET active = active - 1 "
                    "WHERE key = :k AND active > 0"
                ),
                {"k": key},
            )

    _write_admission(
        db,
        job_id,
        AdmissionState.FAILED if failed else AdmissionState.FINISHED,
    )
    _audit(db, "admission_finish", job_id=job_id)


def _enqueue_outbox(
    db: Session,
    job_id: int,
    stage: str,
    exec_uuid: str,
    payload: Optional[dict] = None,
) -> TaskOutbox:
    row = TaskOutbox(
        job_id=job_id,
        stage=stage,
        generation=0,
        state="pending",
        payload=payload or {"exec_uuid": exec_uuid},
    )
    db.add(row)
    db.flush()
    return row


def mark_outbox_published(db: Session, outbox_id: int) -> None:
    db.execute(
        update(TaskOutbox)
        .where(TaskOutbox.id == outbox_id, TaskOutbox.state == "pending")
        .values(state="published", published_at=_utcnow())
    )


def mark_outbox_delivered(db: Session, outbox_id: int) -> None:
    db.execute(
        update(TaskOutbox)
        .where(TaskOutbox.id == outbox_id, TaskOutbox.state == "published")
        .values(state="delivered", delivered_at=_utcnow())
    )


def pending_outbox_rows(db: Session, limit: int = 50) -> list[TaskOutbox]:
    """Return pending outbox rows oldest-first for the publish sweep."""
    return (
        db.query(TaskOutbox)
        .filter(TaskOutbox.state == "pending")
        .order_by(TaskOutbox.created_at)
        .limit(limit)
        .all()
    )


def queue_position(db: Session, job_id: int) -> Optional[int]:
    """Honest 1-based position among queued jobs, or None when not queued."""
    admission = db.get(JobAdmission, job_id)
    if admission is None or admission.state != AdmissionState.QUEUED:
        return None
    earlier = (
        db.query(JobAdmission)
        .filter(
            JobAdmission.state == AdmissionState.QUEUED,
            JobAdmission.queued_at < admission.queued_at,
        )
        .count()
    )
    return earlier + 1
