"""
Settings API Routes

Handles user settings including LLM provider preferences, model selection, and API keys.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routes.auth import get_current_user_from_token
from app.core.crypto import encrypt_field, decrypt_field
from app.db.models import User
from app.schemas import UserSettingsUpdate, UserSettingsResponse


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

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return UserSettingsResponse(
        llm_provider=current_user.llm_provider,
        llm_model=current_user.llm_model,
        llm_ollama_url=current_user.llm_ollama_url,
        has_api_key=bool(current_user.llm_api_key_encrypted),
    )


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
