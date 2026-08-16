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

from app.services.metrics import inc, record_latency

logger = logging.getLogger("vidistiller.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request with timing and request ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        inc("requests_total")
        inc("requests_in_flight")
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            record_latency(duration_ms / 1000.0)
            inc("requests_in_flight", -1)

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
            inc("auth_failures_total")
            log_data["user_agent"] = request.headers.get("user-agent", "")
            logger.warning("Auth failure", extra=log_data)
        elif status >= 500:
            inc("requests_5xx_total")
            logger.error("Server error", extra=log_data)
        elif status >= 400:
            inc("requests_4xx_total")
            logger.warning("Client error", extra=log_data)
        else:
            logger.info("Request completed", extra=log_data)

        response.headers["X-Request-ID"] = request_id
        return response
