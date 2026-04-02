"""
API Routes Package Initialization

Centralizes route registration and router management for the FastAPI application.
All route modules are imported here and combined into a single router that gets
included in the main FastAPI app.
"""

from fastapi import APIRouter

# Import route modules
from app.routes.jobs import router as jobs_router
from app.routes.auth import router as auth_router
from app.routes.videos import router as videos_router
from app.routes.snapshots import router as snapshots_router
from app.routes.health import router as health_router
from app.routes.settings import router as settings_router

# Create combined router
router = APIRouter()

# Register all route modules
router.include_router(auth_router)
router.include_router(settings_router)
router.include_router(videos_router)
router.include_router(snapshots_router)
router.include_router(jobs_router)
router.include_router(health_router)

# Export the combined router
__all__ = ["router"]
