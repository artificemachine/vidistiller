"""
Simple Redis-based rate limiter for FastAPI routes.

Usage:
    @router.post("/login")
    def login(request: Request, _: None = Depends(auth_rate_limit)):
        ...
"""
import os
import logging
from fastapi import Depends, Request
from app.exceptions import RateLimitException

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    """Lazy-initialize Redis client (reuses the same URL as Celery)."""
    global _redis_client
    if _redis_client is None:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def _check_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """
    Sliding-window counter rate limit using Redis INCR + EXPIRE.

    Raises RateLimitException if the limit is exceeded.
    """
    try:
        client = _get_redis()
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_seconds)
        if count > max_requests:
            raise RateLimitException(
                f"Too many requests. Limit: {max_requests} per {window_seconds}s."
            )
    except RateLimitException:
        raise
    except Exception as e:
        # Redis unavailable — log and allow the request through (fail open)
        logger.warning("Rate limiter unavailable, skipping check: %s", e)


def auth_rate_limit(request: Request) -> None:
    """
    Dependency: 10 requests per minute per IP on auth endpoints.
    Protects /auth/login, /auth/register, /auth/forgot-password.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate:auth:{client_ip}"
    _check_rate_limit(key, max_requests=10, window_seconds=60)


def strict_auth_rate_limit(request: Request) -> None:
    """
    Dependency: 5 requests per minute per IP — for login brute-force protection.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate:auth:strict:{client_ip}"
    _check_rate_limit(key, max_requests=5, window_seconds=60)


def job_submit_rate_limit(request: Request) -> None:
    """
    Dependency: 10 job submissions per minute per IP.
    Prevents unbounded Celery task creation from a single authenticated client.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate:jobs:{client_ip}"
    _check_rate_limit(key, max_requests=10, window_seconds=60)
