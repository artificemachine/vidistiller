"""Diagnostics routes for checking external service health."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Environment, get_settings
from app.db.models import User
from app.routes.auth import get_current_user_from_token
from app.services.llm import LLMService

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


@router.get("/ollama")
def ollama_diagnostics(
    current_user: User = Depends(get_current_user_from_token),
) -> dict:
    """Run Ollama connectivity diagnostics and return actionable info.

    Requires authentication. Returns diagnostic info regardless of Ollama being up.
    """
    _ = current_user
    service = LLMService()
    return service.diagnose_ollama()
