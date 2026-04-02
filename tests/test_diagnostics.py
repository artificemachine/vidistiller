"""Tests for Ollama diagnostics (LLMService.diagnose_ollama + endpoint)."""

from unittest.mock import patch, MagicMock

import pytest
import requests
from fastapi.testclient import TestClient

from app.main import app
from app.services.llm import LLMService


# ---------------------------------------------------------------------------
# Unit tests: LLMService.diagnose_ollama()
# ---------------------------------------------------------------------------

class TestDiagnoseOllamaUnit:
    """Test diagnose_ollama with mocked HTTP calls."""

    def _make_service(self) -> LLMService:
        svc = LLMService()
        return svc

    @patch("app.services.llm.requests.get")
    def test_unreachable_connection_refused(self, mock_get):
        """When Ollama is down, result should show not reachable + suggestions."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = self._make_service().diagnose_ollama()

        assert result["reachable"] is False
        assert result["error"] == "Connection refused"
        assert result["models_available"] == []
        assert result["model_found"] is False
        assert any("ollama serve" in s for s in result["suggestions"])
        assert any("OLLAMA_URL" in s for s in result["suggestions"])

    @patch("app.services.llm.requests.get")
    def test_unreachable_timeout(self, mock_get):
        """When Ollama times out, result should show not reachable."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        result = self._make_service().diagnose_ollama()

        assert result["reachable"] is False
        assert result["error"] == "Connection timed out"
        assert any("ollama serve" in s for s in result["suggestions"])

    @patch("app.services.llm.requests.get")
    def test_unreachable_bad_status(self, mock_get):
        """When Ollama returns non-200, result should show not reachable."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = self._make_service().diagnose_ollama()

        assert result["reachable"] is False
        assert "HTTP 500" in result["error"]
        assert any("ollama serve" in s for s in result["suggestions"])

    @patch("app.services.llm.requests.get")
    def test_reachable_model_missing(self, mock_get):
        """When Ollama is up but configured model is not pulled."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "mistral:latest"},
                {"name": "codellama:7b"},
            ]
        }
        mock_get.return_value = mock_resp

        svc = self._make_service()
        # Ensure the configured model differs from what's available
        svc.settings.ollama.model_name = "qwen3:8b"

        result = svc.diagnose_ollama()

        assert result["reachable"] is True
        assert result["model_found"] is False
        assert result["models_available"] == ["mistral:latest", "codellama:7b"]
        assert any("ollama pull qwen3:8b" in s for s in result["suggestions"])

    @patch("app.services.llm.requests.get")
    def test_reachable_model_found_exact(self, mock_get):
        """When Ollama is up and configured model is available (exact match)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3"},
                {"name": "mistral:latest"},
            ]
        }
        mock_get.return_value = mock_resp

        svc = self._make_service()
        svc.settings.ollama.model_name = "llama3"

        result = svc.diagnose_ollama()

        assert result["reachable"] is True
        assert result["model_found"] is True
        assert result["error"] is None
        assert result["response_time_ms"] >= 0
        assert any("journalctl" in s for s in result["suggestions"])

    @patch("app.services.llm.requests.get")
    def test_reachable_model_found_with_tag(self, mock_get):
        """Model 'llama3' matches 'llama3:latest' via prefix."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3:latest"}]
        }
        mock_get.return_value = mock_resp

        svc = self._make_service()
        svc.settings.ollama.model_name = "llama3"

        result = svc.diagnose_ollama()

        assert result["model_found"] is True

    @patch("app.services.llm.requests.get")
    def test_url_and_model_populated(self, mock_get):
        """Result always contains the configured url and model."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        svc = self._make_service()
        result = svc.diagnose_ollama()

        assert result["url"] == str(svc.settings.ollama.base_url)
        assert result["model"] == svc.settings.ollama.model_name


# ---------------------------------------------------------------------------
# Integration test: GET /api/diagnostics/ollama endpoint
# ---------------------------------------------------------------------------

class TestDiagnosticsEndpoint:
    """Test the /api/diagnostics/ollama route."""

    @patch("app.routes.health.LLMService")
    def test_endpoint_returns_diagnostics(self, MockLLMService, auth_headers):
        """Endpoint should return the dict from diagnose_ollama."""
        mock_diag = {
            "url": "http://10.0.0.1:11434",
            "model": "llama3",
            "reachable": False,
            "response_time_ms": 0,
            "models_available": [],
            "model_found": False,
            "error": "Connection refused",
            "suggestions": ["Run: ollama serve"],
        }
        MockLLMService.return_value.diagnose_ollama.return_value = mock_diag

        client = TestClient(app)
        resp = client.get("/api/diagnostics/ollama", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["reachable"] is False
        assert data["error"] == "Connection refused"
        assert data["suggestions"] == ["Run: ollama serve"]

    @patch("app.routes.health.LLMService")
    def test_endpoint_returns_healthy(self, MockLLMService, auth_headers):
        """Endpoint returns healthy diagnostics when Ollama is up."""
        mock_diag = {
            "url": "http://10.0.0.1:11434",
            "model": "llama3",
            "reachable": True,
            "response_time_ms": 42,
            "models_available": ["llama3:latest"],
            "model_found": True,
            "error": None,
            "suggestions": ["Check Ollama logs: journalctl -u ollama"],
        }
        MockLLMService.return_value.diagnose_ollama.return_value = mock_diag

        client = TestClient(app)
        resp = client.get("/api/diagnostics/ollama", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["reachable"] is True
        assert data["model_found"] is True
        assert data["response_time_ms"] == 42
