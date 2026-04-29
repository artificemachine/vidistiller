"""Unit tests for GET /settings/vllm/models — sidecar model discovery proxy."""

from unittest.mock import MagicMock, patch

import httpx
import pytest


VLLM_MODELS_URL = "/api/settings/vllm/models"

SIDECAR_RESPONSE = {
    "object": "list",
    "data": [
        {"id": "qwopus-27b", "object": "model"},
    ],
}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def test_vllm_models_requires_auth(client):
    resp = client.get(VLLM_MODELS_URL, params={"base_url": "http://192.0.2.1:8100"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_vllm_models_returns_model_list(client, auth_headers, monkeypatch):
    mock_response = MagicMock()
    mock_response.json.return_value = SIDECAR_RESPONSE
    mock_response.raise_for_status = MagicMock()

    monkeypatch.setattr("app.routes.settings.httpx.get", lambda *a, **kw: mock_response)

    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.1:8100"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"models": ["qwopus-27b"]}


def test_vllm_models_returns_multiple_models(client, auth_headers, monkeypatch):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "object": "list",
        "data": [
            {"id": "model-a", "object": "model"},
            {"id": "model-b", "object": "model"},
        ],
    }
    mock_response.raise_for_status = MagicMock()
    monkeypatch.setattr("app.routes.settings.httpx.get", lambda *a, **kw: mock_response)

    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.2:8100"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["models"] == ["model-a", "model-b"]


def test_vllm_models_empty_data_list(client, auth_headers, monkeypatch):
    mock_response = MagicMock()
    mock_response.json.return_value = {"object": "list", "data": []}
    mock_response.raise_for_status = MagicMock()
    monkeypatch.setattr("app.routes.settings.httpx.get", lambda *a, **kw: mock_response)

    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.3:8100"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["models"] == []


# ---------------------------------------------------------------------------
# Sidecar unreachable / timeout
# ---------------------------------------------------------------------------

def test_vllm_models_502_when_sidecar_unreachable(client, auth_headers, monkeypatch):
    def _raise(*a, **kw):
        raise Exception("Connection refused")

    monkeypatch.setattr("app.routes.settings.httpx.get", _raise)

    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.1:8100"},
        headers=auth_headers,
    )

    assert resp.status_code == 502
    assert "sidecar" in resp.json()["detail"].lower()


def test_vllm_models_504_on_timeout(client, auth_headers, monkeypatch):
    def _raise(*a, **kw):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.routes.settings.httpx.get", _raise)

    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.1:8100"},
        headers=auth_headers,
    )

    assert resp.status_code == 504


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_vllm_models_400_no_scheme(client, auth_headers):
    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "192.0.2.1:8100"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_vllm_models_400_file_scheme(client, auth_headers):
    resp = client.get(
        VLLM_MODELS_URL,
        params={"base_url": "file:///etc/passwd"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_vllm_models_400_missing_base_url(client, auth_headers):
    resp = client.get(VLLM_MODELS_URL, headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# URL passed to sidecar
# ---------------------------------------------------------------------------

def test_vllm_models_calls_correct_sidecar_endpoint(client, auth_headers, monkeypatch):
    called_with = {}

    def _mock_get(url, **kw):
        called_with["url"] = url
        m = MagicMock()
        m.json.return_value = {"data": []}
        m.raise_for_status = MagicMock()
        return m

    monkeypatch.setattr("app.routes.settings.httpx.get", _mock_get)

    client.get(
        VLLM_MODELS_URL,
        params={"base_url": "http://192.0.2.1:8100"},
        headers=auth_headers,
    )

    assert called_with["url"] == "http://192.0.2.1:8100/v1/models"
