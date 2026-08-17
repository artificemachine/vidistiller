"""Sidecar slot leases with fencing tokens (WP2).

Lease lifecycle per Review Round 1 Finding 5:

- ``acquire_slot`` — atomic ``FOR UPDATE SKIP LOCKED`` on a free slot of the
  chosen sidecar; bumps ``generation`` to the new lease generation; writes
  the audit event. Only called inside the admission transaction.
- ``heartbeat_slot`` — conditional update on ``(state=leased, exec_uuid,
  generation)``; refreshes ``expires_at`` from database time.
- ``release_slot`` — conditional update on the same triple; moves the slot
  to ``free`` with a fresh generation and decrements nothing (counters are
  the admission service's job).
- ``reap_expired_slots`` — leases past ``expires_at`` move to ``expired``;
  they are NOT reused until the quarantine window has also passed. A slot
  is only reset to ``free`` by ``reset_quarantined_slot`` after
  ``quarantine_seconds``, guaranteeing a stale in-flight external request
  cannot be silently overcommitted.

The Celery task id is never used as a fencing token: it is preserved across
redelivery, so a redelivered message would otherwise re-validate a stale
execution. Callers mint a fresh ``exec_uuid`` per worker incarnation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ProcessingJob, ResourceSlot, SlotState

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _db_now(db: Session) -> datetime:
    """Database-time now, authoritative for TTL decisions."""
    try:
        row = db.execute(text("SELECT now()")).scalar()
        return row.replace(tzinfo=None) if row else _utcnow()
    except Exception:
        # SQLite (test suite) has no now(); local UTC is the fallback.
        return _utcnow()


def _audit(db: Session, slot, event: str, detail: Optional[str] = None) -> None:
    from app.db.models import LeaseEvent

    db.add(
        LeaseEvent(
            slot_id=slot.id if slot is not None else None,
            job_id=slot.job_id if slot is not None else None,
            sidecar_id=slot.sidecar_id if slot is not None else None,
            event=event,
            exec_uuid=slot.claim_exec_uuid if slot is not None else None,
            generation=slot.generation if slot is not None else None,
            detail=detail,
        )
    )


def acquire_slot(
    db: Session,
    job: ProcessingJob,
    *,
    exec_uuid: str,
    preferred_sidecar: Optional[str] = None,
) -> Optional[ResourceSlot]:
    """Acquire one free slot for a job inside the admission transaction.

    Capacity truth (Review Round 2 N4): only slots of ENABLED sidecars whose
    cached telemetry is healthy, fresh (non-stale), and serving at least one
    model are eligible. A preferred sidecar that is unavailable returns
    None (the caller queues visibly) rather than falling through to another
    lane. Returns the acquired slot or None when no compatible slot is free.
    """
    settings = get_settings().admission
    from app.services.sidecar import (
        cached_sidecar_telemetry,
        get_sidecar,
        prefetch_sidecar_telemetry,
    )

    # WP3-hotfix: warm this process's local cache from the shared Redis
    # store BEFORE taking any row lock, so the eligibility loop below never
    # performs network I/O while holding DB row locks (Review Round 2 F7
    # invariant). In the Celery worker this is what makes telemetry visible
    # at all — the API scheduler published it; the worker reads it through.
    prefetch_sidecar_telemetry(db)

    def _eligible(sidecar_id: str) -> bool:
        sidecar = get_sidecar(db, sidecar_id)
        if sidecar is None or not sidecar.enabled:
            return False
        telemetry = cached_sidecar_telemetry(sidecar_id)
        if telemetry is None:
            return False  # never probed -> fail closed for new allocations
        if not telemetry.healthy or telemetry.stale:
            return False
        if not telemetry.served_models:
            return False  # no live model -> no capacity
        return True

    candidates = (
        db.query(ResourceSlot)
        .filter(
            ResourceSlot.enabled.is_(True),
            ResourceSlot.state == SlotState.FREE,
        )
        .order_by(ResourceSlot.sidecar_id, ResourceSlot.slot_index)
    )
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)

    for slot in candidates.all():
        if preferred_sidecar and slot.sidecar_id != preferred_sidecar:
            continue
        if not _eligible(slot.sidecar_id):
            continue
        slot.state = SlotState.LEASED
        slot.job_id = job.id
        slot.claim_exec_uuid = exec_uuid
        slot.generation += 1
        slot.heartbeat_at = _db_now(db)
        slot.expires_at = slot.heartbeat_at + timedelta(seconds=settings.lease_ttl_seconds)
        db.flush()
        _audit(db, slot, "acquire", f"ttl={settings.lease_ttl_seconds}s")
        return slot
    return None


def heartbeat_slot(
    db: Session, slot_id: int, exec_uuid: str, generation: int
) -> bool:
    """Refresh a lease's expiry under the fencing triple (conditional update).

    Returns False when the caller no longer owns the lease (expired,
    reassigned, or a stale generation) — the caller must stop work.
    """
    settings = get_settings().admission
    now = _db_now(db)
    expires = now + timedelta(seconds=settings.lease_ttl_seconds)
    result = db.execute(
        update(ResourceSlot)
        .where(
            ResourceSlot.id == slot_id,
            ResourceSlot.state == SlotState.LEASED,
            ResourceSlot.claim_exec_uuid == exec_uuid,
            ResourceSlot.generation == generation,
        )
        .values(heartbeat_at=now, expires_at=expires)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


def release_slot(
    db: Session, slot_id: int, exec_uuid: str, generation: int
) -> bool:
    """Release a lease back to free under the fencing triple.

    Called on success, failure, and cancellation. Returns False when the
    caller does not own the lease.
    """
    result = db.execute(
        update(ResourceSlot)
        .where(
            ResourceSlot.id == slot_id,
            ResourceSlot.state == SlotState.LEASED,
            ResourceSlot.claim_exec_uuid == exec_uuid,
            ResourceSlot.generation == generation,
        )
        .values(
            state=SlotState.FREE,
            job_id=None,
            claim_exec_uuid=None,
            heartbeat_at=None,
            expires_at=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        slot = db.get(ResourceSlot, slot_id)
        if slot is not None:
            _audit(db, slot, "release")
        return True
    return False


def reap_expired_slots(db: Session) -> int:
    """Move leases past TTL to ``expired``. Never reused here."""
    now = _db_now(db)
    result = db.execute(
        update(ResourceSlot)
        .where(
            ResourceSlot.state == SlotState.LEASED,
            ResourceSlot.expires_at < now,
        )
        .values(state=SlotState.EXPIRED, heartbeat_at=None)
        .execution_options(synchronize_session="fetch")
    )
    count = result.rowcount
    if count:
        logger.warning("reaped %d expired sidecar lease(s)", count)
        # Audit each reaped slot.
        for slot in (
            db.query(ResourceSlot)
            .filter(ResourceSlot.state == SlotState.EXPIRED)
            .all()
        ):
            _audit(db, slot, "reap", "ttl exceeded")
    return count


def reset_quarantined_slots(db: Session) -> int:
    """Reset expired slots to free after the quarantine window.

    A slot is only reusable once both the TTL expiry AND the quarantine
    window have passed, so a stale in-flight external request cannot be
    silently overcommitted (Review Round 1 Finding 5).
    """
    settings = get_settings().admission
    cutoff = _db_now(db) - timedelta(seconds=settings.quarantine_seconds)
    result = db.execute(
        update(ResourceSlot)
        .where(
            ResourceSlot.state == SlotState.EXPIRED,
            ResourceSlot.updated_at < cutoff,
        )
        .values(
            state=SlotState.FREE,
            job_id=None,
            claim_exec_uuid=None,
            expires_at=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    count = result.rowcount
    if count:
        logger.info("reset %d quarantined sidecar slot(s) to free", count)
    return count
