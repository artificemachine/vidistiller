"""Tests for chain-of-thought (CoT) leakage stripping in LLM summaries.

Observed on prod 2026-08-07: qwen3.6-27b-awq emits a visible
"Here's a thinking process:" preamble ending with "[Text to output]"
before the real answer, and that reasoning leaked into saved documents.
The strip must remove the CoT block while keeping the actual answer.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm import LLMService


def _service(model="qwen3.6-27b-awq"):
    svc = LLMService()
    svc._model = model
    return svc


# ---------------------------------------------------------------------------
# _strip_cot_leakage unit tests
# ---------------------------------------------------------------------------

class TestStripCotLeakage:
    def test_plain_text_unchanged(self):
        svc = _service()
        text = "Lambda functions streamline thread creation.\n- Bullet one\n- Bullet two"
        assert svc._strip_cot_leakage(text) == text

    def test_empty_text_unchanged(self):
        assert _service()._strip_cot_leakage("") == ""
        assert _service()._strip_cot_leakage(None) is None

    def test_strips_leading_thinking_process(self):
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1.  **Analyze User Input:**\n"
            "   - **Role:** Technical writer\n"
            "   - **Task:** Rewrite the transcript\n"
            "2.  **Draft Paragraph:**\n"
            "   Lambda functions provide a streamlined approach.\n"
            "   Let's check against constraints:\n"
            "   - 1-2 paragraphs? Yes.\n"
            "   Output Generation.\n"
            "   [Text to output]\n"
            "Lambda functions provide a streamlined approach to creating threads.\n"
            "- Inline lambda expressions replace named functions.\n"
            "- Thread constructors accept lambda syntax directly."
        )
        result = svc._strip_cot_leakage(leaked)
        assert "thinking process" not in result.lower()
        assert "Analyze User Input" not in result
        assert "Let's check against constraints" not in result
        assert "Lambda functions provide a streamlined approach to creating threads." in result
        assert "Inline lambda expressions replace named functions." in result

    def test_no_answer_boundary_returns_empty(self):
        """No '[Text to output]' boundary: the whole response is reasoning, return ''."""
        svc = _service()
        leaked = "Here's a thinking process:\n1. step one\n2. step two\nActual summary text here."
        result = svc._strip_cot_leakage(leaked)
        assert result == ""

    def test_section_path_falls_back_to_text_when_all_cot(self):
        """When both the original and the no-CoT retry are reasoning-only, fall back to the text."""
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1.  **Analyze User Input:**\n"
            "   - **Role:** Technical writer\n"
            "   - **Task:** Rewrite the transcript\n"
            "2.  **Draft:**\n"
            "   Some draft summary text.\n"
            "   *Self-Correction:*\n"
            "   Let's check against constraints."
        )
        with patch.object(svc._provider, "generate", side_effect=[leaked, leaked]):
            result = svc._summarize_section("ORIGINAL TRANSCRIPT TEXT", "en")
        assert result == "ORIGINAL TRANSCRIPT TEXT"
        assert "thinking process" not in result.lower()
        assert "Draft" not in result

    def test_section_path_retries_without_cot_and_keeps_clean_answer(self):
        """Reasoning-only first response triggers a no-CoT retry; the clean answer is kept."""
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1.  **Analyze User Input:**\n"
            "   - **Role:** Technical writer\n"
            "2.  **Draft:**\n"
            "   *Self-Correction:*\n"
            "   Let's check."
        )
        clean = "Lambda functions provide a streamlined approach to creating threads."
        with patch.object(svc._provider, "generate", side_effect=[leaked, clean]):
            result = svc._summarize_section("ORIGINAL TRANSCRIPT TEXT", "en")
            assert result == clean
            # The retry prompt must explicitly forbid chain-of-thought
            retry_prompt = svc._provider.generate.call_args_list[1].kwargs["prompt"]
            assert "do NOT show any thinking process" in retry_prompt

    def test_section_path_retry_failure_falls_back_to_text(self):
        """If the no-CoT retry raises, fall back to the transcript text."""
        svc = _service()
        leaked = "Here's a thinking process:\n1. step one\n2. step two"
        with patch.object(
            svc._provider, "generate", side_effect=[leaked, Exception("retry boom")]
        ):
            result = svc._summarize_section("ORIGINAL TRANSCRIPT TEXT", "en")
        assert result == "ORIGINAL TRANSCRIPT TEXT"

    def test_case_insensitive_marker(self):
        svc = _service()
        leaked = "HERE'S A THINKING PROCESS:\nthinking here\n[Text to output]\nReal answer."
        result = svc._strip_cot_leakage(leaked)
        assert result.startswith("Real answer.")

    def test_strips_qwen_think_tags(self):
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1. Draft\n"
            "<think>\n"
            "The user wants a summary. Let me plan the steps.\n"
            "1. Analyze\n"
            "2. Draft\n"
            "</think>\n"
            "The real summary text after the think block."
        )
        result = svc._strip_cot_leakage(leaked)
        assert "<think>" not in result
        assert "Let me plan the steps" not in result
        assert "The real summary text after the think block." in result

    def test_cuts_at_last_output_marker(self):
        """The answer comes after the LAST output-style marker, not the first.

        Observed live (doc 46): the model wrote reasoning with
        '[Output Generation] (proceeds)' early, then more self-correction,
        then '[Output] -> *Proceeds*', then the real summary. Cutting at the
        first marker would keep the later reasoning; cutting at the last one
        yields the answer.
        """
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1. Draft step\n"
            "   [Output Generation] (proceeds)\n"
            "   *(Self-Correction)*: let me re-check the bullets.\n"
            "   [Final Check of the Prompt]: all constraints met.\n"
            "   [Output] -> *Proceeds*\n"
            "   *(Final Text Generation)*\n"
            "Compiling and executing the updated source code confirms the program works.\n"
            "- Thread instantiation relies on constructor signatures.\n"
        )
        result = svc._strip_cot_leakage(leaked)
        assert "Self-Correction" not in result
        assert "Final Check" not in result
        assert "Compiling and executing the updated source code" in result
        assert "Thread instantiation relies on constructor signatures" in result

    def test_strips_think_tags_without_marker(self):
        """<think>...</think> is stripped even when no 'thinking process' marker is present."""
        svc = _service()
        leaked = "<think>internal reasoning here</think>\nClean answer only."
        result = svc._strip_cot_leakage(leaked)
        assert "<think>" not in result
        assert "internal reasoning" not in result
        assert result == "Clean answer only."

    def test_unclosed_think_tag_returns_empty(self):
        """Unclosed <think> tag: no safe content, return '' (caller falls back to transcript)."""
        svc = _service()
        leaked = "<think>reasoning never closed\nAnswer text."
        result = svc._strip_cot_leakage(leaked)
        assert result == ""


# ---------------------------------------------------------------------------
# Section summarization paths apply the strip
# ---------------------------------------------------------------------------

class TestCotStripAppliedInSectionPaths:
    def test_summarize_section_strips_cot(self):
        """Single-pass path: returned summary must not contain the thinking block."""
        svc = _service()
        leaked = (
            "Here's a thinking process:\n"
            "1. Analyze input\n"
            "[Text to output]\n"
            "Real technical summary with facts."
        )
        with patch.object(svc._provider, "generate", return_value=leaked):
            result = svc._summarize_section("some transcript text", "en")
        assert "thinking process" not in result.lower()
        assert "Real technical summary with facts." in result

    def test_summarize_section_adaptive_strips_cot(self):
        """Two-pass path: returned summary must not contain the thinking block."""
        from app.services.llm import TranscriptSection, SectionAnalysis

        svc = _service()
        section = TranscriptSection(
            analysis=SectionAnalysis(
                title="Threads in C++",
                start_timestamp="00:01:00",
                end_timestamp="00:02:00",
                content_type="code_tutorial",
                key_topics=["lambda", "thread"],
            ),
            text="The transcript section text here",
            snapshots=[],
        )
        leaked = (
            "Here's a thinking process:\n"
            "1. Draft\n"
            "[Text to output]\n"
            "Threads in C++ explained: lambda functions encapsulate targets."
        )
        with patch.object(svc._provider, "generate", return_value=leaked):
            result = svc._summarize_section_adaptive(section, "overview", "en")
        assert "thinking process" not in result.lower()
        assert "Threads in C++ explained" in result

    def test_summarize_section_error_fallback_unchanged(self):
        """On provider error the original text is returned (no crash)."""
        svc = _service()
        with patch.object(svc._provider, "generate", side_effect=Exception("boom")):
            result = svc._summarize_section("original text", "en")
        assert result == "original text"


@pytest.mark.parametrize("method_name", ["_summarize_section", "_summarize_section_adaptive"])
def test_strip_is_idempotent(method_name):
    """Applying the strip twice yields the same result."""
    svc = _service()
    leaked = "Here's a thinking process:\n1. x\n[Text to output]\nClean answer."
    once = svc._strip_cot_leakage(leaked)
    assert svc._strip_cot_leakage(once) == once
