"""Outbox → Celery dispatch bridge (WP2).

Published after the admission transaction commits. ``publish_outbox`` sends
each pending outbox row's stage to Celery and marks it published; the worker
marks it delivered on successful processing (see tasks). A startup/periodic
sweep re-publishes rows that are still pending after a crash, closing the
commit-then-crash dispatch gap (Review Round 1 Finding 7).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import TaskOutbox
from app.services.admission import mark_outbox_published, pending_outbox_rows

logger = logging.getLogger(__name__)


def _task_for_stage(stage: str):
    """Map an outbox stage to its Celery task."""
    from app.tasks import (
        process_slides,
        process_snapshots,
        process_transcript,
        process_video_download,
        summarize_transcript_task,
    )

    return {
        "transcript": process_transcript,
        "download": process_video_download,
        "snapshots": process_snapshots,
        "slides": process_slides,
        "summarize": summarize_transcript_task,
    }.get(stage)


def publish_outbox(
    db: Session, *, job_id: Optional[int] = None, limit: int = 50
) -> int:
    """Publish pending outbox rows to Celery; returns count published.

    Redis failures are logged and the row stays pending for the sweep —
    never silently dropped. Rows are marked published only after the .delay()
    call succeeds (at-least-once semantics; the workers' claim-step
    idempotency absorbs duplicate deliveries).
    """
    rows = pending_outbox_rows(db, limit=limit)
    if job_id is not None:
        rows = [row for row in rows if row.job_id == job_id]
    if not rows:
        return 0

    published = 0
    for row in rows:
        task = _task_for_stage(row.stage)
        if task is None:
            logger.error(
                "outbox row %d has unknown stage %r; marking delivered to avoid a loop",
                row.id,
                row.stage,
            )
            from app.services.admission import mark_outbox_delivered
            mark_outbox_delivered(db, row.id)
            db.commit()
            continue
        try:
            task.delay(row.job_id)
        except Exception as exc:
            logger.error("outbox publish failed for row %d: %s", row.id, exc)
            continue  # stays pending; the sweep retries
        mark_outbox_published(db, row.id)
        db.commit()
        published += 1
    return published


def sweep_outbox(db: Session) -> int:
    """Re-publish pending rows (crash recovery); returns count published."""
    return publish_outbox(db)
