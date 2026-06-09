"""Tests for slide-related API routes."""

import pytest

from app.db.models import User


class TestCreateJobSlideMode:
    """Test creating a job with slide_aware processing mode."""

    def test_create_job_with_slide_mode(self, client, auth_headers, mock_celery):
        """Job created with is_slide_mode=True should have processing_mode='slide_aware'."""
        resp = client.post("/api/jobs", json={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "is_slide_mode": True,
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["processing_mode"] == "slide_aware"

    def test_create_job_without_slide_mode(self, client, auth_headers, mock_celery):
        """Job created without is_slide_mode should have processing_mode='standard'."""
        resp = client.post("/api/jobs", json={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["processing_mode"] == "standard"

    def test_create_job_slide_mode_false(self, client, auth_headers, mock_celery):
        """Explicit is_slide_mode=False should produce 'standard' mode."""
        resp = client.post("/api/jobs", json={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "is_slide_mode": False,
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["processing_mode"] == "standard"


class TestGetJobSlides:
    """Test GET /jobs/{id}/slides endpoint."""

    def test_get_slides_for_slide_job(self, client, seeded_slide_job, auth_headers):
        """Should return slides for a slide-aware job."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}/slides", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["slide_number"] == 1
        assert data[1]["slide_number"] == 2
        assert data[0]["ocr_text"] == "Title Slide"
        assert data[1]["transcript_text"] == "Here is the main content"

    def test_get_slides_for_standard_job(self, client, seeded_job, auth_headers):
        """Standard job should return empty slides list."""
        resp = client.get(f"/api/jobs/{seeded_job.job_id}/slides", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_slides_job_not_found(self, client, test_db, test_user, auth_headers):
        """Non-existent job should return 404."""
        resp = client.get("/api/jobs/nonexistent-job-id/slides", headers=auth_headers)
        assert resp.status_code == 404

    def test_slides_ordered_by_number(self, client, seeded_slide_job, auth_headers):
        """Slides should be ordered by slide_number."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}/slides", headers=auth_headers)
        data = resp.json()
        numbers = [s["slide_number"] for s in data]
        assert numbers == sorted(numbers)


class TestGetSlideMetadata:
    """Test GET /jobs/{id}/slide-metadata endpoint."""

    def test_get_metadata_for_slide_job(self, client, seeded_slide_job, auth_headers):
        """Should return metadata for a slide-aware job."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}/slide-metadata", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_slides"] == 2
        assert data["total_transitions"] == 1
        assert data["layout_type_detected"] == "full_frame"
        assert data["sampling_fps"] == 1.0
        assert data["ocr_enabled"] is True
        assert data["processing_time_seconds"] == pytest.approx(15.5)

    def test_get_metadata_for_standard_job(self, client, seeded_job, auth_headers):
        """Standard job without metadata should return 404."""
        resp = client.get(f"/api/jobs/{seeded_job.job_id}/slide-metadata", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_metadata_job_not_found(self, client, test_db, test_user, auth_headers):
        """Non-existent job should return 404."""
        resp = client.get("/api/jobs/nonexistent-id/slide-metadata", headers=auth_headers)
        assert resp.status_code == 404


class TestGetJobWithSlides:
    """Test that GET /jobs/{id} includes slides in the response."""

    def test_job_response_includes_slides(self, client, seeded_slide_job, auth_headers):
        """Full job response should include slides array."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["processing_mode"] == "slide_aware"
        assert len(data["slides"]) == 2
        assert data["slides"][0]["slide_number"] == 1

    def test_standard_job_has_empty_slides(self, client, seeded_job, auth_headers):
        """Standard job should have empty slides array."""
        resp = client.get(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["slides"] == []


# ==============================================================================
# Iteration 3: slide_status tests
# ==============================================================================

import os
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

from app.db.models import ProcessingJob, ProcessingStatus


def _mk_slide_job(test_db, test_user, video_file_path="/tmp/fake.mp4"):
    """Create a minimal slide-aware ProcessingJob for task unit tests."""
    job = ProcessingJob(
        job_id=f"slide-test-{os.urandom(4).hex()}",
        status=ProcessingStatus.PENDING,
        processing_mode="slide_aware",
        video_url="https://www.youtube.com/watch?v=test",
        video_file_path=video_file_path,
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)
    return job


def _run_process_slides(job_id, test_engine, extra_patches=None):
    """Run process_slides synchronously against the test DB.

    Uses task.run() so Celery injects the task instance as self, avoiding
    the "3 args for 2 params" error from calling the task object directly.
    """
    from app.tasks import process_slides

    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    session = TestSession()

    patches = [("app.db.session.SessionLocal", MagicMock(return_value=session))]
    if extra_patches:
        patches.extend(extra_patches)

    ctx_managers = [patch(target, new) for target, new in patches]
    for cm in ctx_managers:
        cm.start()
    try:
        process_slides.run(job_id)
    finally:
        for cm in ctx_managers:
            cm.stop()

    return session


class TestSlideStatusUnit:
    """Unit: slide_status set correctly at each process_slides exit path."""

    def test_slide_status_skipped_when_no_video(self, test_db, test_engine, test_user):
        """No video_file_path → slide_status=skipped, job COMPLETED."""
        job = _mk_slide_job(test_db, test_user, video_file_path=None)

        session = _run_process_slides(job.id, test_engine)

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.status == ProcessingStatus.COMPLETED
        assert refreshed.slide_status == "skipped"

    def test_slide_status_completed_on_success(self, test_db, test_engine, test_user):
        """Successful pipeline run → slide_status=completed, job COMPLETED."""
        job = _mk_slide_job(test_db, test_user)

        mock_provider = MagicMock()
        session = _run_process_slides(
            job.id, test_engine,
            extra_patches=[
                ("app.tasks._resolve_job_llm", MagicMock(return_value=(mock_provider, "model"))),
                ("app.services.slide_detection.SlideDetectionService.run_full_pipeline",
                 MagicMock(return_value=None)),
            ],
        )

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.status == ProcessingStatus.COMPLETED
        assert refreshed.slide_status == "completed"

    def test_slide_status_failed_on_pipeline_exception(self, test_db, test_engine, test_user):
        """Pipeline raises → slide_status=failed, job still COMPLETED (slides are optional)."""
        job = _mk_slide_job(test_db, test_user)

        session = _run_process_slides(
            job.id, test_engine,
            extra_patches=[
                ("app.tasks._resolve_job_llm", MagicMock(return_value=(MagicMock(), "model"))),
                ("app.services.slide_detection.SlideDetectionService.run_full_pipeline",
                 MagicMock(side_effect=RuntimeError("simulated pipeline failure"))),
            ],
        )

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.status == ProcessingStatus.COMPLETED
        assert refreshed.slide_status == "failed"

    def test_job_response_exposes_slide_status(self, client, test_db, test_user, auth_headers):
        """GET /jobs/{id} must include slide_status field (nullable)."""
        job = _mk_slide_job(test_db, test_user)
        job.slide_status = "completed"
        test_db.commit()

        resp = client.get(f"/api/jobs/{job.job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "slide_status" in data
        assert data["slide_status"] == "completed"


class TestSlideStatusIntegration:
    """Integration: exception path leaves job COMPLETED with slide_status=failed."""

    def test_exception_path_completed_with_failed_status(self, test_db, test_engine, test_user):
        """Exception in pipeline: job.status stays COMPLETED, slide_status=failed."""
        job = _mk_slide_job(test_db, test_user)

        session = _run_process_slides(
            job.id, test_engine,
            extra_patches=[
                ("app.tasks._resolve_job_llm", MagicMock(return_value=(MagicMock(), "model"))),
                ("app.services.slide_detection.SlideDetectionService.run_full_pipeline",
                 MagicMock(side_effect=ValueError("db constraint"))),
            ],
        )

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.status == ProcessingStatus.COMPLETED, "job must stay COMPLETED — slides are optional"
        assert refreshed.slide_status == "failed"


class TestSlideStatusStateMachine:
    """State machine: slide_status transitions from None to a terminal value."""

    def test_slide_status_starts_none_and_ends_terminal(self, test_db, test_engine, test_user):
        """Before run: slide_status is None. After run: one of {completed, skipped, failed}."""
        job = _mk_slide_job(test_db, test_user, video_file_path=None)
        assert job.slide_status is None  # pre-condition

        session = _run_process_slides(job.id, test_engine)

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.slide_status in {"completed", "skipped", "failed"}


class TestSlideStatusContract:
    """Contract: JobResponse and JobStatusResponse expose slide_status."""

    def test_job_status_response_has_slide_status_field(self, client, seeded_slide_job, auth_headers):
        """GET /jobs/{id}/status must include slide_status (may be null)."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}/status", headers=auth_headers)
        assert resp.status_code == 200
        assert "slide_status" in resp.json()

    def test_standard_job_slide_status_is_null(self, client, seeded_job, auth_headers):
        """Standard (non-slide) job slide_status must be null — clients unaffected."""
        resp = client.get(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "slide_status" in data
        assert data["slide_status"] is None


class TestSlideStatusRegression:
    """Regression: existing tests pass; standard jobs leave slide_status null."""

    def test_existing_slide_route_unaffected(self, client, seeded_slide_job, auth_headers):
        """GET /jobs/{id}/slides still returns correct slide list."""
        resp = client.get(f"/api/jobs/{seeded_slide_job.job_id}/slides", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestSlideStatusChaos:
    """Chaos: mid-pipeline raise leaves slide_status=failed, job not stuck in processing."""

    def test_mid_pipeline_raise_does_not_leave_processing(self, test_db, test_engine, test_user):
        """If pipeline raises mid-run, job.status must NOT be processing (not stuck)."""
        job = _mk_slide_job(test_db, test_user)

        session = _run_process_slides(
            job.id, test_engine,
            extra_patches=[
                ("app.tasks._resolve_job_llm", MagicMock(return_value=(MagicMock(), "model"))),
                ("app.services.slide_detection.SlideDetectionService.run_full_pipeline",
                 MagicMock(side_effect=TimeoutError("network timeout mid-run"))),
            ],
        )

        refreshed = session.query(ProcessingJob).filter(ProcessingJob.id == job.id).first()
        assert refreshed.status != ProcessingStatus.PROCESSING
        assert refreshed.slide_status == "failed"
