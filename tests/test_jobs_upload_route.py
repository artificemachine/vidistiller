"""Integration tests for the local file upload job route (POST /api/jobs/upload)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ProcessingJob, User


@pytest.fixture()
def upload_data_dir(tmp_path, monkeypatch):
    """Redirect uploaded-file storage to a throwaway tmp dir for this test."""
    monkeypatch.setattr(get_settings().storage, "data_dir", str(tmp_path))
    return tmp_path


class TestUploadJob:
    def test_valid_video_201(
        self, client: TestClient, test_db: Session, test_user: User,
        auth_headers: dict, mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"fake-mp4-bytes", "video/mp4")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["user_id"] == test_user.id

    def test_persists_upload_source_and_file(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"fake-mp4-bytes", "video/mp4")},
            headers=auth_headers,
        )
        job_id = resp.json()["job_id"]
        job = test_db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
        assert job.source_type == "upload"
        assert job.video_url.startswith("upload://")
        assert "clip.mp4" in job.video_url

        saved = list((upload_data_dir / "videos" / job_id).iterdir())
        assert len(saved) == 1
        assert saved[0].read_bytes() == b"fake-mp4-bytes"

    def test_rejects_unsupported_extension(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_rejects_oversized_upload(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir, monkeypatch,
    ):
        monkeypatch.setattr(get_settings().storage, "max_video_upload_size_bytes", 10)
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"0123456789ABCDEF", "video/mp4")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert list((upload_data_dir / "videos").glob("*/*")) == []

    def test_rejects_empty_file(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"", "video/mp4")},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_requires_auth(
        self, client: TestClient, test_db: Session, mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"data", "video/mp4")},
        )
        assert resp.status_code == 401

    def test_audio_only_forces_snapshots_off(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir,
    ):
        resp = client.post(
            "/api/jobs/upload",
            data={"extract_snapshots": "true", "is_slide_mode": "true"},
            files={"file": ("talk.mp3", b"id3-fake-audio", "audio/mpeg")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]
        job = test_db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
        download_step = next((s for s in job.steps if s.name == "download"), None)
        assert download_step is not None
        assert download_step.status.value == "skipped"

    def test_triggers_celery(
        self, client: TestClient, test_db: Session, auth_headers: dict,
        mock_celery, upload_data_dir,
    ):
        client.post(
            "/api/jobs/upload",
            files={"file": ("clip.mp4", b"fake-mp4-bytes", "video/mp4")},
            headers=auth_headers,
        )
        mock_celery.assert_called_once()
