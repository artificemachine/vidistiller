"""Task-level routing contracts for text, vision, and long-context work."""

from unittest.mock import MagicMock, patch


def test_summary_requests_text_capability():
    from app.services.llm_fleet import LLMTask
    from app.services.llm_resolution import resolve_task_llm

    with patch(
        "app.services.llm_resolution.load_model_profiles",
        return_value={("primary", "model"): MagicMock(tier="local")},
    ), patch("app.services.llm_resolution.route_llm") as route:
        resolve_task_llm(None, LLMTask.TRANSCRIPT_SUMMARY)

    assert route.call_args.args[1].required_capabilities == frozenset({"text"})


def test_long_transcript_requests_sufficient_context():
    from app.services.llm_fleet import LLMTask
    from app.tasks import required_context_tokens_for_transcript

    assert required_context_tokens_for_transcript("x" * 16_001) == 8_001
    assert LLMTask.LONG_ANALYSIS.value == "long_analysis"


def test_snapshot_prepass_uses_separate_vision_route():
    from app.services.llm import LLMService

    service = LLMService.__new__(LLMService)
    text_provider = MagicMock(spec=[])
    vision_provider = MagicMock()
    vision_provider.describe_image.return_value = "A deployment diagram."
    service._provider = text_provider
    service._model = "text-model"
    service._vision_provider = vision_provider
    service._vision_model = "vision-model"
    service._use_default_vision_provider = False
    service._check_ollama = MagicMock()
    service._analyze_transcript = MagicMock(return_value=[])
    service._split_into_sections = MagicMock(return_value=[])

    service.summarize_transcript_sections(
        "Transcript body",
        snapshots=[{"timestamp": 0, "image_url": "data:image/png;base64,AA=="}],
    )

    vision_provider.describe_image.assert_called_once_with(
        image_url="data:image/png;base64,AA==", model="vision-model"
    )
    assert not hasattr(text_provider, "describe_image")


def test_incompatible_vision_model_is_never_called():
    from app.services.llm import LLMService

    service = LLMService.__new__(LLMService)
    text_provider = MagicMock()
    service._provider = text_provider
    service._model = "text-model"
    service._vision_provider = None
    service._vision_model = None
    service._use_default_vision_provider = False
    service._check_ollama = MagicMock()
    service._analyze_transcript = MagicMock(return_value=[])
    service._split_into_sections = MagicMock(return_value=[])

    service.summarize_transcript_sections(
        "Transcript body",
        snapshots=[{"timestamp": 0, "image_url": "data:image/png;base64,AA=="}],
    )

    assert text_provider.method_calls == []
