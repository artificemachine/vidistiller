"""
Request logging middleware for YouTube Model Feeder API.

Generates a unique request ID per request, logs method/path/status/duration,
and attaches the request ID to response headers for traceability.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("youtube-model-feeder.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request with timing and request ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        status = response.status_code
        method = request.method
        path = request.url.path

        log_data = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status,
            "duration_ms": duration_ms,
        }

        if status == 401:
            log_data["user_agent"] = request.headers.get("user-agent", "")
            logger.warning("Auth failure", extra=log_data)
        elif status >= 500:
            logger.error("Server error", extra=log_data)
        elif status >= 400:
            logger.warning("Client error", extra=log_data)
        else:
            logger.info("Request completed", extra=log_data)

        response.headers["X-Request-ID"] = request_id
        return response
