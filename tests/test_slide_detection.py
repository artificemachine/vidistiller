"""Tests for the slide detection service."""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from app.services.slide_detection import SlideDetectionService


@pytest.fixture()
def service():
    """Create a SlideDetectionService with default settings."""
    with patch("app.services.slide_detection.get_settings") as mock_settings:
        settings = MagicMock()
        settings.slide_detection.ssim_threshold = 0.85
        settings.slide_detection.ssim_ambiguous_low = 0.85
        settings.slide_detection.ssim_ambiguous_high = 0.93
        settings.slide_detection.sampling_fps = 1.0
        settings.slide_detection.min_slide_duration = 3.0
        settings.slide_detection.llm_model = "mistral"
        settings.slide_detection.llm_timeout = 30
        settings.slide_detection.ocr_enabled = True
        settings.slide_detection.layout_sample_count = 5
        settings.slide_detection.incremental_ssim_threshold = 0.95
        settings.ollama.base_url = "http://localhost:11434"
        mock_settings.return_value = settings
        svc = SlideDetectionService()
        yield svc


class TestLayoutDetection:
    """Test layout classification."""

    def test_returns_full_frame_for_invalid_video(self, service):
        """Invalid video path should default to full_frame."""
        result = service.layout_detection("/nonexistent/video.mp4")
        assert result == "full_frame"

    def test_returns_string_layout_type(self, service):
        """Layout detection should return a valid layout string."""
        result = service.layout_detection("/nonexistent/video.mp4")
        assert result in ("full_frame", "pip_speaker", "split_panel")


class TestSSIMComputation:
    """Test _compute_ssim helper."""

    def test_identical_images_return_high_ssim(self, service):
        """Two identical images should have SSIM close to 1.0."""
        img = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        score = service._compute_ssim(img, img)
        assert score > 0.99

    def test_different_images_return_low_ssim(self, service):
        """Very different images should have low SSIM."""
        img1 = np.zeros((100, 100), dtype=np.uint8)
        img2 = np.full((100, 100), 255, dtype=np.uint8)
        score = service._compute_ssim(img1, img2)
        assert score < 0.1

    def test_different_sized_images(self, service):
        """Different sized images should still compute SSIM."""
        img1 = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        img2 = np.random.randint(0, 255, (120, 130), dtype=np.uint8)
        score = service._compute_ssim(img1, img2)
        # SSIM can be slightly negative for very different random images
        assert -0.1 <= score <= 1.0

    def test_too_small_images_return_one(self, service):
        """Very small images should return 1.0 (too small to compare)."""
        img = np.zeros((2, 2), dtype=np.uint8)
        score = service._compute_ssim(img, img)
        assert score == 1.0


class TestSlideGrouping:
    """Test slide grouping from transitions."""

    def test_no_transitions_creates_single_slide(self, service):
        """No transitions should produce a single slide covering the whole video."""
        slides = service.slide_grouping([], video_duration=300.0)
        assert len(slides) == 1
        assert slides[0]["slide_number"] == 1
        assert slides[0]["start_timestamp"] == 0.0
        assert slides[0]["end_timestamp"] == 300.0

    def test_single_transition(self, service):
        """Single transition should create two slides."""
        transitions = [
            {"timestamp": 60.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        assert len(slides) == 2
        assert slides[0]["start_timestamp"] == 0.0
        assert slides[0]["end_timestamp"] == 60.0
        assert slides[1]["start_timestamp"] == 60.0
        assert slides[1]["end_timestamp"] == 120.0

    def test_multiple_transitions(self, service):
        """Multiple transitions should create correct number of slides."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.6, "classification": "transition"},
            {"timestamp": 90.0, "ssim": 0.4, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        assert len(slides) == 4  # initial + 3 transitions

    def test_min_duration_enforced(self, service):
        """Transitions too close together should be filtered out."""
        transitions = [
            {"timestamp": 10.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 11.0, "ssim": 0.5, "classification": "transition"},  # too close
            {"timestamp": 12.0, "ssim": 0.5, "classification": "transition"},  # too close
            {"timestamp": 60.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        # Only 10.0 and 60.0 should survive (11.0 and 12.0 are < 3s apart)
        timestamps = [s["start_timestamp"] for s in slides]
        assert 11.0 not in timestamps
        assert 12.0 not in timestamps

    def test_incremental_builds_skipped(self, service):
        """Transitions classified as incremental should not create new slides."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.9, "llm_classification": "incremental"},
            {"timestamp": 90.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        # Incremental at 60s should be skipped
        assert len(slides) == 3  # initial + 30s + 90s

    def test_slides_numbered_sequentially(self, service):
        """Slides should have sequential slide_number."""
        transitions = [
            {"timestamp": 20.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 50.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=100.0)
        numbers = [s["slide_number"] for s in slides]
        assert numbers == list(range(1, len(slides) + 1))


class TestTranscriptAlignment:
    """Test transcript segment alignment to slides."""

    def test_basic_alignment(self, service):
        """Segments should be aligned to overlapping slides."""
        slides = [
            {"slide_number": 1, "start_timestamp": 0.0, "end_timestamp": 30.0},
            {"slide_number": 2, "start_timestamp": 30.0, "end_timestamp": 60.0},
        ]

        class FakeSegment:
            def __init__(self, text, start, end):
                self.text = text
                self.start_time = start
                self.end_time = end

        segments = [
            FakeSegment("Hello", 0.0, 10.0),
            FakeSegment("World", 10.0, 25.0),
            FakeSegment("Next slide", 30.0, 45.0),
        ]

        result = service.transcript_alignment(slides, segments)
        assert result[0]["transcript_text"] == "Hello World"
        assert result[1]["transcript_text"] == "Next slide"

    def test_no_segments(self, service):
        """No segments should leave transcript_text as None."""
        slides = [{"slide_number": 1, "start_timestamp": 0.0, "end_timestamp": 30.0}]
        result = service.transcript_alignment(slides, [])
        assert result[0]["transcript_text"] is None

    def test_segment_spanning_slides(self, service):
        """Segment overlapping two slides should appear in both."""
        slides = [
            {"slide_number": 1, "start_timestamp": 0.0, "end_timestamp": 10.0},
            {"slide_number": 2, "start_timestamp": 10.0, "end_timestamp": 20.0},
        ]

        class FakeSegment:
            def __init__(self, text, start, end):
                self.text = text
                self.start_time = start
                self.end_time = end

        segments = [FakeSegment("Spanning text", 5.0, 15.0)]
        result = service.transcript_alignment(slides, segments)
        assert "Spanning text" in result[0]["transcript_text"]
        assert "Spanning text" in result[1]["transcript_text"]


class TestCropContentRegion:
    """Test layout-based frame cropping."""

    def test_full_frame_no_crop(self, service):
        """Full frame layout should return original image."""
        img = np.zeros((100, 200), dtype=np.uint8)
        result = service._crop_content_region(img, "full_frame")
        assert result.shape == (100, 200)

    def test_pip_speaker_crops_corner(self, service):
        """PiP speaker layout should crop out bottom-right area."""
        img = np.zeros((100, 200), dtype=np.uint8)
        result = service._crop_content_region(img, "pip_speaker")
        assert result.shape[0] == 80  # 80% of 100
        assert result.shape[1] == 160  # 80% of 200

    def test_split_panel_uses_left_half(self, service):
        """Split panel layout should use left half."""
        img = np.zeros((100, 200), dtype=np.uint8)
        result = service._crop_content_region(img, "split_panel")
        assert result.shape[0] == 100
        assert result.shape[1] == 100  # 50% of 200


class TestFinalStateCapture:
    """Test final frame capture."""

    def test_invalid_video_raises(self, service):
        """Invalid video should raise SlideDetectionException."""
        from app.exceptions import SlideDetectionException

        slides = [{"slide_number": 1, "start_timestamp": 0.0, "end_timestamp": 10.0}]
        with pytest.raises(SlideDetectionException):
            service.final_state_capture("/nonexistent/video.mp4", slides, "/tmp/test_slides")
