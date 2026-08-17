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

    Each candidate is admitted under the same counter locks and writes a
    concrete first-stage outbox row. The caller commits. Jobs whose
    preferred sidecar is still unavailable stay queued with the reason.
    """
    from app.services.admission import admit_or_queue_job, pending_outbox_rows

    queued = (
        db.query(JobAdmission)
        .join(ProcessingJob, ProcessingJob.id == JobAdmission.job_id)
        .filter(
            JobAdmission.state == AdmissionState.QUEUED,
            ProcessingJob.status.in_(("pending", "processing")),
        )
        .order_by(JobAdmission.queued_at)
        .limit(limit)
        .all()
    )
    promoted = 0
    for admission in queued:
        job = db.get(ProcessingJob, admission.job_id)
        if job is None:
            continue
        preference = getattr(job, "sidecar_preference", None)
        outcome = admit_or_queue_job(
            db, job, exec_uuid=str(uuid.uuid4()), preferred_sidecar=preference
        )
        if outcome.state == "admitted":
            db.commit()
            promoted += 1
            # Publish the new first-stage row immediately.
            from app.services.dispatch import publish_outbox

            try:
                published = publish_outbox(db, job_id=job.id)
                if published:
                    db.commit()
            except Exception as exc:
                logger.warning("promotion publish failed for job %s: %s", job.id, exc)
                db.rollback()
    return promoted


def run_maintenance_cycle(db: Session) -> dict:
    """Run one full maintenance cycle; returns a summary dict."""
    from app.services.dispatch import sweep_outbox
    from app.services.lease import reap_expired_slots, reset_quarantined_slots
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
    """Background asyncio loop driving maintenance every sweep interval."""
    from app.db.session import SessionLocal

    settings = get_settings().admission
    interval = max(5, settings.sweep_interval_seconds)
    logger.info("scheduler loop started (interval=%ss)", interval)

    while True:
        try:
            db = SessionLocal()
            try:
                summary = run_maintenance_cycle(db)
                if any(v for k, v in summary.items() if isinstance(v, int) and v):
                    logger.info("maintenance cycle: %s", summary)
            finally:
                db.close()
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
