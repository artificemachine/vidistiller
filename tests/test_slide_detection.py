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

    def test_incremental_builds_linked_as_children(self, service):
        """Transitions classified as incremental become child slides, not top-level slides."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.9, "llm_classification": "incremental"},
            {"timestamp": 90.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        non_incr = [s for s in slides if not s["is_incremental_build"]]
        assert len(non_incr) == 3  # initial + 30s + 90s (unchanged)
        incr = [s for s in slides if s["is_incremental_build"]]
        assert len(incr) == 1  # incremental at 60s is now a child, not dropped

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


class TestLLMAmbiguityClassification:
    """Test LLM disambiguation of ambiguous transitions via an injected provider."""

    @staticmethod
    def _ambiguous_pair():
        return {
            "classification": "ambiguous",
            "ssim": 0.9,
            "ocr_text_before": "Intro",
            "ocr_text_after": "Intro\nPoint 1",
        }

    def test_incremental_classification(self, service):
        """Provider answering INCREMENTAL marks the pair incremental."""
        provider = MagicMock()
        provider.generate.return_value = "INCREMENTAL"
        pairs = [self._ambiguous_pair()]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="gemma4-31b")
        assert result[0]["llm_classification"] == "incremental"
        provider.generate.assert_called_once()

    def test_transition_classification(self, service):
        """Provider answering TRANSITION marks the pair transition."""
        provider = MagicMock()
        provider.generate.return_value = "TRANSITION"
        pairs = [self._ambiguous_pair()]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="gemma4-31b")
        assert result[0]["llm_classification"] == "transition"

    def test_provider_error_falls_back_to_transition(self, service):
        """A provider failure must not crash — defaults to transition."""
        provider = MagicMock()
        provider.generate.side_effect = RuntimeError("fleet unreachable")
        pairs = [self._ambiguous_pair()]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="gemma4-31b")
        assert result[0]["llm_classification"] == "transition"

    def test_no_provider_leaves_unclassified(self, service):
        """With no provider injected, pairs are left unclassified (no crash)."""
        pairs = [self._ambiguous_pair()]
        result = service.llm_ambiguity_classification(pairs, provider=None)
        assert "llm_classification" not in result[0]

    def test_non_ambiguous_pairs_skipped(self, service):
        """Non-ambiguous pairs are never sent to the provider."""
        provider = MagicMock()
        provider.generate.return_value = "TRANSITION"
        pairs = [{"classification": "transition", "ssim": 0.5}]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="x")
        provider.generate.assert_not_called()
        assert "llm_classification" not in result[0]

    def test_cancel_check_raises(self, service):
        """A truthy cancel_check raises CancelledException before any call."""
        from app.services.llm import CancelledException

        provider = MagicMock()
        pairs = [self._ambiguous_pair()]
        with pytest.raises(CancelledException):
            service.llm_ambiguity_classification(
                pairs, cancel_check=lambda: True, provider=provider, model="x"
            )


# ==============================================================================
# Iteration 4: incremental_ssim_threshold fast-path + parent-slide linking
# ==============================================================================


class TestFastPathIncrementalClassification:
    """Unit: SSIM fast-path in llm_ambiguity_classification."""

    @staticmethod
    def _pair(ssim: float):
        return {"classification": "ambiguous", "ssim": ssim, "ocr_text_before": "a", "ocr_text_after": "a b"}

    def test_high_ssim_classified_incremental_without_llm(self, service):
        """SSIM >= incremental_ssim_threshold → incremental with zero LLM calls."""
        provider = MagicMock()
        pairs = [self._pair(ssim=0.97)]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="m")
        assert result[0]["llm_classification"] == "incremental"
        provider.generate.assert_not_called()

    def test_below_threshold_still_uses_llm(self, service):
        """SSIM below incremental_ssim_threshold → LLM called as before."""
        provider = MagicMock()
        provider.generate.return_value = "TRANSITION"
        pairs = [self._pair(ssim=0.88)]
        service.llm_ambiguity_classification(pairs, provider=provider, model="m")
        provider.generate.assert_called_once()

    def test_llm_call_count_drops_for_high_ssim_set(self, service):
        """Only below-threshold pairs cost an LLM call; high-SSIM pairs are free."""
        provider = MagicMock()
        provider.generate.return_value = "TRANSITION"
        pairs = [
            self._pair(ssim=0.97),  # fast-path
            self._pair(ssim=0.96),  # fast-path
            self._pair(ssim=0.88),  # calls LLM
        ]
        service.llm_ambiguity_classification(pairs, provider=provider, model="m")
        assert provider.generate.call_count == 1

    def test_fast_path_unaffected_by_failing_provider(self, service):
        """Fast-path does not call provider.generate; provider error is irrelevant."""
        provider = MagicMock()
        provider.generate.side_effect = RuntimeError("fleet down")
        pairs = [self._pair(ssim=0.97)]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="m")
        assert result[0]["llm_classification"] == "incremental"
        provider.generate.assert_not_called()


class TestSlideGroupingIncrementalParent:
    """Unit: slide_grouping records incremental builds as linked children."""

    def test_incremental_build_records_parent_slide_number(self, service):
        """Incremental transition produces a child slide with parent_slide_number set."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.97, "llm_classification": "incremental"},
            {"timestamp": 90.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        incremental = [s for s in slides if s["is_incremental_build"]]
        assert len(incremental) == 1
        assert incremental[0]["parent_slide_number"] is not None

    def test_incremental_parent_is_preceding_slide(self, service):
        """Incremental build's parent_slide_number points to the slide before it."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.97, "llm_classification": "incremental"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        non_incr = [s for s in slides if not s["is_incremental_build"]]
        incr = [s for s in slides if s["is_incremental_build"]]
        assert len(incr) == 1
        parent_num = incr[0]["parent_slide_number"]
        parent = next(s for s in non_incr if s["slide_number"] == parent_num)
        assert parent["start_timestamp"] == 30.0

    def test_incremental_build_has_is_incremental_flag(self, service):
        """Child slide must have is_incremental_build=True."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 50.0, "ssim": 0.97, "llm_classification": "incremental"},
        ]
        slides = service.slide_grouping(transitions, video_duration=100.0)
        incr = [s for s in slides if s["is_incremental_build"]]
        assert len(incr) == 1
        assert incr[0]["is_incremental_build"] is True


class TestSlideGroupingIncrementalStateMachine:
    """State machine: incremental → has parent; real transition → no parent."""

    def test_real_transitions_have_no_parent(self, service):
        """Non-incremental slides must always have parent_slide_number=None."""
        transitions = [
            {"timestamp": 20.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 50.0, "ssim": 0.97, "llm_classification": "incremental"},
        ]
        slides = service.slide_grouping(transitions, video_duration=100.0)
        non_incr = [s for s in slides if not s["is_incremental_build"]]
        assert all(s["parent_slide_number"] is None for s in non_incr)

    def test_incrementals_always_have_parent(self, service):
        """Every incremental slide must have a non-None parent_slide_number."""
        transitions = [
            {"timestamp": 10.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 20.0, "ssim": 0.97, "llm_classification": "incremental"},
            {"timestamp": 40.0, "ssim": 0.97, "llm_classification": "incremental"},
        ]
        slides = service.slide_grouping(transitions, video_duration=60.0)
        incr = [s for s in slides if s["is_incremental_build"]]
        assert len(incr) == 2
        assert all(s["parent_slide_number"] is not None for s in incr)


class TestSlideGroupingIncrementalContract:
    """Contract: incremental slide dicts have all required fields."""

    def test_incremental_slide_has_required_fields(self, service):
        """Child slide must expose the same fields as a real slide."""
        transitions = [
            {"timestamp": 10.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 20.0, "ssim": 0.97, "llm_classification": "incremental"},
        ]
        slides = service.slide_grouping(transitions, video_duration=40.0)
        incr = next(s for s in slides if s["is_incremental_build"])
        required = {"slide_number", "start_timestamp", "end_timestamp",
                    "ssim_transition_score", "is_incremental_build", "parent_slide_number"}
        assert required <= set(incr.keys())


class TestSlideGroupingIncrementalRegression:
    """Regression: non-incremental slides are numbered correctly even with incrementals."""

    def test_slide_numbers_unaffected_by_incrementals(self, service):
        """Adding incrementals must not change non-incremental slide numbering."""
        transitions = [
            {"timestamp": 20.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 35.0, "ssim": 0.97, "llm_classification": "incremental"},
            {"timestamp": 60.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=100.0)
        non_incr = sorted([s for s in slides if not s["is_incremental_build"]], key=lambda x: x["slide_number"])
        numbers = [s["slide_number"] for s in non_incr]
        assert numbers == list(range(1, len(non_incr) + 1))

    def test_incremental_count_excluded_from_non_incremental_count(self, service):
        """Updating the existing test: incremental builds are now children, not dropped."""
        transitions = [
            {"timestamp": 30.0, "ssim": 0.5, "classification": "transition"},
            {"timestamp": 60.0, "ssim": 0.9, "llm_classification": "incremental"},
            {"timestamp": 90.0, "ssim": 0.5, "classification": "transition"},
        ]
        slides = service.slide_grouping(transitions, video_duration=120.0)
        non_incr = [s for s in slides if not s["is_incremental_build"]]
        assert len(non_incr) == 3  # initial + 30s + 90s (same as before)
        incr = [s for s in slides if s["is_incremental_build"]]
        assert len(incr) == 1  # incremental at 60s now a child, not dropped


class TestFastPathChaos:
    """Chaos: provider failures below threshold don't affect fast-path."""

    def test_provider_error_below_threshold_falls_back_to_transition(self, service):
        """Provider error on low-SSIM pair falls back to transition (existing chaos test)."""
        provider = MagicMock()
        provider.generate.side_effect = RuntimeError("fleet unreachable")
        pairs = [{"classification": "ambiguous", "ssim": 0.88, "ocr_text_before": "a", "ocr_text_after": "b"}]
        result = service.llm_ambiguity_classification(pairs, provider=provider, model="x")
        assert result[0]["llm_classification"] == "transition"


# ==============================================================================
# Iteration 2 — ssim_transition_scan + layout_detection contour-voting
# ==============================================================================

class TestSSIMTransitionScan:
    """Unit: ssim_transition_scan classifies frame pairs by SSIM band."""

    def _make_cap(self, n_frames, video_fps=30.0):
        """Mock VideoCapture yielding n_frames BGR frames then (False, None)."""
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = video_fps
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        cap.read.side_effect = [(True, frame)] * n_frames + [(False, None)]
        cap.release.return_value = None
        return cap

    def test_cannot_open_video_raises(self, service):
        """Bad video path → SlideDetectionException, not a silent fallback."""
        from app.exceptions import SlideDetectionException
        cap = MagicMock()
        cap.isOpened.return_value = False
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=cap):
            with pytest.raises(SlideDetectionException):
                service.ssim_transition_scan("/nonexistent.mp4", 1.0, "full_frame")

    def test_identical_frames_produce_no_transitions(self, service):
        """Frames with SSIM=1.0 are classified 'same' and not stored."""
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60)), \
             patch.object(service, "_compute_ssim", return_value=1.0):
            transitions, sampled = service.ssim_transition_scan("/fake.mp4", 1.0, "full_frame")
        assert transitions == []
        assert sampled > 0

    def test_low_ssim_produces_transition_classification(self, service):
        """SSIM below ssim_threshold (0.85) → 'transition' classification."""
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60)), \
             patch.object(service, "_compute_ssim", return_value=0.5):
            transitions, _ = service.ssim_transition_scan("/fake.mp4", 1.0, "full_frame")
        assert len(transitions) > 0
        assert all(t["classification"] == "transition" for t in transitions)

    def test_ambiguous_ssim_produces_ambiguous_classification(self, service):
        """SSIM in [ssim_ambiguous_low, ssim_ambiguous_high] → 'ambiguous' classification."""
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60)), \
             patch.object(service, "_compute_ssim", return_value=0.89):
            transitions, _ = service.ssim_transition_scan("/fake.mp4", 1.0, "full_frame")
        assert len(transitions) > 0
        assert all(t["classification"] == "ambiguous" for t in transitions)

    def test_frame_skip_limits_frames_sampled(self, service):
        """video_fps=30, sampling_fps=1 → frame_skip=30, exactly 2 frames sampled in a 60-frame clip."""
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60, video_fps=30.0)), \
             patch.object(service, "_compute_ssim", return_value=1.0):
            _, sampled = service.ssim_transition_scan("/fake.mp4", 1.0, "full_frame")
        assert sampled == 2


class TestLayoutDetectionContourVoting:
    """Unit: layout_detection votes correctly from contour analysis."""

    def _make_cap(self, n_frames=5, w=1000, h=1000):
        """Mock VideoCapture returning n_frames identical blank frames."""
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = float(n_frames)
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        cap.read.return_value = (True, frame)
        cap.set.return_value = None
        cap.release.return_value = None
        return cap

    def test_pip_speaker_box_votes_detected(self, service):
        """Contour with small-corner bounding rect on all frames → pip_speaker."""
        fake_cnt = MagicMock()
        cap = self._make_cap()
        # 200x200 box at (50,50): area_ratio=0.04, aspect=1.0, x=50<300 (corner) → pip vote
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=cap), \
             patch("app.services.slide_detection.cv2.cvtColor",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.Canny",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.findContours",
                   return_value=([fake_cnt], None)), \
             patch("app.services.slide_detection.cv2.boundingRect",
                   return_value=(50, 50, 200, 200)):
            result = service.layout_detection("/fake.mp4")
        assert result == "pip_speaker"

    def test_split_panel_contour_votes_detected(self, service):
        """Contour covering ~half the frame on all frames → split_panel."""
        fake_cnt = MagicMock()
        cap = self._make_cap()
        # 700x700 box: area_ratio=0.49, aspect=1.0 → split vote; not a pip (area_ratio>0.15)
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=cap), \
             patch("app.services.slide_detection.cv2.cvtColor",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.Canny",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.findContours",
                   return_value=([fake_cnt], None)), \
             patch("app.services.slide_detection.cv2.boundingRect",
                   return_value=(0, 0, 700, 700)):
            result = service.layout_detection("/fake.mp4")
        assert result == "split_panel"

    def test_no_voting_contours_returns_full_frame(self, service):
        """Empty contour list → no votes → full_frame default."""
        cap = self._make_cap()
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=cap), \
             patch("app.services.slide_detection.cv2.cvtColor",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.Canny",
                   return_value=np.zeros((1000, 1000), dtype=np.uint8)), \
             patch("app.services.slide_detection.cv2.findContours",
                   return_value=([], None)):
            result = service.layout_detection("/fake.mp4")
        assert result == "full_frame"
