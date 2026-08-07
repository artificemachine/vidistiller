"""Resolve a user's effective LLM configuration.

Single code path shared by background jobs (``app.tasks._resolve_job_llm``)
and the diagnostics endpoint (``GET /diagnostics/llm``) so both always agree
on which provider, model, and endpoint are actually in use.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Fleet VMs: (label, env var holding the vLLM URL). Same order as the
# resolution used by jobs: first VM that has the model loaded wins.
FLEET_VMS = [
    ("vm913", "VLLM_VM913_URL"),
    ("vm903", "VLLM_VM903_URL"),
    ("vm901", "VLLM_VM901_URL"),
    ("vm2900", "VLLM_VM2900_URL"),
]

# Fallback model when neither the user nor the provider default supplies one.
FALLBACK_MODEL = "gemma4-31b"


@dataclass
class ResolvedLLM:
    """Effective LLM configuration for a user."""

    provider_name: str
    model: str
    base_url: Optional[str]
    api_key: Optional[str]
    fleet_node: Optional[str] = None  # label of the fleet VM serving the model


def resolve_fleet_url(model_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Query all vLLM fleet VMs to find which one has *model_name* loaded.

    Calls ``GET /v1/models`` directly on each VM's vLLM port.

    Returns:
        (vllm_url, vm_label) of the first match, or (None, None) if no VM
        has the model loaded or all VMs are unreachable.
    """
    for vm_label, env_var in FLEET_VMS:
        vllm_url = os.environ.get(env_var)
        if not vllm_url:
            continue
        try:
            api = vllm_url.rstrip("/") + "/v1/models"
            resp = requests.get(api, timeout=3)
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", [])]
                if model_name in models:
                    logger.info(
                        "fleet: model %r found on %s (%s)", model_name, vm_label, vllm_url
                    )
                    return vllm_url, vm_label
        except Exception:
            continue

    logger.warning("fleet: model %r not loaded on any VM", model_name)
    return None, None


def resolve_user_llm(owner) -> ResolvedLLM:
    """
    Resolve the effective LLM provider + model for a user (fleet-aware).

    Honours the owner's configured provider/model, defaults to the vLLM fleet,
    and for vllm without a pinned URL picks the VM that actually has the model
    loaded. This mirrors what summarization jobs use.

    Args:
        owner: User row (or None for anonymous/system resolution).

    Returns:
        ResolvedLLM with provider_name, model, base_url, api_key, fleet_node.
    """
    from app.services.llm_providers import DEFAULT_MODELS

    provider_name = owner.llm_provider if owner and owner.llm_provider else "vllm"
    model_name = owner.llm_model if owner and owner.llm_model else None

    resolved_model = model_name or DEFAULT_MODELS.get(provider_name) or FALLBACK_MODEL

    fleet_url, fleet_node = (
        resolve_fleet_url(resolved_model) if provider_name == "vllm" else (None, None)
    )
    default_url = fleet_url or os.environ.get("VLLM_VM913_URL") or os.environ.get("OLLAMA_URL")
    base_url = (owner.llm_ollama_url if owner and owner.llm_ollama_url else None) or default_url

    api_key = None
    if owner and owner.llm_api_key_encrypted:
        from app.core.crypto import decrypt_field

        try:
            api_key = decrypt_field(owner.llm_api_key_encrypted)
        except Exception as e:
            logger.warning(
                "Failed to decrypt API key for user %s: %s", getattr(owner, "id", "?"), e
            )

    return ResolvedLLM(
        provider_name=provider_name,
        model=resolved_model,
        base_url=base_url,
        api_key=api_key,
        fleet_node=fleet_node,
    )
