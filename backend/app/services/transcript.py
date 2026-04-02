"""
Transcript Service

Handles audio transcription via Ollama, caption extraction, transcript
segmentation with timestamps, and language detection.
"""

import logging
import re
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from datetime import datetime

import requests
from sqlalchemy.orm import Session
from langdetect import detect as detect_language
import nltk
from nltk.tokenize import sent_tokenize

from app.core.config import get_settings
from app.db.models import Transcript, TranscriptSegment
from app.services.youtube import YouTubeService
from app.exceptions import TranscriptException, ValidationException

logger = logging.getLogger(__name__)

# Download required NLTK data (run once)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')


class TranscriptService:
    """Service for audio transcription and transcript processing."""

    def __init__(self):
        """Initialize transcript service."""
        self.settings = get_settings()
        self.youtube_service = YouTubeService()

    def transcribe_audio(
        self,
        audio_path: str,
        language: str = "en",
    ) -> Dict:
        """
        Transcribe audio using Ollama's Whisper model.

        Sends audio file to Ollama Whisper API and returns full transcript
        with metadata.

        Args:
            audio_path: Path to audio file (MP3, WAV, etc.)
            language: Language code (e.g., 'en', 'es')

        Returns:
            Dictionary with:
            - full_text: Complete transcript text
            - language: Detected language
            - duration: Audio duration in seconds
            - confidence_score: Overall confidence (0.0-1.0)

        Raises:
            TranscriptException: If transcription fails
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise TranscriptException(f"Audio file not found: {audio_path}")

        try:
            # Check file size (limit to 50MB for Ollama)
            file_size = audio_path.stat().st_size
            if file_size > 50 * 1024 * 1024:
                raise TranscriptException(
                    f"Audio file too large: {file_size / 1024 / 1024:.1f}MB (max: 50MB)"
                )

            logger.info(f"Transcribing audio: {audio_path}")

            # Call Ollama Whisper API
            with open(audio_path, "rb") as f:
                files = {"audio": f}
                data = {"language": language}

                response = requests.post(
                    f"{self.settings.ollama.base_url}/api/transcribe",
                    files=files,
                    data=data,
                    timeout=self.settings.service_timeouts.whisper_timeout,
                )

            if response.status_code != 200:
                raise TranscriptException(
                    f"Ollama API error: {response.status_code} - {response.text}"
                )

            result = response.json()
            full_text = result.get("text", "").strip()

            if not full_text:
                raise TranscriptException("Ollama returned empty transcript")

            # Detect actual language
            detected_language = self._detect_language(full_text)

            # Get audio duration
            duration = self._get_audio_duration(str(audio_path))

            # Estimate confidence (Ollama doesn't return per-word confidence)
            confidence = self._estimate_confidence(full_text)

            logger.info(f"✓ Transcribed {duration}s of audio ({len(full_text)} chars)")

            return {
                "full_text": full_text,
                "language": detected_language,
                "duration": duration,
                "confidence_score": confidence,
                "source": "whisper_local",
            }

        except requests.exceptions.Timeout:
            raise TranscriptException("Transcription timed out (audio too long or Ollama overloaded)")
        except requests.exceptions.ConnectionError as e:
            raise TranscriptException(
                f"Failed to connect to Ollama: {self.settings.ollama.base_url}"
            )
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptException(f"Transcription failed: {str(e)}")

    def get_youtube_captions(self, video_id: str) -> Optional[Dict]:
        """
        Get transcript from YouTube captions (fallback).

        Args:
            video_id: YouTube video ID

        Returns:
            Dictionary with caption transcript or None if unavailable

        Raises:
            TranscriptException: If caption extraction fails
        """
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            captions = self.youtube_service.get_captions(url)

            if not captions:
                return None

            detected_language = self._detect_language(captions)

            return {
                "full_text": captions,
                "language": detected_language,
                "duration": None,
                "confidence_score": 0.85,  # YouTube captions are fairly reliable
                "source": "youtube_captions",
            }

        except Exception as e:
            logger.warning(f"Failed to get YouTube captions: {e}")
            return None

    def segment_transcript(
        self,
        full_text: str,
        max_segment_length: int = 500,
    ) -> List[Dict]:
        """
        Segment transcript into sentence-based segments with timestamp extraction.

        Parses [HH:MM:SS] timestamps from YouTube caption format and assigns
        proper start_time/end_time to each segment.

        Args:
            full_text: Complete transcript text
            max_segment_length: Max characters per segment (default: 500)

        Returns:
            List of segments, each with:
            - text: Segment text
            - start_time: Start time in seconds
            - end_time: End time in seconds
            - sequence: Order in transcript

        Raises:
            ValidationException: If text is empty
        """
        if not full_text or not full_text.strip():
            raise ValidationException("Cannot segment empty transcript")

        try:
            import re

            # Parse timestamped lines: [HH:MM:SS] text
            ts_pattern = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)")
            lines = full_text.split("\n")

            # Build list of (timestamp_seconds, text) tuples
            timed_entries: List[tuple] = []
            last_ts = 0.0
            has_timestamps = False

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                match = ts_pattern.match(line)
                if match:
                    h, m, s, text = int(match[1]), int(match[2]), int(match[3]), match[4].strip()
                    ts = h * 3600 + m * 60 + s
                    last_ts = ts
                    has_timestamps = True
                    if text:
                        timed_entries.append((float(ts), text))
                elif line.startswith("#") or line.startswith("Source:") or line.startswith("Language:"):
                    # Skip header lines (title, source URL, etc.)
                    continue
                elif line.startswith("## ["):
                    # Chapter headers — skip
                    continue
                else:
                    # Non-timestamped text, attach to last known timestamp
                    timed_entries.append((last_ts, line))

            # If no timestamps found, fall back to sentence-based segmentation
            if not has_timestamps:
                return self._segment_without_timestamps(full_text, max_segment_length)

            # Group timed entries into segments respecting max_segment_length
            segments = []
            current_texts: List[str] = []
            current_start = timed_entries[0][0]
            current_end = timed_entries[0][0]
            current_length = 0
            sequence = 0

            for ts, text in timed_entries:
                test_length = current_length + len(text) + 1  # +1 for space

                if test_length > max_segment_length and current_texts:
                    # Save current segment
                    segments.append({
                        "text": " ".join(current_texts),
                        "start_time": current_start,
                        "end_time": current_end,
                        "speaker": None,
                        "confidence_score": 0.95,
                        "sequence": sequence,
                    })
                    sequence += 1
                    current_texts = [text]
                    current_start = ts
                    current_end = ts
                    current_length = len(text)
                else:
                    current_texts.append(text)
                    current_end = ts
                    current_length = test_length

            # Add final segment
            if current_texts:
                segments.append({
                    "text": " ".join(current_texts),
                    "start_time": current_start,
                    "end_time": current_end,
                    "speaker": None,
                    "confidence_score": 0.95,
                    "sequence": sequence,
                })

            logger.info(f"Segmented transcript into {len(segments)} segments")
            return segments

        except Exception as e:
            logger.error(f"Segmentation failed: {e}")
            raise TranscriptException(f"Failed to segment transcript: {str(e)}")

    def _segment_without_timestamps(
        self,
        full_text: str,
        max_segment_length: int = 500,
    ) -> List[Dict]:
        """Fallback segmentation for text without [HH:MM:SS] timestamps."""
        sentences = sent_tokenize(full_text)
        segments = []
        current_segment = ""
        sequence = 0

        for sentence in sentences:
            test_text = current_segment + " " + sentence if current_segment else sentence
            test_text = test_text.strip()

            if len(test_text) > max_segment_length and current_segment:
                segments.append({
                    "text": current_segment.strip(),
                    "start_time": 0.0,
                    "end_time": 0.0,
                    "speaker": None,
                    "confidence_score": 0.95,
                    "sequence": sequence,
                })
                sequence += 1
                current_segment = sentence
            else:
                current_segment = test_text

        if current_segment.strip():
            segments.append({
                "text": current_segment.strip(),
                "start_time": 0.0,
                "end_time": 0.0,
                "speaker": None,
                "confidence_score": 0.95,
                "sequence": sequence,
            })

        logger.info(f"Segmented transcript into {len(segments)} segments (no timestamps)")
        return segments

    def save_transcript(
        self,
        db: Session,
        job_id: int,
        full_text: str,
        language: str = "en",
        source: str = "whisper_local",
        duration: Optional[int] = None,
        confidence_score: Optional[float] = None,
    ) -> Tuple[Transcript, List[TranscriptSegment]]:
        """
        Save transcript and segments to database.

        Args:
            db: Database session
            job_id: Processing job ID
            full_text: Complete transcript text
            language: Language code
            source: Transcript source (whisper_local, youtube_captions, etc.)
            duration: Audio duration in seconds
            confidence_score: Overall confidence score

        Returns:
            Tuple of (Transcript object, List of TranscriptSegment objects)

        Raises:
            TranscriptException: If database operation fails
        """
        try:
            # Create transcript record
            transcript = Transcript(
                job_id=job_id,
                full_text=full_text,
                language=language,
                source=source,
                confidence_score=confidence_score or 0.9,
                duration=duration,
            )

            db.add(transcript)
            db.flush()  # Get transcript ID without committing

            # Create segment records
            segments = self.segment_transcript(full_text)
            segment_objects = []

            for segment_data in segments:
                segment = TranscriptSegment(
                    transcript_id=transcript.id,
                    text=segment_data["text"],
                    start_time=segment_data["start_time"],
                    end_time=segment_data["end_time"],
                    speaker=segment_data["speaker"],
                    confidence_score=segment_data["confidence_score"],
                    sequence=segment_data["sequence"],
                )
                segment_objects.append(segment)
                db.add(segment)

            db.commit()
            db.refresh(transcript)

            logger.info(
                f"✓ Saved transcript with {len(segment_objects)} segments for job {job_id}"
            )
            return transcript, segment_objects

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save transcript: {e}")
            raise TranscriptException(f"Failed to save transcript: {str(e)}")

    # ===========================================================================
    # HELPER METHODS
    # ===========================================================================

    def _detect_language(self, text: str) -> str:
        """
        Detect language of text.

        Args:
            text: Text to analyze

        Returns:
            Language code (e.g., 'en', 'es')
        """
        try:
            # Use first 500 characters for faster detection
            lang = detect_language(text[:500])
            logger.debug(f"Detected language: {lang}")
            return lang
        except Exception as e:
            logger.warning(f"Language detection failed: {e}, defaulting to 'en'")
            return "en"

    def _get_audio_duration(self, audio_path: str) -> int:
        """
        Get duration of audio file in seconds.

        Args:
            audio_path: Path to audio file

        Returns:
            Duration in seconds

        Raises:
            TranscriptException: If duration cannot be determined
        """
        try:
            import subprocess
            import json

            # Use ffprobe to get duration
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    audio_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.warning(f"ffprobe failed: {result.stderr}")
                return 0

            data = json.loads(result.stdout)
            duration = int(float(data["format"]["duration"]))
            logger.debug(f"Audio duration: {duration}s")
            return duration

        except Exception as e:
            logger.warning(f"Failed to get audio duration: {e}")
            return 0

    def _estimate_confidence(self, text: str) -> float:
        """
        Estimate confidence score for transcript.

        Based on text characteristics (length, proper sentences, etc.).

        Args:
            text: Transcript text

        Returns:
            Confidence score (0.0-1.0)
        """
        try:
            score = 0.85  # Base score

            # Add points for length (longer transcripts tend to be more complete)
            if len(text) > 10000:
                score += 0.05
            elif len(text) < 100:
                score -= 0.1

            # Add points for sentence structure
            sentences = sent_tokenize(text)
            if len(sentences) > 5:
                score += 0.03

            # Check for proper capitalization
            capitalized = sum(1 for s in sentences if s[0].isupper()) / max(len(sentences), 1)
            if capitalized > 0.8:
                score += 0.05

            # Check for punctuation (good transcripts have proper punctuation)
            punctuation_chars = sum(1 for c in text if c in ".!?")
            punctuation_ratio = punctuation_chars / max(len(text), 1)
            if 0.01 < punctuation_ratio < 0.1:
                score += 0.02

            return min(score, 1.0)  # Cap at 1.0

        except Exception as e:
            logger.warning(f"Confidence estimation failed: {e}")
            return 0.9
