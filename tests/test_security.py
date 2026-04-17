"""Security tests validating auth boundaries and known edge cases."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ProcessingJob, ProcessingStatus
from app.main import app


# ===========================================================================
# Path Traversal — Snapshot Routes
# ===========================================================================

class TestPathTraversalSnapshots:
    """Snapshot extraction endpoints must reject path traversal attempts."""

    def test_extract_rejects_absolute_path(self, client: TestClient, test_db: Session):
        resp = client.post(
            "/api/snapshots/extract",
            params={"job_id": 1, "video_path": "/etc/passwd", "interval": 5.0},
        )
        # Should not return 200; service error or 422/400
        assert resp.status_code != 200

    def test_extract_rejects_dot_dot_sequence(self, client: TestClient, test_db: Session):
        resp = client.post(
            "/api/snapshots/extract",
            params={"job_id": 1, "video_path": "../../etc/shadow", "interval": 5.0},
        )
        assert resp.status_code != 200

    def test_detect_scenes_rejects_absolute_path(self, client: TestClient, test_db: Session):
        resp = client.post(
            "/api/snapshots/detect-scenes",
            params={"job_id": 1, "video_path": "/etc/passwd"},
        )
        assert resp.status_code != 200

    def test_detect_scenes_rejects_dot_dot_sequence(self, client: TestClient, test_db: Session):
        resp = client.post(
            "/api/snapshots/detect-scenes",
            params={"job_id": 1, "video_path": "../../../etc/shadow"},
        )
        assert resp.status_code != 200


# ===========================================================================
# Import Payload Validation
# ===========================================================================

class TestImportPayloadValidation:
    """Import endpoint must validate file paths in payloads."""

    def test_import_rejects_missing_export_version(self, client: TestClient, test_db: Session, test_user, auth_headers):
        resp = client.post("/api/jobs/import", json={"job": {}}, headers=auth_headers)
        assert resp.status_code == 422

    def test_import_rejects_missing_job_key(self, client: TestClient, test_db: Session, test_user, auth_headers):
        resp = client.post("/api/jobs/import", json={"export_version": "1.0"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_import_rejects_unsupported_version(self, client: TestClient, test_db: Session, test_user, auth_headers):
        resp = client.post("/api/jobs/import", json={
            "export_version": "99.0",
            "job": {"job_id": "x", "status": "completed", "video_url": "https://youtube.com/watch?v=abc12345678"},
        }, headers=auth_headers)
        assert resp.status_code == 422


# ===========================================================================
# JWT Secret Validation
# ===========================================================================

class TestHardcodedJWTSecret:
    """JWT secret validation documented and tested."""

    def test_short_key_rejected(self):
        from pydantic import SecretStr, ValidationError
        from app.core.config import JWTSettings

        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("short"))

    def test_change_me_rejected(self):
        from pydantic import SecretStr, ValidationError
        from app.core.config import JWTSettings

        with pytest.raises(ValidationError):
            JWTSettings(secret_key=SecretStr("change-me-please-this-is-long-enough-1234!A"))

    def test_strong_key_accepted(self):
        from pydantic import SecretStr
        from app.core.config import JWTSettings

        settings = JWTSettings(secret_key=SecretStr("MyStrongProductionKey!2024#SecureApp"))
        assert settings.secret_key.get_secret_value() == "MyStrongProductionKey!2024#SecureApp"


# ===========================================================================
# Authenticated Operational Routes — Auth Now Required
# ===========================================================================

class TestAuthRequiredOnOperationalRoutes:
    """Verify that job routes now require authentication."""

    def test_list_jobs_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.get("/api/jobs")
        assert resp.status_code == 401

    def test_create_job_requires_auth(self, client: TestClient, test_db: Session, mock_celery):
        resp = client.post("/api/jobs", json={
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp.status_code == 401

    def test_import_job_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.post("/api/jobs/import", json={"export_version": "1.0", "job": {}})
        assert resp.status_code == 401

    def test_import_upload_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.post(
            "/api/jobs/import-upload?filename=export.json",
            data=b"{}",
        )
        assert resp.status_code == 401

    def test_import_upload_status_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.get("/api/jobs/import-upload/fake-task-id")
        assert resp.status_code == 401

    def test_video_metadata_requires_no_auth(self, client: TestClient, test_db: Session):
        with patch("app.routes.videos.youtube_service") as mock_yt:
            mock_yt.get_video_metadata.return_value = {
                "video_id": "abc12345678",
                "title": "Test",
                "description": "desc",
                "duration": 100,
                "channel": "Ch",
                "upload_date": "2024-01-01T00:00:00",
                "view_count": 1000,
                "thumbnail_url": "https://example.com/thumb.jpg",
            }
            resp = client.post("/api/videos/metadata", json={
                "url": "https://www.youtube.com/watch?v=abc12345678",
            })
            assert resp.status_code == 200


# ===========================================================================
# Diagnostics Endpoint Access
# ===========================================================================

class TestDiagnosticsAccessControl:
    """Diagnostics endpoint should require authentication."""

    def test_diagnostics_requires_auth(self):
        client = TestClient(app)
        resp = client.get("/api/diagnostics/ollama")
        assert resp.status_code == 401


# ===========================================================================
# Token Refresh — No Blacklist
# ===========================================================================

class TestTokenRefreshNoBlacklist:
    """Document that tokens are not invalidated after logout."""

    def test_token_valid_after_logout(self, client: TestClient, test_db: Session, test_user, auth_headers):
        # Logout
        resp = client.post("/api/auth/logout", headers=auth_headers)
        assert resp.status_code == 204

        # Token still works (no blacklist)
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200

    def test_access_token_rejected_at_refresh(self, client: TestClient, test_db: Session, test_user, auth_headers):
        """Access tokens must be rejected at /auth/refresh — only refresh tokens accepted."""
        resp = client.post("/api/auth/refresh", headers=auth_headers)
        assert resp.status_code == 401
