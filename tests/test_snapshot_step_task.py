"""Snapshot Celery task uses its own durable job-step claim."""

from unittest.mock import MagicMock, patch

from app.db.models import ProcessingJob, ProcessingStatus
from app.services.job_steps import seed_job_steps


def test_unrequested_snapshots_are_skipped(test_db, test_user):
    job = ProcessingJob(
        job_id="snapshots-disabled-001",
        status=ProcessingStatus.PROCESSING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job, extract_snapshots=False)
    test_db.commit()

    with patch("app.db.session.SessionLocal", return_value=test_db), patch(
        "app.services.snapshot.SnapshotService"
    ) as service:
        from app.tasks import process_snapshots

        result = process_snapshots.apply(kwargs={"job_id": job.id}, task_id="snapshot-worker").get()

    assert result["status"] == "skipped"
    service.assert_not_called()


def test_snapshot_retry_skips_existing_completed_rows(test_db, test_user):
    from app.services.job_steps import claim_step, complete_step

    job = ProcessingJob(
        job_id="snapshots-completed-001",
        status=ProcessingStatus.PROCESSING,
        video_url="https://example.test/video.mp4",
        video_file_path="/tmp/synthetic.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "snapshots", "previous-worker")
    complete_step(test_db, job.id, "snapshots", "previous-worker", {"count": 1})
    test_db.commit()

    with patch("app.db.session.SessionLocal", return_value=test_db), patch(
        "app.services.snapshot.SnapshotService"
    ) as service:
        from app.tasks import process_snapshots

        result = process_snapshots.apply(kwargs={"job_id": job.id}, task_id="snapshot-worker").get()

    assert result["status"] == "skipped"
    service.assert_not_called()
