"""Unit tests for VLLMProvider and build_provider("vllm", ...)."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from app.services.llm_providers import (
    DEFAULT_MODELS,
    VLLMProvider,
    build_provider,
)


# ---------------------------------------------------------------------------
# VLLMProvider — URL normalisation
# ---------------------------------------------------------------------------

def test_vllm_provider_appends_v1():
    with patch("openai.OpenAI") as mock_cls:
        VLLMProvider("http://192.0.2.1:8100")
        mock_cls.assert_called_once_with(
            base_url="http://192.0.2.1:8100/v1",
            api_key=ANY,
        )


def test_vllm_provider_does_not_double_append_v1():
    with patch("openai.OpenAI") as mock_cls:
        VLLMProvider("http://192.0.2.1:8100/v1")
        mock_cls.assert_called_once_with(
            base_url="http://192.0.2.1:8100/v1",
            api_key=ANY,
        )


def test_vllm_provider_strips_trailing_slash():
    with patch("openai.OpenAI") as mock_cls:
        VLLMProvider("http://192.0.2.1:8100/")
        base_url_used = mock_cls.call_args.kwargs["base_url"]
        assert base_url_used == "http://192.0.2.1:8100/v1"


# ---------------------------------------------------------------------------
# VLLMProvider.generate()
# ---------------------------------------------------------------------------

def _make_provider(base_url: str = "http://localhost:8100") -> tuple[VLLMProvider, MagicMock]:
    mock_client = MagicMock()
    with patch("openai.OpenAI", return_value=mock_client):
        provider = VLLMProvider(base_url)
    return provider, mock_client


def test_vllm_generate_returns_content():
    provider, mock_client = _make_provider()
    mock_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="generated text"))
    ]

    result = provider.generate("hello", model="qwopus-27b")

    assert result == "generated text"
    mock_client.chat.completions.create.assert_called_once()


def test_vllm_generate_passes_model_and_prompt():
    provider, mock_client = _make_provider()
    mock_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]

    provider.generate("my prompt", model="some-model", timeout=60, max_tokens=512)

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "some-model"
    assert call_kwargs["messages"] == [{"role": "user", "content": "my prompt"}]
    assert call_kwargs["timeout"] == 60
    assert call_kwargs["max_tokens"] == 512


def test_vllm_generate_handles_empty_content():
    provider, mock_client = _make_provider()
    mock_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=None))
    ]

    result = provider.generate("hello", model="qwopus-27b")

    assert result == ""


# ---------------------------------------------------------------------------
# build_provider("vllm", ...)
# ---------------------------------------------------------------------------

def test_build_provider_vllm_returns_vllm_provider():
    with patch("openai.OpenAI"):
        provider = build_provider("vllm", ollama_base_url="http://192.0.2.1:8100")
    assert isinstance(provider, VLLMProvider)


def test_build_provider_vllm_does_not_require_api_key():
    with patch("openai.OpenAI"):
        provider = build_provider("vllm", api_key=None, ollama_base_url="http://192.0.2.1:8100")
    assert isinstance(provider, VLLMProvider)


def test_build_provider_vllm_uses_default_base_url():
    with patch("openai.OpenAI") as mock_cls:
        build_provider("vllm")
    base_url_used = mock_cls.call_args.kwargs["base_url"]
    assert "/v1" in base_url_used


def test_build_provider_unknown_raises():
    with pytest.raises(ValueError, match="vllm"):
        build_provider("unknown_provider")


# ---------------------------------------------------------------------------
# DEFAULT_MODELS
# ---------------------------------------------------------------------------

def test_default_models_includes_vllm():
    assert "vllm" in DEFAULT_MODELS
    assert DEFAULT_MODELS["vllm"] == "gemma4-31b"
