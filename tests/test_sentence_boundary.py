"""Tests for sentence boundary detection in LLMService._split_into_sections."""

import pytest

from app.services.llm import LLMService


# ---------------------------------------------------------------------------
# Unit tests for _ends_sentence
# ---------------------------------------------------------------------------
class TestEndsSentence:
    """Parametrized unit tests calling LLMService._ends_sentence() directly."""

    # --- True: real sentence endings ---
    @pytest.mark.parametrize("text", [
        "This is a sentence.",
        "Wow!",
        "Is this right?",
        "Dr. Smith is here.",
        "She said hello to Mr. Jones at the park.",
        "End of the line!",
    ])
    def test_true_sentence_endings(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is True

    # --- False: abbreviations ---
    @pytest.mark.parametrize("text", [
        "ask Dr.",
        "etc.",
        "e.g.",
        "i.e.",
        "vs.",
        "see Prof.",
        "contact Mrs.",
    ])
    def test_false_abbreviations(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is False

    # --- False: single uppercase letter + dot ---
    @pytest.mark.parametrize("text", [
        "U.",
        "A.",
        "initial J.",
    ])
    def test_false_single_letter(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is False

    # --- False: ellipsis ---
    @pytest.mark.parametrize("text", [
        "and then...",
        "wait....",
        "hmm...",
    ])
    def test_false_ellipsis(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is False

    # --- False: numbers / decimals / versions ---
    @pytest.mark.parametrize("text", [
        "version 3.",
        "costs $5.",
        "Python 3.12.",
        "price 2.99.",
    ])
    def test_false_numbers(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is False

    # --- False: filename-like tokens ---
    @pytest.mark.parametrize("text", [
        "config.py.",
        "index.html.",
        "open main.js.",
    ])
    def test_false_file_extensions(self, text: str) -> None:
        assert LLMService._ends_sentence(text) is False

    # --- Edge cases ---
    def test_empty_string(self) -> None:
        assert LLMService._ends_sentence("") is False

    def test_whitespace_only(self) -> None:
        assert LLMService._ends_sentence("   ") is False

    def test_no_punctuation(self) -> None:
        assert LLMService._ends_sentence("no punctuation here") is False

    def test_just_dot(self) -> None:
        assert LLMService._ends_sentence(".") is False


# ---------------------------------------------------------------------------
# Integration tests for _split_into_sections with boundary detection
# ---------------------------------------------------------------------------
class TestSplitIntoSectionsWithBoundary:
    """Test that _split_into_sections uses improved boundary detection."""

    @pytest.fixture()
    def service(self) -> LLMService:
        return LLMService()

    def test_real_sentence_end_flushes_before_image(
        self, service: LLMService
    ) -> None:
        """When a post-image line ends a sentence, accumulated text is flushed
        and the image marker is placed after it."""
        lines = [
            "[00:00:01] This is a complete sentence.",
            "![Snapshot at 00:00:02](img.png)",
            "[00:00:03] Next sentence ends here.",
            "[00:00:04] Another line in new section.",
        ]
        sections = service._split_into_sections(lines)

        # Text flushed (pre- and post-image lines together), then image
        assert sections[0]["type"] == "text"
        assert "complete sentence" in sections[0]["content"]
        assert sections[1]["type"] == "marker"
        # Remaining text forms a separate section
        assert sections[2]["type"] == "text"
        assert "Another line" in sections[2]["content"]

    def test_abbreviation_does_not_flush(self, service: LLMService) -> None:
        """Abbreviation at line end should NOT cause a flush — sentence spans image."""
        lines = [
            "[00:00:01] Talk to Dr.",
            "![Snapshot at 00:00:02](img.png)",
            "[00:00:03] Smith about the results.",
        ]
        sections = service._split_into_sections(lines)

        # Text should NOT be flushed before the image; it continues
        text_sections = [s for s in sections if s["type"] == "text"]
        assert len(text_sections) == 1
        assert "Dr." in text_sections[0]["content"]
        assert "Smith" in text_sections[0]["content"]

    def test_ellipsis_does_not_flush(self, service: LLMService) -> None:
        """Ellipsis at line end should NOT cause a flush."""
        lines = [
            "[00:00:01] And then...",
            "![Snapshot at 00:00:02](img.png)",
            "[00:00:03] something happened.",
        ]
        sections = service._split_into_sections(lines)

        text_sections = [s for s in sections if s["type"] == "text"]
        assert len(text_sections) == 1
        assert "then..." in text_sections[0]["content"]
        assert "something" in text_sections[0]["content"]

    def test_three_line_fallback_forces_flush(
        self, service: LLMService
    ) -> None:
        """After 3 lines past an image, text should flush regardless."""
        lines = [
            "[00:00:01] Line one",
            "![Snapshot at 00:00:02](img.png)",
            "[00:00:03] Line two",
            "[00:00:04] Line three",
            "[00:00:05] Line four",
        ]
        sections = service._split_into_sections(lines)

        # The 3-line fallback should have triggered a flush
        marker_sections = [s for s in sections if s["type"] == "marker"]
        assert len(marker_sections) == 1

    def test_chapter_header_always_flushes(
        self, service: LLMService
    ) -> None:
        """Chapter headers are hard boundaries — always flush."""
        lines = [
            "[00:00:01] Some text before chapter.",
            "## [00:01:00] New Chapter",
            "[00:01:01] Text in new chapter.",
        ]
        sections = service._split_into_sections(lines)

        assert sections[0] == {
            "type": "text",
            "content": "[00:00:01] Some text before chapter.",
        }
        assert sections[1]["type"] == "marker"
        assert "New Chapter" in sections[1]["content"]
