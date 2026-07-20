"""Authenticated delivery of per-job snapshot and slide images.

These files used to be served by a bare ``StaticFiles`` mount, which meant
anyone who learned a job UUID could read that job's frames without logging in.
Filenames are deterministic (``frame_0001.jpg``), so one leaked UUID exposed
the whole set permanently.

Two things make this route different from the rest of the API:

* It accepts the ``auth_token`` cookie in addition to the usual bearer header.
  A browser cannot attach an ``Authorization`` header to ``<img src>``, and
  these URLs are consumed exactly that way.
* The data directory is resolved per request rather than at import, so a
  reconfigured ``DATA_DIR`` takes effect without a restart.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.exceptions import AuthenticationException, ResourceNotFoundException
from app.db.models import ProcessingJob, User
from app.db.session import get_db

router = APIRouter(tags=["media"])


async def get_media_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the caller from the usual header auth, or from the login cookie.

    The header paths (X-API-Key, bearer) are delegated so machine clients keep
    working exactly as they do on the rest of the API. The cookie fallback is
    what makes ``<img src>`` work, since a browser cannot set a header on it.
    """
    from app.core.api_key_auth import get_current_user

    if x_api_key or authorization:
        return await get_current_user(x_api_key=x_api_key, authorization=authorization, db=db)
    if auth_token:
        return await get_current_user(
            x_api_key=None, authorization=f"Bearer {auth_token}", db=db
        )
    raise AuthenticationException("Not authenticated")


def _resolve_media_file(kind: str, job_id: str, filename: str, user: User, db: Session) -> Path:
    """Return the on-disk path for an owned job's media file.

    Every failure raises NotFoundException so the response cannot be used to
    tell "job does not exist" apart from "job belongs to someone else".
    """
    job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.job_id == job_id, ProcessingJob.user_id == user.id)
        .first()
    )
    if job is None:
        raise ResourceNotFoundException("Media")

    settings = get_settings()
    data_dir = settings.storage.data_dir or str(Path(__file__).resolve().parents[2] / "data")
    base = (Path(data_dir) / kind / job_id).resolve()

    candidate = (base / filename).resolve()
    # Containment check catches traversal that survived path normalisation,
    # including a symlink inside the job directory pointing outside it.
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise ResourceNotFoundException("Media")

    return candidate


def _media_response(path: Path) -> FileResponse:
    return FileResponse(
        path,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/static/snapshots/{job_id}/{filename}")
def get_snapshot(
    job_id: str,
    filename: str,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
) -> Response:
    return _media_response(_resolve_media_file("snapshots", job_id, filename, user, db))


@router.get("/static/slides/{job_id}/{filename}")
def get_slide(
    job_id: str,
    filename: str,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
) -> Response:
    return _media_response(_resolve_media_file("slides", job_id, filename, user, db))
