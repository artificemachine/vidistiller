"""Tests for declared fleet model inventory.

The inventory trusts /v1/models only for what is loaded. Capabilities and
limits remain an operator-declared, non-secret contract.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests


def _write_manifest(tmp_path, profiles):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    return path


def _profile(node="primary", model="text-model", **overrides):
    profile = {
        "node": node,
        "model": model,
        "capabilities": ["text"],
        "priority": 100,
        "context_tokens": 32768,
        "reliability": 0.95,
        "latency_ms": 200,
    }
    profile.update(overrides)
    return profile


def _response(model_ids):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": [{"id": model_id} for model_id in model_ids]}
    return response


def _sidecar_status_response(*, model_id=None, ready=True, running=True):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "current_model": {"id": model_id} if model_id else None,
        "vllm_ready": ready,
        "vllm_running": running,
    }
    return response


def test_profile_manifest_requires_all_routing_fields(tmp_path):
    from app.services.llm_fleet import ProfileManifestError, load_model_profiles

    path = _write_manifest(tmp_path, [{"node": "primary", "model": "missing-fields"}])

    with pytest.raises(ProfileManifestError, match="capabilities"):
        load_model_profiles(path)


def test_inventory_keeps_only_models_reported_by_v1_models(tmp_path, monkeypatch):
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(
        tmp_path,
        [_profile(model="loaded-model"), _profile(model="not-loaded-model")],
    )
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")
    monkeypatch.setattr(
        "app.services.llm_fleet.requests.get",
        lambda *_args, **_kwargs: _response(["loaded-model"]),
    )

    inventory = discover_inventory(path)

    assert [candidate.model for candidate in inventory] == ["loaded-model"]


def test_inventory_records_probe_health_and_latency(tmp_path, monkeypatch):
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(tmp_path, [_profile()])
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")
    monotonic_values = iter((100.0, 100.125))
    monkeypatch.setattr("app.services.llm_fleet.time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        "app.services.llm_fleet.requests.get",
        lambda *_args, **_kwargs: _response(["text-model"]),
    )

    [candidate] = discover_inventory(path)

    assert candidate.healthy is True
    assert candidate.observed_latency_ms == 125
    assert candidate.declared_latency_ms == 200


def test_inventory_rejects_unknown_loaded_model(tmp_path, monkeypatch):
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(tmp_path, [_profile(model="declared-model")])
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")
    monkeypatch.setattr(
        "app.services.llm_fleet.requests.get",
        lambda *_args, **_kwargs: _response(["unknown-model"]),
    )

    assert discover_inventory(path) == []


def test_inventory_excludes_inactive_sidecar_catalog(tmp_path, monkeypatch):
    """A manager catalog is not evidence that its inference engine is loaded."""
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(tmp_path, [_profile(node="vision", model="catalog-only")])
    monkeypatch.setenv("VLLM_VISION_URL", "http://vision:8100")

    def _get(url, **_kwargs):
        if url.endswith("/v1/models"):
            return _response(["catalog-only"])
        if url.endswith("/status"):
            return _sidecar_status_response(model_id=None, ready=False, running=False)
        raise AssertionError(f"unexpected endpoint: {url}")

    monkeypatch.setattr("app.services.llm_fleet.requests.get", _get)

    assert discover_inventory(path) == []


def test_inventory_probes_profile_specific_endpoint(tmp_path, monkeypatch):
    """A vision profile may use a second endpoint on the same fleet node."""
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(
        tmp_path,
        [
            _profile(
                node="primary",
                model="vision-model",
                capabilities=["vision"],
                base_url="http://primary:8102",
            )
        ],
    )
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")

    def _get(url, **_kwargs):
        if url == "http://primary:8000/v1/models":
            return _response([])
        if url == "http://primary:8102/v1/models":
            return _response(["vision-model"])
        raise AssertionError(f"unexpected endpoint: {url}")

    monkeypatch.setattr("app.services.llm_fleet.requests.get", _get)

    [candidate] = discover_inventory(path)

    assert (candidate.model, candidate.base_url) == ("vision-model", "http://primary:8102")


def test_inventory_survives_one_dead_node(tmp_path, monkeypatch):
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(
        tmp_path,
        [_profile(node="primary", model="dead-model"), _profile(node="secondary", model="live-model")],
    )
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")
    monkeypatch.setenv("VLLM_SECONDARY_URL", "http://secondary:8000")
    responses = iter((requests.exceptions.ConnectionError(), _response(["live-model"])))

    def _get(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("app.services.llm_fleet.requests.get", _get)

    inventory = discover_inventory(path)

    assert [(candidate.node, candidate.model) for candidate in inventory] == [
        ("secondary", "live-model")
    ]


def test_duplicate_model_ids_remain_distinct_per_node(tmp_path, monkeypatch):
    from app.services.llm_fleet import discover_inventory

    path = _write_manifest(
        tmp_path,
        [_profile(node="primary", model="shared"), _profile(node="secondary", model="shared")],
    )
    monkeypatch.setenv("VLLM_PRIMARY_URL", "http://primary:8000")
    monkeypatch.setenv("VLLM_SECONDARY_URL", "http://secondary:8000")
    monkeypatch.setattr(
        "app.services.llm_fleet.requests.get",
        lambda *_args, **_kwargs: _response(["shared"]),
    )

    inventory = discover_inventory(path)

    assert {(candidate.node, candidate.model) for candidate in inventory} == {
        ("primary", "shared"),
        ("secondary", "shared"),
    }


def test_route_filters_capabilities_before_sorting():
    from app.services.llm_fleet import (
        FleetObservation,
        LLMTask,
        RouteRequest,
        route_llm,
    )

    chosen = route_llm(
        None,
        RouteRequest.for_task(LLMTask.SNAPSHOT_DESCRIPTION),
        inventory=[
            _candidate(model="fast-text", capabilities=frozenset({"text"}), priority=999),
            _candidate(model="vision", capabilities=frozenset({"vision"}), priority=1),
        ],
    )

    assert chosen.model == "vision"


def test_long_analysis_filters_insufficient_context():
    from app.services.llm_fleet import LLMTask, RouteRequest, route_llm

    chosen = route_llm(
        None,
        RouteRequest.for_task(LLMTask.LONG_ANALYSIS, required_context_tokens=32_000),
        inventory=[
            _candidate(model="short", context_tokens=16_000, priority=999),
            _candidate(model="long", context_tokens=32_000, priority=1),
        ],
    )

    assert chosen.model == "long"


def test_route_excludes_unhealthy_candidate():
    from app.services.llm_fleet import LLMTask, RouteRequest, route_llm

    chosen = route_llm(
        None,
        RouteRequest.for_task(LLMTask.TRANSCRIPT_SUMMARY),
        inventory=[
            _candidate(model="dead", healthy=False, priority=999),
            _candidate(model="live", priority=1),
        ],
    )

    assert chosen.model == "live"


def test_route_orders_priority_then_reliability_then_latency():
    from app.services.llm_fleet import LLMTask, RouteRequest, route_llm

    chosen = route_llm(
        None,
        RouteRequest.for_task(LLMTask.TRANSCRIPT_SUMMARY),
        inventory=[
            _candidate(model="low-priority", priority=9_999),
            _candidate(model="slow", priority=10_000, reliability=0.90, observed_latency_ms=10),
            _candidate(model="reliable", priority=10_000, reliability=0.95, observed_latency_ms=999),
            _candidate(model="fast", priority=10_000, reliability=0.95, observed_latency_ms=5),
        ],
    )

    assert chosen.model == "fast"


def test_route_never_uses_vm_order_as_tiebreaker():
    from app.services.llm_fleet import LLMTask, RouteRequest, route_llm

    chosen = route_llm(
        None,
        RouteRequest.for_task(LLMTask.TRANSCRIPT_SUMMARY),
        inventory=[
            _candidate(node="auxiliary", model="z-model"),
            _candidate(node="primary", model="a-model"),
        ],
    )

    # primary precedes auxiliary in FLEET_VMS, while the explicit lexical
    # tie-break selects auxiliary instead.
    assert (chosen.fleet_node, chosen.model) == ("auxiliary", "z-model")


def test_cloud_fallback_is_disabled_by_default(tmp_path, monkeypatch):
    from app.services.llm_fleet import LLMTask, NoCompatibleModelError, RouteRequest, route_llm

    path = _write_manifest(
        tmp_path,
        [_profile(node="cloud-openai", model="cloud-model", tier="cloud", provider="openai", api_key_env="TEST_CLOUD_KEY")],
    )
    monkeypatch.setenv("TEST_CLOUD_KEY", "fake-key")

    with pytest.raises(NoCompatibleModelError):
        route_llm(
            None,
            RouteRequest.for_task(LLMTask.TRANSCRIPT_SUMMARY),
            inventory=[],
            manifest_path=path,
        )


def test_cloud_fallback_requires_flag_profile_and_key(tmp_path, monkeypatch):
    from app.services.llm_fleet import LLMTask, NoCompatibleModelError, RouteRequest, route_llm

    path = _write_manifest(
        tmp_path,
        [_profile(node="cloud-openai", model="cloud-model", tier="cloud", provider="openai", api_key_env="TEST_CLOUD_KEY")],
    )
    request = RouteRequest.for_task(LLMTask.TRANSCRIPT_SUMMARY)

    with pytest.raises(NoCompatibleModelError):
        route_llm(None, request, inventory=[], manifest_path=path, allow_cloud_fallback=True)

    monkeypatch.setenv("TEST_CLOUD_KEY", "fake-key")
    chosen = route_llm(None, request, inventory=[], manifest_path=path, allow_cloud_fallback=True)

    assert (chosen.provider_name, chosen.model, chosen.fleet_node) == (
        "openai",
        "cloud-model",
        "cloud-openai",
    )
    assert chosen.api_key == "fake-key"


def test_no_compatible_candidate_raises_typed_error():
    from app.services.llm_fleet import (
        LLMTask,
        NoCompatibleModelError,
        RouteRequest,
        route_llm,
    )

    with pytest.raises(NoCompatibleModelError, match="snapshot_description"):
        route_llm(
            None,
            RouteRequest.for_task(LLMTask.SNAPSHOT_DESCRIPTION),
            inventory=[_candidate(capabilities=frozenset({"text"}))],
        )


def _candidate(
    *,
    node="primary",
    model="model",
    capabilities=frozenset({"text"}),
    priority=100,
    context_tokens=32_768,
    reliability=0.95,
    observed_latency_ms=100,
    healthy=True,
):
    from app.services.llm_fleet import FleetObservation

    return FleetObservation(
        node=node,
        model=model,
        base_url=f"http://{node}:8000",
        capabilities=capabilities,
        priority=priority,
        context_tokens=context_tokens,
        reliability=reliability,
        declared_latency_ms=observed_latency_ms,
        observed_latency_ms=observed_latency_ms,
        healthy=healthy,
    )
