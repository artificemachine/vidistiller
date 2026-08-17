"""Periodic scheduler for admission/outbox/lease maintenance (WP2).

Runs inside the API process (one instance per API replica; the counter and
slot locks make concurrent runs safe — promotion is conditional, outbox rows
are claimed atomically). Responsibilities:

1. **Queue promotion** — re-run admission for the oldest queued jobs: when
   capacity has freed, a queued job becomes admitted with a fresh concrete
   first-stage outbox row (Review Round 2 F2).
2. **Outbox sweep** — publish pending outbox rows to Celery (crash recovery).
3. **Lease maintenance** — reap expired leases, reset quarantined slots.
4. **Telemetry refresh** — probe sidecars OUTSIDE any request transaction
   and populate the shared cache (Review Round 2 F7).
5. **Slot reconciliation** — provision missing slot rows for enabled
   sidecars (Review Round 2 F3).

The loop runs every ``ADMISSION_SWEEP_INTERVAL_SECONDS`` (default 30s) as an
asyncio background task started in the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AdmissionState, JobAdmission, ProcessingJob

logger = logging.getLogger(__name__)


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(tzinfo=None)


def promote_queued_jobs(db: Session, limit: int = 10) -> int:
    """Re-run admission for the oldest queued jobs; returns promoted count.

    Race-safe across API replicas (Review Round 2 F2): each candidate row is
    locked with ``FOR UPDATE SKIP LOCKED`` (or serialized by SQLite's writer
    lock) IN THE SAME TRANSACTION as its admission, so two schedulers can
    never promote the same job and no crash gap exists between claiming and
    admitting. Admission runs under the counter locks and writes a concrete
    first-stage outbox row.
    """
    from app.services.admission import admit_or_queue_job

    queued_ids = [
        row[0]
        for row in db.execute(
            text(
                "SELECT ja.job_id FROM job_admissions ja "
                "JOIN processing_jobs pj ON pj.id = ja.job_id "
                "WHERE ja.state = 'queued' AND pj.status IN ('pending', 'processing') "
                "ORDER BY ja.queued_at "
                "LIMIT :limit"
            ),
            {"limit": limit},
        ).all()
    ]
    promoted = 0
    for job_id in queued_ids:
        # Lock THIS queued row; skip rows another scheduler already holds.
        if db.bind.dialect.name == "postgresql":
            locked = db.execute(
                text(
                    "SELECT job_id FROM job_admissions WHERE job_id = :job_id "
                    "AND state = 'queued' FOR UPDATE SKIP LOCKED"
                ),
                {"job_id": job_id},
            ).first()
            if locked is None:
                continue  # promoted by another scheduler or no longer queued
        job = db.get(ProcessingJob, job_id)
        if job is None:
            continue
        preference = getattr(job, "sidecar_preference", None)
        outcome = admit_or_queue_job(
            db, job, exec_uuid=str(uuid.uuid4()), preferred_sidecar=preference
        )
        if outcome.state == "admitted":
            # Commit the admission + outbox row BEFORE publishing so a crash
            # can never leave running Celery work whose promotion rolled
            # back (Review Round 2 N2).
            db.commit()
            promoted += 1
            from app.services.dispatch import publish_outbox

            try:
                publish_outbox(db, job_id=job.id)
                db.commit()
            except Exception as exc:
                logger.warning("promotion publish failed for job %s: %s", job.id, exc)
                db.rollback()
        else:
            # Still queued (e.g. preferred sidecar unavailable): persist the
            # updated queue reason.
            db.commit()
    return promoted


def reap_orphaned_steps(db: Session) -> int:
    """Reset RUNNING steps whose claim is orphaned (worker died) to PENDING
    and enqueue a fresh outbox dispatch for the stage (Review Round 2 F1.2).

    A redelivery that finds a fresh RUNNING claim is correctly fenced out and
    acks; without this sweep nothing would ever retry the orphaned stage.
    Returns the number of steps reaped.
    """
    from datetime import UTC, datetime as _dt, timedelta as _td

    from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus
    from app.services.job_steps import ORPHANED_CLAIM_TTL_SECONDS

    cutoff = _dt.now(UTC).replace(tzinfo=None) - _td(seconds=ORPHANED_CLAIM_TTL_SECONDS)
    orphaned = (
        db.query(JobStep)
        .join(ProcessingJob, ProcessingJob.id == JobStep.job_id)
        .filter(
            JobStep.status == JobStepStatus.RUNNING,
            JobStep.started_at < cutoff,
            ProcessingJob.status == ProcessingStatus.PROCESSING,
        )
        .all()
    )
    reaped = 0
    for step in orphaned:
        db.execute(
            text(
                "UPDATE job_steps SET status = 'pending', claim_token = NULL, "
                "percent = 0, started_at = NULL, finished_at = NULL, error_message = NULL "
                "WHERE id = :id AND status = 'running'"
            ),
            {"id": step.id},
        )
        # Re-dispatch the stage via the durable outbox.
        from app.services.admission import enqueue_first_stage

        enqueue_first_stage(
            db, step.job_id, str(uuid.uuid4()), stage=step.name
        )
        reaped += 1
        logger.warning(
            "orphaned step %s (job %s) reset to pending and re-dispatched",
            step.name, step.job_id,
        )
    if reaped:
        db.commit()
    return reaped


def run_maintenance_cycle(db: Session) -> dict:
    """Run one full maintenance cycle; returns a summary dict."""
    from app.services.dispatch import sweep_outbox
    from app.services.lease import reap_expired_slots, reset_quarantined_slots
    from app.services.scheduler import reap_orphaned_steps  # noqa: F401 (same module)
    from app.services.sidecar import reconcile_slots, refresh_telemetry_cache

    summary = {}

    try:
        reaped = reap_expired_slots(db)
        if reaped:
            db.commit()
        summary["reaped"] = reaped
    except Exception as exc:
        logger.error("lease reap failed: %s", exc)
        db.rollback()

    try:
        orphaned = reap_orphaned_steps(db)
        summary["orphaned_steps"] = orphaned
    except Exception as exc:
        logger.error("orphaned-step reap failed: %s", exc)
        db.rollback()

    try:
        reset = reset_quarantined_slots(db)
        if reset:
            db.commit()
        summary["reset"] = reset
    except Exception as exc:
        logger.error("quarantine reset failed: %s", exc)
        db.rollback()

    try:
        promoted = promote_queued_jobs(db)
        summary["promoted"] = promoted
    except Exception as exc:
        logger.error("queue promotion failed: %s", exc)
        db.rollback()

    try:
        published = sweep_outbox(db)
        summary["published"] = published
    except Exception as exc:
        logger.error("outbox sweep failed: %s", exc)
        db.rollback()

    try:
        created = reconcile_slots(db)
        summary["slots_created"] = created
    except Exception as exc:
        logger.error("slot reconciliation failed: %s", exc)
        db.rollback()

    # Telemetry refresh last: probes outside any long-lived transaction.
    try:
        refresh_telemetry_cache(db)
        summary["telemetry_refreshed"] = True
    except Exception as exc:
        logger.error("telemetry refresh failed: %s", exc)

    return summary


async def scheduler_loop(stop_event: Optional[asyncio.Event] = None) -> None:
    """Background asyncio loop driving maintenance every sweep interval.

    The maintenance cycle itself runs in a worker thread (Review Round 2
    new finding): it does synchronous SQLAlchemy and sidecar HTTP probes,
    which must never block the FastAPI event loop.
    """
    from app.db.session import SessionLocal
    import asyncio as _asyncio

    settings = get_settings().admission
    interval = max(5, settings.sweep_interval_seconds)
    logger.info("scheduler loop started (interval=%ss)", interval)

    loop = _asyncio.get_running_loop()
    while True:
        try:
            await _asyncio.to_thread(_run_cycle)
        except Exception as exc:
            logger.error("scheduler cycle crashed: %s", exc)
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                if stop_event.is_set():
                    logger.info("scheduler loop stopped")
                    return
            else:
                await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            continue


def _run_cycle() -> None:
    """Run one maintenance cycle in a worker thread (blocking-safe)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        summary = run_maintenance_cycle(db)
        if any(v for k, v in summary.items() if isinstance(v, int) and v):
            logger.info("maintenance cycle: %s", summary)
    finally:
        db.close()
