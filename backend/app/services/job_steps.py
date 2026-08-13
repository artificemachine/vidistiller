"""Atomic, idempotent persistence primitives for processing job steps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from sqlalchemy import update
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
    """Atomically claim a pending, failed, or cancelled step for one worker."""
    existing = _step(db, job_id, name)
    if existing is None or existing.status in TERMINAL_STATUSES:
        return None
    if existing.status == JobStepStatus.RUNNING:
        return existing if existing.claim_token == claim_token else None

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
