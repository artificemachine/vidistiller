"""
Snapshot Routes

API endpoints for video snapshot extraction, scene detection, and frame management.
"""

import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import ProcessingJob, Snapshot, User
from app.models import SnapshotResponse, SnapshotListResponse
from app.exceptions import SnapshotException, ValidationException
from app.services.snapshot import SnapshotService
from app.routes.auth import get_current_user_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


def _data_root() -> Path:
    """Resolve data root via settings — never reads env directly."""
    settings = get_settings()
    data_dir = settings.storage.data_dir or str(Path(__file__).resolve().parent.parent.parent / "data")
    return Path(data_dir)


def _snapshots_base() -> Path:
    return _data_root() / "snapshots"


def _videos_base() -> Path:
    return _data_root() / "videos"


def _get_job_for_user_by_pk(
    db: Session,
    job_id: int,
    current_user: User,
) -> ProcessingJob:
    """Fetch a job by numeric PK and enforce ownership."""
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _get_job_for_user_by_uuid(
    db: Session,
    job_uuid: str,
    current_user: User,
) -> ProcessingJob:
    """Fetch a job by public UUID and enforce ownership."""
    job = db.query(ProcessingJob).filter(ProcessingJob.job_id == job_uuid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _get_snapshot_for_user(
    db: Session,
    snapshot_id: int,
    current_user: User,
) -> Snapshot:
    """Fetch a snapshot by ID and enforce job ownership."""
    snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    job = db.query(ProcessingJob).filter(ProcessingJob.id == snapshot.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


class SnapshotCaptureRequest(BaseModel):
    """Request to capture a frame at a specific timestamp."""
    job_id: str = Field(..., description="Job UUID")
    timestamp: float = Field(..., ge=0, description="Video timestamp in seconds")


@router.post("/capture", response_model=SnapshotResponse)
async def capture_snapshot(
    request: SnapshotCaptureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Capture a video frame at a specific timestamp.

    Looks up the job's downloaded video file, extracts a frame using OpenCV,
    saves it to the static snapshots directory, and returns the snapshot record.
    """
    # Look up the job
    job = _get_job_for_user_by_uuid(db, request.job_id, current_user)

    if not job.youtube_url:
        raise HTTPException(status_code=400, detail="Job has no YouTube URL")

    # Download video on-demand if not already available
    video_path = job.video_file_path
    if not video_path or not Path(video_path).exists():
        try:
            from app.services.youtube import YouTubeService
            yt = YouTubeService()
            video_dir = str(_videos_base() / request.job_id)
            video_path, _ = yt.download_video(
                job.youtube_url, output_path=video_dir, quality="720p",
            )
            job.video_file_path = video_path
            db.commit()
            logger.info(f"Video downloaded on-demand for job {request.job_id}")
        except Exception as e:
            logger.error(f"On-demand video download failed: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Could not download video for snapshot: {e}",
            )

    try:
        service = SnapshotService()

        # Output directory: data/snapshots/{job_id}/
        output_dir = str(_snapshots_base() / request.job_id)

        frame_data = service.extract_frame_at_timestamp(
            video_path=video_path,
            timestamp=request.timestamp,
            output_dir=output_dir,
        )

        # Save to database
        snapshot = Snapshot(
            job_id=job.id,
            file_path=frame_data["file_path"],
            timestamp=frame_data["timestamp"],
            image_width=frame_data.get("width"),
            image_height=frame_data.get("height"),
            file_size=frame_data.get("file_size"),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        # Build the public image URL
        relative_path = Path(frame_data["file_path"]).relative_to(_snapshots_base())
        image_url = f"/static/snapshots/{relative_path}"

        response = SnapshotResponse.model_validate(snapshot)
        response.image_url = image_url
        return response

    except SnapshotException as e:
        logger.error(f"Snapshot capture failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/extract", response_model=SnapshotListResponse)
async def extract_snapshots(
    job_id: int,
    video_path: str = "",
    interval: float = 5.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Extract frames from video at regular intervals.

    Args:
        job_id: Processing job ID
        video_path: Path to video file
        interval: Seconds between frames (default: 5s)

    Returns:
        List of extracted snapshots

    Raises:
        400: Invalid input
        404: Job not found
        422: Snapshot extraction failed
    """
    try:
        job = _get_job_for_user_by_pk(db, job_id, current_user)
        if not job.video_file_path:
            raise ValidationException("No downloaded video is available for this job")

        effective_video_path = Path(job.video_file_path).resolve()
        if video_path:
            requested = Path(video_path).resolve()
            if requested != effective_video_path:
                raise ValidationException("video_path must match the job's stored video path")

        if not effective_video_path.exists():
            raise ValidationException("Video file not found for this job")

        service = SnapshotService()

        # Extract frames
        frames = service.extract_frames(str(effective_video_path), interval=interval)

        # Save to database
        snapshots = service.save_snapshots(db=db, job_id=job_id, frames=frames)

        return SnapshotListResponse(
            count=len(snapshots),
            snapshots=[
                SnapshotResponse.from_orm(snapshot)
                for snapshot in snapshots
            ]
        )

    except ValidationException as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except SnapshotException as e:
        logger.error(f"Snapshot extraction failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/detect-scenes", response_model=SnapshotListResponse)
async def detect_scene_changes(
    job_id: int,
    video_path: str = "",
    threshold: float = 27.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Detect scene changes and extract key frames.

    Args:
        job_id: Processing job ID
        video_path: Path to video file
        threshold: Scene change detection threshold (0-100)

    Returns:
        List of detected key frames

    Raises:
        400: Invalid input
        404: Job not found
        422: Scene detection failed
    """
    try:
        job = _get_job_for_user_by_pk(db, job_id, current_user)
        if not job.video_file_path:
            raise ValidationException("No downloaded video is available for this job")

        effective_video_path = Path(job.video_file_path).resolve()
        if video_path:
            requested = Path(video_path).resolve()
            if requested != effective_video_path:
                raise ValidationException("video_path must match the job's stored video path")

        if not effective_video_path.exists():
            raise ValidationException("Video file not found for this job")

        service = SnapshotService()

        # Detect scenes
        key_frames = service.detect_scene_changes(
            str(effective_video_path),
            threshold=threshold,
        )

        # Enrich with text and relevance
        for frame in key_frames:
            detected_text = service.extract_text_from_frame(frame["file_path"])
            frame["detected_text"] = detected_text

            relevance = service.score_frame_relevance(
                frame["file_path"],
                detected_text=detected_text,
            )
            frame["relevance_score"] = relevance

        # Save to database
        snapshots = service.save_snapshots(db=db, job_id=job_id, frames=key_frames)

        return SnapshotListResponse(
            count=len(snapshots),
            snapshots=[
                SnapshotResponse.from_orm(snapshot)
                for snapshot in snapshots
            ]
        )

    except ValidationException as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except SnapshotException as e:
        logger.error(f"Scene detection failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/job/{job_id}", response_model=SnapshotListResponse)
async def get_job_snapshots(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Get all snapshots for a processing job.

    Args:
        job_id: Processing job ID

    Returns:
        List of snapshots

    Raises:
        404: Job not found
    """
    try:
        job = _get_job_for_user_by_pk(db, job_id, current_user)
        snapshots = db.query(Snapshot).filter(
            Snapshot.job_id == job.id
        ).order_by(Snapshot.timestamp).all()

        snapshot_responses = []
        for snapshot in snapshots:
            resp = SnapshotResponse.model_validate(snapshot)
            # Build image_url if file is under snapshots dir
            try:
                relative_path = Path(snapshot.file_path).relative_to(_snapshots_base())
                resp.image_url = f"/static/snapshots/{relative_path}"
            except ValueError:
                pass
            snapshot_responses.append(resp)

        return SnapshotListResponse(
            count=len(snapshot_responses),
            snapshots=snapshot_responses,
        )

    except Exception as e:
        logger.error(f"Failed to retrieve snapshots: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve snapshots")


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Get a specific snapshot by ID.

    Args:
        snapshot_id: Snapshot ID

    Returns:
        Snapshot details

    Raises:
        404: Snapshot not found
    """
    try:
        snapshot = _get_snapshot_for_user(db, snapshot_id, current_user)

        return SnapshotResponse.from_orm(snapshot)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve snapshot: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve snapshot")


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Delete a snapshot by ID.

    Args:
        snapshot_id: Snapshot ID

    Raises:
        404: Snapshot not found
    """
    try:
        snapshot = _get_snapshot_for_user(db, snapshot_id, current_user)

        # Delete file if it exists
        if snapshot.file_path and Path(snapshot.file_path).exists():
            Path(snapshot.file_path).unlink()

        # Delete from database
        db.delete(snapshot)
        db.commit()

        logger.info(f"Deleted snapshot {snapshot_id}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to delete snapshot: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete snapshot")
