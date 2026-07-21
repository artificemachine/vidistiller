"""
FastAPI Application Entry Point

Initializes the FastAPI application with:
- CORS middleware configuration
- Database session dependency
- Error handlers for custom exceptions
- Route registration
- Health checks and monitoring
"""

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import os
import sys

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings, Settings, Environment
from sqlalchemy import text
from app.db.session import health_check, engine, Base
from app.routes import router as api_router
from app.routes.media import router as media_router
from app.middleware import RequestLoggingMiddleware
from app.exceptions import (
    APIException,
    AuthenticationException,
    ResourceNotFoundException,
    ValidationException,
)


def _configure_logging(settings: Settings) -> None:
    """Configure structured JSON logging in production, human-readable in dev."""
    level = getattr(logging, settings.logging.LOG_LEVEL.upper(), logging.INFO)

    if settings.environment == Environment.PRODUCTION:
        from pythonjsonlogger.json import JsonFormatter
        formatter = JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy third-party loggers
    for name in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _init_sentry(settings: Settings) -> None:
    """Initialize Sentry SDK if enabled."""
    if not settings.sentry.enabled or not settings.sentry.dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=settings.sentry.dsn,
        environment=settings.sentry.environment,
        traces_sample_rate=settings.sentry.traces_sample_rate,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )


logger = logging.getLogger(__name__)

# Initialize settings and logging
settings = get_settings()
_configure_logging(settings)
_init_sentry(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify database connectivity and ensure tables exist on startup."""
    try:
        health_check()
        logger.info("✅ Database connection healthy on startup")
    except Exception as e:
        logger.error(f"❌ Database health check failed on startup: {e}")
        raise

    import app.db.models  # noqa: F401 — register models with Base metadata
    Base.metadata.create_all(bind=engine)

    # Ensure nullable columns added after initial schema creation exist on older DBs.
    # create_all() does not ALTER existing tables, so we add missing columns explicitly.
    with engine.connect() as conn:
        for col_def in [
            "ALTER TABLE processing_jobs ADD COLUMN slide_status VARCHAR(20)",
        ]:
            try:
                conn.execute(text(col_def))
                conn.commit()
            except Exception:
                pass  # column already exists

    yield


app = FastAPI(
    title="Vidistiller API",
    description="Turn any video into structured documentation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware (runs after CORS)
app.add_middleware(RequestLoggingMiddleware)


# Snapshot and slide images are served by app.routes.media, not a StaticFiles
# mount. A mount has no notion of who is asking, and frame filenames are
# deterministic, so a leaked job UUID exposed that job's entire frame set to
# anyone. The routes below authenticate the caller and check job ownership.
_data_dir = settings.storage.data_dir or str(Path(__file__).resolve().parent.parent / "data")
_data_root = Path(_data_dir)
(_data_root / "snapshots").mkdir(parents=True, exist_ok=True)
(_data_root / "slides").mkdir(parents=True, exist_ok=True)

app.include_router(media_router)


# ==============================================================================
# EXCEPTION HANDLERS
# ==============================================================================

@app.exception_handler(AuthenticationException)
async def authentication_exception_handler(request: Request, exc: AuthenticationException):
    """Handle 401 Authentication errors."""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "error": "AUTHENTICATION_ERROR",
            "message": str(exc),
            "path": str(request.url.path),
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(ResourceNotFoundException)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundException):
    """Handle 404 Not Found errors."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "NOT_FOUND",
            "message": str(exc),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(ValidationException)
async def validation_exception_handler(request: Request, exc: ValidationException):
    """Handle validation errors."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": str(exc),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    """Strip user input from Pydantic validation errors to prevent data leaks."""
    safe_errors = [
        {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": safe_errors},
    )


@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException):
    """Handle generic API errors."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "API_ERROR",
            "message": str(exc),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception: %s",
        exc,
        extra={"request_id": request_id, "path": str(request.url.path)},
    )
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except ImportError:
        pass
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
            "path": str(request.url.path),
        },
    )


# ==============================================================================
# ROUTES
# ==============================================================================

@app.get("/health", tags=["Health"])
async def health():
    """Liveness check — the process is up. Always 200 if the app is running."""
    return {"status": "healthy"}


@app.get("/readyz", tags=["Health"])
async def readyz():
    """Readiness check — the app can serve traffic.

    Verifies the dependencies a request actually needs (database, and Redis when
    a broker is configured). Returns 503 with per-dependency status when any is
    unreachable, so an orchestrator can stop routing to a pod whose DB is down
    instead of trusting a static 'healthy'.
    """
    checks = {"database": health_check()}

    try:
        import redis as _redis
        client = _redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        client.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    ok = all(checks.values())
    body = {"status": "ready" if ok else "not ready", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)


# Include API routes with /api prefix
app.include_router(api_router, prefix="/api")


# ==============================================================================
# ROOT ENDPOINT
# ==============================================================================

@app.get("/", tags=["Info"])
async def root():
    """API information endpoint."""
    return {
        "name": "Vidistiller API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "docs_alt": "/redoc",
    }
