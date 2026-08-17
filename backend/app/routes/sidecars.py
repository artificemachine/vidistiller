"""User-facing sidecar availability (WP3).

Lets ordinary users pick a preferred sidecar for new jobs without exposing
operator telemetry. Deliberately a strict subset of the operator inventory
(Review Round 1 Finding 11): ``base_url``, VRAM, request counts and
reservation internals are never returned here.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.api_key_auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services.sidecar import inventory

router = APIRouter(prefix="/sidecars", tags=["Sidecars"])


class AvailableSidecar(BaseModel):
    """Sanitized sidecar summary for the submission form."""

    registered_id: str = Field(..., description="Stable id users may select")
    label: str = Field(..., description="Human-readable sidecar name")
    capabilities: List[str] = Field(default_factory=list, description="Declared capability tags")
    healthy: bool = Field(..., description="Live probe health")
    available_slots: int = Field(..., ge=0, description="Unreserved slot capacity")


@router.get("/available", response_model=list[AvailableSidecar])
def list_available_sidecars(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AvailableSidecar]:
    """Registered sidecars the caller may prefer for a new job.

    Sanitized by construction: no base URLs, VRAM, or per-request load.
    """
    return [
        AvailableSidecar(
            registered_id=t.registered_id,
            label=t.label,
            capabilities=list(t.capabilities),
            healthy=t.healthy,
            available_slots=t.available_slots,
        )
        for t in inventory(db)
    ]
