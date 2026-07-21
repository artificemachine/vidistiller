"""
Video Processing Routes

Provides endpoints for YouTube video metadata retrieval and analysis.
Used to validate videos before creating processing jobs.
"""

from typing import List

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.services.youtube import YouTubeService
from app.services.caption_providers import list_youtube_caption_tracks
from app.core.api_key_auth import get_current_user
from app.db.models import User
from app.exceptions import ValidationException

router = APIRouter(prefix="/videos", tags=["Videos"])

# Initialize YouTube service
youtube_service = YouTubeService()


# ==============================================================================
# SCHEMAS
# ==============================================================================

class YouTubeURLRequest(BaseModel):
    """Request to process YouTube URL."""
    url: str = Field(..., description="YouTube video URL")


class VideoMetadataResponse(BaseModel):
    """Response with video metadata."""
    video_id: str = Field(..., description="YouTube video ID")
    title: str = Field(..., description="Video title")
    description: str = Field(..., description="Video description")
    duration: int = Field(..., ge=0, description="Duration in seconds")
    channel: str = Field(..., description="Channel name")
    upload_date: str = Field(..., description="Upload date (ISO format)")
    view_count: int = Field(..., ge=0, description="Number of views")
    thumbnail_url: str = Field(..., description="Thumbnail image URL")


class CaptionsResponse(BaseModel):
    """Response with video captions."""
    video_id: str = Field(..., description="YouTube video ID")
    captions: str = Field(..., description="Caption text")
    language: str = Field(..., description="Language code")


class CaptionTrack(BaseModel):
    """One selectable caption track."""
    language_code: str = Field(..., description="ISO 639-1 language code")
    language_name: str = Field(..., description="Human-readable track name")
    is_generated: bool = Field(..., description="True for auto-generated tracks")


class CaptionTracksResponse(BaseModel):
    """Available caption tracks for a video."""
    video_id: str = Field(..., description="YouTube video ID")
    tracks: List[CaptionTrack] = Field(default_factory=list, description="Available caption tracks")


class VideoCheckResponse(BaseModel):
    """Response from video availability check."""
    video_id: str = Field(..., description="YouTube video ID")
    available: bool = Field(..., description="Whether video is accessible")
    message: str = Field(..., description="Status message")


# ==============================================================================
# GET VIDEO METADATA - POST /videos/metadata
# ==============================================================================

@router.post(
    "/metadata",
    response_model=VideoMetadataResponse,
    status_code=status.HTTP_200_OK,
    summary="Get video metadata",
    description="Extract metadata from a YouTube video URL",
)
def get_video_metadata(
    request: YouTubeURLRequest,
    current_user: User = Depends(get_current_user),
) -> VideoMetadataResponse:
    """
    Retrieve metadata for a YouTube video.

    Extracts title, description, duration, channel, upload date, view count,
    and thumbnail URL from a YouTube video. Results are cached for 24 hours.

    **Request body:**
    - `url`: YouTube video URL (various formats supported)

    **Response:** Video metadata object

    **Status codes:**
    - 200: Metadata retrieved successfully
    - 422: Invalid YouTube URL
    - 503: Video processing service unavailable

    **Example:**
    ```
    POST /api/videos/metadata
    {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }

    Response:
    {
        "video_id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "description": "...",
        "duration": 212,
        "channel": "Rick Astley",
        "upload_date": "2009-10-25T00:00:00",
        "view_count": 1000000000,
        "thumbnail_url": "https://..."
    }
    ```
    """
    try:
        metadata = youtube_service.get_video_metadata(request.url)
        return VideoMetadataResponse(**metadata)
    except ValidationException:
        raise
    except Exception as e:
        raise ValidationException(f"Failed to retrieve video metadata: {str(e)}")


# ==============================================================================
# GET VIDEO CAPTIONS - POST /videos/captions
# ==============================================================================

@router.post(
    "/captions",
    response_model=CaptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get video captions",
    description="Extract captions from a YouTube video",
)
def get_video_captions(
    request: YouTubeURLRequest,
    language: str = "en",
    current_user: User = Depends(get_current_user),
) -> CaptionsResponse:
    """
    Extract captions from a YouTube video.

    Retrieves available captions in the specified language (or auto-generated
    if not available). Useful as a fallback for transcription.

    **Request body:**
    - `url`: YouTube video URL

    **Query parameters:**
    - `language`: Language code (default: "en")

    **Response:** Captions as plain text

    **Status codes:**
    - 200: Captions retrieved successfully
    - 404: No captions available
    - 422: Invalid YouTube URL
    """
    try:
        video_id = YouTubeService.extract_video_id(request.url)
        captions = youtube_service.get_captions(request.url, language=language)

        if not captions:
            raise ValidationException("No captions available for this video")

        return CaptionsResponse(
            video_id=video_id,
            captions=captions,
            language=language,
        )
    except ValidationException:
        raise
    except Exception as e:
        raise ValidationException(f"Failed to retrieve captions: {str(e)}")


# ==============================================================================
# LIST CAPTION TRACKS - POST /videos/caption-tracks
# ==============================================================================

@router.post(
    "/caption-tracks",
    response_model=CaptionTracksResponse,
    status_code=status.HTTP_200_OK,
    summary="List caption tracks",
    description="List the caption languages a YouTube video offers, so a user can choose one before a job runs.",
)
def get_caption_tracks(
    request: YouTubeURLRequest,
    current_user: User = Depends(get_current_user),
) -> CaptionTracksResponse:
    """
    List available caption tracks for a YouTube video.

    Requires authentication: the request triggers an outbound fetch to YouTube.
    Manually-created tracks (including dubs) are listed before auto-generated
    ones. Returns an empty list when no tracks are available or the source is
    not YouTube.

    **Request body:**
    - `url`: YouTube video URL

    **Response:** `{video_id, tracks: [{language_code, language_name, is_generated}]}`

    **Status codes:**
    - 200: Listed (possibly empty)
    - 401: Not authenticated
    - 422: Invalid YouTube URL
    """
    try:
        video_id = YouTubeService.extract_video_id(request.url)
    except Exception as e:
        raise ValidationException(f"Invalid YouTube URL: {str(e)}")

    tracks = list_youtube_caption_tracks(video_id)
    return CaptionTracksResponse(video_id=video_id, tracks=tracks)


# ==============================================================================
# CHECK VIDEO AVAILABILITY - POST /videos/check
# ==============================================================================

@router.post(
    "/check",
    response_model=VideoCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check video availability",
    description="Verify that a video is accessible and downloadable",
)
def check_video_availability(
    request: YouTubeURLRequest,
    current_user: User = Depends(get_current_user),
) -> VideoCheckResponse:
    """
    Check if a YouTube video is accessible and available for processing.

    Verifies that the video can be accessed (not deleted, age-restricted, etc.)
    and that metadata can be retrieved.

    **Request body:**
    - `url`: YouTube video URL

    **Response:** Availability status

    **Status codes:**
    - 200: Check completed
    - 422: Invalid YouTube URL
    """
    try:
        video_id = YouTubeService.extract_video_id(request.url)
    except Exception as e:
        raise ValidationException(f"Invalid YouTube URL: {str(e)}")

    try:
        youtube_service.get_video_metadata(request.url)
        return VideoCheckResponse(
            video_id=video_id,
            available=True,
            message="Video is accessible and ready for processing",
        )
    except Exception as e:
        return VideoCheckResponse(
            video_id=video_id,
            available=False,
            message=f"Video is not accessible: {str(e)}",
        )
