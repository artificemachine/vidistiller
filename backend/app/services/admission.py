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
    """Return the counter row, creating it race-safely if absent.

    Concurrent admissions can both miss the row and try to insert; the
    INSERT ... ON CONFLICT DO NOTHING / INSERT OR IGNORE swallows the
    loser's insert, after which a fresh SELECT returns the winner's row.
    """
    counter = db.get(AdmissionCounter, key)
    if counter is not None:
        return counter
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text(
                "INSERT INTO admission_counters (key, active, \"limit\", updated_at) "
                "VALUES (:k, 0, :l, now()) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "l": limit},
        )
    else:
        db.execute(
            text(
                "INSERT OR IGNORE INTO admission_counters (key, active, \"limit\") "
                "VALUES (:k, 0, :l)"
            ),
            {"k": key, "l": limit},
        )
    db.flush()
    counter = db.get(AdmissionCounter, key)
    if counter is None:  # pragma: no cover - defensive
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
    commits). Locks counters in deterministic global→user order; checks an
    explicit sidecar preference against live telemetry (fail closed: an
    unavailable preferred sidecar queues the job visibly); writes the
    admission row and a concrete first-stage outbox dispatch. On limits, the
    job is queued with the reason — it is never overcommitted nor failed
    ambiguously. Sidecar slots themselves are leased by the task incarnation
    at the point of external work (Review Round 2 F2/F3).
    """
    settings = get_settings().admission
    exec_uuid = exec_uuid or str(uuid.uuid4())

    # 0. Fail-closed explicit preference check against live telemetry: an
    # unavailable/full/unprobed preferred sidecar queues the job with a
    # visible reason instead of silently running elsewhere (WP3 /
    # Review Round 2 F6). Unknown (never probed) also fails closed: after
    # the startup maintenance refresh, unknown means the sidecar is not
    # confirmed capable — and an explicit preference must never silently
    # fall through to a different lane.
    if preferred_sidecar:
        from app.services.sidecar import get_sidecar_telemetry_status

        status = get_sidecar_telemetry_status(preferred_sidecar)
        if status in ("unhealthy", "stale", "no_capacity", "unknown"):
            _write_admission(
                db,
                job.id,
                AdmissionState.QUEUED,
                f"preferred sidecar {preferred_sidecar} {status}",
            )
            return AdmissionOutcome(
                state="queued",
                queue_reason=f"preferred sidecar {preferred_sidecar} {status}",
            )

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
        # The ORM attributes were loaded before the locks; refresh so the
        # limit checks below see the post-lock (latest committed) values.
        db.refresh(global_counter, ["active", "limit"])
        db.refresh(user_counter, ["active", "limit"])
    else:
        # SQLite serializes writers with a database-wide lock; the counter
        # updates below are the atomic step. (Test suite runs on SQLite.)
        db.flush()

    # 2. Verify limits against the DURABLE counter row values (the row is the
    # authority once created; settings only seed it at creation and the
    # startup sweep reconciles). This keeps tests and operator edits
    # deterministic regardless of when settings were first cached.
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

    # The concrete first-stage outbox row is written here (in the same
    # transaction). Capacity for the LLM stages is leased later by the task
    # incarnation itself (Review Round 2 F2/F3) — admission decides the
    # active-job limits, not the sidecar slot, so a no-slot admit still
    # dispatches and the worker leases at the point of external work.
    enqueue_first_stage(db, job.id, exec_uuid)
    return AdmissionOutcome(
        state="admitted",
        sidecar_id=None,
        slot_id=None,
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


def sync_admission_limits(db: Session) -> None:
    """Reconcile counter row limits from settings (startup sweep).

    The row is the runtime authority; this makes operator config changes
    effective for NEW limits without touching active counts. Called from
    the API startup maintenance sweep. Updates the global row AND every
    existing per-user row so a limit change applies fleet-wide
    (Review Round 2 new finding).
    """
    settings = get_settings().admission
    # Global.
    global_counter = _ensure_counter(db, GLOBAL_COUNTER_KEY, settings.global_active_limit)
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text(
                "UPDATE admission_counters SET \"limit\" = :l, updated_at = now() "
                "WHERE key = :k"
            ),
            {"k": GLOBAL_COUNTER_KEY, "l": settings.global_active_limit},
        )
        # Every existing per-user counter row (user:<id>) gets the configured
        # per-user limit; new users are seeded on first admission.
        db.execute(
            text(
                "UPDATE admission_counters SET \"limit\" = :l, updated_at = now() "
                "WHERE key LIKE 'user:%'"
            ),
            {"l": settings.per_user_active_limit},
        )
    else:
        # SQLite (dev/tests): no now() (Review Round 2 N9).
        db.execute(
            text(
                "UPDATE admission_counters SET \"limit\" = :l "
                "WHERE key = :k"
            ),
            {"k": GLOBAL_COUNTER_KEY, "l": settings.global_active_limit},
        )
        db.execute(
            text(
                "UPDATE admission_counters SET \"limit\" = :l "
                "WHERE key LIKE 'user:%'"
            ),
            {"l": settings.per_user_active_limit},
        )
    db.commit()


def finish_job_admission(db: Session, job_id: int, *, failed: bool = False) -> bool:
    """Mark a job's admission finished/failed and decrement its counters.

    Exactly-once (Review Round 2 F4): the admission row is transitioned with
    a conditional UPDATE (``WHERE state='admitted'``); only the winner of
    that transition decrements the counters, so a duplicate call or a
    concurrent duplicate delivery can never double-release. Returns True
    when this call performed the release.
    """
    from app.db.models import AdmissionCounter

    target = AdmissionState.FAILED if failed else AdmissionState.FINISHED

    # Transition 1: an ADMITTED job -> terminal; it incremented the counters,
    # so the winner of this conditional UPDATE decrements them exactly once.
    if db.bind.dialect.name == "postgresql":
        result = db.execute(
            text(
                "UPDATE job_admissions SET state = :state, finished_at = now(), "
                "updated_at = now() WHERE job_id = :job_id AND state = 'admitted' "
                "RETURNING job_id"
            ),
            {"state": target.value, "job_id": job_id},
        )
    else:
        result = db.execute(
            text(
                "UPDATE job_admissions SET state = :state, finished_at = :now "
                "WHERE job_id = :job_id AND state = 'admitted'"
            ),
            {"state": target.value, "job_id": job_id, "now": _utcnow()},
        )
    if result.rowcount == 1:
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
        _audit(db, "admission_finish", job_id=job_id)
        return True

    # Transition 2: a QUEUED job -> terminal. Queued jobs never incremented
    # the counters, so nothing is decremented (cancellation of a queued job,
    # Review Round 2 N5).
    if db.bind.dialect.name == "postgresql":
        result = db.execute(
            text(
                "UPDATE job_admissions SET state = :state, finished_at = now(), "
                "updated_at = now() WHERE job_id = :job_id AND state = 'queued' "
                "RETURNING job_id"
            ),
            {"state": target.value, "job_id": job_id},
        )
    else:
        result = db.execute(
            text(
                "UPDATE job_admissions SET state = :state, finished_at = :now "
                "WHERE job_id = :job_id AND state = 'queued'"
            ),
            {"state": target.value, "job_id": job_id, "now": _utcnow()},
        )
    if result.rowcount == 1:
        _audit(db, "admission_finish_queued", job_id=job_id)
        return True
    return False


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


def enqueue_first_stage(
    db: Session, job_id: int, exec_uuid: str, stage: str = "transcript",
    payload: Optional[dict] = None,
) -> TaskOutbox:
    """Write the concrete first-stage outbox row (WP2, Review Round 2 F2).

    The outbox holds the actual Celery stage (``transcript``, ``download``,
    …) — never an abstract ``dispatch`` marker — so the publish bridge can
    map it directly to a task. ``payload`` carries stage context (e.g.
    summarize force) that the dispatcher forwards to the task (P12-NEW-26).
    """
    return _enqueue_outbox(db, job_id, stage, exec_uuid, payload=payload)


def mark_outbox_published(db: Session, outbox_id: int) -> None:
    db.execute(
        update(TaskOutbox)
        .where(TaskOutbox.id == outbox_id, TaskOutbox.state.in_(("pending", "publishing")))
        .values(state="published", published_at=_utcnow())
    )


def mark_outbox_delivered(db: Session, outbox_id: int) -> None:
    db.execute(
        update(TaskOutbox)
        .where(TaskOutbox.id == outbox_id, TaskOutbox.state.in_(("pending", "published", "publishing")))
        .values(state="delivered", delivered_at=_utcnow())
    )


def pending_outbox_rows(db: Session, limit: int = 50) -> list[TaskOutbox]:
    """Return pending (and publishing, i.e. claimed-but-unpublished) outbox
    rows oldest-first for the publish sweep."""
    return (
        db.query(TaskOutbox)
        .filter(TaskOutbox.state.in_(("pending", "publishing")))
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
