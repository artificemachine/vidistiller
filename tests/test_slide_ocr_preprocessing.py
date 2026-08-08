"""Tests for OCR preprocessing in slide detection.

The OCR quality on small code slides (pip_speaker layout) was noisy because
frames were fed to tesseract at native resolution without any preprocessing.
These tests pin the preprocessing: upscaling, contrast enhancement, and the
tesseract config string.
"""

import numpy as np
from unittest.mock import MagicMock, patch

from app.services.slide_detection import SlideDetectionService


def _service():
    with patch("app.services.slide_detection.get_settings") as mock_settings:
        settings = MagicMock()
        settings.slide_detection.ocr_enabled = True
        settings.slide_detection.pip_speaker_ssim_threshold = 0.65
        settings.slide_detection.pip_speaker_ssim_ambiguous_low = 0.65
        settings.slide_detection.pip_speaker_ssim_ambiguous_high = 0.80
        settings.slide_detection.pip_speaker_min_slide_duration = 20.0
        settings.slide_detection.ssim_threshold = 0.85
        settings.slide_detection.ssim_ambiguous_low = 0.85
        settings.slide_detection.ssim_ambiguous_high = 0.93
        settings.slide_detection.sampling_fps = 1.0
        settings.slide_detection.min_slide_duration = 3.0
        settings.slide_detection.llm_model = "mistral"
        settings.slide_detection.llm_timeout = 30
        settings.slide_detection.layout_sample_count = 5
        settings.slide_detection.incremental_ssim_threshold = 0.95
        settings.ollama.base_url = "http://localhost:11434"
        mock_settings.return_value = settings
        return SlideDetectionService()


class TestOcrPreprocessing:
    def test_frame_is_upscaled_before_ocr(self):
        """The frame passed to tesseract must be at least 2x the original."""
        svc = _service()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "  clean text  "

        with patch("app.services.slide_detection.pytesseract", fake_pt):
            with patch("app.services.slide_detection.Image") as mock_img_cls:
                result = svc._extract_ocr_text(frame)

        assert result == "clean text"
        pil_img = mock_img_cls.fromarray.call_args[0][0]
        assert pil_img.shape[0] == 200  # 2x height
        assert pil_img.shape[1] == 400  # 2x width

    def test_tesseract_config_uses_psm6(self):
        """Slides are uniform text blocks; PSM 6 is the right segmentation mode."""
        svc = _service()
        frame = np.zeros((50, 80, 3), dtype=np.uint8)
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "text"

        with patch("app.services.slide_detection.pytesseract", fake_pt):
            with patch("app.services.slide_detection.Image"):
                svc._extract_ocr_text(frame)

        config = fake_pt.image_to_string.call_args.kwargs.get("config")
        assert config is not None
        assert "--psm 6" in config

    def test_empty_ocr_returns_none(self):
        """Blank tesseract output yields None (no empty strings stored)."""
        svc = _service()
        frame = np.zeros((50, 80, 3), dtype=np.uint8)
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "   \n  "

        with patch("app.services.slide_detection.pytesseract", fake_pt):
            with patch("app.services.slide_detection.Image"):
                assert svc._extract_ocr_text(frame) is None

    def test_ocr_error_returns_none(self):
        """A tesseract failure must not raise — returns None and logs."""
        svc = _service()
        frame = np.zeros((50, 80, 3), dtype=np.uint8)
        fake_pt = MagicMock()
        fake_pt.image_to_string.side_effect = RuntimeError("tesseract exploded")

        with patch("app.services.slide_detection.pytesseract", fake_pt):
            with patch("app.services.slide_detection.Image"):
                assert svc._extract_ocr_text(frame) is None

    def test_grayscale_frame_processed(self):
        """Grayscale (2D) frames must not crash the preprocessing."""
        svc = _service()
        frame = np.zeros((60, 90), dtype=np.uint8)  # 2D grayscale
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "text"

        with patch("app.services.slide_detection.pytesseract", fake_pt):
            with patch("app.services.slide_detection.Image"):
                assert svc._extract_ocr_text(frame) == "text"
