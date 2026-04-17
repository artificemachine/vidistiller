"""
LLM Service

Handles document generation, section structuring, code extraction, and
content generation using configurable LLM providers (Ollama, OpenAI, Anthropic).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Callable

import requests


class CancelledException(Exception):
    """Raised when a summarization is cancelled by the user."""
    pass

from app.core.config import get_settings
from app.exceptions import DocumentGenerationException
from app.services.llm_providers import build_provider, DEFAULT_MODELS, LLMProvider
from sqlalchemy.orm import Session
from app.db.models import Document

logger = logging.getLogger(__name__)



_ABBREVIATIONS: frozenset[str] = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "etc.", "e.g.", "i.e.", "vs.", "approx.", "dept.",
    "est.", "incl.", "govt.", "corp.", "inc.", "ltd.",
    "fig.", "eq.", "ch.", "vol.", "no.", "nos.",
    "min.", "max.", "avg.",
    "st.", "ave.", "blvd.",
})

class ContentType(Enum):
    INTRO = "intro"
    CONCEPTUAL = "conceptual"
    CODE_WALKTHROUGH = "code_walkthrough"
    DEMO_TUTORIAL = "demo_tutorial"
    CONCLUSION = "conclusion"
    GENERAL = "general"


@dataclass
class SectionAnalysis:
    title: str
    start_timestamp: str       # "HH:MM:SS"
    end_timestamp: str         # "HH:MM:SS" or "END"
    content_type: ContentType
    key_topics: list[str] = field(default_factory=list)


@dataclass
class TranscriptSection:
    analysis: SectionAnalysis
    text: str
    snapshots: list[dict] = field(default_factory=list)


_MAX_ANALYSIS_CHARS = 30_000

_CONTENT_TYPE_PROMPTS: dict[ContentType, str] = {
    ContentType.INTRO: (
        "Orient the reader: summarize what the video covers, mention any "
        "prerequisites or tools needed, and set expectations for what will be learned."
    ),
    ContentType.CONCEPTUAL: (
        "Explain the concept directly and clearly. State key principles, definitions, "
        "and relationships. Use factual statements—do not reference a speaker or video."
    ),
    ContentType.CODE_WALKTHROUGH: (
        "Explain what the code does step by step. Preserve important code snippets "
        "in fenced code blocks. Highlight key functions, variables, and patterns."
    ),
    ContentType.DEMO_TUTORIAL: (
        "Write a numbered step-by-step guide. Preserve exact commands, file paths, "
        "and configuration values in code blocks. Be precise and actionable."
    ),
    ContentType.CONCLUSION: (
        "Summarize the key outcomes and main takeaways. List what was accomplished "
        "and suggest logical next steps or further resources."
    ),
    ContentType.GENERAL: (
        "Rewrite into 1-2 concise paragraphs followed by 3-5 bullet points. "
        "Write as if explaining the topic directly to a reader. Use factual statements."
    ),
}

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "ru": "Russian",
    "ja": "Japanese", "ko": "Korean", "zh-cn": "Chinese", "ar": "Arabic",
    "hi": "Hindi", "tr": "Turkish", "pl": "Polish", "sv": "Swedish",
}


def _language_name(code: str) -> str:
    """Return the human-readable name for a language code."""
    return _LANGUAGE_NAMES.get(code.lower(), code)


class LLMService:
    """Service for LLM-powered content generation."""

    def __init__(
        self,
        provider_name: str = "ollama",
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
    ):
        """
        Initialize LLM service with configurable provider.

        Args:
            provider_name: LLM provider ("ollama", "openai", "anthropic"). Defaults to "ollama".
            model_name: Model name. If None, uses provider default.
            api_key: API key for cloud providers (required for openai/anthropic, ignored for ollama).
            ollama_base_url: Custom Ollama base URL. If None, uses settings default.
        """
        self.settings = get_settings()
        self._provider_name = provider_name

        # Use custom Ollama URL or fall back to settings default
        if ollama_base_url is None:
            ollama_base_url = str(self.settings.ollama.base_url)

        # Build provider instance
        self._provider = build_provider(
            provider_name=provider_name,
            api_key=api_key,
            ollama_base_url=ollama_base_url,
        )

        # Set model: use provided model, then provider default, then Ollama default
        if model_name:
            self._model = model_name
        else:
            default = DEFAULT_MODELS.get(provider_name)
            if default:
                self._model = default
            else:
                self._model = self.settings.ollama.model_name

    def generate_documentation(
        self,
        transcript_text: str,
        snapshots: Optional[List[Dict]] = None,
        title: str = "Video Documentation",
        format_type: str = "markdown",
    ) -> str:
        """
        Generate documentation from transcript and snapshots.

        Args:
            transcript_text: Full transcript text
            snapshots: List of snapshot metadata
            title: Document title
            format_type: Output format (markdown, html)

        Returns:
            Generated documentation text

        Raises:
            DocumentGenerationException: If generation fails
        """
        try:
            # Create prompt for documentation generation
            prompt = self._create_prompt(
                transcript_text,
                snapshots,
                title,
                format_type,
            )

            # Call LLM provider
            try:
                content = self._provider.generate(
                    prompt=prompt,
                    model=self._model,
                    timeout=self.settings.service_timeouts.llm_timeout,
                ).strip()
            except Exception as e:
                raise DocumentGenerationException(
                    f"LLM generation error: {str(e)}"
                )

            if not content:
                raise DocumentGenerationException("LLM returned empty response")

            logger.info(f"✓ Generated {len(content)} chars of documentation")
            return content

        except requests.exceptions.Timeout:
            raise DocumentGenerationException("LLM generation timed out")
        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            raise DocumentGenerationException(f"Generation failed: {str(e)}")

    def detect_sections(self, transcript_text: str) -> List[Dict]:
        """
        Detect and structure sections in transcript.

        Args:
            transcript_text: Full transcript text

        Returns:
            List of section dicts with:
            - title: Section title
            - start_char: Start position
            - end_char: End position
            - content: Section content
        """
        try:
            # Use LLM to identify sections
            prompt = f"""Analyze this video transcript and identify main sections/chapters.
List each section with a title. Be concise.

Transcript:
{transcript_text[:2000]}

Output format:
SECTION: Title
"""

            try:
                content = self._provider.generate(
                    prompt=prompt,
                    model=self._model,
                    timeout=30,
                )
            except Exception as e:
                logger.warning(f"Section detection failed ({e}), using heuristics")
                return self._detect_sections_heuristic(transcript_text)

            sections = []
            for line in content.split("\n"):
                if line.startswith("SECTION:"):
                    title = line.replace("SECTION:", "").strip()
                    sections.append({
                        "title": title,
                        "content": "",
                    })

            return sections if sections else self._detect_sections_heuristic(transcript_text)

        except Exception as e:
            logger.warning(f"Section detection failed: {e}")
            return self._detect_sections_heuristic(transcript_text)

    def extract_code_blocks(self, text: str) -> List[Dict]:
        """
        Extract and format code blocks from text.

        Args:
            text: Text containing code examples

        Returns:
            List of code block dicts with:
            - language: Programming language
            - code: Code content
            - context: Surrounding text
        """
        code_blocks = []

        # Pattern for markdown code blocks
        pattern = r"```(\w+)?\n(.*?)```"
        matches = re.finditer(pattern, text, re.DOTALL)

        for match in matches:
            language = match.group(1) or "text"
            code = match.group(2).strip()

            code_blocks.append({
                "language": language,
                "code": code,
                "context": "",
            })

        return code_blocks

    def generate_summary(self, content: str, max_length: int = 500) -> str:
        """
        Generate executive summary of content.

        Args:
            content: Full content to summarize
            max_length: Maximum summary length

        Returns:
            Summary text
        """
        try:
            prompt = f"""Write a brief {max_length}-character summary of this content:

{content[:1500]}

Summary:"""

            return self._provider.generate(
                prompt=prompt,
                model=self._model,
                timeout=30,
            ).strip()

        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            return "See full documentation for details."

    def _check_ollama(self) -> None:
        """Verify Ollama is reachable and the configured model is available."""
        if self._provider_name != "ollama":
            return

        try:
            resp = requests.get(
                f"{self.settings.ollama.base_url}/api/tags",
                timeout=5,
            )
            if resp.status_code != 200:
                raise DocumentGenerationException(
                    "Ollama is not responding. Please ensure Ollama is running on the server."
                )
            # Verify the configured model is actually pulled
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            if self._model and not any(
                m == self._model or m.startswith(f"{self._model}:") for m in models
            ):
                available = ", ".join(models) if models else "none"
                raise DocumentGenerationException(
                    f"Model '{self._model}' not found in Ollama. "
                    f"Available models: {available}. "
                    f"Run: ollama pull {self._model}"
                )
        except DocumentGenerationException:
            raise
        except requests.exceptions.ConnectionError:
            raise DocumentGenerationException(
                "Cannot connect to Ollama. Please ensure Ollama is running on the server."
            )
        except requests.exceptions.Timeout:
            raise DocumentGenerationException(
                "Ollama connection timed out. Please ensure Ollama is running on the server."
            )

    def diagnose_ollama(self) -> Dict:
        """Run diagnostics on the Ollama connection and return actionable info. Only applies when using Ollama provider."""
        import time

        if self._provider_name != "ollama":
            return {
                "error": f"diagnose_ollama() only applies to Ollama provider. Currently using: {self._provider_name}",
                "suggestions": [],
            }

        url = str(self.settings.ollama.base_url)
        model = self.settings.ollama.model_name
        result: Dict = {
            "url": url,
            "model": model,
            "reachable": False,
            "response_time_ms": 0,
            "models_available": [],
            "model_found": False,
            "error": None,
            "suggestions": [],
        }

        # 1. Check connectivity
        try:
            start = time.monotonic()
            resp = requests.get(f"{url}/api/tags", timeout=5)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result["response_time_ms"] = elapsed_ms

            if resp.status_code != 200:
                result["error"] = f"Ollama returned HTTP {resp.status_code}"
                result["suggestions"] = [
                    "Run: ollama serve",
                    f"Check OLLAMA_URL is correct (currently: {url})",
                    "Check firewall / network",
                ]
                return result

            result["reachable"] = True

            # 2. Parse available models
            models = [
                m.get("name", "")
                for m in resp.json().get("models", [])
            ]
            result["models_available"] = models

            # 3. Check if configured model is available
            # Model names may include a tag like "llama3:latest"
            result["model_found"] = any(
                m == model or m.startswith(f"{model}:")
                for m in models
            )

            if not result["model_found"]:
                available = ", ".join(models[:10]) if models else "none"
                result["suggestions"] = [
                    f"Run: ollama pull {model}",
                    f"Or set OLLAMA_MODEL to one of: {available}",
                ]
            else:
                result["suggestions"] = [
                    "Check Ollama logs: journalctl -u ollama",
                ]

        except requests.exceptions.ConnectionError:
            result["error"] = "Connection refused"
            result["suggestions"] = [
                "Run: ollama serve",
                f"Check OLLAMA_URL is correct (currently: {url})",
                "Check firewall / network",
            ]
        except requests.exceptions.Timeout:
            result["error"] = "Connection timed out"
            result["suggestions"] = [
                "Run: ollama serve",
                f"Check OLLAMA_URL is correct (currently: {url})",
                "Check firewall / network",
            ]

        return result

    def summarize_transcript_sections(
        self,
        transcript_text: str,
        snapshots: Optional[List[Dict]] = None,
        language: str = "en",
        title: str = "",
        video_url: str = "",
        source_type: str = "",
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Summarize transcript using a two-pass context-aware pipeline.

        Pass 1: Analyze the full transcript to identify sections and
        classify content types.
        Pass 2: Summarize each section with an adaptive, content-type-specific
        prompt and awareness of the overall document structure.

        Falls back to the original single-pass pipeline if either pass fails.

        Args:
            transcript_text: Full transcript text with chapter headers
            snapshots: List of snapshot dicts with 'timestamp' and 'image_url'
            language: ISO 639-1 language code (e.g. "en", "fr")
            cancel_check: Optional callback returning True if cancelled

        Returns:
            Summary markdown with section headers, LLM summaries, and
            snapshot images placed after each section

        Raises:
            DocumentGenerationException: If Ollama is not reachable
            CancelledException: If cancel_check returns True
        """
        self._check_ollama()

        def _check_cancel():
            if cancel_check and cancel_check():
                raise CancelledException("Summarization cancelled by user")

        try:
            # --- Two-pass pipeline ---
            # Pass 1: Analyze transcript structure
            _check_cancel()
            analyses = self._analyze_transcript(transcript_text, language)

            # Build global context string
            global_context = "This is part of a video covering: " + "; ".join(
                f"{a.title} ({a.content_type.value})" for a in analyses
            )

            # Extract sections (slice text + assign snapshots)
            sections = self._extract_sections_from_analysis(
                transcript_text, analyses, snapshots or []
            )

            # Pass 2: Summarize each section with adaptive prompts
            summaries: List[str] = []
            for section in sections:
                _check_cancel()
                if not section.text.strip():
                    summaries.append("")
                    continue
                summary = self._summarize_section_adaptive(section, global_context, language)
                summaries.append(summary)

            # Assemble final output
            return self._assemble_output(sections, summaries, title=title, video_url=video_url, source_type=source_type)

        except CancelledException:
            raise

        except Exception as e:
            logger.warning(
                f"Two-pass pipeline failed, falling back to single-pass: {e}"
            )

        # --- Fallback: original single-pass pipeline ---
        full_lines = self._inject_snapshot_refs(transcript_text, snapshots or [])
        split_sections = self._split_into_sections(full_lines)

        result_parts: List[str] = []
        for section in split_sections:
            _check_cancel()
            if section["type"] == "marker":
                result_parts.append(section["content"])
            elif section["type"] == "text":
                text = section["content"].strip()
                if not text:
                    continue
                summary = self._summarize_section(text, language)
                result_parts.append(summary)

        result = "\n\n".join(result_parts)
        result = self._prepend_title_header(result, title, video_url, source_type)
        return result

    def export_format(self, content: str, format_type: str = "markdown") -> str:
        """
        Export content in specified format.

        Args:
            content: Generated content
            format_type: Output format (markdown, html, pdf_markdown)

        Returns:
            Formatted content
        """
        if format_type == "html":
            return self._markdown_to_html(content)
        elif format_type == "pdf_markdown":
            return content  # PDF generation handled elsewhere
        else:
            return content

    def save_document(
        self,
        db: Session,
        job_id: int,
        title: str,
        content: str,
        format_type: str = "markdown",
        file_path: Optional[str] = None,
    ) -> Document:
        """
        Save generated document to database.

        Args:
            db: Database session
            job_id: Processing job ID
            title: Document title
            content: Document content
            format_type: Document format
            file_path: Path to saved file

        Returns:
            Document object

        Raises:
            DocumentGenerationException: If save fails
        """
        try:
            document = Document(
                job_id=job_id,
                title=title,
                content=content,
                format=format_type,
                file_path=file_path,
                file_size=len(content),
            )

            db.add(document)
            db.commit()
            db.refresh(document)

            logger.info(f"✓ Saved document '{title}' for job {job_id}")
            return document

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save document: {e}")
            raise DocumentGenerationException(f"Failed to save document: {str(e)}")

    # ===========================================================================
    # HELPER METHODS
    # ===========================================================================

    def _create_prompt(
        self,
        transcript: str,
        snapshots: Optional[List[Dict]],
        title: str,
        format_type: str,
    ) -> str:
        """Create LLM prompt for documentation generation."""
        format_instructions = (
            "Format as Markdown with proper headers, lists, and code blocks."
            if format_type == "markdown"
            else "Format as HTML with proper tags."
        )

        snapshots_info = ""
        if snapshots:
            snapshots_info = f"\n\nThe video also includes {len(snapshots)} visual snapshots at key moments."

        return f"""Generate comprehensive documentation from the following video transcript.

Title: {title}

{format_instructions}

Include:
- Clear section structure with headers
- Key concepts and learning points
- Code examples where applicable
- Practical use cases
- Summary at the end{snapshots_info}

Transcript:
{transcript[:3000]}

Documentation:"""

    def _inject_snapshot_refs(
        self, transcript_text: str, snapshots: List[Dict]
    ) -> List[str]:
        """Inject snapshot image refs into transcript lines at correct positions."""
        lines = transcript_text.split("\n")
        if not snapshots:
            return lines

        sorted_snaps = sorted(snapshots, key=lambda s: s["timestamp"])

        # Extract timestamp (in seconds) from each line
        line_timestamps: List[Optional[float]] = []
        for line in lines:
            ts_match = re.match(r"^(?:## )?\[(\d{2}):(\d{2}):(\d{2})\]", line)
            if ts_match:
                seconds = (
                    int(ts_match[1]) * 3600
                    + int(ts_match[2]) * 60
                    + int(ts_match[3])
                )
                line_timestamps.append(seconds)
            else:
                line_timestamps.append(None)

        # Map each snapshot to the line with the closest earlier-or-equal timestamp
        snap_map: Dict[int, List[Dict]] = {}
        for snap in sorted_snaps:
            best_idx = -1
            best_ts = -1.0
            for i, ts in enumerate(line_timestamps):
                if ts is not None and ts <= snap["timestamp"] and ts > best_ts:
                    best_ts = ts
                    best_idx = i
            if best_idx >= 0:
                snap_map.setdefault(best_idx, []).append(snap)

        # Rebuild lines with image refs inserted after their mapped lines
        result: List[str] = []
        for i, line in enumerate(lines):
            result.append(line)
            if i in snap_map:
                for snap in snap_map[i]:
                    ts = snap["timestamp"]
                    h = int(ts // 3600)
                    m = int((ts % 3600) // 60)
                    s = int(ts % 60)
                    image_url = snap.get("image_url", "")
                    result.append(
                        f"![Snapshot at {h:02d}:{m:02d}:{s:02d}]({image_url})"
                    )
        return result

    @staticmethod
    def _ends_sentence(text: str) -> bool:
        """Return True if *text* looks like it ends a complete sentence.

        Avoids false positives on abbreviations, ellipsis, decimal/version
        numbers, and file extensions so that sentence-spanning image
        boundaries don't split mid-thought.
        """
        text = text.rstrip()
        if not text:
            return False

        last = text[-1]
        if last not in ".!?":
            return False
        if last in "!?":
            return True

        # Ellipsis — three or more dots
        if text.endswith("..."):
            return False

        token = text.split()[-1]
        lower_token = token.lower()

        # Common abbreviations
        if lower_token in _ABBREVIATIONS:
            return False

        # Single uppercase letter + dot  (e.g. "U.", "A.")
        if len(token) == 2 and token[0].isupper() and token[1] == ".":
            return False

        stem = token.rstrip(".")

        # Bare punctuation (e.g. just ".")
        if not stem:
            return False

        # Numeric / currency values  (e.g. "3.", "$5.")
        if stem.lstrip("-$€£¥").replace(",", "").isdigit():
            return False

        # Decimal / version numbers  (e.g. "3.12.", "2.99.")
        parts = stem.split(".")
        if len(parts) >= 2 and all(p.isdigit() for p in parts if p):
            return False

        # Filename-like tokens  (e.g. "config.py.", "index.html.")
        if "." in stem and len(parts) >= 2 and all(p.isalnum() for p in parts if p):
            return False

        return True

    def _split_into_sections(self, lines: List[str]) -> List[Dict]:
        """Split lines into sections based on structural markers.

        Chapter headers (## [HH:MM:SS]) are hard boundaries that always split sections.
        Image refs (![Snapshot ...]) are deferred: text continues accumulating across
        an image so that a sentence spanning an image is kept whole and placed before
        the image in the output.
        """
        chapter_re = re.compile(r"^## \[\d{2}:\d{2}:\d{2}\]")
        image_re = re.compile(r"^!\[Snapshot at \d{2}:\d{2}:\d{2}\]")
        ts_text_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*(.*)")

        sections: List[Dict] = []
        current_text_lines: List[str] = []
        pending_images: List[str] = []
        lines_since_image = 0

        def flush_text():
            nonlocal current_text_lines
            text = "\n".join(current_text_lines).strip()
            if text:
                sections.append({"type": "text", "content": text})
            current_text_lines = []

        def flush_images():
            nonlocal pending_images, lines_since_image
            for img in pending_images:
                sections.append({"type": "marker", "content": img})
            pending_images = []
            lines_since_image = 0

        for line in lines:
            if chapter_re.match(line):
                # Chapter is a hard boundary — flush everything
                flush_text()
                flush_images()
                sections.append({"type": "marker", "content": line})
            elif image_re.match(line):
                # Defer image — don't split text yet
                pending_images.append(line)
                lines_since_image = 0
            else:
                current_text_lines.append(line)
                if pending_images:
                    lines_since_image += 1
                    # Check if this line ends a sentence
                    m = ts_text_re.match(line)
                    text_part = (m.group(1) if m else line).rstrip()
                    ends_sentence = bool(text_part) and self._ends_sentence(text_part)
                    if ends_sentence or lines_since_image >= 3:
                        flush_text()
                        flush_images()

        # Flush remaining
        flush_text()
        flush_images()

        return sections

    def _summarize_section(self, text: str, language: str = "en") -> str:
        """Call Ollama to summarize a single transcript section."""
        lang_instruction = ""
        if language != "en":
            name = _language_name(language)
            lang_instruction = f"\nIMPORTANT: Write your entire response in {name}.\n"

        prompt = (
            "You are a technical writer. Rewrite the following into 1-2 concise paragraphs "
            "followed by 3-5 bullet points. Write as if you are explaining the topic directly "
            "to a reader. Use factual statements like 'Google announced...' or "
            "'Revenue exceeded...'. Never reference a speaker, transcript, video, "
            "content, or section. Just state the facts.\n"
            f"{lang_instruction}\n"
            f"{text}\n\nRewrite:"
        )
        try:
            summary = self._provider.generate(
                prompt=prompt,
                model=self._model,
                timeout=self.settings.service_timeouts.llm_timeout,
            ).strip()
            return summary if summary else text

        except requests.exceptions.Timeout:
            logger.warning("Section summarization timed out")
            return text
        except Exception as e:
            logger.warning(f"Section summarization failed: {e}")
            return text

    # ===========================================================================
    # TWO-PASS PIPELINE METHODS
    # ===========================================================================

    def _build_analysis_prompt(
        self, transcript_text: str, has_chapters: bool, language: str = "en"
    ) -> str:
        """Build the Pass 1 prompt for transcript analysis.

        Args:
            transcript_text: Full transcript text
            has_chapters: Whether the transcript contains chapter markers
            language: ISO 639-1 language code

        Returns:
            Prompt string for the LLM
        """
        # Truncate if needed, but preserve chapter header lines
        if len(transcript_text) > _MAX_ANALYSIS_CHARS:
            kept = transcript_text[:_MAX_ANALYSIS_CHARS]
            remainder = transcript_text[_MAX_ANALYSIS_CHARS:]
            chapter_lines = [
                line for line in remainder.split("\n")
                if re.match(r"^## \[\d{2}:\d{2}:\d{2}\]", line)
            ]
            if chapter_lines:
                kept += "\n...\n" + "\n".join(chapter_lines)
            transcript_text = kept

        if has_chapters:
            task = (
                "The transcript below contains chapter markers formatted as "
                "'## [HH:MM:SS] Chapter Title'. For each chapter, classify its "
                "content type and identify 2-4 key topics. Preserve the exact "
                "chapter titles and timestamps."
            )
        else:
            task = (
                "The transcript below has no chapter markers. Identify 3-8 logical "
                "topic sections. For each section, create a descriptive title, "
                "assign approximate start/end timestamps from the transcript lines, "
                "classify its content type, and list 2-4 key topics."
            )

        lang_instruction = ""
        if language != "en":
            name = _language_name(language)
            lang_instruction = (
                f"\nThe transcript is in {name}. Keep section titles in {name}.\n"
            )

        return (
            f"{task}\n\n"
            "Content types: intro, conceptual, code_walkthrough, demo_tutorial, "
            "conclusion, general\n\n"
            "Respond ONLY with a JSON array. Each element must have:\n"
            '- "title": string\n'
            '- "start_timestamp": "HH:MM:SS"\n'
            '- "end_timestamp": "HH:MM:SS" or "END"\n'
            '- "content_type": one of the types above\n'
            '- "key_topics": array of strings\n'
            f"{lang_instruction}\n"
            f"Transcript:\n{transcript_text}"
        )

    def _parse_analysis_response(self, raw: str) -> list[SectionAnalysis]:
        """Parse LLM JSON output from Pass 1 into SectionAnalysis objects.

        Args:
            raw: Raw LLM response string

        Returns:
            List of SectionAnalysis objects

        Raises:
            ValueError: If JSON is invalid or result is empty
        """
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Pass 1 returned invalid JSON: {e}")

        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("Pass 1 returned empty or non-array JSON")

        valid_types = {ct.value for ct in ContentType}
        analyses: list[SectionAnalysis] = []
        for item in data:
            ct_str = item.get("content_type", "general")
            if ct_str not in valid_types:
                ct_str = "general"

            analyses.append(SectionAnalysis(
                title=item.get("title", "Untitled"),
                start_timestamp=item.get("start_timestamp", "00:00:00"),
                end_timestamp=item.get("end_timestamp", "END"),
                content_type=ContentType(ct_str),
                key_topics=item.get("key_topics", []),
            ))

        return analyses

    def _analyze_transcript(
        self, transcript_text: str, language: str = "en"
    ) -> list[SectionAnalysis]:
        """Pass 1: Analyze full transcript structure and classify sections.

        Args:
            transcript_text: Full transcript text
            language: ISO 639-1 language code

        Returns:
            List of SectionAnalysis objects

        Raises:
            ValueError: If analysis fails or returns invalid data
        """
        has_chapters = bool(
            re.search(r"^## \[\d{2}:\d{2}:\d{2}\]", transcript_text, re.MULTILINE)
        )
        prompt = self._build_analysis_prompt(transcript_text, has_chapters, language)

        try:
            raw = self._provider.generate(
                prompt=prompt,
                model=self._model,
                timeout=self.settings.service_timeouts.llm_timeout,
            ).strip()
        except Exception as e:
            raise ValueError(f"Pass 1 LLM error: {str(e)}")

        if not raw:
            raise ValueError("Pass 1 returned empty response")

        return self._parse_analysis_response(raw)

    def _get_section_prompt(self, content_type: ContentType) -> str:
        """Look up the adaptive prompt template for a content type.

        Args:
            content_type: The section's content type

        Returns:
            Prompt instruction string
        """
        return _CONTENT_TYPE_PROMPTS.get(
            content_type, _CONTENT_TYPE_PROMPTS[ContentType.GENERAL]
        )

    @staticmethod
    def _ts_to_seconds(ts: str) -> Optional[float]:
        """Convert 'HH:MM:SS' to seconds, or None if invalid."""
        m = re.match(r"(\d{2}):(\d{2}):(\d{2})", ts)
        if not m:
            return None
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])

    def _extract_sections_from_analysis(
        self,
        transcript_text: str,
        analyses: list[SectionAnalysis],
        snapshots: list[dict],
    ) -> list[TranscriptSection]:
        """Slice transcript by timestamp ranges and assign snapshots.

        Args:
            transcript_text: Full transcript text
            analyses: Section analyses from Pass 1
            snapshots: Snapshot dicts with 'timestamp' and 'image_url'

        Returns:
            List of TranscriptSection with text and snapshots assigned
        """
        lines = transcript_text.split("\n")
        ts_re = re.compile(r"^(?:## )?\[(\d{2}):(\d{2}):(\d{2})\]")

        # Build list of (seconds, line_index) for timestamp lines
        line_ts: list[tuple[float, int]] = []
        for i, line in enumerate(lines):
            m = ts_re.match(line)
            if m:
                secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
                line_ts.append((secs, i))

        sections: list[TranscriptSection] = []
        sorted_snaps = sorted(snapshots, key=lambda s: s["timestamp"])

        for idx, analysis in enumerate(analyses):
            start_secs = self._ts_to_seconds(analysis.start_timestamp)
            if analysis.end_timestamp == "END":
                end_secs = None
            else:
                end_secs = self._ts_to_seconds(analysis.end_timestamp)

            # Find line range
            start_line = 0
            end_line = len(lines)

            if start_secs is not None:
                for secs, li in line_ts:
                    if secs >= start_secs:
                        start_line = li
                        break

            if end_secs is not None:
                for secs, li in line_ts:
                    if secs >= end_secs:
                        end_line = li
                        break

            # Extract text, stripping chapter header lines
            section_lines = []
            for line in lines[start_line:end_line]:
                # Skip chapter headers — they become ## Title in output
                if re.match(r"^## \[\d{2}:\d{2}:\d{2}\]", line):
                    continue
                # Skip snapshot image refs — handled separately
                if re.match(r"^!\[Snapshot at", line):
                    continue
                section_lines.append(line)
            text = "\n".join(section_lines).strip()

            # Assign snapshots within this section's time range
            sec_snaps = []
            for snap in sorted_snaps:
                snap_ts = snap["timestamp"]
                if start_secs is not None and snap_ts < start_secs:
                    continue
                if end_secs is not None and snap_ts >= end_secs:
                    continue
                sec_snaps.append(snap)

            sections.append(TranscriptSection(
                analysis=analysis,
                text=text,
                snapshots=sec_snaps,
            ))

        return sections

    def _summarize_section_adaptive(
        self, section: TranscriptSection, global_context: str, language: str = "en"
    ) -> str:
        """Pass 2: Summarize a section with content-type-specific prompt.

        Args:
            section: TranscriptSection with analysis, text, and snapshots
            global_context: Overview string of all sections
            language: ISO 639-1 language code

        Returns:
            Summary markdown text
        """
        instruction = self._get_section_prompt(section.analysis.content_type)
        topics = ", ".join(section.analysis.key_topics) if section.analysis.key_topics else "general topics"

        lang_instruction = ""
        if language != "en":
            name = _language_name(language)
            lang_instruction = f"\nIMPORTANT: Write your entire response in {name}.\n"

        prompt = (
            f"You are a technical writer. {instruction}\n\n"
            f"Section: {section.analysis.title}\n"
            f"Key topics: {topics}\n"
            f"Context: {global_context}\n\n"
            "Write as if explaining directly to a reader. Never reference a speaker, "
            "transcript, video, or section. Just state the facts.\n"
            f"{lang_instruction}\n"
            f"{section.text}\n\nRewrite:"
        )

        try:
            summary = self._provider.generate(
                prompt=prompt,
                model=self._model,
                timeout=self.settings.service_timeouts.llm_timeout,
            ).strip()
            return summary if summary else section.text

        except TimeoutError:
            logger.warning("Pass 2 section summarization timed out")
            return section.text
        except Exception as e:
            logger.warning(f"Pass 2 section summarization failed: {e}")
            return section.text

    @staticmethod
    def _prepend_title_header(content: str, title: str = "", video_url: str = "", source_type: str = "") -> str:
        """Prepend video title and source URL as a markdown header."""
        if not title:
            return content
        header = f"# {title}"
        if video_url:
            source_label = f" ({source_type})" if source_type else ""
            header += f"\n\nSource: {video_url}{source_label}"
        header += "\n\n---"
        if content:
            return header + "\n\n" + content
        return header

    @staticmethod
    def _assemble_output(
        sections: list[TranscriptSection],
        summaries: list[str],
        title: str = "",
        video_url: str = "",
        source_type: str = "",
    ) -> str:
        """Combine section headers, summaries, and snapshot images."""
        parts: list[str] = []
        header = LLMService._prepend_title_header("", title, video_url, source_type)
        if header:
            parts.append(header)
        for section, summary in zip(sections, summaries):
            # Section header
            part = f"## {section.analysis.title}\n\n{summary}"

            # Append snapshot images
            if section.snapshots:
                images = []
                for snap in section.snapshots:
                    ts = snap["timestamp"]
                    h = int(ts // 3600)
                    m = int((ts % 3600) // 60)
                    s = int(ts % 60)
                    url = snap.get("image_url", "")
                    images.append(f"![Snapshot at {h:02d}:{m:02d}:{s:02d}]({url})")
                part += "\n\n" + "\n".join(images)

            parts.append(part)

        return "\n\n".join(parts)

    def _detect_sections_heuristic(self, text: str) -> List[Dict]:
        """Simple heuristic for section detection."""
        sections = []
        paragraphs = text.split("\n\n")

        for i, para in enumerate(paragraphs[:5]):  # Limit to first 5 sections
            if len(para) > 50:
                # Use first sentence as title
                title = para.split(".")[0][:100]
                sections.append({
                    "title": title,
                    "content": para,
                })

        return sections

    def _markdown_to_html(self, markdown: str) -> str:
        """Simple markdown to HTML conversion."""
        html = markdown

        # Headers
        html = re.sub(r"^### (.*?)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.*?)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.*?)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

        # Bold and italic
        html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.*?)\*", r"<em>\1</em>", html)

        # Code blocks
        html = re.sub(
            r"```(.*?)```",
            r"<pre><code>\1</code></pre>",
            html,
            flags=re.DOTALL,
        )

        # Inline code
        html = re.sub(r"`(.*?)`", r"<code>\1</code>", html)

        # Line breaks
        html = html.replace("\n\n", "</p><p>")
        html = f"<p>{html}</p>"

        return html
