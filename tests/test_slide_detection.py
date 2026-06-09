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
        settings.slide_detection.pip_speaker_ssim_threshold = 0.65
        settings.slide_detection.pip_speaker_ssim_ambiguous_low = 0.65
        settings.slide_detection.pip_speaker_ssim_ambiguous_high = 0.80
        settings.slide_detection.pip_speaker_min_slide_duration = 20.0
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

    def test_pip_speaker_uses_lower_thresholds(self, service):
        """pip_speaker layout uses pip_speaker_ssim_* thresholds, not the full_frame ones.
        SSIM=0.83: below full_frame threshold (0.85) → transition.
        SSIM=0.83: above pip_speaker_ssim_ambiguous_high (0.80) → same → no transition stored.
        """
        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60)), \
             patch.object(service, "_compute_ssim", return_value=0.83):
            full_transitions, _ = service.ssim_transition_scan("/fake.mp4", 1.0, "full_frame")
        assert len(full_transitions) > 0, "full_frame should flag 0.83 as transition"

        with patch("app.services.slide_detection.cv2.VideoCapture", return_value=self._make_cap(60)), \
             patch.object(service, "_compute_ssim", return_value=0.83):
            pip_transitions, _ = service.ssim_transition_scan("/fake.mp4", 1.0, "pip_speaker")
        assert len(pip_transitions) == 0, "pip_speaker should treat 0.83 as same-content"

    def test_pip_speaker_grouping_uses_longer_min_duration(self, service):
        """slide_grouping with layout=pip_speaker enforces 20s minimum, not 3s.
        Transitions at 5s, 10s, 15s, 25s: only t=25 passes the 20s gap from 0.
        An initial slide is inserted at 0.0 (covers 0-25s), then the 25s slide.
        Compare: full_frame (3s min) would produce a slide at each transition.
        """
        transitions = [
            {"timestamp": 5.0, "ssim": 0.5, "classification": "transition", "llm_classification": "transition"},
            {"timestamp": 10.0, "ssim": 0.5, "classification": "transition", "llm_classification": "transition"},
            {"timestamp": 15.0, "ssim": 0.5, "classification": "transition", "llm_classification": "transition"},
            {"timestamp": 25.0, "ssim": 0.5, "classification": "transition", "llm_classification": "transition"},
        ]
        pip_slides = service.slide_grouping(transitions, video_duration=60.0, layout="pip_speaker")
        full_slides = service.slide_grouping(transitions, video_duration=60.0, layout="full_frame")
        # pip_speaker: initial (0→25) + one real transition at 25s = 2 slides
        assert len(pip_slides) == 2
        assert pip_slides[0]["start_timestamp"] == 0.0
        assert pip_slides[1]["start_timestamp"] == 25.0
        # full_frame: all 4 transitions pass the 3s minimum → 4 slides (+ initial at 0.0 = 5)
        assert len(full_slides) > len(pip_slides)


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


# ==============================================================================
# Iteration 3 — run_full_pipeline orchestration integration tests
# ==============================================================================

class TestRunFullPipeline:
    """Integration: run_full_pipeline orchestrates all stages in the correct order."""

    def _slide_dict(self, num, is_incremental=False, parent_num=None):
        return {
            "slide_number": num,
            "start_timestamp": float(num * 30),
            "end_timestamp": float(num * 30 + 30),
            "ssim_transition_score": 0.5,
            "is_incremental_build": is_incremental,
            "parent_slide_number": parent_num,
            "final_frame_path": None,
            "ocr_text": None,
            "transcript_text": None,
            "image_width": None,
            "image_height": None,
            "file_size": None,
        }

    def test_missing_video_raises_slide_detection_exception(self, service):
        """No video file path → SlideDetectionException before any stage runs."""
        from app.exceptions import SlideDetectionException

        db = MagicMock()
        job = MagicMock()
        job.video_file_path = None

        with pytest.raises(SlideDetectionException):
            service.run_full_pipeline(db, job, None)

    def test_pipeline_calls_all_steps_in_order(self, service, tmp_path):
        """Happy path: stages run in order (layout→ssim→grouping→capture)."""
        video_file = tmp_path / "fake.mp4"
        video_file.write_bytes(b"FAKE")

        db = MagicMock()
        job = MagicMock()
        job.video_file_path = str(video_file)
        job.job_id = "order-test-uuid"
        job.id = 1
        job.transcripts = []

        call_order = []

        with patch.object(service, "layout_detection",
                          side_effect=lambda *a: call_order.append("layout") or "full_frame"), \
             patch.object(service, "ssim_transition_scan",
                          side_effect=lambda *a, **kw: call_order.append("ssim") or ([], 0)), \
             patch.object(service, "slide_grouping",
                          side_effect=lambda *a: call_order.append("grouping") or [self._slide_dict(1)]), \
             patch.object(service, "final_state_capture",
                          side_effect=lambda *a, **kw: call_order.append("capture") or [self._slide_dict(1)]), \
             patch("app.services.slide_detection.cv2.VideoCapture") as MockCap:
            MockCap.return_value.get.return_value = 30.0
            service.run_full_pipeline(db, job, None)

        # No ambiguous transitions → LLM step skipped. No transcript segments → alignment skipped.
        assert call_order == ["layout", "ssim", "grouping", "capture"]

    def test_cancel_mid_pipeline_raises_cancelled_exception(self, service, tmp_path):
        """cancel_check returning True after layout detection raises CancelledException."""
        from app.services.llm import CancelledException

        video_file = tmp_path / "fake.mp4"
        video_file.write_bytes(b"FAKE")

        db = MagicMock()
        job = MagicMock()
        job.video_file_path = str(video_file)
        job.job_id = "cancel-test-uuid"
        job.id = 2

        call_count = {"n": 0}

        def cancel_after_layout():
            call_count["n"] += 1
            return call_count["n"] >= 2  # False on 1st, True on 2nd

        with patch.object(service, "layout_detection", return_value="full_frame"), \
             patch("app.services.slide_detection.cv2.VideoCapture") as MockCap:
            MockCap.return_value.get.return_value = 30.0
            with pytest.raises(CancelledException):
                service.run_full_pipeline(db, job, cancel_after_layout)

    def test_incremental_builds_linked_via_parent_slide_id(self, service, test_db, test_user, tmp_path):
        """Incremental slide has parent_slide_id pointing to the correct parent row."""
        from app.db.models import (
            ProcessingJob, ProcessingMode, ProcessingStatus, Slide,
        )

        video_file = tmp_path / "fake.mp4"
        video_file.write_bytes(b"FAKE")

        job = ProcessingJob(
            job_id="incr-parent-test-uuid",
            status=ProcessingStatus.PROCESSING,
            video_url="https://youtube.com/watch?v=fake",
            video_file_path=str(video_file),
            processing_mode=ProcessingMode.SLIDE_AWARE.value,
            user_id=test_user.id,
        )
        test_db.add(job)
        test_db.flush()

        non_incr = self._slide_dict(1, is_incremental=False)
        incr = self._slide_dict(2, is_incremental=True, parent_num=1)

        with patch.object(service, "layout_detection", return_value="full_frame"), \
             patch.object(service, "ssim_transition_scan", return_value=([], 0)), \
             patch.object(service, "slide_grouping", return_value=[non_incr, incr]), \
             patch.object(service, "final_state_capture", return_value=[non_incr, incr]), \
             patch.object(service, "transcript_alignment",
                          side_effect=lambda slides, *a: slides), \
             patch("app.services.slide_detection.cv2.VideoCapture") as MockCap:
            MockCap.return_value.get.return_value = 30.0
            service.run_full_pipeline(test_db, job, None)

        slides = test_db.query(Slide).filter(Slide.job_id == job.id).all()
        parent_slides = [s for s in slides if not s.is_incremental_build]
        incremental_slides = [s for s in slides if s.is_incremental_build]

        assert len(parent_slides) == 1, "Expected 1 non-incremental slide"
        assert len(incremental_slides) == 1, "Expected 1 incremental slide"
        assert incremental_slides[0].parent_slide_id == parent_slides[0].id

    def test_metadata_row_committed(self, service, test_db, test_user, tmp_path):
        """After a successful run, a SlideDetectionMetadata row is persisted."""
        from app.db.models import (
            ProcessingJob, ProcessingMode, ProcessingStatus, SlideDetectionMetadata,
        )

        video_file = tmp_path / "fake.mp4"
        video_file.write_bytes(b"FAKE")

        job = ProcessingJob(
            job_id="metadata-test-uuid",
            status=ProcessingStatus.PROCESSING,
            video_url="https://youtube.com/watch?v=fake2",
            video_file_path=str(video_file),
            processing_mode=ProcessingMode.SLIDE_AWARE.value,
            user_id=test_user.id,
        )
        test_db.add(job)
        test_db.flush()

        with patch.object(service, "layout_detection", return_value="full_frame"), \
             patch.object(service, "ssim_transition_scan", return_value=([], 0)), \
             patch.object(service, "slide_grouping", return_value=[self._slide_dict(1)]), \
             patch.object(service, "final_state_capture", return_value=[self._slide_dict(1)]), \
             patch("app.services.slide_detection.cv2.VideoCapture") as MockCap:
            MockCap.return_value.get.return_value = 30.0
            service.run_full_pipeline(test_db, job, None)

        metadata = (
            test_db.query(SlideDetectionMetadata)
            .filter(SlideDetectionMetadata.job_id == job.id)
            .first()
        )
        assert metadata is not None
        assert metadata.total_slides == 1

    def test_video_duration_nonzero_when_frame_count_zero(self, service, tmp_path):
        """VBR containers report FRAME_COUNT==0; _get_video_duration must fall back to POS_MSEC/1000."""
        import cv2 as _cv2

        video_file = tmp_path / "vbr.mp4"
        video_file.write_bytes(b"FAKE")

        db = MagicMock()
        job = MagicMock()
        job.video_file_path = str(video_file)
        job.job_id = "vbr-duration-uuid"
        job.id = 10
        job.transcripts = []

        captured_duration = {}

        def capture_grouping(transitions, duration, layout="full_frame"):
            captured_duration["v"] = duration
            return [self._slide_dict(1)]

        def mock_get(prop):
            if prop == _cv2.CAP_PROP_FRAME_COUNT:
                return 0.0
            if prop == _cv2.CAP_PROP_FPS:
                return 30.0
            if prop == _cv2.CAP_PROP_POS_MSEC:
                return 60000.0
            return 0.0

        with patch.object(service, "layout_detection", return_value="full_frame"), \
             patch.object(service, "ssim_transition_scan", return_value=([], 0)), \
             patch.object(service, "slide_grouping", side_effect=capture_grouping), \
             patch.object(service, "final_state_capture", return_value=[self._slide_dict(1)]), \
             patch("app.services.slide_detection.cv2.VideoCapture") as MockCap:
            mock_cap = MagicMock()
            mock_cap.get.side_effect = mock_get
            MockCap.return_value = mock_cap
            service.run_full_pipeline(db, job, None)

        assert captured_duration.get("v") == 60.0


class TestAddOcrContext:
    """Unit: _add_ocr_context_to_transitions builds an OCR cache; final_state_capture reuses it."""

    def test_ocr_not_called_twice_for_ambiguous_frame(self, service, tmp_path):
        """OCR for a transition frame is cached; final_state_capture must not re-OCR the same frame index."""
        fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)

        def make_cap():
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.get.side_effect = lambda p: 30.0
            cap.read.return_value = (True, fake_frame)
            return cap

        # Ambiguous transition at frame 30; final_state_capture targets frame 30
        # (end_ts=1.5 → capture_ts=1.0 → frame_idx=int(1.0*30)=30)
        transition = {"classification": "ambiguous", "frame_index": 30, "timestamp": 1.0}
        slides = [{"slide_number": 1, "start_timestamp": 0.0, "end_timestamp": 1.5}]
        output_dir = str(tmp_path / "slides")

        with patch("app.services.slide_detection.cv2.VideoCapture", side_effect=lambda *a: make_cap()), \
             patch.object(service, "_extract_ocr_text", return_value="cached text") as mock_ocr:
            cache = service._add_ocr_context_to_transitions("/fake/video.mp4", [transition], "full_frame")
            ocr_count_after_first_pass = mock_ocr.call_count

            service.final_state_capture("/fake/video.mp4", slides, output_dir, frame_ocr_cache=cache)

        assert mock_ocr.call_count == ocr_count_after_first_pass, (
            f"_extract_ocr_text was called {mock_ocr.call_count - ocr_count_after_first_pass} extra time(s) "
            "in final_state_capture — frame OCR cache was not applied"
        )
