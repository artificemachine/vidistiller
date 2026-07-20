"""
Settings API Routes

Handles user settings including LLM provider preferences, model selection, and API keys.
"""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.routes.auth import get_current_user_from_token
from app.core.crypto import encrypt_field, decrypt_field
from app.db.models import User
from app.schemas import UserSettingsUpdate, UserSettingsResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/me", response_model=UserSettingsResponse)
def get_user_settings(
    current_user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_db),
) -> UserSettingsResponse:
    """
    Get current user's LLM settings.

    Returns:
        UserSettingsResponse with provider, model, ollama_url, and has_api_key flag (no actual key returned)
    """
    return UserSettingsResponse(
        llm_provider=current_user.llm_provider,
        llm_model=current_user.llm_model,
        llm_ollama_url=current_user.llm_ollama_url,
        has_api_key=bool(current_user.llm_api_key_encrypted),
        summary_language=current_user.summary_language,
    )


@router.patch("/me", response_model=UserSettingsResponse)
def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_db),
) -> UserSettingsResponse:
    """
    Update current user's LLM settings.

    Args:
        settings_update: Settings update payload (provider, model, api_key are all optional)

    Returns:
        Updated UserSettingsResponse
    """
    # Update provider if provided
    if settings_update.llm_provider is not None:
        current_user.llm_provider = settings_update.llm_provider

    # Update model if provided
    if settings_update.llm_model is not None:
        current_user.llm_model = settings_update.llm_model

    # Update Ollama URL if provided
    if settings_update.llm_ollama_url is not None:
        current_user.llm_ollama_url = settings_update.llm_ollama_url if settings_update.llm_ollama_url else None

    # Update and encrypt API key if provided
    if settings_update.llm_api_key is not None:
        if settings_update.llm_api_key:
            # Encrypt the key before storing
            current_user.llm_api_key_encrypted = encrypt_field(settings_update.llm_api_key)
        else:
            # Empty string means clear the key
            current_user.llm_api_key_encrypted = None

    # Update summary output language if provided ("" = clear, None = unchanged)
    if settings_update.summary_language is not None:
        current_user.summary_language = settings_update.summary_language or None

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return UserSettingsResponse(
        llm_provider=current_user.llm_provider,
        llm_model=current_user.llm_model,
        llm_ollama_url=current_user.llm_ollama_url,
        has_api_key=bool(current_user.llm_api_key_encrypted),
        summary_language=current_user.summary_language,
    )


@router.get("/vllm/fleet")
def get_vllm_fleet(
    current_user: User = Depends(get_current_user_from_token),
) -> dict:
    """
    Return the configured vLLM fleet nodes from server env vars.
    Only includes nodes whose URL env var is set.
    """
    fleet_cfg = get_settings().vllm_fleet
    _nodes = [
        {"id": "vm913",  "label": "VM913",  "tier": "opus-class",   "desc": "4× RTX 3090 · 96 GB · TP=2", "model": "gemma4-31b", "url": fleet_cfg.vm913_url},
        {"id": "vm903",  "label": "VM903",  "tier": "sonnet-class", "desc": "2× RTX 3090 · 48 GB",              "model": "",           "url": fleet_cfg.vm903_url},
        {"id": "vm901",  "label": "VM901",  "tier": "haiku-class",  "desc": "2× RTX 3080 · 20 GB",              "model": "",           "url": fleet_cfg.vm901_url},
        {"id": "vm2900", "label": "VM2900", "tier": "small",        "desc": "RTX 3060 Ti · 8 GB usable",            "model": "",           "url": fleet_cfg.vm2900_url},
    ]
    return {"nodes": [n for n in _nodes if n["url"]]}


@router.get("/vllm/models")
def get_vllm_models(
    base_url: str = Query(..., description="vLLM sidecar base URL, e.g. http://10.0.150.36:8100"),
    current_user: User = Depends(get_current_user_from_token),
) -> dict:
    """
    Proxy call to a vLLM sidecar to discover which model is currently loaded.
    Returns {"models": ["model-id", ...]}
    """
    # This endpoint fetches base_url and returns the response body to the
    # caller, so an unrestricted value would make it a general-purpose read
    # proxy into the private network. vLLM sidecars are legitimately on private
    # addresses, so the host is checked against the operator allowlist.
    from app.core.url_guard import validate_llm_endpoint

    try:
        base_url = validate_llm_endpoint(
            base_url, get_settings().allowed_llm_host_list
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sidecar_url = base_url.rstrip("/") + "/v1/models"
    try:
        response = httpx.get(sidecar_url, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        models = [m["id"] for m in data.get("data", [])]
        return {"models": models}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Sidecar did not respond within 5 s")
    except Exception as exc:
        # The exception text is logged, not returned: reflecting it gave the
        # caller connection-level detail about hosts behind the backend.
        logger.warning("vLLM sidecar request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach sidecar")


@router.delete("/me/api-key", response_model=UserSettingsResponse)
def delete_api_key(
    current_user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_db),
) -> UserSettingsResponse:
    """
    Delete the stored API key for the current user.

    Returns:
        Updated UserSettingsResponse with has_api_key=false
    """
    current_user.llm_api_key_encrypted = None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return UserSettingsResponse(
        llm_provider=current_user.llm_provider,
        llm_model=current_user.llm_model,
        llm_ollama_url=current_user.llm_ollama_url,
        has_api_key=False,
    )
