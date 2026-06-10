"""Tests for vision pre-pass: snapshot description via fleet vision model."""

from unittest.mock import MagicMock, call, patch

import pytest

from app.services.llm import LLMService


SAMPLE_TRANSCRIPT = (
    "## [00:00:00] Intro\n"
    "[00:00:01] Welcome to this tutorial.\n"
    "[00:01:00] Here is the scanner UI.\n"
    "## [00:02:00] Setup\n"
    "[00:02:05] Configure the settings.\n"
)

SNAPSHOTS = [
    {"timestamp": 10, "image_url": "/static/snapshots/snap_10.jpg"},
    {"timestamp": 70, "image_url": "/static/snapshots/snap_70.jpg"},
    {"timestamp": 125, "image_url": "/static/snapshots/snap_125.jpg"},
]


# ---------------------------------------------------------------------------
# VLLMProvider.describe_image tests
# ---------------------------------------------------------------------------

class TestDescribeImage:
    def test_describe_image_sends_multimodal_request(self):
        """describe_image() sends image_url content type to the completions API."""
        from app.services.llm_providers import VLLMProvider
        provider = VLLMProvider(base_url="http://fake:8100")

        mock_choice = MagicMock()
        mock_choice.message.content = "TradingView gap scanner showing 5 stocks."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(provider.client.chat.completions, "create", return_value=mock_response) as mock_create:
            result = provider.describe_image(
                image_url="http://fake/snap.jpg",
                model="qwen2.5-vl-7b",
            )

        assert result == "TradingView gap scanner showing 5 stocks."
        args, kwargs = mock_create.call_args
        messages = kwargs.get("messages") or args[1] if args else kwargs["messages"]
        # Must include an image_url content block
        content = messages[0]["content"]
        assert isinstance(content, list)
        types = [c["type"] for c in content]
        assert "image_url" in types

    def test_describe_image_returns_empty_string_on_error(self):
        """describe_image() returns '' on any exception — never raises."""
        from app.services.llm_providers import VLLMProvider
        provider = VLLMProvider(base_url="http://fake:8100")

        with patch.object(provider.client.chat.completions, "create", side_effect=Exception("timeout")):
            result = provider.describe_image(image_url="http://fake/snap.jpg", model="qwen2.5-vl-7b")

        assert result == ""

    def test_describe_image_not_available_on_non_vllm_providers(self):
        """OllamaProvider and others don't expose describe_image."""
        from app.services.llm_providers import OllamaProvider
        provider = OllamaProvider()
        assert not hasattr(provider, "describe_image")


# ---------------------------------------------------------------------------
# LLMService vision pre-pass integration tests
# ---------------------------------------------------------------------------

class TestVisionPrepass:
    def _make_service(self):
        with patch("app.services.llm.get_settings") as mock_settings:
            mock_settings.return_value.vllm_fleet.vm913_url = "http://fake:8100"
            mock_settings.return_value.vllm_fleet.vm903_url = ""
            mock_settings.return_value.vllm_fleet.vm901_url = ""
            mock_settings.return_value.vllm_fleet.vm2900_url = ""
            mock_settings.return_value.ollama.base_url = "http://localhost:11434"
            mock_settings.return_value.ollama.model_name = "llama3"
            mock_settings.return_value.service_timeouts.llm_timeout = 120
            svc = LLMService(provider_name="vllm", model_name="qwen2.5-vl-7b")
            svc.settings = mock_settings.return_value
            return svc

    def test_describe_image_called_for_each_snapshot(self):
        """Vision pre-pass calls describe_image once per snapshot before section loop."""
        svc = self._make_service()

        descriptions = ["Scanner UI", "Config panel", "Results chart"]
        call_count = {"n": 0}

        def fake_describe(image_url, model, timeout=30):
            result = descriptions[call_count["n"]]
            call_count["n"] += 1
            return result

        def fake_generate(prompt, model, timeout=120, max_tokens=4096):
            return "Summary paragraph.\n- bullet"

        with patch.object(svc._provider, "describe_image", side_effect=fake_describe), \
             patch.object(svc._provider, "generate", side_effect=fake_generate):
            svc.summarize_transcript_sections(
                transcript_text=SAMPLE_TRANSCRIPT,
                snapshots=SNAPSHOTS,
                language="en",
            )

        assert call_count["n"] == len(SNAPSHOTS)

    def test_vision_prepass_skipped_when_no_snapshots(self):
        """Vision pre-pass is skipped entirely when snapshots list is empty."""
        svc = self._make_service()

        with patch.object(svc._provider, "describe_image") as mock_describe, \
             patch.object(svc._provider, "generate", return_value="Summary.\n- bullet"):
            svc.summarize_transcript_sections(
                transcript_text=SAMPLE_TRANSCRIPT,
                snapshots=[],
                language="en",
            )

        mock_describe.assert_not_called()

    def test_snapshot_descriptions_appear_in_section_prompt(self):
        """Snapshot descriptions are injected into the text passed to generate()."""
        svc = self._make_service()

        seen_prompts = []

        def fake_describe(image_url, model, timeout=30):
            return "VISION_DESCRIPTION_MARKER"

        def fake_generate(prompt, model, timeout=120, max_tokens=4096):
            seen_prompts.append(prompt)
            return "Summary.\n- bullet"

        with patch.object(svc._provider, "describe_image", side_effect=fake_describe), \
             patch.object(svc._provider, "generate", side_effect=fake_generate):
            svc.summarize_transcript_sections(
                transcript_text=SAMPLE_TRANSCRIPT,
                snapshots=SNAPSHOTS,
                language="en",
            )

        combined = "\n".join(seen_prompts)
        assert "VISION_DESCRIPTION_MARKER" in combined

    def test_vision_prepass_non_vllm_provider_graceful(self):
        """Non-vLLM providers (Ollama) silently skip vision pre-pass."""
        with patch("app.services.llm.get_settings") as mock_settings:
            mock_settings.return_value.ollama.base_url = "http://localhost:11434"
            mock_settings.return_value.ollama.model_name = "llama3"
            mock_settings.return_value.vllm_fleet.vm913_url = ""
            mock_settings.return_value.vllm_fleet.vm903_url = ""
            mock_settings.return_value.vllm_fleet.vm901_url = ""
            mock_settings.return_value.vllm_fleet.vm2900_url = ""
            mock_settings.return_value.service_timeouts.llm_timeout = 120
            svc = LLMService(provider_name="ollama", model_name="llama3")
            svc.settings = mock_settings.return_value

        with patch.object(svc, "_check_ollama"), \
             patch.object(svc._provider, "generate", return_value="Summary.\n- bullet"):
            # Must not raise even though OllamaProvider has no describe_image
            result = svc.summarize_transcript_sections(
                transcript_text=SAMPLE_TRANSCRIPT,
                snapshots=SNAPSHOTS,
                language="en",
            )

        assert isinstance(result, str)
