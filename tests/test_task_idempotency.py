"""Idempotency of process_transcript.

With task_acks_late, a worker that dies after finishing but before acking gets
the same job redelivered. Reprocessing a completed job would overwrite its
transcript and re-run the LLM, so a terminal-state job must be skipped.

Also covers the staleness guard against a *different* still-active delivery
(video download + Whisper fallback can legitimately run past Redis' broker
visibility timeout on slow hardware) -- the same bug class found live in
process_slides on 2026-08-12 (see incident_log.md), which had no such guard.
"""

from unittest.mock import patch

from app.db.models import ProcessingJob, ProcessingStatus
from app.tasks import process_transcript


def _make_job(db, status):
    job = ProcessingJob(
        job_id="idem-1",
        status=status,
        video_url="https://youtu.be/abc",
        source_type="youtube",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestProcessTranscriptIdempotency:
    def _run_with_test_db(self, test_db, job_id):
        # process_transcript opens its own SessionLocal; point it at the test DB
        # and keep the session open (real code calls db.close()).
        test_db.close = lambda: None
        with patch("app.db.session.SessionLocal", return_value=test_db), \
             patch("app.tasks._fetch_platform_captions") as mock_fetch:
            result = process_transcript.run(job_id)
        return result, mock_fetch

    def test_completed_job_is_skipped(self, test_db):
        job = _make_job(test_db, ProcessingStatus.COMPLETED)
        result, mock_fetch = self._run_with_test_db(test_db, job.id)
        assert result.get("skipped") is True
        mock_fetch.assert_not_called()

    def test_cancelled_job_is_skipped(self, test_db):
        job = _make_job(test_db, ProcessingStatus.CANCELLED)
        result, mock_fetch = self._run_with_test_db(test_db, job.id)
        assert result.get("skipped") is True
        mock_fetch.assert_not_called()


class TestProcessTranscriptStalenessGuard:
    """A redelivered/duplicate execution must not restart a still-active pipeline."""

    def _run(self, test_db, job_id, task_id, fetch_return=("", "en")):
        test_db.close = lambda: None
        with patch("app.db.session.SessionLocal", return_value=test_db), \
             patch("app.tasks._fetch_platform_captions", return_value=fetch_return) as mock_fetch, \
             patch("app.tasks._transcribe_audio", return_value=("", "en")):
            result = process_transcript.apply(kwargs={"job_id": job_id}, task_id=task_id).get()
        return result, mock_fetch

    def test_skips_when_another_delivery_already_claimed_the_job(self, test_db):
        job = _make_job(test_db, ProcessingStatus.PROCESSING)
        job.celery_task_id = "some-other-task-id"
        test_db.commit()

        result, mock_fetch = self._run(test_db, job.id, task_id="task-current")

        assert result.get("status") == "skipped"
        mock_fetch.assert_not_called()

    def test_proceeds_when_no_prior_claim(self, test_db):
        job = _make_job(test_db, ProcessingStatus.PENDING)

        result, mock_fetch = self._run(test_db, job.id, task_id="task-current")

        mock_fetch.assert_called_once()
        assert result.get("error") == "Empty transcript"

    def test_proceeds_when_claimed_by_this_same_delivery(self, test_db):
        """celery_task_id already equals this task's own request id -> not a duplicate."""
        job = _make_job(test_db, ProcessingStatus.PROCESSING)
        job.celery_task_id = "task-current"
        test_db.commit()

        result, mock_fetch = self._run(test_db, job.id, task_id="task-current")

        mock_fetch.assert_called_once()
        assert result.get("error") == "Empty transcript"
