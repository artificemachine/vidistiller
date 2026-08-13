"""Resolve a user's effective LLM configuration.

Single code path shared by background jobs (``app.tasks._resolve_job_llm``)
and the diagnostics endpoint (``GET /diagnostics/llm``) so both always agree
on which provider, model, and endpoint are actually in use.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from app.services.llm_fleet import (
    FLEET_VMS,
    LLMTask,
    ResolvedLLM,
    RouteRequest,
    load_model_profiles,
    route_llm,
)

logger = logging.getLogger(__name__)

# Fallback model when neither the user nor the provider default supplies one.
FALLBACK_MODEL = "gemma4-31b"


def _get_vm_model_ids(url: str) -> list[str]:
    """Return the model ids exposed by a fleet VM's ``GET /v1/models``.

    Transport errors, non-200 responses, malformed JSON, and empty model
    lists all return an empty list — callers treat that as "skip this VM".
    """
    try:
        resp = requests.get(url.rstrip("/") + "/v1/models", timeout=3)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    return [m["id"] for m in body.get("data", []) if isinstance(m, dict)]


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
        model_ids = _get_vm_model_ids(vllm_url)
        if model_name in model_ids:
            logger.info(
                "fleet: model %r found on %s (%s)", model_name, vm_label, vllm_url
            )
            return vllm_url, vm_label

    logger.warning("fleet: model %r not loaded on any VM", model_name)
    return None, None


def discover_fleet_model() -> tuple[str, str, str] | None:
    """
    Return ``(model_id, vllm_url, vm_label)`` for the first model actually
    loaded on the first reachable fleet VM.

    Lets ``resolve_user_llm`` adopt the fleet's current default instead of
    requesting a hardcoded model name. Returns ``None`` when no VM is
    reachable or none reports a loaded model — the caller falls back to
    the configured default.
    """
    for vm_label, env_var in FLEET_VMS:
        vllm_url = os.environ.get(env_var)
        if not vllm_url:
            continue
        model_ids = _get_vm_model_ids(vllm_url)
        if model_ids:
            logger.info(
                "fleet: adopting %r from %s (%s)", model_ids[0], vm_label, vllm_url
            )
            return model_ids[0], vllm_url, vm_label
    return None


def resolve_user_llm(owner) -> ResolvedLLM:
    """
    Resolve the effective LLM provider + model for a user (fleet-aware).

    Honours the owner's configured provider/model, defaults to the vLLM fleet,
    and for vllm without a pinned model adopts the first loaded model on the
    first reachable fleet VM. Hardcoded defaults remain only as the final
    fallback when the fleet is unreachable. This mirrors what summarization
    jobs use.

    Args:
        owner: User row (or None for anonymous/system resolution).

    Returns:
        ResolvedLLM with provider_name, model, base_url, api_key, fleet_node.
    """
    from app.services.llm_providers import DEFAULT_MODELS

    provider_name = owner.llm_provider if owner and owner.llm_provider else "vllm"
    model_name = owner.llm_model if owner and owner.llm_model else None

    fleet_node: Optional[str] = None
    fleet_url: Optional[str] = None
    adopted_url: Optional[str] = None
    resolved_model: str
    if model_name:
        resolved_model = model_name
    else:
        # vllm + no user model: adopt whatever the fleet is currently serving.
        adopted = discover_fleet_model() if provider_name == "vllm" else None
        if adopted is not None:
            resolved_model, adopted_url, fleet_node = adopted
        else:
            resolved_model = DEFAULT_MODELS.get(provider_name) or FALLBACK_MODEL

    if adopted_url is None and provider_name == "vllm":
        # No adoption; fall back to the fleet lookup that finds a VM with the
        # configured default model loaded.
        fleet_url, fleet_node = resolve_fleet_url(resolved_model)

    default_url = (
        adopted_url
        or fleet_url
        or os.environ.get("VLLM_PRIMARY_URL")
        or os.environ.get("OLLAMA_URL")
    )
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


def resolve_task_llm(
    owner,
    task: LLMTask,
    required_context_tokens: int = 0,
) -> ResolvedLLM:
    """Resolve a task-specific route when the fleet has declared profiles.

    An empty checked-in manifest intentionally preserves the legacy resolver
    until an operator has certified at least one local profile. Once profiles
    exist, route selection is strict: no candidate means no task dispatch,
    rather than silently using the first reachable VM.
    """
    profiles = load_model_profiles()
    has_local_profiles = any(profile.tier == "local" for profile in profiles.values())
    if has_local_profiles:
        return route_llm(
            owner,
            RouteRequest.for_task(task, required_context_tokens),
        )
    return resolve_user_llm(owner)
