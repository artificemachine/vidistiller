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
            mock_job.celery_task_id = None
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job

            MockServiceCls.return_value.run_full_pipeline.side_effect = RuntimeError("disk full")

            from app.tasks import process_slides
            result = process_slides.apply(kwargs={"job_id": 1}).get()

        assert "error" in result
        assert result.get("status") != "cancelled"


class TestProcessSlidesStalenessGuard:
    """A redelivered/duplicate execution must not restart an already-active or finished pipeline.

    Regression: job 268 (2026-08-12) looped every ~60min for 7 hours because
    each redelivery unconditionally overwrote celery_task_id and restarted
    the pipeline from scratch, starving the worker queue for every other job.
    """

    def _run(self, mock_job, request_id="task-current"):
        from app.db.models import ProcessingMode

        with patch("app.db.session.SessionLocal") as MockSession, \
             patch("app.services.slide_detection.SlideDetectionService") as MockServiceCls, \
             patch("app.tasks._resolve_job_llm", return_value=(MagicMock(), "model")), \
             patch("app.tasks._add_log"):

            mock_db = MagicMock()
            MockSession.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = mock_job

            from app.tasks import process_slides
            # .apply() lets us control task_id so it doesn't collide with the
            # job's simulated celery_task_id.
            result = process_slides.apply(kwargs={"job_id": 1}, task_id=request_id).get()

            return result, MockServiceCls

    def test_skips_when_another_delivery_already_claimed_the_job(self):
        """job.celery_task_id set to a DIFFERENT task id -> another delivery owns this job."""
        from app.db.models import ProcessingStatus, ProcessingMode

        mock_job = MagicMock()
        mock_job.processing_mode = ProcessingMode.SLIDE_AWARE.value
        mock_job.video_file_path = "/fake/video.mp4"
        mock_job.status = ProcessingStatus.PROCESSING
        mock_job.celery_task_id = "some-other-task-id"

        result, MockServiceCls = self._run(mock_job, request_id="task-current")

        assert result == {"status": "skipped", "reason": "another delivery is active"}
        MockServiceCls.return_value.run_full_pipeline.assert_not_called()

    def test_skips_when_job_already_completed(self):
        """status already COMPLETED (e.g. a prior delivery already finished it) -> skip."""
        from app.db.models import ProcessingStatus, ProcessingMode

        mock_job = MagicMock()
        mock_job.processing_mode = ProcessingMode.SLIDE_AWARE.value
        mock_job.video_file_path = "/fake/video.mp4"
        mock_job.status = ProcessingStatus.COMPLETED
        mock_job.celery_task_id = None

        result, MockServiceCls = self._run(mock_job)

        assert result == {"status": "skipped", "reason": "already completed"}
        MockServiceCls.return_value.run_full_pipeline.assert_not_called()

    def test_proceeds_when_no_prior_claim(self):
        """celery_task_id is None (fresh job, first delivery) -> pipeline runs normally."""
        from app.db.models import ProcessingStatus, ProcessingMode

        mock_job = MagicMock()
        mock_job.processing_mode = ProcessingMode.SLIDE_AWARE.value
        mock_job.video_file_path = "/fake/video.mp4"
        mock_job.status = ProcessingStatus.PROCESSING
        mock_job.celery_task_id = None

        result, MockServiceCls = self._run(mock_job)

        MockServiceCls.return_value.run_full_pipeline.assert_called_once()
        assert result == {"status": "completed"}

    def test_proceeds_when_claimed_by_this_same_delivery(self):
        """celery_task_id already equals this task's own request id -> not a duplicate, proceed.

        (e.g. Celery's own internal retry of the same task instance.)
        """
        from app.db.models import ProcessingStatus, ProcessingMode

        mock_job = MagicMock()
        mock_job.processing_mode = ProcessingMode.SLIDE_AWARE.value
        mock_job.video_file_path = "/fake/video.mp4"
        mock_job.status = ProcessingStatus.PROCESSING
        mock_job.celery_task_id = "task-current"

        result, MockServiceCls = self._run(mock_job, request_id="task-current")

        MockServiceCls.return_value.run_full_pipeline.assert_called_once()
        assert result == {"status": "completed"}
