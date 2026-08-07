"""Unit tests for LLM reachability probes (app.services.llm_health.probe_llm)."""

from unittest.mock import patch, MagicMock

import requests

from app.services.llm_health import probe_llm

# Obviously-fake credential for header/assertion checks (never a real key).
FAKE_KEY = "fake-key-123"


def _resp(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

class TestProbeOllama:
    @patch("app.services.llm_health.requests.get")
    def test_reachable_model_found_exact(self, mock_get):
        mock_get.return_value = _resp(200, {"models": [{"name": "qwen3:8b"}, {"name": "mistral:latest"}]})

        result = probe_llm("ollama", "qwen3:8b", base_url="http://localhost:11434")

        assert result["reachable"] is True
        assert result["model_found"] is True
        assert result["auth_ok"] is None
        assert result["error"] is None
        assert result["models_available"] == ["qwen3:8b", "mistral:latest"]
        assert result["latency_ms"] >= 0

    @patch("app.services.llm_health.requests.get")
    def test_model_matches_via_tag_prefix(self, mock_get):
        mock_get.return_value = _resp(200, {"models": [{"name": "llama3:latest"}]})

        result = probe_llm("ollama", "llama3", base_url="http://localhost:11434")

        assert result["model_found"] is True

    @patch("app.services.llm_health.requests.get")
    def test_reachable_model_missing(self, mock_get):
        mock_get.return_value = _resp(200, {"models": [{"name": "mistral:latest"}]})

        result = probe_llm("ollama", "qwen3:8b", base_url="http://localhost:11434")

        assert result["reachable"] is True
        assert result["model_found"] is False

    @patch("app.services.llm_health.requests.get")
    def test_defaults_to_localhost_when_no_base_url(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError()

        probe_llm("ollama", "llama3", base_url=None)

        called_url = mock_get.call_args[0][0]
        assert called_url == "http://localhost:11434/api/tags"

    @patch("app.services.llm_health.requests.get")
    def test_connection_refused(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = probe_llm("ollama", "llama3", base_url="http://localhost:11434")

        assert result["reachable"] is False
        assert result["error"] == "connection refused"

    @patch("app.services.llm_health.requests.get")
    def test_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()

        result = probe_llm("ollama", "llama3", base_url="http://localhost:11434")

        assert result["reachable"] is False
        assert result["error"] == "connection timed out"


# ---------------------------------------------------------------------------
# vLLM / OpenCode (OpenAI-compatible self-hosted)
# ---------------------------------------------------------------------------

class TestProbeVLLM:
    @patch("app.services.llm_health.requests.get")
    def test_appends_v1_and_finds_model(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": "gemma4-31b"}]})

        result = probe_llm("vllm", "gemma4-31b", base_url="http://10.0.150.36:8000")

        called_url = mock_get.call_args[0][0]
        assert called_url == "http://10.0.150.36:8000/v1/models"
        assert result["reachable"] is True
        assert result["model_found"] is True
        assert result["auth_ok"] is None  # no auth on self-hosted without key

    @patch("app.services.llm_health.requests.get")
    def test_no_double_v1_suffix(self, mock_get):
        mock_get.return_value = _resp(200, {"data": []})

        probe_llm("vllm", "m", base_url="http://host:8000/v1")

        called_url = mock_get.call_args[0][0]
        assert called_url == "http://host:8000/v1/models"

    @patch("app.services.llm_health.requests.get")
    def test_model_not_loaded(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": "other-model"}]})

        result = probe_llm("vllm", "gemma4-31b", base_url="http://host:8000")

        assert result["reachable"] is True
        assert result["model_found"] is False
        assert result["models_available"] == ["other-model"]

    @patch("app.services.llm_health.requests.get")
    def test_http_error_counts_as_reachable(self, mock_get):
        mock_get.return_value = _resp(502)

        result = probe_llm("vllm", "m", base_url="http://host:8000")

        assert result["reachable"] is True
        assert result["error"] == "endpoint returned HTTP 502"

    def test_missing_base_url(self):
        result = probe_llm("vllm", "m", base_url=None)

        assert result["reachable"] is False
        assert result["error"] == "no base URL configured"

    @patch("app.services.llm_health.requests.get")
    def test_opencode_sends_bearer_when_key_present(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": "MiniMax-Text-01"}]})

        result = probe_llm(
            "opencode", "MiniMax-Text-01",
            base_url="https://api.example.com", api_key=FAKE_KEY,
        )

        headers = mock_get.call_args[1]["headers"]
        assert headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert result["auth_ok"] is True


# ---------------------------------------------------------------------------
# Cloud providers
# ---------------------------------------------------------------------------

class TestProbeCloud:
    @patch("app.services.llm_health.requests.get")
    def test_openai_key_accepted(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": "gpt-4o-mini"}]})

        result = probe_llm("openai", "gpt-4o-mini", api_key=FAKE_KEY)

        called_url = mock_get.call_args[0][0]
        assert called_url == "https://api.openai.com/v1/models"
        assert result["reachable"] is True
        assert result["auth_ok"] is True
        assert result["model_found"] is True

    @patch("app.services.llm_health.requests.get")
    def test_openai_key_rejected(self, mock_get):
        mock_get.return_value = _resp(401)

        result = probe_llm("openai", "gpt-4o-mini", api_key=FAKE_KEY)

        assert result["reachable"] is True
        assert result["auth_ok"] is False
        assert "api key rejected" in result["error"]

    def test_cloud_without_key_skips_http(self):
        with patch("app.services.llm_health.requests.get") as mock_get:
            result = probe_llm("deepseek", "deepseek-chat", api_key=None)

        mock_get.assert_not_called()
        assert result["reachable"] is False
        assert result["error"] == "no api key configured"

    @patch("app.services.llm_health.requests.get")
    def test_anthropic_sends_key_headers(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": "claude-sonnet-4-6"}]})

        result = probe_llm("anthropic", "claude-sonnet-4-6", api_key=FAKE_KEY)

        called_url = mock_get.call_args[0][0]
        headers = mock_get.call_args[1]["headers"]
        assert called_url == "https://api.anthropic.com/v1/models"
        assert headers["x-api-key"] == FAKE_KEY
        assert "anthropic-version" in headers
        assert result["auth_ok"] is True
        assert result["model_found"] is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestProbeEdgeCases:
    def test_unknown_provider(self):
        result = probe_llm("doesnotexist", "m")

        assert result["reachable"] is False
        assert "unknown provider" in result["error"]

    @patch("app.services.llm_health.requests.get")
    def test_models_list_capped(self, mock_get):
        mock_get.return_value = _resp(200, {"data": [{"id": f"m{i}"} for i in range(50)]})

        result = probe_llm("vllm", "m0", base_url="http://host:8000")

        assert len(result["models_available"]) == 20

    @patch("app.services.llm_health.requests.get")
    def test_invalid_json_body(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        mock_get.return_value = resp

        result = probe_llm("vllm", "m", base_url="http://host:8000")

        assert result["reachable"] is True
        assert result["error"] == "endpoint returned invalid JSON"

    @patch("app.services.llm_health.requests.get")
    def test_result_shape_is_uniform(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError()

        result = probe_llm("ollama", "llama3", base_url="http://localhost:11434")

        assert set(result.keys()) == {
            "provider", "model", "base_url", "reachable", "auth_ok",
            "model_found", "models_available", "latency_ms", "error",
        }
