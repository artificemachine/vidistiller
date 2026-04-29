"""
Pydantic Schemas for API Request/Response Validation

Defines all Pydantic models for the YouTube Tutorial to Doc Converter API.
Uses Pydantic v2 with model_validator and ConfigDict patterns.

Schema Categories:
- Job: Processing job creation and status
- Video: YouTube video metadata
- Transcript: Full transcripts and segments
- Snapshot: Video frame captures
- Document: Generated documentation
- User: Authentication and user management
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, field_validator, EmailStr
import re


def _validate_password_strength(v: str) -> str:
    """Validate password meets complexity requirements (uppercase, lowercase, digit)."""
    if not re.search(r'[A-Z]', v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r'\d', v):
        raise ValueError("Password must contain at least one digit")
    return v


# ==============================================================================
# ENUMS (Mirror database enums for API)
# ==============================================================================

class ProcessingStatusEnum(str, Enum):
    """Processing job status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocumentFormatEnum(str, Enum):
    """Supported document output formats."""
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    SUMMARY = "summary"


class TranscriptSourceEnum(str, Enum):
    """Source of transcript extraction."""
    YOUTUBE_CAPTIONS = "youtube_captions"
    YT_DLP_CAPTIONS = "yt_dlp_captions"
    WHISPER_API = "whisper_api"
    WHISPER_LOCAL = "whisper_local"


class LogLevelEnum(str, Enum):
    """Log severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ==============================================================================
# BASE CONFIGURATION
# ==============================================================================

class BaseSchema(BaseModel):
    """Base schema with ORM mode enabled for SQLAlchemy compatibility."""
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# JOB LOG SCHEMAS
# ==============================================================================

class JobLogResponse(BaseSchema):
    """Response schema for a job log entry."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    level: LogLevelEnum = Field(..., description="Log severity level")
    message: str = Field(..., description="Log message")
    step: Optional[str] = Field(None, description="Processing step name")
    created_at: datetime = Field(..., description="Log entry timestamp")


# ==============================================================================
# VIDEO SCHEMAS
# ==============================================================================

class VideoBase(BaseSchema):
    """Base video fields shared across schemas."""
    url: str = Field(..., description="Video source URL")
    video_id: str = Field(..., min_length=1, max_length=100, description="Platform-native video ID")
    source_type: Optional[str] = Field(None, description="Source platform (youtube, vimeo, twitch, etc.)")
    title: str = Field(..., min_length=1, max_length=512, description="Video title")
    description: Optional[str] = Field(None, description="Video description")
    duration: Optional[int] = Field(None, ge=0, description="Video duration in seconds")
    thumbnail_url: Optional[str] = Field(None, max_length=512, description="Thumbnail image URL")
    channel_name: Optional[str] = Field(None, max_length=255, description="Channel or uploader name")
    upload_date: Optional[datetime] = Field(None, description="Video upload date")
    view_count: Optional[int] = Field(None, ge=0, description="Number of views")


class VideoResponse(VideoBase):
    """Video response with database fields."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": 1,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "video_id": "dQw4w9WgXcQ",
                "title": "Sample Tutorial Video",
                "description": "A comprehensive tutorial on...",
                "duration": 3600,
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
                "channel_name": "Tutorial Channel",
                "upload_date": "2024-01-15T10:30:00",
                "view_count": 150000,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:30:00"
            }
        }
    )


# ==============================================================================
# TRANSCRIPT SEGMENT SCHEMAS
# ==============================================================================

class TranscriptSegmentBase(BaseSchema):
    """Base transcript segment fields."""
    text: str = Field(..., min_length=1, max_length=2048, description="Segment text content")
    start_time: float = Field(..., ge=0, description="Start time in seconds")
    end_time: float = Field(..., ge=0, description="End time in seconds")
    speaker: Optional[str] = Field(None, max_length=255, description="Speaker identification")
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Transcription confidence (0.0-1.0)")
    sequence: int = Field(..., ge=0, description="Order in transcript")


class TranscriptSegmentResponse(TranscriptSegmentBase):
    """Transcript segment response with database fields."""
    id: int = Field(..., description="Database ID")
    transcript_id: int = Field(..., description="Parent transcript ID")
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "transcript_id": 1,
                "text": "Welcome to this tutorial on Python programming.",
                "start_time": 0.0,
                "end_time": 3.5,
                "speaker": "Host",
                "confidence_score": 0.95,
                "sequence": 0,
                "created_at": "2024-01-20T14:30:00"
            }
        }
    )


# ==============================================================================
# TRANSCRIPT SCHEMAS
# ==============================================================================

class TranscriptBase(BaseSchema):
    """Base transcript fields."""
    full_text: str = Field(..., min_length=1, description="Complete transcript text")
    language: str = Field(default="en", min_length=2, max_length=10, description="Transcript language code (ISO 639-1)")
    source: Optional[TranscriptSourceEnum] = Field(None, description="Transcript extraction source")
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Overall confidence score (0.0-1.0)")
    duration: Optional[int] = Field(None, ge=0, description="Audio duration in seconds")


class TranscriptResponse(TranscriptBase):
    """Transcript response with database fields and nested segments."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    segments: List[TranscriptSegmentResponse] = Field(default_factory=list, description="Transcript segments with timing")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": 1,
                "full_text": "Welcome to this tutorial...",
                "language": "en",
                "source": "youtube_captions",
                "confidence_score": 0.92,
                "duration": 3600,
                "segments": [],
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:30:00"
            }
        }
    )


# ==============================================================================
# SNAPSHOT SCHEMAS
# ==============================================================================

class SnapshotBase(BaseSchema):
    """Base snapshot fields."""
    file_path: str = Field(..., min_length=1, max_length=512, description="Path to snapshot image file")
    timestamp: float = Field(..., ge=0, description="Video timestamp in seconds")
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Content relevance score (0.0-1.0)")
    detected_text: Optional[str] = Field(None, description="OCR-extracted text from image")
    image_width: Optional[int] = Field(None, ge=1, description="Image width in pixels")
    image_height: Optional[int] = Field(None, ge=1, description="Image height in pixels")
    file_size: Optional[int] = Field(None, ge=0, description="File size in bytes")


class SnapshotCaptureRequest(BaseModel):
    """Request to capture a snapshot at a specific timestamp."""
    job_id: str = Field(..., description="Job UUID")
    timestamp: float = Field(..., ge=0, description="Video timestamp in seconds")


class SnapshotResponse(SnapshotBase):
    """Snapshot response with database fields."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    image_url: Optional[str] = Field(None, description="Public URL to snapshot image")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": 1,
                "file_path": "snapshots/job_abc123/frame_00120.png",
                "timestamp": 120.5,
                "relevance_score": 0.85,
                "detected_text": "Code Example: def hello_world():",
                "image_width": 1920,
                "image_height": 1080,
                "file_size": 245760,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:30:00"
            }
        }
    )


# ==============================================================================
# SLIDE SCHEMAS
# ==============================================================================

class SlideResponse(BaseModel):
    """Slide response for API."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    slide_number: int = Field(..., description="Slide number in sequence")
    start_timestamp: float = Field(..., description="Start timestamp in seconds")
    end_timestamp: float = Field(..., description="End timestamp in seconds")
    final_frame_path: Optional[str] = Field(None, description="Path to final frame image")
    image_url: Optional[str] = Field(None, description="Public URL to slide image")
    ocr_text: Optional[str] = Field(None, description="OCR-extracted text from slide")
    transcript_text: Optional[str] = Field(None, description="Aligned transcript text")
    layout_type: Optional[str] = Field(None, description="Detected layout type")
    ssim_transition_score: Optional[float] = Field(None, description="SSIM score at transition")
    is_incremental_build: bool = Field(False, description="Whether this is an incremental build of a previous slide")
    parent_slide_id: Optional[int] = Field(None, description="Parent slide ID for incremental builds")
    image_width: Optional[int] = Field(None, description="Image width in pixels")
    image_height: Optional[int] = Field(None, description="Image height in pixels")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class SlideDetectionMetadataResponse(BaseModel):
    """Slide detection metadata response."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    total_frames_sampled: Optional[int] = Field(None, description="Total frames analysed")
    sampling_fps: Optional[float] = Field(None, description="Sampling rate used")
    ssim_threshold: Optional[float] = Field(None, description="SSIM threshold")
    ssim_ambiguous_low: Optional[float] = Field(None, description="Ambiguous range lower bound")
    ssim_ambiguous_high: Optional[float] = Field(None, description="Ambiguous range upper bound")
    layout_type_detected: Optional[str] = Field(None, description="Detected layout type")
    total_slides: Optional[int] = Field(None, description="Total slides detected")
    total_transitions: Optional[int] = Field(None, description="Total transitions found")
    llm_classifications_count: Optional[int] = Field(None, description="LLM classification calls")
    ocr_enabled: Optional[bool] = Field(None, description="Whether OCR was enabled")
    processing_time_seconds: Optional[float] = Field(None, description="Total processing time")
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# DOCUMENT SCHEMAS
# ==============================================================================

class DocumentBase(BaseSchema):
    """Base document fields."""
    title: str = Field(..., min_length=1, max_length=512, description="Document title")
    content: str = Field(..., min_length=1, description="Document content")
    format: DocumentFormatEnum = Field(default=DocumentFormatEnum.MARKDOWN, description="Document format")
    file_path: Optional[str] = Field(None, max_length=512, description="Path to generated file")
    file_size: Optional[int] = Field(None, ge=0, description="File size in bytes")


class DocumentResponse(DocumentBase):
    """Document response with database fields."""
    id: int = Field(..., description="Database ID")
    job_id: int = Field(..., description="Associated processing job ID")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": 1,
                "title": "Python Programming Tutorial",
                "content": "# Python Programming Tutorial\n\n## Introduction\n...",
                "format": "markdown",
                "file_path": "documents/job_abc123/tutorial.md",
                "file_size": 15360,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:30:00"
            }
        }
    )


# ==============================================================================
# JOB SCHEMAS
# ==============================================================================

class JobCreate(BaseModel):
    """Schema for creating a new processing job."""
    video_url: str = Field(
        ...,
        min_length=10,
        max_length=512,
        description="Video URL to process (YouTube, Vimeo, Twitch, Twitter/X, TikTok, Reddit, Rumble, or direct MP4)"
    )
    output_format: DocumentFormatEnum = Field(
        default=DocumentFormatEnum.MARKDOWN,
        description="Desired output document format"
    )
    extract_snapshots: bool = Field(
        default=True,
        description="Whether to extract video snapshots"
    )
    is_slide_mode: bool = Field(
        default=False,
        description="Enable presentation/slide-aware processing mode"
    )

    @field_validator("video_url")
    @classmethod
    def validate_video_url(cls, v: str) -> str:
        """Accept any well-formed HTTP/HTTPS URL."""
        from urllib.parse import urlparse
        v = v.strip()
        if not re.match(r'^https?://', v, re.IGNORECASE):
            raise ValueError("URL must start with http:// or https://")
        parsed = urlparse(v)
        if not parsed.netloc or '.' not in parsed.netloc:
            raise ValueError("Invalid URL: missing or malformed host")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "output_format": "markdown",
                "extract_snapshots": True
            }
        }
    )


class JobStatusResponse(BaseSchema):
    """Lightweight job status response for polling."""
    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: ProcessingStatusEnum = Field(..., description="Current processing status")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    summarize_status: Optional[str] = Field(None, description="Summarization status (processing/completed/failed)")
    processing_mode: Optional[str] = Field(None, description="Processing mode (standard or slide_aware)")
    video_url: Optional[str] = Field(None, description="Original video URL")
    source_type: Optional[str] = Field(None, description="Source platform (youtube, vimeo, twitch, etc.)")
    video_title: Optional[str] = Field(None, description="Video title")
    user_id: Optional[int] = Field(None, description="Owner user ID")
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last status update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "processing",
                "error_message": None,
                "summarize_status": None,
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "source_type": "youtube",
                "video_title": "Sample Tutorial Video",
                "user_id": 1,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:35:00"
            }
        }
    )


class JobResponse(BaseSchema):
    """Full job response with all related data."""
    id: int = Field(..., description="Database ID")
    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: ProcessingStatusEnum = Field(..., description="Current processing status")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    summarize_status: Optional[str] = Field(None, description="Summarization status (processing/completed/failed)")
    processing_mode: Optional[str] = Field(None, description="Processing mode (standard or slide_aware)")
    video_url: Optional[str] = Field(None, description="Original video URL")
    source_type: Optional[str] = Field(None, description="Source platform (youtube, vimeo, twitch, etc.)")
    user_id: Optional[int] = Field(None, description="Owner user ID")
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    # Nested relationships
    videos: List[VideoResponse] = Field(default_factory=list, description="Associated video metadata")
    transcripts: List[TranscriptResponse] = Field(default_factory=list, description="Generated transcripts")
    snapshots: List[SnapshotResponse] = Field(default_factory=list, description="Extracted snapshots")
    documents: List[DocumentResponse] = Field(default_factory=list, description="Generated documents")
    slides: List[SlideResponse] = Field(default_factory=list, description="Detected slides (slide_aware mode)")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "error_message": None,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:45:00",
                "videos": [],
                "transcripts": [],
                "snapshots": [],
                "documents": []
            }
        }
    )


# ==============================================================================
# USER & AUTHENTICATION SCHEMAS
# ==============================================================================

class UserCreate(BaseModel):
    """Schema for user registration."""
    username: str = Field(
        ...,
        min_length=3,
        max_length=255,
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Username (alphanumeric, underscore, hyphen)"
    )
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (minimum 8 characters)"
    )
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "johndoe",
                "email": "john.doe@example.com",
                "password": "SecurePass123",
                "full_name": "John Doe"
            }
        }
    )


class UserLogin(BaseModel):
    """Schema for user login."""
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="User password")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "johndoe",
                "password": "SecurePass123"
            }
        }
    )


class UserResponse(BaseSchema):
    """Safe user response (excludes password and encrypted API keys)."""
    id: int = Field(..., description="Database ID")
    username: str = Field(..., description="Username")
    email: EmailStr = Field(..., description="Email address")
    full_name: Optional[str] = Field(None, description="User's full name")
    is_active: bool = Field(..., description="Account active status")
    llm_provider: Optional[str] = Field(None, description="LLM provider choice (anthropic/openai/ollama)")
    llm_model: Optional[str] = Field(None, description="Model name for the selected provider")
    has_api_key: bool = Field(default=False, description="Whether user has stored an API key")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "username": "johndoe",
                "email": "john.doe@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "llm_provider": "anthropic",
                "llm_model": "claude-sonnet-4-6",
                "has_api_key": True,
                "created_at": "2024-01-20T14:30:00",
                "updated_at": "2024-01-20T14:30:00"
            }
        }
    )


class Token(BaseModel):
    """JWT token response."""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="JWT refresh token (7-day expiry)")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600
            }
        }
    )


class UserSettingsUpdate(BaseModel):
    """Schema for updating user LLM settings."""
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider (anthropic, openai, ollama, or vllm)",
        pattern="^(anthropic|openai|ollama|vllm)$"
    )
    llm_model: Optional[str] = Field(
        None,
        max_length=100,
        description="Model name for the selected provider"
    )
    llm_api_key: Optional[str] = Field(
        None,
        description="API key for cloud providers (leave empty to clear)"
    )
    llm_ollama_url: Optional[str] = Field(
        None,
        max_length=512,
        description="Custom base URL for Ollama or vLLM sidecar (e.g. http://10.255.150.36:8100)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "llm_provider": "anthropic",
                "llm_model": "claude-sonnet-4-6",
                "llm_api_key": "sk-ant-..."
            }
        }
    )


class UserSettingsResponse(BaseSchema):
    """Response for user LLM settings (excludes actual API key)."""
    llm_provider: Optional[str] = Field(None, description="LLM provider")
    llm_model: Optional[str] = Field(None, description="Model name")
    llm_ollama_url: Optional[str] = Field(None, description="Custom Ollama URL")
    has_api_key: bool = Field(default=False, description="Whether an API key is stored")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "llm_provider": "anthropic",
                "llm_model": "claude-sonnet-4-6",
                "llm_ollama_url": None,
                "has_api_key": True
            }
        }
    )


class TokenPayload(BaseModel):
    """JWT token payload for decoding."""
    sub: str = Field(..., description="Subject (user ID)")
    exp: datetime = Field(..., description="Expiration timestamp")
    iat: datetime = Field(..., description="Issued at timestamp")


class PasswordResetRequest(BaseModel):
    """Schema for requesting a password reset email."""
    email: EmailStr = Field(..., description="Email address associated with the account")


class PasswordResetConfirm(BaseModel):
    """Schema for confirming a password reset with a new password."""
    token: str = Field(..., description="Password reset token from email link")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (minimum 8 characters)",
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str = Field(..., description="Response message")


# ==============================================================================
# PAGINATION & LIST SCHEMAS
# ==============================================================================

class PaginationParams(BaseModel):
    """Pagination query parameters."""
    skip: int = Field(default=0, ge=0, description="Number of records to skip")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum records to return")


class JobListResponse(BaseModel):
    """Paginated list of jobs."""
    items: List[JobStatusResponse] = Field(..., description="List of jobs")
    total: int = Field(..., ge=0, description="Total number of jobs")
    skip: int = Field(..., ge=0, description="Records skipped")
    limit: int = Field(..., ge=1, description="Maximum records returned")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 42,
                "skip": 0,
                "limit": 20
            }
        }
    )


# ==============================================================================
# ERROR SCHEMAS
# ==============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Application-specific error code")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Job not found",
                "error_code": "JOB_NOT_FOUND"
            }
        }
    )


class ValidationErrorDetail(BaseModel):
    """Validation error detail."""
    loc: List[str] = Field(..., description="Error location (field path)")
    msg: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")


class ValidationErrorResponse(BaseModel):
    """Validation error response."""
    detail: List[ValidationErrorDetail] = Field(..., description="List of validation errors")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": [
                    {
                        "loc": ["body", "video_url"],
                        "msg": "Invalid YouTube URL",
                        "type": "value_error"
                    }
                ]
            }
        }
    )
