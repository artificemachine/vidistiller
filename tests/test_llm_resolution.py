"""Unit tests for shared LLM resolution (app.services.llm_resolution).

This resolution is the single code path used both by background jobs and by
GET /diagnostics/llm, so its precedence rules are tested explicitly.
"""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
import requests

from app.services.llm_resolution import (
    FALLBACK_MODEL,
    discover_fleet_model,
    resolve_fleet_url,
    resolve_user_llm,
)


_FLEET_ENV_VARS = (
    "VLLM_VM913_URL", "VLLM_VM903_URL", "VLLM_VM901_URL", "VLLM_VM2900_URL",
)


@pytest.fixture(autouse=True)
def _clean_fleet_env(monkeypatch):
    """Fleet resolution reads env vars; keep tests isolated from the host env."""
    for var in _FLEET_ENV_VARS + ("OLLAMA_URL",):
        monkeypatch.delenv(var, raising=False)


def _owner(provider=None, model=None, url=None, key_encrypted=None):
    return SimpleNamespace(
        id=1,
        llm_provider=provider,
        llm_model=model,
        llm_ollama_url=url,
        llm_api_key_encrypted=key_encrypted,
    )


def _fleet_resp(status_code=200, model_ids=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"data": [{"id": m} for m in (model_ids or [])]}
    return resp


# ---------------------------------------------------------------------------
# resolve_user_llm — precedence rules
# ---------------------------------------------------------------------------

class TestResolveUserLLM:
    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    def test_defaults_to_vllm_when_owner_unset(self, _fleet, monkeypatch):
        monkeypatch.delenv("VLLM_VM913_URL", raising=False)
        monkeypatch.delenv("OLLAMA_URL", raising=False)

        result = resolve_user_llm(None)

        assert result.provider_name == "vllm"
        assert result.model == "gemma4-31b"  # DEFAULT_MODELS["vllm"] (aligned with FALLBACK_MODEL)
        assert result.base_url is None
        assert result.api_key is None

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    def test_owner_provider_and_model_win(self, _fleet):
        owner = _owner(provider="ollama", model="qwen3:8b", url="http://localhost:11434")

        result = resolve_user_llm(owner)

        assert result.provider_name == "ollama"
        assert result.model == "qwen3:8b"
        assert result.base_url == "http://localhost:11434"
        _fleet.assert_not_called()  # fleet lookup is vllm-only

    @patch("app.services.llm_resolution.resolve_fleet_url")
    def test_vllm_uses_fleet_vm_with_model(self, mock_fleet):
        mock_fleet.return_value = ("http://vm903:8000", "vm903")

        result = resolve_user_llm(_owner(provider="vllm", model="gemma4-31b"))

        mock_fleet.assert_called_once_with("gemma4-31b")
        assert result.base_url == "http://vm903:8000"
        assert result.fleet_node == "vm903"

    @patch("app.services.llm_resolution.resolve_fleet_url")
    def test_pinned_url_beats_fleet(self, mock_fleet):
        mock_fleet.return_value = ("http://vm903:8000", "vm903")
        owner = _owner(provider="vllm", model="gemma4-31b", url="http://pinned:8000")

        result = resolve_user_llm(owner)

        assert result.base_url == "http://pinned:8000"

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    def test_falls_back_to_vm913_env(self, _fleet, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")

        result = resolve_user_llm(_owner(provider="vllm", model="gemma4-31b"))

        assert result.base_url == "http://vm913:8000"

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    def test_model_falls_back_when_provider_has_no_default(self, _fleet):
        # opencode has no default model -> global fallback
        result = resolve_user_llm(_owner(provider="opencode"))

        assert result.model == FALLBACK_MODEL

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.core.crypto.decrypt_field", return_value="sk-decrypted")
    def test_api_key_decrypted(self, _decrypt, _fleet):
        result = resolve_user_llm(_owner(provider="openai", key_encrypted="enc"))

        assert result.api_key == "sk-decrypted"

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.core.crypto.decrypt_field", side_effect=ValueError("bad key material"))
    def test_decrypt_failure_yields_none_key(self, _decrypt, _fleet):
        result = resolve_user_llm(_owner(provider="openai", key_encrypted="enc"))

        assert result.api_key is None  # never raises


# ---------------------------------------------------------------------------
# resolve_fleet_url
# ---------------------------------------------------------------------------

class TestResolveFleetUrl:
    @patch("app.services.llm_resolution.requests.get")
    def test_first_vm_with_model_wins(self, mock_get, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        monkeypatch.setenv("VLLM_VM903_URL", "http://vm903:8000")
        mock_get.return_value = _fleet_resp(200, ["gemma4-31b"])

        url, label = resolve_fleet_url("gemma4-31b")

        assert (url, label) == ("http://vm913:8000", "vm913")

    @patch("app.services.llm_resolution.requests.get")
    def test_skips_vm_without_model(self, mock_get, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        monkeypatch.setenv("VLLM_VM903_URL", "http://vm903:8000")
        mock_get.side_effect = [
            _fleet_resp(200, ["other-model"]),
            _fleet_resp(200, ["gemma4-31b"]),
        ]

        url, label = resolve_fleet_url("gemma4-31b")

        assert (url, label) == ("http://vm903:8000", "vm903")

    @patch("app.services.llm_resolution.requests.get")
    def test_unreachable_vm_is_skipped(self, mock_get, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        monkeypatch.setenv("VLLM_VM903_URL", "http://vm903:8000")
        mock_get.side_effect = [
            requests.exceptions.ConnectionError(),
            _fleet_resp(200, ["gemma4-31b"]),
        ]

        url, label = resolve_fleet_url("gemma4-31b")

        assert (url, label) == ("http://vm903:8000", "vm903")

    def test_no_env_vars_returns_none(self, monkeypatch):
        for var in ("VLLM_VM913_URL", "VLLM_VM903_URL", "VLLM_VM901_URL", "VLLM_VM2900_URL"):
            monkeypatch.delenv(var, raising=False)

        assert resolve_fleet_url("gemma4-31b") == (None, None)


# ---------------------------------------------------------------------------
# discover_fleet_model + dynamic adoption in resolve_user_llm
# ---------------------------------------------------------------------------

class TestDynamicFleetAdoption:
    """When the user has no model configured and the provider is vllm,
    adopt the first model actually loaded on the first reachable fleet VM.

    Hardcoded defaults remain only as the final fallback when the fleet is
    unreachable or every VM reports no loaded models.
    """

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.services.llm_resolution.requests.get")
    def test_vllm_no_user_model_adopts_first_loaded_model(
        self, mock_get, _fleet, monkeypatch
    ):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        mock_get.return_value = _fleet_resp(200, ["gemma4-31b-awq", "qwen3.6-27b-awq"])

        result = resolve_user_llm(_owner(provider="vllm"))

        assert result.provider_name == "vllm"
        assert result.model == "gemma4-31b-awq"
        assert result.base_url == "http://vm913:8000"
        assert result.fleet_node == "vm913"
        _fleet.assert_not_called()  # adoption replaced the fleet-model lookup

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.services.llm_resolution.requests.get")
    def test_vllm_no_user_model_skips_dead_vm_adopts_from_next(
        self, mock_get, _fleet, monkeypatch
    ):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        monkeypatch.setenv("VLLM_VM903_URL", "http://vm903:8000")
        mock_get.side_effect = [
            requests.exceptions.ConnectionError(),
            _fleet_resp(200, ["qwen3.6-27b-awq"]),
        ]

        result = resolve_user_llm(_owner(provider="vllm"))

        assert result.model == "qwen3.6-27b-awq"
        assert result.base_url == "http://vm903:8000"
        assert result.fleet_node == "vm903"
        _fleet.assert_not_called()

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.services.llm_resolution.requests.get", side_effect=requests.exceptions.ConnectionError())
    def test_vllm_no_user_model_fleet_empty_falls_back_to_default(
        self, _get, _fleet, monkeypatch
    ):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")

        result = resolve_user_llm(_owner(provider="vllm"))

        # Adoption failed; the existing fleet/fallback chain runs and picks
        # the configured default + the env-var fallback URL.
        from app.services.llm_providers import DEFAULT_MODELS

        assert result.model == DEFAULT_MODELS["vllm"]
        assert result.base_url == "http://vm913:8000"
        assert result.fleet_node is None
        _fleet.assert_called_once_with(DEFAULT_MODELS["vllm"])

    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    @patch("app.services.llm_resolution.requests.get")
    def test_vllm_no_user_model_skips_malformed_json(
        self, mock_get, _fleet, monkeypatch
    ):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        monkeypatch.setenv("VLLM_VM903_URL", "http://vm903:8000")
        bad = MagicMock()
        bad.status_code = 200
        bad.json.side_effect = ValueError("not json")
        mock_get.side_effect = [bad, _fleet_resp(200, ["qwen3.6-27b-awq"])]

        result = resolve_user_llm(_owner(provider="vllm"))

        assert result.model == "qwen3.6-27b-awq"
        assert result.fleet_node == "vm903"
        _fleet.assert_not_called()

    @patch("app.services.llm_resolution.resolve_fleet_url")
    def test_vllm_user_pinned_model_behavior_unchanged(self, mock_fleet):
        """Pinned-model path MUST NOT invoke adoption."""
        mock_fleet.return_value = ("http://vm903:8000", "vm903")

        result = resolve_user_llm(_owner(provider="vllm", model="gemma4-31b"))

        mock_fleet.assert_called_once_with("gemma4-31b")
        assert result.model == "gemma4-31b"
        assert result.base_url == "http://vm903:8000"
        assert result.fleet_node == "vm903"

    @patch("app.services.llm_resolution.discover_fleet_model", return_value=None)
    @patch("app.services.llm_resolution.resolve_fleet_url", return_value=(None, None))
    def test_non_vllm_provider_never_runs_adoption(self, _fleet, mock_discover):
        result = resolve_user_llm(_owner(provider="ollama", model="qwen3:8b"))

        mock_discover.assert_not_called()
        assert result.provider_name == "ollama"
        assert result.model == "qwen3:8b"

    @patch("app.services.llm_resolution.requests.get")
    def test_discover_fleet_model_unit_returns_first_loaded_model(self, mock_get, monkeypatch):
        monkeypatch.setenv("VLLM_VM913_URL", "http://vm913:8000")
        mock_get.return_value = _fleet_resp(200, ["gemma4-31b-awq", "qwen3.6-27b-awq"])

        result = discover_fleet_model()

        assert result == ("gemma4-31b-awq", "http://vm913:8000", "vm913")
