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


@router.get("/llm")
def llm_diagnostics(
    current_user: User = Depends(get_current_user_from_token),
) -> dict:
    """Report which LLM the current user is configured for and whether it is reachable.

    Resolves the effective provider/model/endpoint with the same code path jobs
    use (fleet-aware), then probes it. Always returns 200 with a status dict:

        {provider, model, base_url, reachable, auth_ok, model_found,
         models_available, latency_ms, error, fleet_node}
    """
    from app.services.llm_resolution import resolve_user_llm
    from app.services.llm_health import probe_llm

    resolved = resolve_user_llm(current_user)
    status = probe_llm(
        resolved.provider_name,
        resolved.model,
        base_url=resolved.base_url,
        api_key=resolved.api_key,
    )
    status["fleet_node"] = resolved.fleet_node
    return status
