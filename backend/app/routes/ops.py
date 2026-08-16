"""Global operations surface (WP4).

Sanitized aggregate view for operators. Every field is allowlisted; source
URLs, transcripts, output paths, tokens and credentials are never included
(Review Round 1 Finding 11). Ordinary users never reach these routes — the
``require_operator`` dependency fails closed with an indistinguishable 404.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.rbac import require_operator
from app.db.models import (
    AdmissionState,
    JobAdmission,
    ProcessingJob,
    ProcessingStatus,
    ResourceSlot,
    SlotState,
    User,
)
from app.db.session import get_db
from app.schemas import OperatorJobRow, SidecarStatusRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["Ops"])

_TERMINAL = (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED, ProcessingStatus.CANCELLED)


def _elapsed_seconds(job: ProcessingJob, now: datetime) -> Optional[float]:
    if job.created_at is None:
        return None
    end = now
    if job.status in _TERMINAL and job.updated_at is not None:
        end = job.updated_at
    return max(0.0, (end - job.created_at).total_seconds())


def _failure_category(job: ProcessingJob) -> Optional[str]:
    if job.status != ProcessingStatus.FAILED:
        return None
    message = (job.error_message or "").lower()
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "unavailable" in message or "no compatible model" in message or "not loaded" in message:
        return "capacity"
    if "invalid" in message or "422" in message:
        return "validation"
    if "transcription failed" in message or "no transcript" in message:
        return "transcription"
    if "download" in message:
        return "download"
    return "other"


def _step_progress(job: ProcessingJob) -> Optional[int]:
    """Overall job progress as a monotonic 0..100 derived from step percents."""
    if not job.steps:
        return None
    if job.status == ProcessingStatus.COMPLETED:
        return 100
    weights = {
        "download": 10,
        "transcribe": 20,
        "snapshots": 15,
        "slides": 30,
        "summarize": 20,
        "export": 5,
    }
    total = sum(weights.get(step.name, 10) for step in job.steps)
    if total == 0:
        return None
    weighted = sum(
        (step.percent or 0) * weights.get(step.name, 10) for step in job.steps
    )
    return max(0, min(100, weighted // total))


@router.get("/jobs", response_model=list[OperatorJobRow])
def list_operator_jobs(
    status_filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> list[OperatorJobRow]:
    """Global job view with owner, admission state, sidecar, progress, ETA.

    Owner identity is exposed to operators only (this route is operator-
    gated). Payload-free by construction: the DTO contains no URLs, no
    transcripts, no file paths.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    query = (
        db.query(ProcessingJob)
        .options(
            joinedload(ProcessingJob.steps),
            joinedload(ProcessingJob.admission),
            joinedload(ProcessingJob.user),
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        try:
            query = query.filter(
                ProcessingJob.status == ProcessingStatus[status_filter.upper()]
            )
        except KeyError:
            raise ValueError(f"invalid status filter: {status_filter}")

    # Sidecar assignment from the active lease.
    leased = {
        slot.job_id: slot
        for slot in db.query(ResourceSlot)
        .filter(ResourceSlot.state == SlotState.LEASED)
        .all()
    }

    rows: list[OperatorJobRow] = []
    for job in query.all():
        slot = leased.get(job.id)
        admission: JobAdmission | None = job.admission
        queue_position: Optional[int] = None
        if admission is not None and admission.state == AdmissionState.QUEUED:
            queue_position = (
                db.query(JobAdmission)
                .filter(
                    JobAdmission.state == AdmissionState.QUEUED,
                    JobAdmission.queued_at < admission.queued_at,
                )
                .count()
                + 1
            )
        rows.append(
            OperatorJobRow(
                job_id=job.job_id,
                owner_id=job.user_id,
                owner_username=job.user.username if job.user else None,
                status=job.status.value,
                error_message=_failure_category(job),
                admission_state=admission.state.value if admission else "unknown",
                queue_reason=admission.queue_reason if admission else None,
                queue_position=queue_position,
                sidecar_id=slot.sidecar_id if slot else None,
                model=slot.sidecar_id if slot else None,
                elapsed_seconds=_elapsed_seconds(job, now),
                progress=_step_progress(job),
                processing_mode=job.processing_mode,
                created_at=job.created_at,
            )
        )
    return rows


@router.get("/sidecars", response_model=list[SidecarStatusRow])
def list_sidecar_status(
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> list[SidecarStatusRow]:
    """Live sidecar inventory for operators (WP3 telemetry, sanitized)."""
    from app.services.sidecar import inventory

    settings = get_settings()
    _ = settings
    telemetry = inventory(db)
    return [
        SidecarStatusRow(
            registered_id=t.registered_id,
            label=t.label,
            healthy=t.healthy,
            served_models=t.served_models,
            declared_model=t.declared_model,
            running_requests=t.running_requests,
            waiting_requests=t.waiting_requests,
            reserved_slots=t.reserved_slots,
            total_slots=t.total_slots,
            vram_used_mib=t.vram_used_mib,
            vram_total_mib=t.vram_total_mib,
            stale=t.stale,
        )
        for t in telemetry
    ]
