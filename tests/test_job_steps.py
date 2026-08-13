"""Persistent, claim-token protected processing-step state transitions."""

from app.db.models import ProcessingJob, ProcessingStatus


def _job(test_db, test_user):
    job = ProcessingJob(
        job_id="steps-job-001",
        status=ProcessingStatus.PENDING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    return job


def test_seed_creates_six_unique_steps(test_db, test_user):
    from app.services.job_steps import CANONICAL_STEP_NAMES, seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job, extract_snapshots=False, is_slide_mode=False)
    test_db.flush()

    assert [step.name for step in job.steps] == list(CANONICAL_STEP_NAMES)
    assert job.steps[2].status.value == "skipped"
    assert job.steps[3].status.value == "skipped"


def test_seed_skips_download_when_no_video_artifact_is_requested(test_db, test_user):
    from app.services.job_steps import seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job, extract_snapshots=False, is_slide_mode=False)

    assert job.steps[0].status.value == "skipped"


def test_claim_pending_step_is_atomic_and_increments_attempt(test_db, test_user):
    from app.services.job_steps import claim_step, seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job)

    claimed = claim_step(test_db, job.id, "download", "worker-a")

    assert claimed is not None
    assert (claimed.status.value, claimed.attempt, claimed.claim_token) == (
        "running", 1, "worker-a"
    )
    assert claim_step(test_db, job.id, "download", "worker-b") is None


def test_same_claim_token_is_idempotent(test_db, test_user):
    from app.services.job_steps import claim_step, seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job)

    first = claim_step(test_db, job.id, "transcribe", "worker-a")
    second = claim_step(test_db, job.id, "transcribe", "worker-a")

    assert first.id == second.id
    assert second.attempt == 1


def test_progress_is_monotonic_and_bounded(test_db, test_user):
    import pytest

    from app.services.job_steps import claim_step, seed_job_steps, set_step_progress

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker-a")

    assert set_step_progress(test_db, job.id, "download", "worker-a", 40) is True
    assert set_step_progress(test_db, job.id, "download", "worker-a", 39) is False
    with pytest.raises(ValueError):
        set_step_progress(test_db, job.id, "download", "worker-a", 101)


def test_stale_claim_cannot_complete_step(test_db, test_user):
    from app.services.job_steps import claim_step, complete_step, seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "download", "worker-a")

    assert complete_step(test_db, job.id, "download", "worker-b") is False
    assert complete_step(test_db, job.id, "download", "worker-a") is True


def test_failure_persists_error_finish_time_and_metrics(test_db, test_user):
    from app.services.job_steps import claim_step, fail_step, seed_job_steps

    job = _job(test_db, test_user)
    seed_job_steps(test_db, job)
    claim_step(test_db, job.id, "transcribe", "worker-a")

    assert fail_step(
        test_db, job.id, "transcribe", "worker-a", "caption unavailable", {"source": "captions"}
    ) is True
    step = next(step for step in job.steps if step.name == "transcribe")
    assert step.status.value == "failed"
    assert step.finished_at is not None
    assert step.error_message == "caption unavailable"
    assert step.metrics == {"source": "captions"}
