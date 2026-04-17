"""
API Models and Schemas

Pydantic models for request/response validation and OpenAPI documentation.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ==============================================================================
# JOB MODELS
# ==============================================================================

class JobCreateRequest(BaseModel):
    """Request to create a new processing job."""
    video_url: str = Field(..., description="Video URL")


class JobResponse(BaseModel):
    """Job status and details response."""
    id: int
    job_id: str = Field(..., description="Unique UUID for job")
    status: str
    error_message: Optional[str] = None
    video_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """List of jobs with pagination."""
    count: int
    jobs: List[JobResponse]


class JobDetailResponse(JobResponse):
    """Detailed job response with all related data."""
    videos: List['VideoResponse'] = []
    transcripts: List['TranscriptResponse'] = []
    snapshots: List['SnapshotResponse'] = []
    documents: List['DocumentResponse'] = []


# ==============================================================================
# VIDEO MODELS
# ==============================================================================

class VideoResponse(BaseModel):
    """Video metadata response."""
    id: int
    job_id: int
    url: str
    video_id: str
    title: str
    description: Optional[str] = None
    duration: int = Field(..., description="Duration in seconds")
    thumbnail_url: Optional[str] = None
    channel_name: Optional[str] = None
    upload_date: Optional[datetime] = None
    view_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==============================================================================
# TRANSCRIPT MODELS
# ==============================================================================

class TranscriptSegmentResponse(BaseModel):
    """Single transcript segment."""
    id: int
    transcript_id: int
    text: str
    start_time: float = Field(..., description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    speaker: Optional[str] = None
    confidence_score: float = Field(default=1.0, description="0-1 confidence")
    sequence: int = Field(..., description="Segment order")
    created_at: datetime

    class Config:
        from_attributes = True


class TranscriptResponse(BaseModel):
    """Full transcript with segments."""
    id: int
    job_id: int
    full_text: str
    language: str
    source: str = Field(default="whisper", description="Transcription source")
    confidence_score: float = Field(default=1.0, description="0-1 confidence")
    duration: Optional[int] = None
    segments: List[TranscriptSegmentResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==============================================================================
# SNAPSHOT MODELS
# ==============================================================================

class SnapshotResponse(BaseModel):
    """Video snapshot/frame response."""
    id: int
    job_id: int
    file_path: str
    timestamp: float = Field(..., description="Time in seconds")
    relevance_score: Optional[float] = Field(None, description="0-1 relevance")
    detected_text: Optional[str] = None
    image_url: Optional[str] = Field(None, description="Public URL to snapshot image")
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    file_size: Optional[int] = Field(None, description="Size in bytes")
    created_at: datetime

    class Config:
        from_attributes = True


class SnapshotListResponse(BaseModel):
    """List of snapshots."""
    count: int
    snapshots: List[SnapshotResponse]


# ==============================================================================
# DOCUMENT MODELS
# ==============================================================================

class DocumentResponse(BaseModel):
    """Generated documentation response."""
    id: int
    job_id: int
    title: str
    content: str
    format: str = Field(..., description="markdown, html, or pdf")
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==============================================================================
# AUTHENTICATION MODELS
# ==============================================================================

class UserRegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., description="Valid email address")
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    full_name: Optional[str] = Field(None, max_length=100)


class UserLoginRequest(BaseModel):
    """User login request."""
    username: str = Field(..., description="Username or email")
    password: str = Field(...)


class UserResponse(BaseModel):
    """User profile response."""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(default=1800, description="Seconds until expiry")


class AuthResponse(BaseModel):
    """Authentication response with user data."""
    user: UserResponse
    tokens: TokenResponse


# ==============================================================================
# ERROR MODELS
# ==============================================================================

class ErrorDetail(BaseModel):
    """Error response detail."""
    error: str
    message: str
    status_code: int
    timestamp: datetime


# ==============================================================================
# UPDATE FORWARD REFERENCES
# ==============================================================================

JobDetailResponse.model_rebuild()
