"""Integration tests for job API routes."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    ProcessingJob, ProcessingStatus, Video, Transcript,
    TranscriptSegment, Document, User,
)


# ===========================================================================
# Create Job — POST /api/jobs
# ===========================================================================

class TestCreateJob:
    def test_valid_url_201(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict, mock_celery):
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["user_id"] == test_user.id

    def test_triggers_celery(self, client: TestClient, test_db: Session, auth_headers: dict, mock_celery):
        client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        mock_celery.assert_called_once()

    def test_invalid_url_422(self, client: TestClient, test_db: Session, auth_headers: dict, mock_celery):
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://example.com/not-youtube",
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_persists_to_db(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict, mock_celery):
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        job_id = resp.json()["job_id"]
        job = test_db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
        assert job is not None
        assert job.youtube_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert job.user_id == test_user.id

    def test_requires_auth(self, client: TestClient, test_db: Session, mock_celery):
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp.status_code == 401


# ===========================================================================
# Get Job — GET /api/jobs/{job_id}
# ===========================================================================

class TestGetJob:
    def test_existing_200(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == seeded_job.job_id

    def test_nonexistent_404(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.get("/api/jobs/nonexistent-uuid", headers=auth_headers)
        assert resp.status_code == 404

    def test_includes_nested_relations(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        data = resp.json()
        assert len(data["videos"]) == 1
        assert len(data["transcripts"]) == 1
        assert len(data["snapshots"]) == 1
        assert len(data["documents"]) == 1


# ===========================================================================
# Get Job Status — GET /api/jobs/{job_id}/status
# ===========================================================================

class TestGetJobStatus:
    def test_lightweight_response(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get(f"/api/jobs/{seeded_job.job_id}/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "videos" not in data

    def test_404(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.get("/api/jobs/nonexistent/status", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# List Jobs — GET /api/jobs
# ===========================================================================

class TestListJobs:
    def test_returns_all(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get("/api/jobs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_skip(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get("/api/jobs?skip=100", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_limit(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get("/api/jobs?limit=1", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    def test_status_filter(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.get("/api/jobs?status_filter=completed", headers=auth_headers)
        assert resp.status_code == 200
        for job in resp.json():
            assert job["status"] == "completed"

    def test_invalid_filter_422(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.get("/api/jobs?status_filter=invalid_status", headers=auth_headers)
        assert resp.status_code == 422

    def test_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.get("/api/jobs")
        assert resp.status_code == 401


# ===========================================================================
# Delete Job — DELETE /api/jobs/{job_id}
# ===========================================================================

class TestDeleteJob:
    def test_204(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        resp = client.delete(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_cascades(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        job_pk = seeded_job.id
        client.delete(f"/api/jobs/{seeded_job.job_id}", headers=auth_headers)
        assert test_db.query(Video).filter(Video.job_id == job_pk).count() == 0
        assert test_db.query(Transcript).filter(Transcript.job_id == job_pk).count() == 0

    def test_nonexistent_404(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.delete("/api/jobs/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# Summarize Transcript — POST /api/jobs/{job_id}/summarize
# ===========================================================================

class TestSummarizeTranscript:
    def test_force_dispatches_task_202(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict, mock_celery):
        """Force summarize dispatches background Celery task and returns 202."""
        # Remove existing summary document so it doesn't return cached
        test_db.query(Document).filter(
            Document.job_id == seeded_job.id, Document.format == "summary"
        ).delete()
        test_db.commit()

        resp = client.post(f"/api/jobs/{seeded_job.job_id}/summarize?force=true", headers=auth_headers)
        assert resp.status_code == 202
        data = resp.json()
        assert data["message"] == "Summarization started"

    def test_cached_returns_200(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        """Cached summary returns 200 with document content."""
        resp = client.post(f"/api/jobs/{seeded_job.job_id}/summarize", headers=auth_headers)
        assert resp.status_code == 200
        assert "content" in resp.json()

    def test_no_transcript_422(self, client: TestClient, test_db: Session, auth_headers: dict, mock_celery):
        """No transcript returns 422."""
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        job_id = resp.json()["job_id"]

        resp = client.post(f"/api/jobs/{job_id}/summarize?force=true", headers=auth_headers)
        assert resp.status_code == 422

    def test_nonexistent_job_404(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.post("/api/jobs/nonexistent/summarize", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# Cancel Job — POST /api/jobs/{job_id}/cancel
# ===========================================================================

class TestCancelJob:
    def test_cancel_processing_job(self, client: TestClient, test_db: Session, auth_headers: dict, mock_celery, mock_celery_control):
        """Cancelling a processing job revokes the Celery task and sets CANCELLED."""
        resp = client.post("/api/jobs", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        job_id = resp.json()["job_id"]

        # Set job to processing with a celery task ID
        job = test_db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = "fake-celery-task-id"
        test_db.commit()

        resp = client.post(f"/api/jobs/{job_id}/cancel", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        mock_celery_control.assert_called_once_with("fake-celery-task-id", terminate=True, signal="SIGTERM")

    def test_cancel_summarization(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict, mock_celery_control):
        """Cancelling a summarization on a completed job keeps job COMPLETED."""
        seeded_job.summarize_status = "processing"
        seeded_job.celery_task_id = "fake-summarize-task-id"
        test_db.commit()

        resp = client.post(f"/api/jobs/{seeded_job.job_id}/cancel", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Job stays completed, only summarize_status changes
        assert data["status"] == "completed"
        assert data["summarize_status"] == "failed"
        mock_celery_control.assert_called_once_with("fake-summarize-task-id", terminate=True, signal="SIGTERM")

    def test_cancel_completed_job_422(self, client: TestClient, test_db: Session, seeded_job, auth_headers: dict):
        """Cannot cancel a completed job (without active summarization)."""
        resp = client.post(f"/api/jobs/{seeded_job.job_id}/cancel", headers=auth_headers)
        assert resp.status_code == 422

    def test_cancel_nonexistent_404(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.post("/api/jobs/nonexistent/cancel", headers=auth_headers)
        assert resp.status_code == 404
