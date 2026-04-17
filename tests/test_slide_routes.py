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
