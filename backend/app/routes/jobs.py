"""
Job Processing Routes

Provides endpoints for managing YouTube to documentation conversion jobs:
- Create new processing jobs from YouTube URLs
- Retrieve job status and results
- List user's jobs with pagination
- Delete completed or failed jobs

All routes require authentication via JWT Bearer token or X-API-Key header.
"""

import base64
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, or_, text
from typing import List, Any, Dict

import os
from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import (
    ProcessingJob, ProcessingMode, ProcessingStatus, Video, Transcript,
    TranscriptSegment, Snapshot, Document, JobLog, LogLevel, User,
    Slide, SlideDetectionMetadata,
)
from app.schemas import (
    JobCreate,
    JobResponse,
    JobStatusResponse,
    JobLogResponse,
    VideoResponse,
    TranscriptResponse,
    SnapshotResponse,
    DocumentResponse,
    SlideResponse,
    SlideDetectionMetadataResponse,
)
from app.exceptions import DuplicateResourceException, ResourceNotFoundException, ValidationException
from app.tasks import (
    celery_app,
    import_job_payload_file_task,
    process_transcript,
    process_video_download,
    process_snapshots,
    process_slides,
    summarize_transcript_task,
)
from app.services.llm import LLMService
from app.services.job_import import import_job_payload
from app.core.api_key_auth import get_current_user  # supports X-API-Key + JWT
from app.core.rate_limit import job_submit_rate_limit
import uuid

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def _get_job_for_user(
    db: Session, job_id: str, current_user: User
) -> ProcessingJob:
    """Fetch a job by job_id and verify ownership. Returns 404 if not found or not owned."""
    job = db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
    if not job:
        raise ResourceNotFoundException("Job", job_id)
    if job.user_id != current_user.id:
        raise ResourceNotFoundException("Job", job_id)
    return job


def _finish_job_admission_for_route(db: Session, job_id: int, *, failed: bool = False) -> None:
    """Route-level admission release (cancel/delete paths), Review Round 2 F5."""
    from app.services.admission import finish_job_admission

    try:
        finish_job_admission(db, job_id, failed=failed)
    except Exception as exc:
        logger.warning("admission finish failed for job %s: %s", job_id, exc)
        db.rollback()


def _find_duplicate_job(
    db: Session, user_id: int, video_url: str, source_type, video_id: str
) -> ProcessingJob | None:
    """
    Look for an existing (non-cancelled) job of the same user pointing at the
    same video, matched by normalized platform video_id where the URL matches
    a known platform pattern (so youtu.be/X and youtube.com/watch?v=X&t=30
    dedupe as the same video), falling back to an exact URL match for
    platforms with no known pattern (direct files, long-tail sources).
    """
    from app.services.source_resolver import VideoSourceResolver

    candidates = (
        db.query(ProcessingJob)
        .filter(
            ProcessingJob.user_id == user_id,
            ProcessingJob.source_type == source_type.value,
            ProcessingJob.status != ProcessingStatus.CANCELLED,
        )
        .all()
    )
    for candidate in candidates:
        known = VideoSourceResolver.match_known(candidate.video_url or "")
        if known is not None:
            if known[1] == video_id:
                return candidate
        elif candidate.video_url == video_url:
            return candidate
    return None


def _search_filter(db: Session, q: str):
    """
    Build a WHERE clause matching a job's video title, URL, or transcript text.

    Transcripts can run 60K+ chars, so a plain ILIKE table-scan on full_text
    doesn't hold up on Postgres — use the generated tsvector column + GIN
    index instead (see migrations/versions/0002_transcript_fulltext_search.py).
    SQLite (used by the test suite) has no tsvector equivalent, so it falls
    back to ILIKE on full_text directly.
    """
    like = f"%{q}%"
    title_match = db.query(Video.id).filter(
        Video.job_id == ProcessingJob.id, Video.title.ilike(like)
    ).exists()

    if db.bind.dialect.name == "postgresql":
        transcript_match = db.query(Transcript.id).filter(
            Transcript.job_id == ProcessingJob.id,
            text("full_text_tsv @@ websearch_to_tsquery('english', :q)").bindparams(q=q),
        ).exists()
    else:
        transcript_match = db.query(Transcript.id).filter(
            Transcript.job_id == ProcessingJob.id, Transcript.full_text.ilike(like)
        ).exists()

    return or_(ProcessingJob.video_url.ilike(like), title_match, transcript_match)


# ==============================================================================
# CREATE JOB - POST /jobs
# ==============================================================================

@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new processing job",
    description="Create a new job to convert a YouTube video into documentation",
)
def create_job(
    job_data: JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rate_limit: None = Depends(job_submit_rate_limit),
) -> JobResponse:
    """
    Create a new processing job from a YouTube URL.

    **Request body:**
    - `video_url`: Video URL to process (YouTube, Vimeo, Twitch, Twitter/X, TikTok, Reddit, Rumble, or direct MP4)
    - `output_format`: Desired output format (markdown, html, pdf)
    - `extract_snapshots`: Whether to extract key frames (default: true)

    **Response:** Full job details with ID and UUID

    **Status codes:**
    - 201: Job created successfully
    - 422: Invalid URL or parameters
    """
    try:
        from app.services.source_resolver import VideoSourceResolver
        source_type, video_id = VideoSourceResolver.resolve(job_data.video_url)

        if not job_data.force:
            duplicate = _find_duplicate_job(
                db, current_user.id, job_data.video_url, source_type, video_id
            )
            if duplicate is not None:
                raise DuplicateResourceException(
                    "A job for this video already exists",
                    existing={
                        "job_id": duplicate.job_id,
                        "status": duplicate.status.value,
                        "created_at": duplicate.created_at.isoformat(),
                        "video_title": duplicate.videos[0].title if duplicate.videos else None,
                    },
                )

        processing_mode = ProcessingMode.SLIDE_AWARE.value if job_data.is_slide_mode else ProcessingMode.STANDARD.value
        from app.services.sidecar import validate_sidecar_preference
        sidecar_pref = validate_sidecar_preference(db, job_data.sidecar_preference)
        new_job = ProcessingJob(
            job_id=str(uuid.uuid4()),
            status=ProcessingStatus.PENDING,
            video_url=job_data.video_url,
            source_type=source_type.value,
            processing_mode=processing_mode,
            caption_language=job_data.caption_language,
            sidecar_preference=sidecar_pref,
            user_id=current_user.id,
        )

        db.add(new_job)
        from app.services.job_steps import seed_job_steps

        seed_job_steps(
            db,
            new_job,
            extract_snapshots=job_data.extract_snapshots,
            is_slide_mode=job_data.is_slide_mode,
        )
        # WP2: admit or queue atomically in the same transaction that creates
        # the job. A job that cannot start is queued with a visible reason —
        # it is never overcommitted nor failed ambiguously. When admitted, an
        # outbox dispatch row is written; it is published to Redis only after
        # commit (durable at-least-once, Review Round 1 Finding 7).
        from app.services.admission import admit_or_queue_job

        outcome = admit_or_queue_job(
            db, new_job, preferred_sidecar=sidecar_pref
        )
        db.commit()
        db.refresh(new_job)

        if outcome.state == "admitted":
            from app.services.admission import (
                mark_outbox_delivered,
                pending_outbox_rows,
            )
            from app.services.dispatch import publish_outbox

            published = publish_outbox(db, job_id=new_job.id)
            if published:
                db.commit()
            # Legacy safety: if nothing was published (no outbox row or Redis
            # unavailable), fall back to the direct .delay() path so a
            # pre-outbox deployment never silently drops jobs. The task
            # itself remains idempotent via claim_step. A Redis outage here
            # must not fail the already-committed job creation.
            if not published:
                try:
                    from app.tasks import process_transcript
                    process_transcript.delay(new_job.id)
                except Exception as _delay_exc:
                    logger.warning(
                        "Job %s committed but dispatch failed (Redis down?): %s — outbox sweep will retry",
                        new_job.job_id, _delay_exc,
                    )
        else:
            logger.info(
                "Job %s queued (admission): %s", new_job.job_id, outcome.queue_reason
            )

        return JobResponse.model_validate(new_job)

    except DuplicateResourceException:
        raise
    except Exception as e:
        db.rollback()
        raise ValidationException("Failed to create job: " + str(e))


# ==============================================================================
# LIST JOBS - GET /jobs
# ==============================================================================

@router.get(
    "",
    response_model=List[JobStatusResponse],
    summary="List all processing jobs",
    description="Retrieve a paginated list of all processing jobs",
)
def list_jobs(
    skip: int = Query(0, ge=0, description="Number of jobs to skip"),
    limit: int = Query(10, ge=1, le=100, description="Maximum jobs to return"),
    status_filter: str | None = Query(None, description="Filter by status (pending, processing, completed, failed, cancelled)"),
    q: str | None = Query(None, min_length=1, max_length=200, description="Search video title, URL, or transcript text"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[JobStatusResponse]:
    """
    List all processing jobs with optional filtering, search, and pagination.

    **Query parameters:**
    - `skip`: Number of jobs to skip (default: 0)
    - `limit`: Maximum jobs to return (default: 10, max: 100)
    - `status_filter`: Filter by status (optional)
    - `q`: Search video title, URL, or transcript text (optional)

    **Response:** List of job status objects

    **Status codes:**
    - 200: Jobs retrieved successfully
    """
    query = db.query(ProcessingJob).options(
        joinedload(ProcessingJob.videos)
    ).filter(
        ProcessingJob.user_id == current_user.id
    ).order_by(desc(ProcessingJob.created_at))

    # Apply status filter if provided
    if status_filter:
        try:
            status_enum = ProcessingStatus[status_filter.upper()]
            query = query.filter(ProcessingJob.status == status_enum)
        except KeyError:
            raise ValidationException(
                f"Invalid status filter: {status_filter}. "
                f"Valid options: {', '.join([s.value for s in ProcessingStatus])}"
            )

    if q:
        query = query.filter(_search_filter(db, q))

    # Apply pagination
    jobs = query.offset(skip).limit(limit).all()

    results = []
    for job in jobs:
        data = JobStatusResponse.model_validate(job)
        if job.videos:
            data.video_title = job.videos[0].title
        # WP2/WP5: admission state, queue position, progress, ETA for the owner.
        from app.services.job_payload import enrich_job_payload

        enrich_job_payload(db, job, data)
        results.append(data)
    return results


# ==============================================================================
# IMPORT JOB - POST /jobs/import
# ==============================================================================

@router.post(
    "/import",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a previously exported job",
    description="Recreate a full job from an exported JSON file",
)
def import_job(
    data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    try:
        new_job = import_job_payload(db, data, current_user.id)
        return JobResponse.model_validate(new_job)

    except ValidationException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise ValidationException(f"Failed to import job: {str(e)}")


@router.post(
    "/import-upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue large import from uploaded JSON/JSON.GZ",
    description="Stream upload to disk and process import asynchronously via Celery.",
)
async def import_job_upload(
    request: Request,
    filename: str = Query("import.json", description="Original filename, used to infer .json/.gz"),
    current_user: User = Depends(get_current_user),
):
    lower_name = filename.lower()
    if not (lower_name.endswith(".json") or lower_name.endswith(".json.gz") or lower_name.endswith(".gz")):
        raise ValidationException("Unsupported file type. Use .json or .json.gz")

    settings = get_settings()
    _data_dir = settings.storage.data_dir or str(Path(__file__).resolve().parent.parent.parent / "data")
    data_root = Path(_data_dir)
    import_dir = data_root / "imports" / str(current_user.id)
    import_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".json.gz" if lower_name.endswith(".gz") else ".json"
    upload_id = str(uuid.uuid4())
    upload_path = import_dir / f"{upload_id}{suffix}"

    max_bytes = settings.storage.max_import_size_bytes
    bytes_written = 0
    with upload_path.open("wb") as out:
        async for chunk in request.stream():
            if chunk:
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    upload_path.unlink(missing_ok=True)
                    raise ValidationException(
                        f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MB"
                    )
                out.write(chunk)

    task = import_job_payload_file_task.delay(str(upload_path), current_user.id)

    # Track task ownership in Redis so the status endpoint can verify the caller
    try:
        import redis as _redis
        _r = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        _r.setex(f"import_task:{task.id}", 86400, str(current_user.id))
    except Exception as _e:
        logger.warning("Could not register import task ownership in Redis: %s", _e)

    return {
        "message": "Import queued",
        "task_id": task.id,
        "upload_id": upload_id,
    }


def verify_import_task_ownership(task_id: str, current_user: User = Depends(get_current_user)) -> None:
    """Dependency: confirm task_id was created by current_user via Redis lookup."""
    try:
        import redis as _redis
        _r = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        owner_id = _r.get(f"import_task:{task_id}")
        if owner_id is None or int(owner_id) != current_user.id:
            raise ResourceNotFoundException("ImportTask", task_id)
    except ResourceNotFoundException:
        raise
    except Exception as _e:
        # Redis unavailable — fail CLOSED. This is a cross-user authorization
        # check; skipping it on a Redis error would let any authenticated user
        # read another user's import status during an outage. Deny instead.
        logger.error(
            "Could not verify import task ownership from Redis, denying (fail closed): %s",
            _e,
        )
        raise ResourceNotFoundException("ImportTask", task_id)


@router.get(
    "/import-upload/{task_id}",
    summary="Check async import status",
    description="Read the Celery task state/result for a queued import.",
)
def get_import_upload_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    _ownership: None = Depends(verify_import_task_ownership),
):

    result = celery_app.AsyncResult(task_id)
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.status == "SUCCESS":
        payload["result"] = result.result
    elif result.status == "FAILURE":
        payload["error"] = str(result.result)

    return payload


# ==============================================================================
# GET JOB STATUS - GET /jobs/{job_id}
# ==============================================================================

@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job details",
    description="Retrieve complete job information including all related data",
)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """
    Retrieve complete details for a specific job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** Full job details with nested relationships

    **Status codes:**
    - 200: Job found and returned
    - 404: Job not found
    """
    job = (
        db.query(ProcessingJob)
        .options(
            joinedload(ProcessingJob.videos),
            joinedload(ProcessingJob.transcripts),
            joinedload(ProcessingJob.snapshots),
            joinedload(ProcessingJob.slides),
        )
        .filter(ProcessingJob.job_id == job_id)
        .first()
    )

    if not job:
        raise ResourceNotFoundException("Job", job_id)
    if job.user_id != current_user.id:
        raise ResourceNotFoundException("Job", job_id)

    response = JobResponse.model_validate(job)

    # WP2/WP5: admission state, queue position, progress, ETA for the owner.
    from app.services.job_payload import enrich_job_payload

    enrich_job_payload(db, job, response)

    _data_dir = get_settings().storage.data_dir or str(Path(__file__).resolve().parent.parent.parent / "data")
    data_root = Path(_data_dir)

    # Compute image_url for each snapshot
    snapshots_base = data_root / "snapshots"
    for snapshot_resp in response.snapshots:
        try:
            relative = Path(snapshot_resp.file_path).relative_to(snapshots_base)
            snapshot_resp.image_url = f"/static/snapshots/{relative}"
        except (ValueError, TypeError):
            pass

    # Compute image_url for each slide
    slides_base = data_root / "slides"
    for slide_resp in response.slides:
        if slide_resp.final_frame_path:
            try:
                relative = Path(slide_resp.final_frame_path).relative_to(slides_base)
                slide_resp.image_url = f"/static/slides/{relative}"
            except (ValueError, TypeError):
                pass

    return response


# ==============================================================================
# GET JOB STATUS ONLY - GET /jobs/{job_id}/status
# ==============================================================================

@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Get job status (lightweight)",
    description="Retrieve only the status of a job (for polling)",
)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobStatusResponse:
    """
    Retrieve lightweight job status for polling.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** Job status with error message if failed

    **Status codes:**
    - 200: Status retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)
    status = JobStatusResponse.model_validate(job)
    from app.services.job_payload import enrich_job_payload

    enrich_job_payload(db, job, status)
    return status


# ==============================================================================
# GET JOB VIDEOS - GET /jobs/{job_id}/videos
# ==============================================================================

@router.get(
    "/{job_id}/videos",
    response_model=List[VideoResponse],
    summary="Get job video metadata",
    description="Retrieve all video metadata for a job",
)
def get_job_videos(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[VideoResponse]:
    """
    Retrieve all video metadata associated with a job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of video metadata objects

    **Status codes:**
    - 200: Videos retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)
    return [VideoResponse.model_validate(video) for video in job.videos]


# ==============================================================================
# GET JOB TRANSCRIPTS - GET /jobs/{job_id}/transcripts
# ==============================================================================

@router.get(
    "/{job_id}/transcripts",
    response_model=List[TranscriptResponse],
    summary="Get job transcripts",
    description="Retrieve all transcripts for a job",
)
def get_job_transcripts(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[TranscriptResponse]:
    """
    Retrieve all transcripts associated with a job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of transcript objects with segments

    **Status codes:**
    - 200: Transcripts retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)
    return [TranscriptResponse.model_validate(transcript) for transcript in job.transcripts]


# ==============================================================================
# GET JOB SNAPSHOTS - GET /jobs/{job_id}/snapshots
# ==============================================================================

@router.get(
    "/{job_id}/snapshots",
    response_model=List[SnapshotResponse],
    summary="Get job snapshots",
    description="Retrieve all extracted snapshots for a job",
)
def get_job_snapshots(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SnapshotResponse]:
    """
    Retrieve all snapshots (key frames) extracted from a job's video.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of snapshot objects ordered by timestamp

    **Status codes:**
    - 200: Snapshots retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)

    # Return snapshots ordered by timestamp
    snapshots = sorted(job.snapshots, key=lambda s: s.timestamp)
    return [SnapshotResponse.model_validate(snapshot) for snapshot in snapshots]


# ==============================================================================
# GET JOB LOGS - GET /jobs/{job_id}/logs
# ==============================================================================

@router.get(
    "/{job_id}/logs",
    response_model=List[JobLogResponse],
    summary="Get job processing logs",
    description="Retrieve all processing log entries for a job",
)
def get_job_logs(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[JobLogResponse]:
    """
    Retrieve all log entries for a specific job, ordered by timestamp.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of log entry objects ordered by created_at

    **Status codes:**
    - 200: Logs retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)
    return [JobLogResponse.model_validate(log) for log in job.logs]


# ==============================================================================
# GET JOB DOCUMENTS - GET /jobs/{job_id}/documents
# ==============================================================================

@router.get(
    "/{job_id}/documents",
    response_model=List[DocumentResponse],
    summary="Get job documents",
    description="Retrieve all generated documentation for a job",
)
def get_job_documents(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[DocumentResponse]:
    """
    Retrieve all generated documentation for a job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of document objects

    **Status codes:**
    - 200: Documents retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)
    return [DocumentResponse.model_validate(document) for document in job.documents]


# ==============================================================================
# GET JOB SLIDES - GET /jobs/{job_id}/slides
# ==============================================================================

@router.get(
    "/{job_id}/slides",
    response_model=List[SlideResponse],
    summary="Get job slides",
    description="Retrieve all detected slides for a slide-aware job",
)
def get_job_slides(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SlideResponse]:
    """
    Retrieve all detected slides for a job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** List of slide objects with image URLs

    **Status codes:**
    - 200: Slides retrieved successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)

    _data_dir = get_settings().storage.data_dir or str(Path(__file__).resolve().parent.parent.parent / "data")
    data_root = Path(_data_dir)
    slides_base = data_root / "slides"

    slides = []
    for slide in sorted(job.slides, key=lambda s: s.slide_number):
        resp = SlideResponse.model_validate(slide)
        if slide.final_frame_path:
            try:
                relative = Path(slide.final_frame_path).relative_to(slides_base)
                resp.image_url = f"/static/slides/{relative}"
            except (ValueError, TypeError):
                pass
        slides.append(resp)

    return slides


# ==============================================================================
# GET SLIDE METADATA - GET /jobs/{job_id}/slide-metadata
# ==============================================================================

@router.get(
    "/{job_id}/slide-metadata",
    response_model=SlideDetectionMetadataResponse,
    summary="Get slide detection metadata",
    description="Retrieve metadata about the slide detection process",
)
def get_job_slide_metadata(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SlideDetectionMetadataResponse:
    """
    Retrieve slide detection metadata for a job.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** Slide detection metadata

    **Status codes:**
    - 200: Metadata retrieved successfully
    - 404: Job or metadata not found
    """
    job = _get_job_for_user(db, job_id, current_user)

    metadata = job.slide_detection_metadata
    if not metadata:
        raise ResourceNotFoundException("SlideDetectionMetadata", job_id)

    return SlideDetectionMetadataResponse.model_validate(metadata)


# ==============================================================================
# EXPORT JOB - GET /jobs/{job_id}/export
# ==============================================================================

@router.get(
    "/{job_id}/export",
    summary="Export job as self-contained JSON",
    description="Download a JSON file containing all job data including base64-encoded snapshots",
)
def export_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_job_for_user(db, job_id, current_user)
    export_claim_token = f"export:{uuid.uuid4()}"
    export_claimed = False
    if isinstance(getattr(job, "steps", None), list) and job.steps:
        from app.services.job_steps import claim_step

        export_claimed = claim_step(
            db, job.id, "export", export_claim_token
        ) is not None

    _data_dir_str = get_settings().storage.data_dir or str(Path(__file__).resolve().parent.parent.parent / "data")
    DATA_DIR = Path(_data_dir_str)

    # Build snapshot data with base64 images — cap at 200 snapshots to bound memory use
    MAX_EXPORT_SNAPSHOTS = 200
    sorted_snaps = sorted(job.snapshots, key=lambda s: s.timestamp)[:MAX_EXPORT_SNAPSHOTS]
    snapshots_data = []
    for snap in sorted_snaps:
        snap_dict = {
            "file_path": snap.file_path,
            "timestamp": snap.timestamp,
            "relevance_score": snap.relevance_score,
            "detected_text": snap.detected_text,
            "image_width": snap.image_width,
            "image_height": snap.image_height,
            "file_size": snap.file_size,
        }
        image_path = Path(snap.file_path)
        if image_path.exists():
            snap_dict["image_base64"] = base64.b64encode(image_path.read_bytes()).decode()
        snapshots_data.append(snap_dict)

    export_data = {
        "export_version": "1.0",
        "job": {
            "job_id": job.job_id,
            "status": job.status.value,
            "video_url": job.video_url,
            "source_type": job.source_type,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        },
        "videos": [
            {
                "url": v.url,
                "video_id": v.video_id,
                "title": v.title,
                "description": v.description,
                "duration": v.duration,
                "thumbnail_url": v.thumbnail_url,
                "channel_name": v.channel_name,
                "view_count": v.view_count,
            }
            for v in job.videos
        ],
        "transcripts": [
            {
                "full_text": t.full_text,
                "language": t.language,
                "source": t.source,
                "confidence_score": t.confidence_score,
                "duration": t.duration,
                "segments": [
                    {
                        "text": seg.text,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "speaker": seg.speaker,
                        "confidence_score": seg.confidence_score,
                        "sequence": seg.sequence,
                    }
                    for seg in sorted(t.segments, key=lambda s: s.sequence)
                ],
            }
            for t in job.transcripts
        ],
        "snapshots": snapshots_data,
        "documents": [
            {
                "title": d.title,
                "content": d.content,
                "format": d.format,
            }
            for d in job.documents
        ],
        "logs": [
            {
                "level": log.level.value,
                "message": log.message,
                "step": log.step,
                "created_at": log.created_at.isoformat(),
            }
            for log in job.logs
        ],
    }

    video_title = job.videos[0].title if job.videos else job.job_id
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in video_title)[:60].strip()
    filename = f"{safe_name}.json" if safe_name else f"{job.job_id}.json"

    if export_claimed:
        from app.services.job_steps import complete_step

        complete_step(
            db,
            job.id,
            "export",
            export_claim_token,
            {
                "bytes": len(json.dumps(export_data)),
                "transcripts": len(export_data["transcripts"]),
                "snapshots": len(snapshots_data),
                "documents": len(export_data["documents"]),
            },
        )
        db.commit()

    return JSONResponse(
        content=export_data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==============================================================================
# SUMMARIZE TRANSCRIPT - POST /jobs/{job_id}/summarize
# ==============================================================================

@router.post(
    "/{job_id}/summarize",
    summary="Summarize transcript via LLM",
    description="Summarize each transcript section into paragraphs and bullet points",
)
def summarize_transcript(
    job_id: str,
    force: bool = Query(False, description="Force re-summarization even if cached"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Summarize the job's transcript into structured paragraphs and bullet points.

    Returns cached summary (200) if available, otherwise dispatches a background
    Celery task and returns 202 Accepted.

    **Query parameters:**
    - `force`: If true, regenerate even if a cached summary exists

    **Status codes:**
    - 200: Cached summary returned
    - 202: Summarization task dispatched (poll job status for completion)
    - 404: Job not found
    - 422: No transcript available
    """
    job = _get_job_for_user(db, job_id, current_user)

    # Return cached summary if available (unless force=True)
    if not force:
        cached = (
            db.query(Document)
            .filter(Document.job_id == job.id, Document.format == "summary")
            .first()
        )
        if cached:
            return DocumentResponse.model_validate(cached)

    # Validate transcript exists
    if not job.transcripts:
        raise ValidationException("No transcript available for this job")

    # Avoid duplicate tasks: if a summarization is already running and the
    # caller did not force, do not dispatch a second task (two concurrent
    # tasks on the same job race on the document row and one can mark the
    # job failed even though the other saved a valid summary).
    running_task_id = None
    if job.summarize_status == "processing" and not force:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": "Summarization already in progress", "job_id": job_id},
        )

    # P17-NEW: the ENTIRE force transaction is atomic (P16-NEW-36): lock the
    # job row, mint the generation, re-check status under the lock, update
    # state/task-id, enqueue the outbox row, then commit ONCE. No pre-outbox
    # commit exists, so a crash can never leave processing state without a
    # recoverable dispatch. Revoke runs only after the durable row commits.
    from app.services.admission import enqueue_first_stage
    from app.services.dispatch import publish_outbox

    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"),
            {"job_id": job.id},
        )
    # P18-NEW-38: read BOTH summarize_status and celery_task_id fresh under
    # the lock — the ORM object may predate a worker's task-id write, and
    # revoking the stale id would leave the live worker running.
    locked = db.execute(
        text(
            "SELECT summarize_status, celery_task_id FROM processing_jobs "
            "WHERE id = :job_id"
        ),
        {"job_id": job.id},
    ).first()
    locked_status = locked[0] if locked else None
    if job.summarize_status == "processing" or locked_status == "processing":
        running_task_id = locked[1] if locked else job.celery_task_id
    force_generation = _mint_force_generation(db, job.id)
    if locked_status == "failed":
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "Summarization was cancelled; cannot force-start", "job_id": job_id},
        )
    job.celery_task_id = None
    job.summarize_status = "processing"
    enqueue_first_stage(
        db, job.id, str(uuid.uuid4()),
        stage="summarize",
        payload={"force": force, "force_generation": force_generation},
    )
    db.commit()

    # P15-NEW-34: state + outbox row are durable now. Revoke the old task
    # AFTER the durable recovery state exists (P16-NEW-36): a revoke failure
    # or crash cannot strand committed processing state without a
    # recoverable dispatch.
    if running_task_id:
        try:
            celery_app.control.revoke(running_task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:
            logger.warning("revoke of stale task %s failed: %s", running_task_id, exc)

    try:
        publish_outbox(db, job_id=job.id)
        db.commit()
    except Exception as exc:
        logger.warning(
            "summarize dispatch publish failed for job %s (outbox will retry): %s",
            job.id, exc,
        )
        db.rollback()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Summarization started", "job_id": job_id},
    )


@router.post("/{job_id}/steps/{step_name}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job_step(
    job_id: str,
    step_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry one failed/cancelled stage without resetting completed stages."""
    job = _get_job_for_user(db, job_id, current_user)
    from app.services.job_steps import CANONICAL_STEP_NAMES, retry_failed_step

    if step_name not in CANONICAL_STEP_NAMES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown processing step")
    # P18-NEW-39: acquire the JOB row lock BEFORE resetting the step so the
    # retry transaction follows the same job->step lock order as claim_step
    # and the summarize task — concurrent retry/claim cannot deadlock.
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"),
            {"job_id": job.id},
        )
    if not retry_failed_step(db, job.id, step_name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Step is not retryable")

    dispatchers = {
        "download": lambda: _enqueue_stage_retry(db, job.id, "download"),
        "transcribe": lambda: _enqueue_stage_retry(db, job.id, "transcribe"),
        "snapshots": lambda: _enqueue_stage_retry(db, job.id, "snapshots"),
        "slides": lambda: _enqueue_stage_retry(db, job.id, "slides"),
        "summarize": lambda: _dispatch_summarize_retry(db, job),
    }
    if step_name == "export":
        db.commit()
        return {"message": "Export step reset; request the export download again", "job_id": job_id}
    if step_name == "summarize":
        # The step reset above and _dispatch_summarize_retry's generation/
        # status/outbox co-commit run in ONE transaction (P16-NEW-36): no
        # pre-outbox commit exists here.
        _dispatch_summarize_retry(db, job)
        return {"message": f"Retry for {step_name} started", "job_id": job_id}
    # P16-NEW-36: the step reset and the durable outbox row commit in ONE
    # transaction (no crash gap leaving a stranded pending step).
    from app.services.admission import enqueue_first_stage

    enqueue_first_stage(db, job.id, str(uuid.uuid4()), stage=step_name)
    db.commit()
    dispatchers[step_name]()
    return {"message": f"Retry for {step_name} started", "job_id": job_id}


def _enqueue_stage_retry(db: Session, job_id: int, step_name: str) -> None:
    """Publish a step retry outbox row that was committed with the reset
    (P15-NEW-35/P16-NEW-36). The row already exists; this only delivers it."""
    from app.services.dispatch import publish_outbox

    try:
        publish_outbox(db, job_id=job_id)
        db.commit()
    except Exception as exc:
        logger.warning(
            "step retry publish failed for job %s/%s (outbox will retry): %s",
            job_id, step_name, exc,
        )
        db.rollback()


# ==============================================================================
# CANCEL JOB - POST /jobs/{job_id}/cancel
# ==============================================================================

@router.post(
    "/{job_id}/cancel",
    response_model=JobStatusResponse,
    summary="Cancel a processing job",
    description="Stop a pending, processing, or summarizing job",
)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobStatusResponse:
    """
    Cancel a pending/processing job or an in-progress summarization.

    Revokes the running Celery task (if any) to stop Ollama calls.

    **Path parameters:**
    - `job_id`: UUID of the processing job

    **Response:** Updated job status

    **Status codes:**
    - 200: Job/summarization cancelled successfully
    - 404: Job not found
    - 422: Job cannot be cancelled
    """
    job = _get_job_for_user(db, job_id, current_user)

    # Allow cancelling an in-progress summarization on a completed job
    if job.summarize_status == "processing":
        running_task_id = job.celery_task_id
        # Fence in the DB first, then revoke (Review Round 2 F1).
        job.summarize_status = "failed"
        job.celery_task_id = None
        db.commit()
        if running_task_id:
            celery_app.control.revoke(running_task_id, terminate=True, signal="SIGTERM")
        db.refresh(job)
        return JobStatusResponse.model_validate(job)

    if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED, ProcessingStatus.CANCELLED):
        raise ValidationException(
            f"Cannot cancel job with status '{job.status.value}'. "
            "Only pending or processing jobs can be cancelled."
        )

    # Fence in the DB FIRST, then revoke the task (Review Round 2 F1/F5/N5):
    # the status transition and the admission release happen in ONE
    # transaction so a crash cannot leak the active-job counter. The revoke
    # merely terminates the in-flight OS process.
    running_task_id = job.celery_task_id
    # Lock order JOB -> ADMISSION (Review Round 2 P8-NEW-13): explicitly lock
    # the job row before the admission transition so a concurrent promotion
    # (which locks job then admission) serializes with cancellation.
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"),
            {"job_id": job.id},
        )
    job.status = ProcessingStatus.CANCELLED
    job.error_message = "Cancelled by user"
    job.celery_task_id = None
    _finish_job_admission_for_route(db, job.id, failed=True)
    db.commit()

    # Revoke the running Celery task (after the DB fence committed).
    if running_task_id:
        celery_app.control.revoke(running_task_id, terminate=True, signal="SIGTERM")

    db.refresh(job)
    return JobStatusResponse.model_validate(job)


# ==============================================================================
# DELETE JOB - DELETE /jobs/{job_id}
# ==============================================================================

def _dispatch_summarize_retry(db: Session, job, reset_step: bool = False) -> None:
    """Retry summarization with a fresh force generation (Review Round 2 NEW-7).

    P14-NEW-31: persist the authorized 'processing' state before dispatch so
    the retried task is not skipped by the failed-status guard.
    P15-NEW-35/P16-NEW-36: generation mint, status transition, the step
    reset (when requested) and the durable outbox row commit in ONE
    transaction — no crash gap stranding processing state without a
    recoverable dispatch. When called from the step-retry route the step
    reset already happened in the same uncommitted transaction.
    """
    if reset_step:
        from app.services.job_steps import retry_failed_step

        retry_failed_step(db, job.id, "summarize")
    gen = _mint_force_generation(db, job.id)
    job.summarize_status = "processing"
    from app.services.admission import enqueue_first_stage
    from app.services.dispatch import publish_outbox

    enqueue_first_stage(
        db, job.id, str(uuid.uuid4()),
        stage="summarize",
        payload={"force": True, "force_generation": gen},
    )
    db.commit()
    try:
        publish_outbox(db, job_id=job.id)
        db.commit()
    except Exception as exc:
        logger.warning(
            "summarize retry publish failed for job %s (outbox will retry): %s",
            job.id, exc,
        )
        db.rollback()


def _mint_force_generation(db: Session, job_id: int) -> int:
    """Atomically bump processing_jobs.force_generation and return the new
    value (Review Round 2 NEW-7): concurrent force requests always receive
    distinct generations."""
    if db.bind.dialect.name == "postgresql":
        row = db.execute(
            text(
                "UPDATE processing_jobs SET force_generation = force_generation + 1 "
                "WHERE id = :job_id RETURNING force_generation"
            ),
            {"job_id": job_id},
        ).first()
        return int(row[0]) if row else 0
    from datetime import UTC, datetime as _dt

    from app.db.models import ProcessingJob

    job = db.get(ProcessingJob, job_id)
    if job is None:
        return 0
    job.force_generation = (job.force_generation or 0) + 1
    db.flush()
    return job.force_generation


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a job",
    description="Delete a processing job and all associated data",
)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a processing job and cascade-delete all related data.

    Active (processing/pending) jobs are rejected: deleting them would orphan
    the admission counter and the leased sidecar slot (Review Round 2 F5).
    The caller must cancel first, which fences and releases atomically.

    **Path parameters:**
    - `job_id`: UUID of the processing job to delete

    **Response:** No content

    **Status codes:**
    - 204: Job deleted successfully
    - 404: Job not found
    - 422: Active job cannot be deleted (cancel it first)
    """
    job = _get_job_for_user(db, job_id, current_user)

    if job.status in (ProcessingStatus.PROCESSING, ProcessingStatus.PENDING):
        raise ValidationException(
            "Cannot delete an active job. Cancel it first (POST /jobs/{id}/cancel)."
        )
    if job.summarize_status == "processing":
        raise ValidationException(
            "Cannot delete a job with an in-progress summarization. "
            "Cancel it first (POST /jobs/{id}/cancel)."
        )

    # Belt-and-braces admission release for terminal-but-unfinished rows
    # (finish is exactly-once).
    _finish_job_admission_for_route(db, job.id)
    db.commit()

    try:
        db.delete(job)
        db.commit()
    except Exception as e:
        db.rollback()
        raise ValidationException("Failed to delete job: " + str(e))
