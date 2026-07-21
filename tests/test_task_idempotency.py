"""Idempotency of process_transcript.

With task_acks_late, a worker that dies after finishing but before acking gets
the same job redelivered. Reprocessing a completed job would overwrite its
transcript and re-run the LLM, so a terminal-state job must be skipped.
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
