"""Atomic, idempotent persistence primitives for processing job steps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.db.models import JobStep, JobStepStatus, ProcessingJob

CANONICAL_STEP_NAMES = (
    "download",
    "transcribe",
    "snapshots",
    "slides",
    "summarize",
    "export",
)
TERMINAL_STATUSES = frozenset({
    JobStepStatus.COMPLETED,
    JobStepStatus.SKIPPED,
})

# A RUNNING step whose claim is older than this is presumed orphaned (the
# worker died without completing/acking — Review Round 2 F1). Redelivery can
# then reclaim it instead of skipping forever. Must comfortably exceed the
# longest task hard limit (CELERY_TASK_TIME_LIMIT, default 7200s).
ORPHANED_CLAIM_TTL_SECONDS = 7200


def _utcnow() -> datetime:
    """Return a UTC timestamp while retaining the project's naive DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def seed_job_steps(
    db: Session,
    job: ProcessingJob,
    *,
    extract_snapshots: bool = True,
    is_slide_mode: bool = False,
) -> list[JobStep]:
    """Create the six canonical steps in the transaction that creates *job*."""
    initial_statuses = {
        "download": (
            JobStepStatus.PENDING
            if extract_snapshots or is_slide_mode
            else JobStepStatus.SKIPPED
        ),
        "snapshots": JobStepStatus.PENDING if extract_snapshots else JobStepStatus.SKIPPED,
        "slides": JobStepStatus.PENDING if is_slide_mode else JobStepStatus.SKIPPED,
    }
    steps = [
        JobStep(
            job=job,
            name=name,
            status=initial_statuses.get(name, JobStepStatus.PENDING),
            percent=100 if initial_statuses.get(name) == JobStepStatus.SKIPPED else 0,
        )
        for name in CANONICAL_STEP_NAMES
    ]
    db.add_all(steps)
    db.flush()
    return steps


def _step(db: Session, job_id: int, name: str) -> JobStep | None:
    return db.query(JobStep).filter(JobStep.job_id == job_id, JobStep.name == name).first()


def claim_step(db: Session, job_id: int, name: str, claim_token: str) -> JobStep | None:
    """Atomically claim a pending, failed, cancelled, or orphaned step.

    The claim is ONE conditional UPDATE whose WHERE clause carries the full
    eligibility predicate (Review Round 2 N1): the row must be pending/
    failed/cancelled, OR running-and-orphaned (started_at older than
    ``ORPHANED_CLAIM_TTL_SECONDS``). Because the UPDATE is atomic and
    rowcount-checked, two concurrent claimers can never both succeed — the
    loser's WHERE no longer matches after the winner transitions the row.
    """
    from datetime import UTC, datetime as _dt, timedelta as _td

    # Serialize with terminalization (P9-NEW-17): lock the JOB row so a
    # concurrent capacity-exhaustion terminalizer (which locks the same row
    # before failing the job) cannot interleave with our claim. Also refuse
    # to claim a step on a terminal job: a job failed/cancelled concurrently
    # must never receive a fresh claim (the claimer loses the race).
    if db.bind.dialect.name == "postgresql":
        job_row = db.execute(
            text(
                "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
            ),
            {"job_id": job_id},
        ).first()
        if job_row is None or job_row[0] in ("failed", "cancelled"):
            return None

    existing = _step(db, job_id, name)
    if existing is None or existing.status in TERMINAL_STATUSES:
        return None
    if existing.status == JobStepStatus.RUNNING and existing.claim_token == claim_token:
        return existing  # same incarnation re-entry

    orphan_cutoff = _dt.now(UTC).replace(tzinfo=None) - _td(seconds=ORPHANED_CLAIM_TTL_SECONDS)
    statement = (
        update(JobStep)
        .where(
            JobStep.id == existing.id,
            JobStep.status.in_((
                JobStepStatus.PENDING,
                JobStepStatus.FAILED,
                JobStepStatus.CANCELLED,
            )),
        )
        .values(
            status=JobStepStatus.RUNNING,
            attempt=JobStep.attempt + 1,
            claim_token=claim_token,
            started_at=_utcnow(),
            finished_at=None,
            error_message=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    if db.execute(statement).rowcount != 1:
        # Either another claimant won (status now RUNNING under a newer
        # started_at), or the row is RUNNING under a live claim. The only
        # remaining legal path is orphaned reclamation, which is itself a
        # single atomic conditional UPDATE (Review Round 2 N1).
        statement = (
            update(JobStep)
            .where(
                JobStep.id == existing.id,
                JobStep.status == JobStepStatus.RUNNING,
                JobStep.started_at < orphan_cutoff,
            )
            .values(
                status=JobStepStatus.RUNNING,
                attempt=JobStep.attempt + 1,
                claim_token=claim_token,
                started_at=_utcnow(),
                finished_at=None,
                error_message=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        if db.execute(statement).rowcount != 1:
            return None
    db.flush()
    return _step(db, job_id, name)


def set_step_progress(
    db: Session, job_id: int, name: str, claim_token: str, percent: int
) -> bool:
    """Persist progress only when it moves forward under the current claim."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    statement = (
        update(JobStep)
        .where(
            JobStep.job_id == job_id,
            JobStep.name == name,
            JobStep.status == JobStepStatus.RUNNING,
            JobStep.claim_token == claim_token,
            JobStep.percent <= percent,
        )
        .values(percent=percent)
        .execution_options(synchronize_session="fetch")
    )
    changed = db.execute(statement).rowcount == 1
    db.flush()
    return changed


def complete_step(
    db: Session,
    job_id: int,
    name: str,
    claim_token: str,
    metrics: Mapping | None = None,
) -> bool:
    """Finish a running step only for the worker that holds its claim."""
    statement = (
        update(JobStep)
        .where(
            JobStep.job_id == job_id,
            JobStep.name == name,
            JobStep.status == JobStepStatus.RUNNING,
            JobStep.claim_token == claim_token,
        )
        .values(
            status=JobStepStatus.COMPLETED,
            percent=100,
            finished_at=_utcnow(),
            metrics=dict(metrics or {}),
        )
        .execution_options(synchronize_session="fetch")
    )
    changed = db.execute(statement).rowcount == 1
    db.flush()
    return changed


def fail_step(
    db: Session,
    job_id: int,
    name: str,
    claim_token: str,
    error_message: str,
    metrics: Mapping | None = None,
) -> bool:
    """Record a failure only if the reporting worker still owns the step."""
    statement = (
        update(JobStep)
        .where(
            JobStep.job_id == job_id,
            JobStep.name == name,
            JobStep.status == JobStepStatus.RUNNING,
            JobStep.claim_token == claim_token,
        )
        .values(
            status=JobStepStatus.FAILED,
            finished_at=_utcnow(),
            error_message=error_message[:1024],
            metrics=dict(metrics or {}),
        )
        .execution_options(synchronize_session="fetch")
    )
    changed = db.execute(statement).rowcount == 1
    db.flush()
    return changed


def skip_step(db: Session, job_id: int, name: str, reason: str = "") -> bool:
    """Mark a not-yet-running optional step as intentionally skipped."""
    statement = (
        update(JobStep)
        .where(
            JobStep.job_id == job_id,
            JobStep.name == name,
            JobStep.status == JobStepStatus.PENDING,
        )
        .values(
            status=JobStepStatus.SKIPPED,
            percent=100,
            finished_at=_utcnow(),
            error_message=reason[:1024] or None,
        )
        .execution_options(synchronize_session="fetch")
    )
    changed = db.execute(statement).rowcount == 1
    db.flush()
    return changed


def retry_failed_step(db: Session, job_id: int, name: str) -> bool:
    """Make exactly one failed/cancelled step pending again; keep predecessors intact."""
    statement = (
        update(JobStep)
        .where(
            JobStep.job_id == job_id,
            JobStep.name == name,
            JobStep.status.in_((JobStepStatus.FAILED, JobStepStatus.CANCELLED)),
        )
        .values(
            status=JobStepStatus.PENDING,
            percent=0,
            claim_token=None,
            started_at=None,
            finished_at=None,
            error_message=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    changed = db.execute(statement).rowcount == 1
    db.flush()
    return changed
