"""Unit tests for TranscriptService: segmentation, language detection, confidence."""

from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.db.models import ProcessingJob, ProcessingStatus, Transcript
from app.services.transcript import TranscriptService
from app.exceptions import ValidationException, TranscriptException


# ===========================================================================
# Segment Transcript
# ===========================================================================

class TestSegmentTranscript:
    def _svc(self):
        with patch("app.services.transcript.YouTubeService"):
            return TranscriptService()

    def test_single_segment(self):
        svc = self._svc()
        segments = svc.segment_transcript("Hello world. This is a test.")
        assert len(segments) >= 1
        assert segments[0]["sequence"] == 0

    def test_splits_at_max_length(self):
        svc = self._svc()
        long_text = ". ".join(["This is a long sentence that fills up space"] * 50)
        segments = svc.segment_transcript(long_text, max_segment_length=200)
        assert len(segments) > 1

    def test_empty_text_raises(self):
        svc = self._svc()
        with pytest.raises(ValidationException):
            svc.segment_transcript("")

    def test_sequence_numbers_consecutive(self):
        svc = self._svc()
        text = ". ".join(["Sentence number " + str(i) for i in range(20)])
        segments = svc.segment_transcript(text, max_segment_length=100)
        seqs = [s["sequence"] for s in segments]
        assert seqs == list(range(len(seqs)))

    def test_timestamps_default_zero(self):
        svc = self._svc()
        segments = svc.segment_transcript("Hello world. This is a test.")
        for seg in segments:
            assert seg["start_time"] == 0.0
            assert seg["end_time"] == 0.0

    def test_whitespace_only_raises(self):
        svc = self._svc()
        with pytest.raises(ValidationException):
            svc.segment_transcript("   \n\t  ")


# ===========================================================================
# Detect Language
# ===========================================================================

class TestDetectLanguage:
    def test_english_detection(self):
        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        lang = svc._detect_language("This is a sample English text for language detection.")
        assert lang == "en"

    @patch("app.services.transcript.detect_language", side_effect=Exception("fail"))
    def test_failure_defaults_to_en(self, mock_detect):
        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        lang = svc._detect_language("Some text")
        assert lang == "en"


# ===========================================================================
# Estimate Confidence
# ===========================================================================

class TestEstimateConfidence:
    def _svc(self):
        with patch("app.services.transcript.YouTubeService"):
            return TranscriptService()

    def test_long_text_above_base(self):
        svc = self._svc()
        long_text = "This is a proper sentence. " * 500
        score = svc._estimate_confidence(long_text)
        assert score > 0.85

    def test_short_text_below_base(self):
        svc = self._svc()
        score = svc._estimate_confidence("Short.")
        assert score < 0.85

    def test_capped_at_one(self):
        svc = self._svc()
        # Very well-structured text should not exceed 1.0
        text = "This is excellent. " * 1000
        score = svc._estimate_confidence(text)
        assert score <= 1.0


# ===========================================================================
# Transcribe Audio (mocked Ollama)
# ===========================================================================

class TestTranscribeAudio:
    @patch("app.services.transcript.requests.post")
    def test_success(self, mock_post, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake audio content")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "Transcribed text here."}
        mock_post.return_value = mock_resp

        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        with patch.object(svc, "_get_audio_duration", return_value=60):
            result = svc.transcribe_audio(str(audio_file))

        assert result["full_text"] == "Transcribed text here."
        assert "language" in result

    @patch("app.services.transcript.requests.post")
    def test_ollama_error(self, mock_post, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake audio")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal error"
        mock_post.return_value = mock_resp

        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        with pytest.raises(TranscriptException, match="Ollama API error"):
            svc.transcribe_audio(str(audio_file))

    def test_missing_file(self):
        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        with pytest.raises(TranscriptException, match="not found"):
            svc.transcribe_audio("/nonexistent/audio.mp3")


# ===========================================================================
# Save Transcript
# ===========================================================================

class TestSaveTranscript:
    def test_saves_to_db(self, test_db: Session):
        job = ProcessingJob(
            job_id="save-test-1",
            status=ProcessingStatus.PENDING,
            youtube_url="https://www.youtube.com/watch?v=test12345ab",
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        transcript, segments = svc.save_transcript(
            test_db, job.id, "Hello world. This is a test.", language="en",
        )
        assert transcript.id is not None
        assert transcript.full_text == "Hello world. This is a test."

    def test_segment_count_matches(self, test_db: Session):
        job = ProcessingJob(
            job_id="save-test-2",
            status=ProcessingStatus.PENDING,
            youtube_url="https://www.youtube.com/watch?v=test12345ac",
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        with patch("app.services.transcript.YouTubeService"):
            svc = TranscriptService()
        transcript, segments = svc.save_transcript(
            test_db, job.id, "One sentence. Two sentence.", language="en",
        )
        assert len(segments) >= 1
