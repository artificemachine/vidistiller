"""
FastAPI Application Entry Point

This module serves as the entry point for the FastAPI application.
Used by uvicorn and other ASGI servers.

Example:
    Run with uvicorn:
    $ uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from app.main import app

# Export the FastAPI application instance
__all__ = ["app"]
