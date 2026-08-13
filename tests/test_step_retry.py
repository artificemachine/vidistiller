"""Targeted retry leaves completed predecessor steps untouched."""

from unittest.mock import patch

from app.db.models import ProcessingJob, ProcessingStatus
from app.services.job_steps import claim_step, complete_step, fail_step, seed_job_steps


def test_retry_failed_snapshots_dispatches_snapshot_task_only(
    client, test_db, test_user, auth_headers
):
    job = ProcessingJob(
        job_id="retry-snapshot-001",
        status=ProcessingStatus.PROCESSING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker")
    complete_step(test_db, job.id, "download", "worker")
    claim_step(test_db, job.id, "snapshots", "worker")
    fail_step(test_db, job.id, "snapshots", "worker", "disk full")
    test_db.commit()

    with patch("app.routes.jobs.process_snapshots.delay") as dispatch:
        response = client.post(
            f"/api/jobs/{job.job_id}/steps/snapshots/retry", headers=auth_headers
        )

    assert response.status_code == 202
    dispatch.assert_called_once_with(job.id)
    steps = {step.name: step for step in job.steps}
    assert steps["download"].status.value == "completed"
    assert steps["snapshots"].status.value == "pending"


def test_retry_rejects_running_completed_or_unauthorised_step(
    client, test_db, test_user, auth_headers
):
    job = ProcessingJob(
        job_id="retry-reject-001",
        status=ProcessingStatus.PROCESSING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker")
    test_db.commit()

    running = client.post(f"/api/jobs/{job.job_id}/steps/download/retry", headers=auth_headers)
    missing = client.post("/api/jobs/not-owned/steps/download/retry", headers=auth_headers)

    assert running.status_code == 409
    assert missing.status_code == 404


def test_retry_failed_download_dispatches_download_task_even_after_job_completion(
    client, test_db, test_user, auth_headers
):
    job = ProcessingJob(
        job_id="retry-download-001",
        status=ProcessingStatus.COMPLETED,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker")
    fail_step(test_db, job.id, "download", "worker", "temporary download failure")
    test_db.commit()

    with patch("app.routes.jobs.process_video_download.delay") as dispatch:
        response = client.post(
            f"/api/jobs/{job.job_id}/steps/download/retry", headers=auth_headers
        )

    assert response.status_code == 202
    dispatch.assert_called_once_with(job.id)


def test_completed_download_retry_dispatches_pending_snapshot_step(test_db, test_user):
    """A successful download retry resumes the artifact step it had blocked."""
    job = ProcessingJob(
        job_id="retry-download-resume-001",
        status=ProcessingStatus.COMPLETED,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker")
    fail_step(test_db, job.id, "download", "worker", "temporary download failure")
    test_db.commit()

    with patch("app.db.session.SessionLocal", return_value=test_db), patch(
        "app.services.video.VideoService.download_video",
        return_value=("/tmp/retry-download-resume.mp4", {}),
    ), patch("app.tasks.process_snapshots.delay") as dispatch:
        from app.tasks import process_video_download

        result = process_video_download.apply(
            kwargs={"job_id": job.id}, task_id="download-retry-worker"
        ).get()

    assert result == {"job_id": job.id, "status": "dependent_step_queued", "step": "snapshots"}
    assert job.status == ProcessingStatus.PROCESSING
    dispatch.assert_called_once_with(job.id)


def test_export_records_bytes_and_item_counts(client, seeded_job, test_db, auth_headers):
    from app.services.job_steps import seed_job_steps

    seed_job_steps(test_db, seeded_job)
    test_db.commit()

    response = client.get(f"/api/jobs/{seeded_job.job_id}/export", headers=auth_headers)

    assert response.status_code == 200
    export_step = next(step for step in seeded_job.steps if step.name == "export")
    assert export_step.status.value == "completed"
    assert export_step.metrics["bytes"] > 0
    assert export_step.metrics["transcripts"] == 1
