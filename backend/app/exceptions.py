"""
Custom Exception Classes for Error Handling

Provides application-specific exceptions that are caught by FastAPI exception
handlers and converted to appropriate HTTP responses.
"""
from typing import Optional


class APIException(Exception):
    """Base exception class for all API errors."""

    def __init__(self, message: str, code: str = "API_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ValidationException(APIException):
    """Raised when request validation fails."""

    def __init__(self, message: str):
        super().__init__(message, code="VALIDATION_ERROR")


class ResourceNotFoundException(APIException):
    """Raised when a requested resource is not found."""

    def __init__(self, resource_type: str, resource_id: Optional[str] = None):
        if resource_id:
            message = f"{resource_type} with ID '{resource_id}' not found"
        else:
            message = f"{resource_type} not found"
        super().__init__(message, code="NOT_FOUND")


class VideoProcessingException(APIException):
    """Raised when video processing fails."""

    def __init__(self, message: str):
        super().__init__(message, code="VIDEO_PROCESSING_ERROR")


class TranscriptException(APIException):
    """Raised when transcript processing fails."""

    def __init__(self, message: str):
        super().__init__(message, code="TRANSCRIPT_ERROR")


class SnapshotException(APIException):
    """Raised when snapshot extraction fails."""

    def __init__(self, message: str):
        super().__init__(message, code="SNAPSHOT_ERROR")


class DocumentGenerationException(APIException):
    """Raised when document generation fails."""

    def __init__(self, message: str):
        super().__init__(message, code="DOCUMENT_GENERATION_ERROR")


class AuthenticationException(APIException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTHENTICATION_ERROR")


class AuthorizationException(APIException):
    """Raised when user lacks required permissions."""

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, code="AUTHORIZATION_ERROR")


class RateLimitException(APIException):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, code="RATE_LIMIT_EXCEEDED")


class SlideDetectionException(APIException):
    """Raised when slide detection fails."""

    def __init__(self, message: str):
        super().__init__(message, code="SLIDE_DETECTION_ERROR")
