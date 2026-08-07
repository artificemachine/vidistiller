"""Reachability probes for LLM endpoints.

Used only by the diagnostics endpoint — never on the processing hot path.
Every probe is short-timeout and never raises: the caller always gets a
uniform status dict it can render.

Security note: probed self-hosted URLs come from the user's stored settings
(validated against the operator allowlist at write time) or from server env
vars, so no additional SSRF guard is needed here. Cloud endpoints are fixed
constants, never user input.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 5.0

# Fixed cloud model-list endpoints (never user-controlled).
CLOUD_MODEL_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "minimax": "https://api.minimaxi.chat/v1/models",
}
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_VERSION = "2023-06-01"

# Cap the returned model list so payloads stay small.
_MAX_MODELS_RETURNED = 20


def _base_result(
    provider_name: str,
    model: Optional[str],
    base_url: Optional[str],
) -> dict:
    return {
        "provider": provider_name,
        "model": model,
        "base_url": base_url,
        "reachable": False,
        "auth_ok": None,  # None = not applicable (self-hosted, no auth)
        "model_found": False,
        "models_available": [],
        "latency_ms": 0,
        "error": None,
    }


def _apply_transport_error(result: dict, exc: Exception) -> dict:
    """Map a requests transport error onto the result dict (generic messages
    only — raw exception text can leak internal network detail)."""
    if isinstance(exc, requests.exceptions.Timeout):
        result["error"] = "connection timed out"
    elif isinstance(exc, requests.exceptions.ConnectionError):
        result["error"] = "connection refused"
    else:
        result["error"] = "request failed"
    return result


def _probe_models_endpoint(
    result: dict,
    url: str,
    model: Optional[str],
    headers: dict,
    match_tags: bool = False,
    auth_expected: bool = False,
) -> dict:
    """GET an OpenAI-style or Ollama-style models endpoint and interpret it.

    Args:
        match_tags: True for Ollama, where 'llama3' matches 'llama3:latest'.
        auth_expected: True when the endpoint authenticates, so a 200 means
            the key was accepted (auth_ok=True). False keeps auth_ok=None.

    Returns the filled-in result dict.
    """
    start = time.monotonic()
    try:
        resp = requests.get(url, headers=headers, timeout=PROBE_TIMEOUT)
    except Exception as exc:  # transport-level failure
        return _apply_transport_error(result, exc)

    result["latency_ms"] = int((time.monotonic() - start) * 1000)
    result["reachable"] = True  # the endpoint answered, whatever the status

    if resp.status_code in (401, 403):
        result["auth_ok"] = False
        result["error"] = f"api key rejected (HTTP {resp.status_code})"
        return result

    if resp.status_code != 200:
        result["error"] = f"endpoint returned HTTP {resp.status_code}"
        return result

    result["auth_ok"] = True if auth_expected else None

    try:
        body = resp.json()
    except ValueError:
        result["error"] = "endpoint returned invalid JSON"
        return result

    # OpenAI-style: {"data": [{"id": ...}]}; Ollama: {"models": [{"name": ...}]}
    if isinstance(body.get("data"), list):
        models = [m.get("id", "") for m in body["data"] if isinstance(m, dict)]
    else:
        models = [m.get("name", "") for m in body.get("models", []) if isinstance(m, dict)]
    models = [m for m in models if m]

    result["models_available"] = models[:_MAX_MODELS_RETURNED]

    if model:
        if match_tags:
            result["model_found"] = any(
                m == model or m.startswith(f"{model}:") for m in models
            )
        else:
            result["model_found"] = model in models

    return result


def probe_llm(
    provider_name: str,
    model: Optional[str],
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Probe an LLM endpoint and return a uniform status dict. Never raises.

    Args:
        provider_name: One of the supported providers (ollama, vllm, opencode,
            openai, anthropic, deepseek, minimax).
        model: Model name to check availability for (may be None).
        base_url: Endpoint for self-hosted providers (ollama, vllm, opencode).
        api_key: Key for providers that authenticate.

    Returns:
        {provider, model, base_url, reachable, auth_ok, model_found,
         models_available, latency_ms, error}
        - reachable: endpoint answered at all (any HTTP status)
        - auth_ok: True/False for authenticating providers, None otherwise
        - model_found: configured model present in the endpoint's model list
    """
    provider_name = (provider_name or "").lower()
    result = _base_result(provider_name, model, base_url)

    if provider_name == "anthropic":
        if not api_key:
            result["error"] = "no api key configured"
            return result
        return _probe_models_endpoint(
            result,
            ANTHROPIC_MODELS_URL,
            model,
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
            auth_expected=True,
        )

    if provider_name in CLOUD_MODEL_ENDPOINTS:
        if not api_key:
            result["error"] = "no api key configured"
            return result
        return _probe_models_endpoint(
            result,
            CLOUD_MODEL_ENDPOINTS[provider_name],
            model,
            headers={"Authorization": f"Bearer {api_key}"},
            auth_expected=True,
        )

    if provider_name in ("vllm", "opencode"):
        if not base_url:
            result["error"] = "no base URL configured"
            return result
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return _probe_models_endpoint(
            result, f"{url}/models", model, headers, auth_expected=bool(api_key)
        )

    if provider_name == "ollama":
        url = (base_url or "http://localhost:11434").rstrip("/")
        return _probe_models_endpoint(
            result, f"{url}/api/tags", model, headers={}, match_tags=True
        )

    result["error"] = f"unknown provider: {provider_name}"
    return result
