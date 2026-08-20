"""Outbox → Celery dispatch bridge (WP2).

Published after the admission transaction commits. ``publish_outbox`` sends
each pending outbox row's stage to Celery and marks it published; the worker
marks it delivered on successful processing (see tasks). A startup/periodic
sweep re-publishes rows that are still pending after a crash, closing the
commit-then-crash dispatch gap (Review Round 1 Finding 7).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import TaskOutbox
from app.services.admission import mark_outbox_published, pending_outbox_rows

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _task_for_stage(stage: str):
    """Map an outbox stage to its Celery task (P13-NEW-28).

    The canonical job_steps name is ``transcribe`` while the first-stage
    outbox/task name is ``transcript``; both must dispatch to the same
    task so orphan-reaped transcribe steps recover correctly.
    """
    from app.tasks import (
        process_slides,
        process_snapshots,
        process_transcript,
        process_video_download,
        summarize_transcript_task,
    )

    return {
        "transcript": process_transcript,
        "transcribe": process_transcript,  # canonical step name alias (P13-NEW-28)
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
    idempotency absorbs duplicate deliveries). When ``job_id`` is given the
    query filters BEFORE the limit so a specific job's row is always found
    even under backlog (Review Round 2 new finding).

    Crash recovery (Review Round 2 N2/N7): ``publishing`` rows are claimed
    in the same UPDATE that selects them, so a row left ``publishing`` by a
    publisher that crashed mid-flight is picked up by the next sweep — it
    is never stranded.
    """
    query = db.query(TaskOutbox).filter(TaskOutbox.state == "pending")
    if job_id is not None:
        query = query.filter(TaskOutbox.job_id == job_id)
    rows = query.order_by(TaskOutbox.created_at).limit(limit).all()
    if not rows:
        return 0

    published = 0
    for row in rows:
        # Atomic claim: only one publisher (scheduler, create-route, another
        # API replica) may publish a given row (Review Round 2 F2).
        if db.bind.dialect.name == "postgresql":
            claimed = db.execute(
                text(
                    "UPDATE task_outbox SET state = 'publishing', claimed_at = now() "
                    "WHERE id = :id AND state = 'pending' RETURNING id"
                ),
                {"id": row.id},
            )
            if claimed.rowcount != 1:
                db.rollback()
                continue
        else:
            db.execute(
                text(
                    "UPDATE task_outbox SET state = 'publishing', claimed_at = :now "
                    "WHERE id = :id AND state = 'pending'"
                ),
                {"id": row.id, "now": _utcnow()},
            )
            db.flush()

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
            payload = row.payload or {}
            if row.stage == "summarize" and payload.get("force"):
                # Force summarize (route or orphan-reaped): the payload
                # carries the generation minted by the route when present;
                # otherwise mint a fresh one (P12-NEW-26). Fenced against
                # cancellation (P13-NEW-29): if the user cancelled after
                # the outbox row was written, summarize_status is 'failed'
                # and this recovery must NOT restart the work.
                if db.bind.dialect.name == "postgresql":
                    state = db.execute(
                        text(
                            "SELECT summarize_status FROM processing_jobs "
                            "WHERE id = :job_id"
                        ),
                        {"job_id": row.job_id},
                    ).scalar()
                else:
                    from app.db.models import ProcessingJob

                    _j = db.get(ProcessingJob, row.job_id)
                    state = _j.summarize_status if _j else None
                if state != "processing":
                    logger.info(
                        "outbox: skipping summarize dispatch for job %s (summarize_status=%s)",
                        row.job_id, state,
                    )
                    from app.services.admission import mark_outbox_delivered

                    mark_outbox_delivered(db, row.id)
                    db.commit()
                    published += 1
                    continue
                gen = payload.get("force_generation")
                if gen is None:
                    from app.routes.jobs import _mint_force_generation

                    gen = _mint_force_generation(db, row.job_id)
                db.commit()
                task.delay(row.job_id, True, gen)
            elif row.stage == "summarize":
                # P22-NEW-54: non-force summarize deliveries also carry the
                # generation minted at dispatch so their final writes are
                # fenced against any later force.
                gen = payload.get("force_generation")
                if gen is None:
                    from app.routes.jobs import _mint_force_generation

                    gen = _mint_force_generation(db, row.job_id)
                db.commit()
                task.delay(row.job_id, False, gen)
            else:
                task.delay(row.job_id)
        except Exception as exc:
            logger.error("outbox publish failed for row %d: %s", row.id, exc)
            db.rollback()
            # Release the publishing claim so the sweep can retry.
            db.execute(
                text(
                    "UPDATE task_outbox SET state = 'pending' "
                    "WHERE id = :id AND state = 'publishing'"
                ),
                {"id": row.id},
            )
            db.commit()
            continue  # stays pending; the sweep retries
        mark_outbox_published(db, row.id)
        db.commit()
        published += 1
    return published


def sweep_outbox(db: Session) -> int:
    """Re-publish pending rows (crash recovery); returns count published."""
    return publish_outbox(db)
