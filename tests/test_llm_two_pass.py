"""Tests for the two-pass context-aware LLM summarization pipeline."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm import (
    ContentType,
    LLMService,
    SectionAnalysis,
    TranscriptSection,
    _CONTENT_TYPE_PROMPTS,
    _LANGUAGE_NAMES,
    _language_name,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def service() -> LLMService:
    return LLMService()


SAMPLE_ANALYSES = [
    SectionAnalysis(
        title="Introduction",
        start_timestamp="00:00:00",
        end_timestamp="00:02:00",
        content_type=ContentType.INTRO,
        key_topics=["overview", "prerequisites"],
    ),
    SectionAnalysis(
        title="Setting Up the Project",
        start_timestamp="00:02:00",
        end_timestamp="00:05:00",
        content_type=ContentType.DEMO_TUTORIAL,
        key_topics=["npm init", "dependencies"],
    ),
    SectionAnalysis(
        title="Conclusion",
        start_timestamp="00:05:00",
        end_timestamp="END",
        content_type=ContentType.CONCLUSION,
        key_topics=["summary", "next steps"],
    ),
]

SAMPLE_TRANSCRIPT = (
    "[00:00:01] Welcome to this tutorial on building a web app.\n"
    "[00:00:10] Today we will cover the basics.\n"
    "[00:01:30] You need Node.js installed.\n"
    "## [00:02:00] Setting Up the Project\n"
    "[00:02:05] First run npm init.\n"
    "[00:03:00] Then install express.\n"
    "[00:04:30] Create an index.js file.\n"
    "## [00:05:00] Conclusion\n"
    "[00:05:05] That wraps it up.\n"
    "[00:05:30] Next steps are to add routes.\n"
)

SAMPLE_ANALYSIS_JSON = json.dumps([
    {
        "title": "Introduction",
        "start_timestamp": "00:00:00",
        "end_timestamp": "00:02:00",
        "content_type": "intro",
        "key_topics": ["overview", "prerequisites"],
    },
    {
        "title": "Setting Up the Project",
        "start_timestamp": "00:02:00",
        "end_timestamp": "00:05:00",
        "content_type": "demo_tutorial",
        "key_topics": ["npm init", "dependencies"],
    },
    {
        "title": "Conclusion",
        "start_timestamp": "00:05:00",
        "end_timestamp": "END",
        "content_type": "conclusion",
        "key_topics": ["summary", "next steps"],
    },
])


# ---------------------------------------------------------------------------
# TestParseAnalysisResponse
# ---------------------------------------------------------------------------
class TestParseAnalysisResponse:
    def test_valid_json(self, service: LLMService) -> None:
        raw = json.dumps([
            {
                "title": "Intro",
                "start_timestamp": "00:00:00",
                "end_timestamp": "00:01:00",
                "content_type": "intro",
                "key_topics": ["overview"],
            }
        ])
        result = service._parse_analysis_response(raw)
        assert len(result) == 1
        assert result[0].title == "Intro"
        assert result[0].content_type == ContentType.INTRO
        assert result[0].key_topics == ["overview"]

    def test_fenced_json(self, service: LLMService) -> None:
        inner = json.dumps([{
            "title": "Setup",
            "start_timestamp": "00:00:00",
            "end_timestamp": "00:05:00",
            "content_type": "demo_tutorial",
            "key_topics": [],
        }])
        raw = f"```json\n{inner}\n```"
        result = service._parse_analysis_response(raw)
        assert len(result) == 1
        assert result[0].content_type == ContentType.DEMO_TUTORIAL

    def test_missing_fields_defaults(self, service: LLMService) -> None:
        raw = json.dumps([{"start_timestamp": "00:00:00"}])
        result = service._parse_analysis_response(raw)
        assert result[0].title == "Untitled"
        assert result[0].end_timestamp == "END"
        assert result[0].content_type == ContentType.GENERAL
        assert result[0].key_topics == []

    def test_unknown_content_type_defaults_to_general(
        self, service: LLMService
    ) -> None:
        raw = json.dumps([{
            "title": "Mystery",
            "start_timestamp": "00:00:00",
            "end_timestamp": "00:01:00",
            "content_type": "unknown_type",
            "key_topics": [],
        }])
        result = service._parse_analysis_response(raw)
        assert result[0].content_type == ContentType.GENERAL

    def test_empty_array_raises(self, service: LLMService) -> None:
        with pytest.raises(ValueError, match="empty"):
            service._parse_analysis_response("[]")

    def test_non_json_raises(self, service: LLMService) -> None:
        with pytest.raises(ValueError, match="invalid JSON"):
            service._parse_analysis_response("not json at all")

    def test_non_array_raises(self, service: LLMService) -> None:
        with pytest.raises(ValueError, match="empty or non-array"):
            service._parse_analysis_response('{"key": "value"}')


# ---------------------------------------------------------------------------
# TestBuildAnalysisPrompt
# ---------------------------------------------------------------------------
class TestBuildAnalysisPrompt:
    def test_with_chapters(self, service: LLMService) -> None:
        prompt = service._build_analysis_prompt("some text", has_chapters=True)
        assert "chapter markers" in prompt.lower()
        assert "some text" in prompt

    def test_without_chapters(self, service: LLMService) -> None:
        prompt = service._build_analysis_prompt("some text", has_chapters=False)
        assert "no chapter markers" in prompt.lower()
        assert "3-8 logical" in prompt

    def test_truncation_preserves_chapter_lines(
        self, service: LLMService
    ) -> None:
        # Build a transcript that exceeds _MAX_ANALYSIS_CHARS
        filler = "x" * 30_001
        chapter_line = "## [01:00:00] Late Chapter"
        transcript = filler + "\n" + chapter_line + "\n"

        prompt = service._build_analysis_prompt(transcript, has_chapters=True)
        assert "Late Chapter" in prompt


# ---------------------------------------------------------------------------
# TestExtractSectionsFromAnalysis
# ---------------------------------------------------------------------------
class TestExtractSectionsFromAnalysis:
    def test_timestamp_slicing(self, service: LLMService) -> None:
        sections = service._extract_sections_from_analysis(
            SAMPLE_TRANSCRIPT, SAMPLE_ANALYSES, []
        )
        assert len(sections) == 3
        # First section: intro text
        assert "Welcome" in sections[0].text
        assert "Node.js" in sections[0].text
        # Second section: setup text
        assert "npm init" in sections[1].text
        # Third section: conclusion text
        assert "wraps it up" in sections[2].text

    def test_chapter_headers_stripped(self, service: LLMService) -> None:
        sections = service._extract_sections_from_analysis(
            SAMPLE_TRANSCRIPT, SAMPLE_ANALYSES, []
        )
        for section in sections:
            assert "## [" not in section.text

    def test_snapshot_assignment(self, service: LLMService) -> None:
        snapshots = [
            {"timestamp": 30, "image_url": "snap1.png"},
            {"timestamp": 150, "image_url": "snap2.png"},
            {"timestamp": 310, "image_url": "snap3.png"},
        ]
        sections = service._extract_sections_from_analysis(
            SAMPLE_TRANSCRIPT, SAMPLE_ANALYSES, snapshots
        )
        # snap1 (30s) -> intro (0-120s)
        assert len(sections[0].snapshots) == 1
        assert sections[0].snapshots[0]["image_url"] == "snap1.png"
        # snap2 (150s) -> setup (120-300s)
        assert len(sections[1].snapshots) == 1
        assert sections[1].snapshots[0]["image_url"] == "snap2.png"
        # snap3 (310s) -> conclusion (300-END)
        assert len(sections[2].snapshots) == 1
        assert sections[2].snapshots[0]["image_url"] == "snap3.png"


# ---------------------------------------------------------------------------
# TestGetSectionPrompt
# ---------------------------------------------------------------------------
class TestGetSectionPrompt:
    @pytest.mark.parametrize("ct,keyword", [
        (ContentType.INTRO, "prerequisites"),
        (ContentType.CONCEPTUAL, "concept"),
        (ContentType.CODE_WALKTHROUGH, "code"),
        (ContentType.DEMO_TUTORIAL, "step-by-step"),
        (ContentType.CONCLUSION, "takeaways"),
        (ContentType.GENERAL, "bullet points"),
    ])
    def test_each_type_returns_relevant_prompt(
        self, service: LLMService, ct: ContentType, keyword: str
    ) -> None:
        prompt = service._get_section_prompt(ct)
        assert keyword in prompt.lower()


# ---------------------------------------------------------------------------
# TestAssembleOutput
# ---------------------------------------------------------------------------
class TestAssembleOutput:
    def test_headers_and_summaries(self) -> None:
        sections = [
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="Intro",
                    start_timestamp="00:00:00",
                    end_timestamp="00:01:00",
                    content_type=ContentType.INTRO,
                ),
                text="raw text",
                snapshots=[],
            ),
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="Setup",
                    start_timestamp="00:01:00",
                    end_timestamp="END",
                    content_type=ContentType.DEMO_TUTORIAL,
                ),
                text="raw text 2",
                snapshots=[],
            ),
        ]
        result = LLMService._assemble_output(sections, ["Summary 1", "Summary 2"])
        assert "## Intro" in result
        assert "Summary 1" in result
        assert "## Setup" in result
        assert "Summary 2" in result

    def test_title_and_url_prepended(self) -> None:
        sections = [
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="Intro",
                    start_timestamp="00:00:00",
                    end_timestamp="END",
                    content_type=ContentType.INTRO,
                ),
                text="raw text",
                snapshots=[],
            ),
        ]
        result = LLMService._assemble_output(
            sections, ["Summary"],
            title="My Video", youtube_url="https://www.youtube.com/watch?v=abc",
        )
        assert result.startswith("# My Video")
        assert "Source: https://www.youtube.com/watch?v=abc" in result
        assert "---" in result
        assert "## Intro" in result


    def test_images_after_summary(self) -> None:
        sections = [
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="Demo",
                    start_timestamp="00:00:00",
                    end_timestamp="END",
                    content_type=ContentType.DEMO_TUTORIAL,
                ),
                text="raw",
                snapshots=[
                    {"timestamp": 90, "image_url": "img1.png"},
                    {"timestamp": 135, "image_url": "img2.png"},
                ],
            ),
        ]
        result = LLMService._assemble_output(sections, ["Demo summary."])
        # Summary comes before images
        summary_pos = result.index("Demo summary.")
        img1_pos = result.index("![Snapshot at 00:01:30](img1.png)")
        img2_pos = result.index("![Snapshot at 00:02:15](img2.png)")
        assert summary_pos < img1_pos < img2_pos

    def test_correct_order(self) -> None:
        sections = [
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="A",
                    start_timestamp="00:00:00",
                    end_timestamp="00:01:00",
                    content_type=ContentType.GENERAL,
                ),
                text="text a",
                snapshots=[{"timestamp": 30, "image_url": "a.png"}],
            ),
            TranscriptSection(
                analysis=SectionAnalysis(
                    title="B",
                    start_timestamp="00:01:00",
                    end_timestamp="END",
                    content_type=ContentType.GENERAL,
                ),
                text="text b",
                snapshots=[],
            ),
        ]
        result = LLMService._assemble_output(sections, ["Sum A", "Sum B"])
        # Order: ## A, Sum A, image, ## B, Sum B
        a_pos = result.index("## A")
        sum_a_pos = result.index("Sum A")
        img_pos = result.index("![Snapshot at 00:00:30]")
        b_pos = result.index("## B")
        sum_b_pos = result.index("Sum B")
        assert a_pos < sum_a_pos < img_pos < b_pos < sum_b_pos


# ---------------------------------------------------------------------------
# TestTwoPassPipeline (integration, mocked Ollama)
# ---------------------------------------------------------------------------
class TestTwoPassPipeline:
    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_full_pipeline(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Pass 1 returns valid JSON, Pass 2 returns summaries."""
        # Mock _check_ollama (GET /api/tags)
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        # Build responses: first call = Pass 1, then one per section for Pass 2
        pass1_response = MagicMock(status_code=200)
        pass1_response.json.return_value = {"response": SAMPLE_ANALYSIS_JSON}

        pass2_responses = []
        for title in ["Introduction", "Setting Up the Project", "Conclusion"]:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"response": f"Summary of {title}."}
            pass2_responses.append(resp)

        mock_post.side_effect = [pass1_response] + pass2_responses

        result = service.summarize_transcript_sections(
            SAMPLE_TRANSCRIPT,
            snapshots=[{"timestamp": 90, "image_url": "snap.png"}],
        )

        # Verify structured output
        assert "## Introduction" in result
        assert "## Setting Up the Project" in result
        assert "## Conclusion" in result
        assert "Summary of Introduction." in result
        assert "Summary of Conclusion." in result
        # Snapshot placed in intro section (90s < 120s)
        assert "![Snapshot at 00:01:30](snap.png)" in result

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_pipeline_with_title_and_url(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Title and URL are prepended to the output."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        pass1_response = MagicMock(status_code=200)
        pass1_response.json.return_value = {"response": SAMPLE_ANALYSIS_JSON}

        pass2_responses = []
        for title in ["Introduction", "Setting Up the Project", "Conclusion"]:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"response": f"Summary of {title}."}
            pass2_responses.append(resp)

        mock_post.side_effect = [pass1_response] + pass2_responses

        result = service.summarize_transcript_sections(
            SAMPLE_TRANSCRIPT,
            title="My Tutorial",
            youtube_url="https://www.youtube.com/watch?v=test123",
        )

        assert result.startswith("# My Tutorial")
        assert "Source: https://www.youtube.com/watch?v=test123" in result
        assert "## Introduction" in result

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_pipeline_with_no_snapshots(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Pipeline works when no snapshots are provided."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        pass1_response = MagicMock(status_code=200)
        pass1_response.json.return_value = {"response": SAMPLE_ANALYSIS_JSON}

        pass2_responses = []
        for title in ["Introduction", "Setting Up the Project", "Conclusion"]:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"response": f"Summary of {title}."}
            pass2_responses.append(resp)

        mock_post.side_effect = [pass1_response] + pass2_responses

        result = service.summarize_transcript_sections(SAMPLE_TRANSCRIPT)

        assert "## Introduction" in result
        assert "![Snapshot" not in result


# ---------------------------------------------------------------------------
# TestFallbackToSinglePass
# ---------------------------------------------------------------------------
class TestFallbackToSinglePass:
    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_pass1_failure_falls_back(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """When Pass 1 fails, the output should come from single-pass pipeline."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        # First call (Pass 1) fails, subsequent calls (single-pass) succeed
        pass1_fail = MagicMock(status_code=500)
        single_pass_resp = MagicMock(status_code=200)
        single_pass_resp.json.return_value = {
            "response": "Single pass summary."
        }

        mock_post.side_effect = [pass1_fail, single_pass_resp, single_pass_resp]

        result = service.summarize_transcript_sections(SAMPLE_TRANSCRIPT)
        # Should contain single-pass output, not two-pass headers
        assert "## Introduction" not in result
        assert "Single pass summary." in result

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_pass1_invalid_json_falls_back(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """When Pass 1 returns garbage, falls back to single-pass."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        pass1_garbage = MagicMock(status_code=200)
        pass1_garbage.json.return_value = {"response": "not json at all"}

        single_pass_resp = MagicMock(status_code=200)
        single_pass_resp.json.return_value = {
            "response": "Fallback summary."
        }

        mock_post.side_effect = [pass1_garbage, single_pass_resp, single_pass_resp]

        result = service.summarize_transcript_sections(SAMPLE_TRANSCRIPT)
        assert "## Introduction" not in result

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_pass1_empty_array_falls_back(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """When Pass 1 returns [], falls back to single-pass."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        pass1_empty = MagicMock(status_code=200)
        pass1_empty.json.return_value = {"response": "[]"}

        single_pass_resp = MagicMock(status_code=200)
        single_pass_resp.json.return_value = {
            "response": "Fallback summary."
        }

        mock_post.side_effect = [pass1_empty, single_pass_resp, single_pass_resp]

        result = service.summarize_transcript_sections(SAMPLE_TRANSCRIPT)
        assert "## Introduction" not in result


# ---------------------------------------------------------------------------
# TestLanguageAware
# ---------------------------------------------------------------------------
class TestLanguageAware:
    """Tests for language-aware LLM summarization."""

    def test_language_name_known_codes(self) -> None:
        assert _language_name("fr") == "French"
        assert _language_name("es") == "Spanish"
        assert _language_name("EN") == "English"  # case-insensitive

    def test_language_name_unknown_returns_code(self) -> None:
        assert _language_name("xx") == "xx"
        assert _language_name("swahili") == "swahili"

    def test_build_analysis_prompt_french(self, service: LLMService) -> None:
        prompt = service._build_analysis_prompt("some text", has_chapters=True, language="fr")
        assert "French" in prompt
        assert "Keep section titles in French" in prompt

    def test_build_analysis_prompt_english_no_extra(self, service: LLMService) -> None:
        prompt = service._build_analysis_prompt("some text", has_chapters=True, language="en")
        assert "French" not in prompt
        assert "Write your entire response" not in prompt

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_summarize_section_adaptive_french(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Pass 2 prompt includes French instruction when language='fr'."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        section = TranscriptSection(
            analysis=SectionAnalysis(
                title="Introduction",
                start_timestamp="00:00:00",
                end_timestamp="00:01:00",
                content_type=ContentType.INTRO,
                key_topics=["overview"],
            ),
            text="Bienvenue dans ce tutoriel.",
            snapshots=[],
        )

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"response": "Résumé en français."}
        mock_post.return_value = resp

        result = service._summarize_section_adaptive(section, "context", language="fr")
        assert result == "Résumé en français."

        # Verify the prompt sent to Ollama contains French instruction
        call_args = mock_post.call_args
        prompt_sent = call_args[1]["json"]["prompt"] if "json" in call_args[1] else call_args[0][0]
        assert "Write your entire response in French" in prompt_sent

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_summarize_section_fallback_french(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Fallback single-pass prompt includes French instruction."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"response": "Résumé simple."}
        mock_post.return_value = resp

        result = service._summarize_section("Du texte en français.", language="fr")
        assert result == "Résumé simple."

        call_args = mock_post.call_args
        prompt_sent = call_args[1]["json"]["prompt"] if "json" in call_args[1] else call_args[0][0]
        assert "Write your entire response in French" in prompt_sent

    @patch("app.services.llm.requests.post")
    @patch("app.services.llm.requests.get")
    def test_full_pipeline_with_language(
        self, mock_get: MagicMock, mock_post: MagicMock, service: LLMService
    ) -> None:
        """Language threads through entire two-pass pipeline."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen3:8b"}]},
        )

        pass1_response = MagicMock(status_code=200)
        pass1_response.json.return_value = {"response": SAMPLE_ANALYSIS_JSON}

        pass2_responses = []
        for title in ["Introduction", "Setting Up the Project", "Conclusion"]:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"response": f"Résumé de {title}."}
            pass2_responses.append(resp)

        mock_post.side_effect = [pass1_response] + pass2_responses

        result = service.summarize_transcript_sections(
            SAMPLE_TRANSCRIPT, language="fr"
        )

        assert "## Introduction" in result
        assert "Résumé de Introduction." in result

        # Verify Pass 1 prompt included French instruction
        pass1_call = mock_post.call_args_list[0]
        pass1_prompt = pass1_call[1]["json"]["prompt"] if "json" in pass1_call[1] else ""
        assert "French" in pass1_prompt

        # Verify Pass 2 prompts included French instruction
        pass2_call = mock_post.call_args_list[1]
        pass2_prompt = pass2_call[1]["json"]["prompt"] if "json" in pass2_call[1] else ""
        assert "Write your entire response in French" in pass2_prompt
