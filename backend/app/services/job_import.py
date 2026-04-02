"""
Job import service helpers.

Provides shared logic for importing exported job payloads into the database.
Used by both synchronous and async import endpoints/tasks.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict
import uuid

from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    JobLog,
    LogLevel,
    ProcessingJob,
    ProcessingStatus,
    Snapshot,
    Transcript,
    TranscriptSegment,
    User,
    Video,
)
from app.exceptions import ValidationException


def get_data_dir() -> Path:
    """Resolve DATA_DIR used for imported artifact storage."""
    return Path(
        os.environ.get(
            "DATA_DIR",
            Path(__file__).resolve().parent.parent.parent / "data",
        )
    )


def import_job_payload(
    db: Session,
    data: Dict[str, Any],
    current_user_id: int,
    data_dir: Path | None = None,
) -> ProcessingJob:
    """
    Import a previously exported job payload for a specific user.

    Returns the newly created ProcessingJob row.
    """
    if data.get("export_version") != "1.0":
        raise ValidationException(f"Unsupported export version: {data.get('export_version')}")

    job_data = data.get("job", {})
    if not job_data:
        raise ValidationException("Missing 'job' key in export data")

    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise ValidationException("Import user not found")

    for v in data.get("videos", []):
        existing = db.query(Video).filter(Video.video_id == v["video_id"]).first()
        if existing:
            raise ValidationException(
                f"Video '{v['video_id']}' already exists (job {existing.job_id}). "
                "Delete the existing job first."
            )

    resolved_data_dir = data_dir or get_data_dir()

    new_job = ProcessingJob(
        job_id=str(uuid.uuid4()),
        status=ProcessingStatus.COMPLETED,
        youtube_url=job_data.get("youtube_url"),
        user_id=current_user_id,
    )
    db.add(new_job)
    db.flush()

    for v in data.get("videos", []):
        db.add(
            Video(
                job_id=new_job.id,
                url=v["url"],
                video_id=v["video_id"],
                title=v["title"],
                description=v.get("description"),
                duration=v.get("duration"),
                thumbnail_url=v.get("thumbnail_url"),
                channel_name=v.get("channel_name"),
                view_count=v.get("view_count"),
            )
        )

    for t in data.get("transcripts", []):
        transcript = Transcript(
            job_id=new_job.id,
            full_text=t["full_text"],
            language=t.get("language", "en"),
            source=t.get("source"),
            confidence_score=t.get("confidence_score"),
            duration=t.get("duration"),
        )
        db.add(transcript)
        db.flush()
        for seg in t.get("segments", []):
            db.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    text=seg["text"],
                    start_time=seg["start_time"],
                    end_time=seg["end_time"],
                    speaker=seg.get("speaker"),
                    confidence_score=seg.get("confidence_score"),
                    sequence=seg["sequence"],
                )
            )

    snap_dir = resolved_data_dir / "snapshots" / new_job.job_id
    for s in data.get("snapshots", []):
        filename = Path(s["file_path"]).name
        file_path = snap_dir / filename
        if s.get("image_base64"):
            snap_dir.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(base64.b64decode(s["image_base64"]))
        db.add(
            Snapshot(
                job_id=new_job.id,
                file_path=str(file_path),
                timestamp=s["timestamp"],
                relevance_score=s.get("relevance_score"),
                detected_text=s.get("detected_text"),
                image_width=s.get("image_width"),
                image_height=s.get("image_height"),
                file_size=s.get("file_size"),
            )
        )

    for d in data.get("documents", []):
        db.add(
            Document(
                job_id=new_job.id,
                title=d["title"],
                content=d["content"],
                format=d.get("format", "markdown"),
            )
        )

    for log in data.get("logs", []):
        level_str = log.get("level", "info").upper()
        try:
            level_enum = LogLevel[level_str]
        except KeyError:
            level_enum = LogLevel.INFO
        db.add(
            JobLog(
                job_id=new_job.id,
                level=level_enum,
                message=log["message"],
                step=log.get("step"),
            )
        )

    db.commit()
    db.refresh(new_job)
    return new_job
