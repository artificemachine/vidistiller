"""Job response enrichment: admission state, progress, ETA (WP2/WP5).

Single code path so the owner job views and the operator view agree on what
a job reports. ``enrich_job_payload`` mutates a dict (e.g. a
``JobStatusResponse.model_dump()``) with the admission/progress/ETA fields;
it never fabricates values — cold ETA and missing admission rows degrade to
None, and progress is only reported when steps exist.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import AdmissionState, JobAdmission, ProcessingJob
from app.services.eta import estimate_eta, overall_progress


def enrich_job_payload(
    db: Session,
    job: ProcessingJob,
    payload: dict,
    *,
    include_eta: bool = True,
) -> dict:
    """Add admission_state/queue_*/progress/eta_* fields to a job dict.

    ``payload`` may be a plain dict or a pydantic model with matching
    fields (set via attribute when present); the dict form is returned.
    """
    admission = db.get(JobAdmission, job.id) if job.id else None

    def _set(name: str, value) -> None:
        if isinstance(payload, dict):
            payload[name] = value
        elif hasattr(payload, name):
            setattr(payload, name, value)

    if admission is not None:
        _set("admission_state", admission.state.value)
        _set("queue_reason", admission.queue_reason)
        _set("queue_position", _queue_position(db, admission))
    else:
        _set("admission_state", None)
        _set("queue_reason", None)
        _set("queue_position", None)

    _set("sidecar_preference", job.sidecar_preference)

    progress = overall_progress(job)
    _set("progress", progress)
    if include_eta:
        estimate = estimate_eta(db, job, sidecar=job.sidecar_preference)
        _set("eta_low_seconds", estimate.eta_low_seconds)
        _set("eta_high_seconds", estimate.eta_high_seconds)
        _set("eta_confidence", estimate.confidence)
        _set("eta_basis", estimate.basis)
    return payload if isinstance(payload, dict) else payload


def _queue_position(db: Session, admission: JobAdmission) -> Optional[int]:
    if admission.state != AdmissionState.QUEUED:
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
