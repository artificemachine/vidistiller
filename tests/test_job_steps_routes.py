"""API exposure of persisted steps keeps canonical execution order."""

from app.db.models import ProcessingJob, ProcessingStatus
from app.services.job_steps import seed_job_steps


def test_job_status_returns_steps_in_canonical_order(client, test_db, test_user, auth_headers):
    job = ProcessingJob(
        job_id="steps-route-001",
        status=ProcessingStatus.PENDING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job)
    test_db.commit()

    response = client.get(f"/api/jobs/{job.job_id}/status", headers=auth_headers)

    assert response.status_code == 200
    assert [step["name"] for step in response.json()["steps"]] == [
        "download", "transcribe", "snapshots", "slides", "summarize", "export"
    ]
