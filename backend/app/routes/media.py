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

WP1 (2026-08-16): the database session is now closed BEFORE the response body
streams. The previous implementation held the ``get_db()`` dependency open
until response completion; a gallery burst of many parallel authenticated
media requests each pinned a SQLAlchemy connection in an idle transaction,
exhausting the 60-connection pool and taking down health and login (the
2026-08-16 incident). Authorization and ownership are now resolved in a
short-lived explicit session that rolls back and closes before
``FileResponse`` is constructed (Review Round 1 Finding 1).
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Header, Response
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.exceptions import ResourceNotFoundException
from app.db.models import ProcessingJob
from app.db.session import db_session

router = APIRouter(tags=["media"])


async def _resolve_media_file(
    kind: str,
    job_id: str,
    filename: str,
    x_api_key: Optional[str],
    authorization: Optional[str],
    auth_token: Optional[str],
) -> Path:
    """Authenticate the caller, verify ownership, and resolve the file.

    Runs entirely inside a short-lived ``db_session`` that is closed before
    returning, so no connection is held open while the file streams. The
    resolved ``Path`` is immutable once the session closes — no ORM objects
    cross the boundary.

    Every failure raises NotFoundException so the response cannot be used to
    tell "job does not exist" apart from "job belongs to someone else".
    """
    from app.core.api_key_auth import get_current_user

    with db_session() as db:
        if x_api_key or authorization:
            user = await get_current_user(x_api_key=x_api_key, authorization=authorization, db=db)
        elif auth_token:
            user = await get_current_user(
                x_api_key=None, authorization=f"Bearer {auth_token}", db=db
            )
        else:
            from app.exceptions import AuthenticationException
            raise AuthenticationException("Not authenticated")

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
        headers={
            "Cache-Control": "private, max-age=3600",
            # Authenticated responses must not be reused across account
            # changes by a shared cache (Review Round 1 Finding 2).
            "Vary": "Cookie, Authorization, X-API-Key",
        },
    )


@router.get("/static/snapshots/{job_id}/{filename}")
async def get_snapshot(
    job_id: str,
    filename: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Cookie(None),
) -> Response:
    path = await _resolve_media_file(
        "snapshots", job_id, filename, x_api_key, authorization, auth_token
    )
    return _media_response(path)


@router.get("/static/slides/{job_id}/{filename}")
async def get_slide(
    job_id: str,
    filename: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Cookie(None),
) -> Response:
    path = await _resolve_media_file(
        "slides", job_id, filename, x_api_key, authorization, auth_token
    )
    return _media_response(path)
