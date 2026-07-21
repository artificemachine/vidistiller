"""
Database Models (SQLAlchemy ORM)

Defines all SQLAlchemy ORM models for the YouTube Tutorial to Doc Converter.
Uses SQLAlchemy 2.0+ with DeclarativeBase pattern.

All models include:
- Proper relationships and foreign keys
- Timestamps (created_at, updated_at) for audit trails
- Indexes for query performance
- Helper methods where appropriate
"""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import uuid4
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Boolean, Enum, Index, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from .session import Base


# ==============================================================================
# ENUMS
# ==============================================================================

class ProcessingStatus(PyEnum):
    """Status of a processing job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingMode(PyEnum):
    """Processing mode for a job."""
    STANDARD = "standard"
    SLIDE_AWARE = "slide_aware"


class LogLevel(PyEnum):
    """Severity level for job log entries."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ==============================================================================
# PROCESSINGJOB MODEL (Parent aggregate)
# ==============================================================================

class ProcessingJob(Base):
    """
    Root processing job that aggregates all work for a YouTube video conversion.

    One ProcessingJob can have:
    - 1 Video record
    - 0-1 Transcript records
    - 0-N Snapshot records
    - 0-1 Document records
    """

    __tablename__ = "processing_jobs"

    id: int = Column(Integer, primary_key=True)
    job_id: str = Column(String(36), unique=True, default=lambda: str(uuid4()), nullable=False)
    status: ProcessingStatus = Column(Enum(ProcessingStatus, values_callable=lambda x: [e.value for e in x]), default=ProcessingStatus.PENDING, nullable=False)
    error_message: Optional[str] = Column(String(1024), nullable=True)
    video_url: Optional[str] = Column(String(512), nullable=True)
    source_type: Optional[str] = Column(String(20), nullable=True)
    video_file_path: Optional[str] = Column(String(512), nullable=True)  # path to downloaded MP4
    celery_task_id: Optional[str] = Column(String(255), nullable=True)
    summarize_status: Optional[str] = Column(String(20), nullable=True)
    slide_status: Optional[str] = Column(String(20), nullable=True)
    processing_mode: Optional[str] = Column(String(20), nullable=True, server_default="standard")
    # Preferred caption language (ISO 639-1). None means "let the pipeline
    # decide" (defaults to English). Set explicitly so an auto-dubbed video is
    # transcribed in the language the user asked for, not the first dub track.
    caption_language: Optional[str] = Column(String(10), nullable=True)
    user_id: Optional[int] = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships (cascade delete orphaned children)
    user = relationship("User", back_populates="jobs")
    videos = relationship("Video", back_populates="job", cascade="all, delete-orphan")
    transcripts = relationship("Transcript", back_populates="job", cascade="all, delete-orphan")
    snapshots = relationship("Snapshot", back_populates="job", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="job", cascade="all, delete-orphan")
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan", order_by="JobLog.created_at")
    slides = relationship("Slide", back_populates="job", cascade="all, delete-orphan", order_by="Slide.slide_number")
    slide_detection_metadata = relationship("SlideDetectionMetadata", back_populates="job", uselist=False, cascade="all, delete-orphan")

    # Index on job_id for quick lookup
    __table_args__ = (
        Index("ix_processing_jobs_job_id", "job_id"),
        Index("ix_processing_jobs_status", "status"),
        Index("ix_processing_jobs_created_at", "created_at"),
        Index("ix_processing_jobs_user_id", "user_id"),
        Index("ix_processing_jobs_user_id_created_at", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ProcessingJob(id={self.id}, job_id={self.job_id}, status={self.status.value})>"

    def is_completed(self) -> bool:
        """Check if job has completed successfully."""
        return self.status == ProcessingStatus.COMPLETED

    def is_failed(self) -> bool:
        """Check if job has failed."""
        return self.status == ProcessingStatus.FAILED

    def is_processing(self) -> bool:
        """Check if job is currently processing."""
        return self.status == ProcessingStatus.PROCESSING


# ==============================================================================
# JOB LOG MODEL
# ==============================================================================

class JobLog(Base):
    """Structured log entry for a processing job."""

    __tablename__ = "job_logs"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False)
    level: LogLevel = Column(Enum(LogLevel, values_callable=lambda x: [e.value for e in x]), default=LogLevel.INFO, nullable=False)
    message: str = Column(String(1024), nullable=False)
    step: Optional[str] = Column(String(100), nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="logs")

    # Indexes
    __table_args__ = (
        Index("ix_job_logs_job_id_created_at", "job_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<JobLog(id={self.id}, job_id={self.job_id}, level={self.level.value}, step={self.step})>"


# ==============================================================================
# VIDEO MODEL
# ==============================================================================

class Video(Base):
    """YouTube video metadata and content information."""

    __tablename__ = "videos"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id"), nullable=False)
    url: str = Column(String(512), nullable=False)
    video_id: str = Column(String(100), nullable=False)
    source_type: Optional[str] = Column(String(20), nullable=True)
    title: str = Column(String(512), nullable=False)
    description: Optional[str] = Column(Text, nullable=True)
    duration: Optional[int] = Column(Integer, nullable=True)  # seconds
    thumbnail_url: Optional[str] = Column(String(512), nullable=True)
    channel_name: Optional[str] = Column(String(255), nullable=True)
    upload_date: Optional[datetime] = Column(DateTime, nullable=True)
    view_count: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="videos")

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint("video_id", "job_id", name="uq_videos_video_id_job_id"),
        Index("ix_videos_job_id", "job_id"),
        Index("ix_videos_video_id", "video_id"),
        Index("ix_videos_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Video(id={self.id}, video_id={self.video_id}, title={self.title[:30]}...)>"


# ==============================================================================
# TRANSCRIPT MODEL
# ==============================================================================

class Transcript(Base):
    """Full transcript of video audio."""

    __tablename__ = "transcripts"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id"), nullable=False)
    full_text: str = Column(Text, nullable=False)
    language: str = Column(String(10), default="en", nullable=False)
    source: Optional[str] = Column(String(50), nullable=True)  # youtube_captions, whisper_api, whisper_local
    confidence_score: Optional[float] = Column(Float, nullable=True)  # 0.0-1.0
    duration: Optional[int] = Column(Integer, nullable=True)  # seconds
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="transcripts")
    segments = relationship("TranscriptSegment", back_populates="transcript", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_transcripts_job_id", "job_id"),
        Index("ix_transcripts_language", "language"),
    )

    def __repr__(self) -> str:
        return f"<Transcript(id={self.id}, job_id={self.job_id}, language={self.language})>"


# ==============================================================================
# TRANSCRIPT SEGMENT MODEL
# ==============================================================================

class TranscriptSegment(Base):
    """
    Segmented transcript with timing information.

    One Transcript contains many TranscriptSegments.
    """

    __tablename__ = "transcript_segments"

    id: int = Column(Integer, primary_key=True)
    transcript_id: int = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    text: str = Column(String(2048), nullable=False)
    start_time: float = Column(Float, nullable=False)  # seconds
    end_time: float = Column(Float, nullable=False)  # seconds
    speaker: Optional[str] = Column(String(255), nullable=True)
    confidence_score: Optional[float] = Column(Float, nullable=True)  # 0.0-1.0
    sequence: int = Column(Integer, nullable=False)  # order in transcript
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    transcript = relationship("Transcript", back_populates="segments")

    # Indexes
    __table_args__ = (
        Index("ix_transcript_segments_transcript_id_sequence", "transcript_id", "sequence"),
        Index("ix_transcript_segments_start_time", "start_time"),
    )

    def __repr__(self) -> str:
        return f"<TranscriptSegment(id={self.id}, transcript_id={self.transcript_id}, sequence={self.sequence})>"


# ==============================================================================
# SNAPSHOT MODEL
# ==============================================================================

class Snapshot(Base):
    """
    Extracted video frame (snapshot) at specific timestamp.

    One ProcessingJob can have many Snapshots.
    """

    __tablename__ = "snapshots"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id"), nullable=False)
    file_path: str = Column(String(512), nullable=False)  # relative path to image
    timestamp: float = Column(Float, nullable=False)  # seconds in video
    relevance_score: Optional[float] = Column(Float, nullable=True)  # 0.0-1.0, importance
    detected_text: Optional[str] = Column(Text, nullable=True)  # OCR results
    image_width: Optional[int] = Column(Integer, nullable=True)  # pixels
    image_height: Optional[int] = Column(Integer, nullable=True)  # pixels
    file_size: Optional[int] = Column(Integer, nullable=True)  # bytes
    slide_id: Optional[int] = Column(Integer, ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    ssim_delta_vs_prev: Optional[float] = Column(Float, nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="snapshots")
    slide = relationship("Slide", back_populates="snapshots")

    # Indexes
    __table_args__ = (
        Index("ix_snapshots_job_id_timestamp", "job_id", "timestamp"),
        Index("ix_snapshots_relevance_score", "relevance_score"),
    )

    def __repr__(self) -> str:
        return f"<Snapshot(id={self.id}, job_id={self.job_id}, timestamp={self.timestamp:.2f}s)>"


# ==============================================================================
# DOCUMENT MODEL
# ==============================================================================

class Document(Base):
    """Generated documentation in various formats."""

    __tablename__ = "documents"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id"), nullable=False)
    title: str = Column(String(512), nullable=False)
    content: str = Column(Text, nullable=False)
    format: str = Column(String(50), default="markdown", nullable=False)  # markdown, html, pdf
    file_path: Optional[str] = Column(String(512), nullable=True)  # relative path to file
    file_size: Optional[int] = Column(Integer, nullable=True)  # bytes
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="documents")

    # Indexes
    __table_args__ = (
        Index("ix_documents_job_id_format", "job_id", "format"),
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, job_id={self.job_id}, format={self.format})>"


# ==============================================================================
# SLIDE MODEL
# ==============================================================================

class Slide(Base):
    """
    Detected slide from a presentation-style video.

    One ProcessingJob can have many Slides (only when processing_mode='slide_aware').
    """

    __tablename__ = "slides"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False)
    slide_number: int = Column(Integer, nullable=False)
    start_timestamp: float = Column(Float, nullable=False)
    end_timestamp: float = Column(Float, nullable=False)
    final_frame_path: Optional[str] = Column(String(512), nullable=True)
    ocr_text: Optional[str] = Column(Text, nullable=True)
    transcript_text: Optional[str] = Column(Text, nullable=True)
    layout_type: Optional[str] = Column(String(50), nullable=True)
    ssim_transition_score: Optional[float] = Column(Float, nullable=True)
    is_incremental_build: bool = Column(Boolean, default=False, nullable=False)
    parent_slide_id: Optional[int] = Column(Integer, ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    image_width: Optional[int] = Column(Integer, nullable=True)
    image_height: Optional[int] = Column(Integer, nullable=True)
    file_size: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="slides")
    snapshots = relationship("Snapshot", back_populates="slide")
    parent = relationship("Slide", remote_side=[id], backref="children")

    # Indexes
    __table_args__ = (
        Index("ix_slides_job_id_slide_number", "job_id", "slide_number"),
        Index("ix_slides_job_id_start_timestamp", "job_id", "start_timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Slide(id={self.id}, job_id={self.job_id}, slide_number={self.slide_number})>"


# ==============================================================================
# SLIDE DETECTION METADATA MODEL
# ==============================================================================

class SlideDetectionMetadata(Base):
    """
    Metadata about the slide detection process for a job.

    One ProcessingJob has at most one SlideDetectionMetadata record.
    """

    __tablename__ = "slide_detection_metadata"

    id: int = Column(Integer, primary_key=True)
    job_id: int = Column(Integer, ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    total_frames_sampled: Optional[int] = Column(Integer, nullable=True)
    sampling_fps: Optional[float] = Column(Float, nullable=True)
    ssim_threshold: Optional[float] = Column(Float, nullable=True)
    ssim_ambiguous_low: Optional[float] = Column(Float, nullable=True)
    ssim_ambiguous_high: Optional[float] = Column(Float, nullable=True)
    layout_type_detected: Optional[str] = Column(String(50), nullable=True)
    total_slides: Optional[int] = Column(Integer, nullable=True)
    total_transitions: Optional[int] = Column(Integer, nullable=True)
    llm_classifications_count: Optional[int] = Column(Integer, nullable=True)
    ocr_enabled: Optional[bool] = Column(Boolean, nullable=True)
    processing_time_seconds: Optional[float] = Column(Float, nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    job = relationship("ProcessingJob", back_populates="slide_detection_metadata")

    # Indexes
    __table_args__ = (
        Index("ix_slide_detection_metadata_job_id", "job_id"),
    )

    def __repr__(self) -> str:
        return f"<SlideDetectionMetadata(id={self.id}, job_id={self.job_id}, total_slides={self.total_slides})>"


# ==============================================================================
# USER MODEL (Optional - for future authentication)
# ==============================================================================

class User(Base):
    """User account for authentication and job ownership tracking."""

    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True)
    username: str = Column(String(255), unique=True, nullable=False)
    email: str = Column(String(255), unique=True, nullable=False)
    password_hash: str = Column(String(255), nullable=False)
    full_name: Optional[str] = Column(String(255), nullable=True)
    is_active: bool = Column(Boolean, default=True, nullable=False)
    password_reset_token: Optional[str] = Column(String(512), nullable=True)
    password_reset_expires: Optional[datetime] = Column(DateTime, nullable=True)
    llm_provider: Optional[str] = Column(String(20), nullable=True)
    llm_model: Optional[str] = Column(String(100), nullable=True)
    llm_api_key_encrypted: Optional[str] = Column(Text, nullable=True)
    llm_ollama_url: Optional[str] = Column(String(512), nullable=True)
    summary_language: Optional[str] = Column(String(10), nullable=True)
    created_at: datetime = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    jobs = relationship("ProcessingJob", back_populates="user")

    # Indexes
    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
