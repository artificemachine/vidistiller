"""Inventory the models currently loaded by the configured vLLM fleet.

The OpenAI-compatible models endpoint tells us only which model IDs are
loaded. Routing-relevant capabilities, context length, and operating
preferences are an explicit operator-owned manifest beside this module.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

FLEET_VMS = (
    ("primary", "VLLM_PRIMARY_URL"),
    ("secondary", "VLLM_SECONDARY_URL"),
    ("vision", "VLLM_VISION_URL"),
    ("auxiliary", "VLLM_AUXILIARY_URL"),
)
FLEET_PROBE_TIMEOUT_SECONDS = 3


class ProfileManifestError(ValueError):
    """Raised when an operator profile manifest cannot safely drive routing."""


class NoCompatibleModelError(RuntimeError):
    """Raised when no healthy, compatible, authorised LLM is available."""


class LLMTask(StrEnum):
    """The work categories used to derive non-negotiable route requirements."""

    TRANSCRIPT_SUMMARY = "transcript_summary"
    SNAPSHOT_DESCRIPTION = "snapshot_description"
    SLIDE_DESCRIPTION = "slide_description"
    LONG_ANALYSIS = "long_analysis"
    SLIDE_CLASSIFICATION = "slide_classification"


TASK_CAPABILITIES: dict[LLMTask, frozenset[str]] = {
    LLMTask.TRANSCRIPT_SUMMARY: frozenset({"text"}),
    LLMTask.SNAPSHOT_DESCRIPTION: frozenset({"vision"}),
    LLMTask.SLIDE_DESCRIPTION: frozenset({"vision"}),
    LLMTask.LONG_ANALYSIS: frozenset({"text"}),
    LLMTask.SLIDE_CLASSIFICATION: frozenset({"text"}),
}


@dataclass(frozen=True)
class RouteRequest:
    """The capability and context contract a selected model must satisfy."""

    task: LLMTask
    required_capabilities: frozenset[str]
    required_context_tokens: int = 0

    @classmethod
    def for_task(
        cls, task: LLMTask, required_context_tokens: int = 0
    ) -> "RouteRequest":
        if required_context_tokens < 0:
            raise ValueError("required_context_tokens cannot be negative")
        return cls(
            task=task,
            required_capabilities=TASK_CAPABILITIES[task],
            required_context_tokens=required_context_tokens,
        )


@dataclass(frozen=True)
class ResolvedLLM:
    """An endpoint and model selected for a concrete request."""

    provider_name: str
    model: str
    base_url: str | None
    api_key: str | None
    fleet_node: str | None = None


@dataclass(frozen=True)
class ModelProfile:
    """Operator-declared routing properties for one node/model pair."""

    node: str
    model: str
    capabilities: frozenset[str]
    priority: int
    context_tokens: int
    reliability: float
    latency_ms: int
    tier: str = "local"
    provider_name: str = "vllm"
    base_url: str | None = None
    api_key_env: str | None = None


@dataclass(frozen=True)
class FleetObservation:
    """A declared model confirmed as loaded and healthy by a live probe."""

    node: str
    model: str
    base_url: str
    capabilities: frozenset[str]
    priority: int
    context_tokens: int
    reliability: float
    declared_latency_ms: int
    observed_latency_ms: int
    healthy: bool
    provider_name: str = "vllm"


def default_profile_path() -> Path:
    """Return the checked-in, non-secret default profile manifest."""
    return Path(__file__).resolve().parent.parent / "core" / "llm_model_profiles.json"


def _require_string(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ProfileManifestError(f"{field} must be a non-empty string")
    return raw.strip()


def _require_positive_int(raw: object, field: str, allow_zero: bool = False) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < (0 if allow_zero else 1):
        qualifier = "a non-negative integer" if allow_zero else "a positive integer"
        raise ProfileManifestError(f"{field} must be {qualifier}")
    return raw


def _parse_profile(raw: object) -> ModelProfile:
    if not isinstance(raw, dict):
        raise ProfileManifestError("every profile must be an object")
    node = _require_string(raw.get("node"), "node")
    model = _require_string(raw.get("model"), "model")
    capabilities_raw = raw.get("capabilities")
    if not isinstance(capabilities_raw, list) or not capabilities_raw:
        raise ProfileManifestError("capabilities must be a non-empty list")
    capabilities = frozenset(_require_string(value, "capabilities") for value in capabilities_raw)
    priority = _require_positive_int(raw.get("priority"), "priority", allow_zero=True)
    context_tokens = _require_positive_int(raw.get("context_tokens"), "context_tokens")
    latency_ms = _require_positive_int(raw.get("latency_ms"), "latency_ms")
    reliability = raw.get("reliability")
    if isinstance(reliability, bool) or not isinstance(reliability, (int, float)):
        raise ProfileManifestError("reliability must be a number between 0 and 1")
    reliability = float(reliability)
    if not 0.0 <= reliability <= 1.0:
        raise ProfileManifestError("reliability must be a number between 0 and 1")
    tier = raw.get("tier", "local")
    if tier not in {"local", "cloud"}:
        raise ProfileManifestError("tier must be either local or cloud")
    provider_name = _require_string(raw.get("provider", "vllm"), "provider")
    base_url_raw = raw.get("base_url")
    base_url = _require_string(base_url_raw, "base_url") if base_url_raw is not None else None
    api_key_env_raw = raw.get("api_key_env")
    api_key_env = (
        _require_string(api_key_env_raw, "api_key_env")
        if api_key_env_raw is not None
        else None
    )
    if tier == "cloud" and not api_key_env:
        raise ProfileManifestError("cloud profile requires api_key_env")
    return ModelProfile(
        node=node,
        model=model,
        capabilities=capabilities,
        priority=priority,
        context_tokens=context_tokens,
        reliability=reliability,
        latency_ms=latency_ms,
        tier=tier,
        provider_name=provider_name,
        base_url=base_url,
        api_key_env=api_key_env,
    )


def load_model_profiles(path: str | Path | None = None) -> dict[tuple[str, str], ModelProfile]:
    """Load a strictly validated manifest indexed by node and model ID."""
    manifest_path = Path(
        path or os.environ.get("LLM_MODEL_PROFILES_PATH") or default_profile_path()
    )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileManifestError(f"profile manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileManifestError(f"profile manifest contains invalid JSON: {manifest_path}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        raise ProfileManifestError("profile manifest must contain a profiles list")

    profiles: dict[tuple[str, str], ModelProfile] = {}
    for raw in payload["profiles"]:
        profile = _parse_profile(raw)
        key = (profile.node, profile.model)
        if key in profiles:
            raise ProfileManifestError(f"duplicate profile for {profile.node}:{profile.model}")
        profiles[key] = profile
    return profiles


def _probe_loaded_model_ids(base_url: str) -> tuple[list[str], int] | None:
    """Return model IDs and observed latency, or None for an unhealthy node."""
    start = time.monotonic()
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/v1/models",
            timeout=FLEET_PROBE_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        return None
    return (
        [entry["id"] for entry in raw_models if isinstance(entry, dict) and isinstance(entry.get("id"), str)],
        elapsed_ms,
    )


def _filter_sidecar_catalog(base_url: str, model_ids: list[str]) -> list[str]:
    """Intersect a vllm-manager catalog with its current engine state.

    The manager listens on port 8100 and can list selectable models even when
    no inference engine is running.  A direct model server has no such status
    contract, so its OpenAI-compatible inventory remains authoritative.
    """
    if urlparse(base_url).port != 8100:
        return model_ids
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/status",
            timeout=FLEET_PROBE_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        logger.warning("fleet inventory: sidecar status probe failed for %s", base_url)
        return []
    if response.status_code != 200:
        logger.warning("fleet inventory: sidecar status probe was not healthy for %s", base_url)
        return []
    try:
        status = response.json()
    except ValueError:
        return []
    if not isinstance(status, dict):
        return []
    current_model = status.get("current_model")
    current_model_id = current_model.get("id") if isinstance(current_model, dict) else None
    if (
        status.get("vllm_ready") is not True
        or status.get("vllm_running") is not True
        or not isinstance(current_model_id, str)
        or current_model_id not in model_ids
    ):
        return []
    return [current_model_id]


def _configured_nodes() -> Iterable[tuple[str, str]]:
    for node, env_var in FLEET_VMS:
        base_url = os.environ.get(env_var)
        if base_url:
            yield node, base_url


def _inventory_endpoints(
    profiles: Iterable[ModelProfile],
) -> Iterable[tuple[str, str]]:
    """Return each configured or profile-specific endpoint once.

    A node can serve text and vision models on different ports.  The profile
    endpoint is explicit configuration, while the environment endpoint keeps
    compatibility with the standard one-model-per-node deployment.
    """
    seen: set[tuple[str, str]] = set()
    for node, base_url in _configured_nodes():
        endpoint = (node, base_url)
        if endpoint not in seen:
            seen.add(endpoint)
            yield endpoint
    for profile in profiles:
        if profile.tier != "local" or not profile.base_url:
            continue
        endpoint = (profile.node, profile.base_url)
        if endpoint not in seen:
            seen.add(endpoint)
            yield endpoint


def discover_inventory(path: str | Path | None = None) -> list[FleetObservation]:
    """Return declared profiles that are confirmed loaded on a healthy node."""
    profiles = load_model_profiles(path)
    inventory: list[FleetObservation] = []
    for node, base_url in _inventory_endpoints(profiles.values()):
        result = _probe_loaded_model_ids(base_url)
        if result is None:
            logger.warning("fleet inventory: %s did not return a usable model list", node)
            continue
        loaded_model_ids, observed_latency_ms = result
        loaded_model_ids = _filter_sidecar_catalog(base_url, loaded_model_ids)
        for model in loaded_model_ids:
            profile = profiles.get((node, model))
            if profile is None:
                logger.warning(
                    "fleet inventory: ignoring undeclared loaded model %r on %s",
                    model,
                    node,
                )
                continue
            if profile.tier != "local":
                logger.warning(
                    "fleet inventory: ignoring non-local profile %r on %s",
                    model,
                    node,
                )
                continue
            inventory.append(
                FleetObservation(
                    node=node,
                    model=model,
                    base_url=profile.base_url or base_url,
                    capabilities=profile.capabilities,
                    priority=profile.priority,
                    context_tokens=profile.context_tokens,
                    reliability=profile.reliability,
                    declared_latency_ms=profile.latency_ms,
                    observed_latency_ms=observed_latency_ms,
                    healthy=True,
                    provider_name=profile.provider_name,
                )
            )
    return inventory


def filter_candidates(
    candidates: Iterable[FleetObservation], request: RouteRequest
) -> list[FleetObservation]:
    """Keep only healthy local candidates that meet the request contract."""
    return [
        candidate
        for candidate in candidates
        if candidate.healthy
        and request.required_capabilities.issubset(candidate.capabilities)
        and candidate.context_tokens >= request.required_context_tokens
    ]


def rank_candidates(candidates: Iterable[FleetObservation]) -> list[FleetObservation]:
    """Return candidates in the documented deterministic routing order."""
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.priority,
            -candidate.reliability,
            candidate.observed_latency_ms,
            candidate.node,
            candidate.model,
        ),
    )


def _cloud_candidates(
    request: RouteRequest, manifest_path: str | Path | None
) -> list[tuple[ModelProfile, str]]:
    """Find authorised manifest-defined cloud fallbacks without probing them."""
    candidates: list[tuple[ModelProfile, str]] = []
    for profile in load_model_profiles(manifest_path).values():
        if profile.tier != "cloud":
            continue
        if not request.required_capabilities.issubset(profile.capabilities):
            continue
        if profile.context_tokens < request.required_context_tokens:
            continue
        api_key = os.environ.get(profile.api_key_env or "")
        if api_key:
            candidates.append((profile, api_key))
    return candidates


def _cloud_fallback_enabled() -> bool:
    return os.environ.get("LLM_ALLOW_CLOUD_FALLBACK", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def route_llm(
    owner,
    request: RouteRequest,
    *,
    inventory: Iterable[FleetObservation] | None = None,
    manifest_path: str | Path | None = None,
    allow_cloud_fallback: bool | None = None,
) -> ResolvedLLM:
    """Select the best compatible local candidate, then an authorised cloud one.

    ``owner`` is deliberately accepted for the compatibility adapter, but route
    policy is fleet-owned: a user setting cannot turn an incompatible endpoint
    into a candidate.
    """
    del owner
    local_candidates = filter_candidates(
        discover_inventory(manifest_path) if inventory is None else inventory,
        request,
    )
    if local_candidates:
        chosen = rank_candidates(local_candidates)[0]
        return ResolvedLLM(
            provider_name=chosen.provider_name,
            model=chosen.model,
            base_url=chosen.base_url,
            api_key=None,
            fleet_node=chosen.node,
        )

    if allow_cloud_fallback if allow_cloud_fallback is not None else _cloud_fallback_enabled():
        cloud_candidates = _cloud_candidates(request, manifest_path)
        if cloud_candidates:
            profile, api_key = sorted(
                cloud_candidates,
                key=lambda item: (
                    -item[0].priority,
                    -item[0].reliability,
                    item[0].latency_ms,
                    item[0].node,
                    item[0].model,
                ),
            )[0]
            return ResolvedLLM(
                provider_name=profile.provider_name,
                model=profile.model,
                base_url=profile.base_url,
                api_key=api_key,
                fleet_node=profile.node,
            )

    raise NoCompatibleModelError(
        f"no compatible model for task {request.task.value} "
        f"(capabilities={sorted(request.required_capabilities)}, "
        f"context={request.required_context_tokens})"
    )
