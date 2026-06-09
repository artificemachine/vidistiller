"""Tests for process_slides Celery task — cancel_check signal and exception routing."""

from unittest.mock import MagicMock, patch

import pytest


class TestIsSlideCancelled:
    """Unit: _is_slide_cancelled returns True only on CANCELLED status."""

    def _db_with_status(self, status_value):
        db = MagicMock()
        job = MagicMock()
        job.status = status_value
        db.query.return_value.filter.return_value.first.return_value = job
        return db

    def test_returns_false_when_processing(self):
        """PROCESSING status must not trigger cancellation."""
        from app.tasks import _is_slide_cancelled
        from app.db.models import ProcessingStatus

        assert _is_slide_cancelled(self._db_with_status(ProcessingStatus.PROCESSING), 1) is False

    def test_returns_true_when_cancelled(self):
        """CANCELLED status must trigger cancel_check."""
        from app.tasks import _is_slide_cancelled
        from app.db.models import ProcessingStatus

        assert _is_slide_cancelled(self._db_with_status(ProcessingStatus.CANCELLED), 1) is True

    def test_returns_false_when_failed(self):
        """Regression guard: FAILED must NOT trigger cancellation (was the old bug)."""
        from app.tasks import _is_slide_cancelled
        from app.db.models import ProcessingStatus

        assert _is_slide_cancelled(self._db_with_status(ProcessingStatus.FAILED), 1) is False

    def test_returns_true_when_job_missing(self):
        """Missing job returns True — treat as gone / cancelled."""
        from app.tasks import _is_slide_cancelled

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert _is_slide_cancelled(db, 999) is True


class TestProcessSlidesExceptionRouting:
    """Genuine pipeline failures must route to except Exception, not CancelledException."""

    def test_genuine_failure_returns_error_dict(self):
        """run_full_pipeline raising RuntimeError returns {"error": ...}, not {"status": "cancelled"}."""
        from app.db.models import ProcessingStatus, ProcessingMode

        with patch("app.db.session.SessionLocal") as MockSession, \
             patch("app.services.slide_detection.SlideDetectionService") as MockServiceCls, \
             patch("app.tasks._resolve_job_llm", return_value=(MagicMock(), "model")), \
             patch("app.tasks._add_log"):

            mock_db = MagicMock()
            MockSession.return_value = mock_db

            mock_job = MagicMock()
            mock_job.processing_mode = ProcessingMode.SLIDE_AWARE.value
            mock_job.video_file_path = "/fake/video.mp4"
            mock_job.status = ProcessingStatus.PROCESSING
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job

            MockServiceCls.return_value.run_full_pipeline.side_effect = RuntimeError("disk full")

            from app.tasks import process_slides
            result = process_slides.apply(kwargs={"job_id": 1}).get()

        assert "error" in result
        assert result.get("status") != "cancelled"
