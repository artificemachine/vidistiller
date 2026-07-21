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
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
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
from app.exceptions import ResourceNotFoundException, ValidationException
from app.tasks import (
    celery_app,
    import_job_payload_file_task,
    process_transcript,
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
        source_type, _ = VideoSourceResolver.resolve(job_data.video_url)

        processing_mode = ProcessingMode.SLIDE_AWARE.value if job_data.is_slide_mode else ProcessingMode.STANDARD.value
        new_job = ProcessingJob(
            job_id=str(uuid.uuid4()),
            status=ProcessingStatus.PENDING,
            video_url=job_data.video_url,
            source_type=source_type.value,
            processing_mode=processing_mode,
            caption_language=job_data.caption_language,
            user_id=current_user.id,
        )

        db.add(new_job)
        db.commit()
        db.refresh(new_job)

        # Trigger transcript processing in background (task sets celery_task_id itself)
        process_transcript.delay(new_job.id)

        return JobResponse.model_validate(new_job)

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[JobStatusResponse]:
    """
    List all processing jobs with optional filtering and pagination.

    **Query parameters:**
    - `skip`: Number of jobs to skip (default: 0)
    - `limit`: Maximum jobs to return (default: 10, max: 100)
    - `status_filter`: Filter by status (optional)

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

    # Apply pagination
    jobs = query.offset(skip).limit(limit).all()

    results = []
    for job in jobs:
        data = JobStatusResponse.model_validate(job)
        if job.videos:
            data.video_title = job.videos[0].title
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
        logger.warning("Could not verify import task ownership from Redis: %s", _e)
        # Redis unavailable — fail open rather than blocking all status checks


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
    return JobStatusResponse.model_validate(job)


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

    # Dispatch background summarization task (task sets celery_task_id itself)
    summarize_transcript_task.delay(job.id, force)
    job.summarize_status = "processing"
    db.commit()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Summarization started", "job_id": job_id},
    )


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
        if job.celery_task_id:
            celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
        job.summarize_status = "failed"
        job.celery_task_id = None
        db.commit()
        db.refresh(job)
        return JobStatusResponse.model_validate(job)

    if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED, ProcessingStatus.CANCELLED):
        raise ValidationException(
            f"Cannot cancel job with status '{job.status.value}'. "
            "Only pending or processing jobs can be cancelled."
        )

    # Revoke the running Celery task
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")

    job.status = ProcessingStatus.CANCELLED
    job.error_message = "Cancelled by user"
    job.celery_task_id = None
    db.commit()
    db.refresh(job)

    return JobStatusResponse.model_validate(job)


# ==============================================================================
# DELETE JOB - DELETE /jobs/{job_id}
# ==============================================================================

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

    **Path parameters:**
    - `job_id`: UUID of the processing job to delete

    **Response:** No content

    **Status codes:**
    - 204: Job deleted successfully
    - 404: Job not found
    """
    job = _get_job_for_user(db, job_id, current_user)

    try:
        db.delete(job)
        db.commit()
    except Exception as e:
        db.rollback()
        raise ValidationException("Failed to delete job: " + str(e))
