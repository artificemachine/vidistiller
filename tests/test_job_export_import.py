"""Tests for job export/import endpoints."""

import base64
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.db.models import (
    ProcessingJob, ProcessingStatus, Video, Transcript,
    TranscriptSegment, Snapshot, Document, JobLog, LogLevel, User,
)
from app.main import app
from app.services.auth import AuthService
from app.core.rate_limit import auth_rate_limit, strict_auth_rate_limit, job_submit_rate_limit
from app.routes.jobs import verify_import_task_ownership


# ---------------------------------------------------------------------------
# Test database fixture (in-memory SQLite with shared connection)
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_db():
    """Create a fresh in-memory SQLite DB for each test.

    Uses StaticPool so every session shares the same underlying connection,
    which means the tables created here are visible to the FastAPI routes.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    session = TestSession()

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield session
    session.close()
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(test_db):
    app.dependency_overrides[auth_rate_limit] = lambda: None
    app.dependency_overrides[strict_auth_rate_limit] = lambda: None
    app.dependency_overrides[job_submit_rate_limit] = lambda: None
    app.dependency_overrides[verify_import_task_ownership] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(auth_rate_limit, None)
    app.dependency_overrides.pop(strict_auth_rate_limit, None)
    app.dependency_overrides.pop(job_submit_rate_limit, None)
    app.dependency_overrides.pop(verify_import_task_ownership, None)


@pytest.fixture()
def test_user(test_db) -> User:
    """Seed a User row for auth."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=AuthService.hash_password("TestPass123"),
        full_name="Test User",
        is_active=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture()
def auth_headers(client, test_user) -> dict:
    """Login and return Authorization headers."""
    resp = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "TestPass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helper: seed a complete job with all child records
# ---------------------------------------------------------------------------

def _seed_job(db: Session, *, with_snapshot_file: bool = True, user_id: int = None) -> ProcessingJob:
    job = ProcessingJob(
        job_id="aaaa-bbbb-cccc",
        status=ProcessingStatus.COMPLETED,
        youtube_url="https://www.youtube.com/watch?v=test12345",
        user_id=user_id,
    )
    db.add(job)
    db.flush()

    db.add(Video(
        job_id=job.id,
        url="https://www.youtube.com/watch?v=test12345",
        video_id="test12345ab",
        title="Test Tutorial",
        description="A test video",
        duration=600,
        channel_name="TestChannel",
    ))

    transcript = Transcript(
        job_id=job.id,
        full_text="[00:00:00] Hello world",
        language="en",
        source="youtube_captions",
    )
    db.add(transcript)
    db.flush()

    db.add(TranscriptSegment(
        transcript_id=transcript.id,
        text="Hello world",
        start_time=0.0,
        end_time=3.0,
        sequence=0,
    ))

    snap_path = "/nonexistent/path/snap.jpg"
    if with_snapshot_file:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(b"\xff\xd8\xff\xe0FAKE_JPEG_DATA")
        tmp.close()
        snap_path = tmp.name

    db.add(Snapshot(
        job_id=job.id,
        file_path=snap_path,
        timestamp=5.0,
        relevance_score=0.8,
        image_width=1920,
        image_height=1080,
        file_size=1234,
    ))

    db.add(Document(
        job_id=job.id,
        title="Test Tutorial",
        content="# Summary\nHello world",
        format="summary",
    ))

    db.add(JobLog(
        job_id=job.id,
        level=LogLevel.INFO,
        message="Job completed",
        step="complete",
    ))

    db.commit()
    db.refresh(job)
    return job


# ===========================================================================
# EXPORT TESTS
# ===========================================================================

class TestExportJob:
    def test_export_returns_json_with_all_sections(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        job = _seed_job(test_db, user_id=test_user.id)
        resp = client.get(f"/api/jobs/{job.job_id}/export", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()

        assert data["export_version"] == "1.0"
        assert data["job"]["job_id"] == job.job_id
        assert data["job"]["youtube_url"] == job.youtube_url
        assert len(data["videos"]) == 1
        assert len(data["transcripts"]) == 1
        assert len(data["snapshots"]) == 1
        assert len(data["documents"]) == 1
        assert len(data["logs"]) == 1

    def test_export_includes_transcript_segments(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        _seed_job(test_db, user_id=test_user.id)
        data = client.get("/api/jobs/aaaa-bbbb-cccc/export", headers=auth_headers).json()

        segments = data["transcripts"][0]["segments"]
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["start_time"] == 0.0

    def test_export_snapshot_has_base64_when_file_exists(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        _seed_job(test_db, with_snapshot_file=True, user_id=test_user.id)
        data = client.get("/api/jobs/aaaa-bbbb-cccc/export", headers=auth_headers).json()

        snap = data["snapshots"][0]
        assert "image_base64" in snap
        decoded = base64.b64decode(snap["image_base64"])
        assert decoded.startswith(b"\xff\xd8\xff\xe0")

    def test_export_snapshot_no_base64_when_file_missing(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        _seed_job(test_db, with_snapshot_file=False, user_id=test_user.id)
        data = client.get("/api/jobs/aaaa-bbbb-cccc/export", headers=auth_headers).json()

        snap = data["snapshots"][0]
        assert "image_base64" not in snap

    def test_export_has_content_disposition_header(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        _seed_job(test_db, user_id=test_user.id)
        resp = client.get("/api/jobs/aaaa-bbbb-cccc/export", headers=auth_headers)

        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "Test Tutorial" in cd

    def test_export_404_for_unknown_job(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        resp = client.get("/api/jobs/nonexistent/export", headers=auth_headers)
        assert resp.status_code == 404

    def test_export_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.get("/api/jobs/aaaa-bbbb-cccc/export")
        assert resp.status_code == 401


# ===========================================================================
# IMPORT TESTS
# ===========================================================================

def _make_export_payload(**overrides) -> dict:
    """Build a minimal valid export payload."""
    payload = {
        "export_version": "1.0",
        "job": {
            "job_id": "old-uuid",
            "status": "completed",
            "youtube_url": "https://www.youtube.com/watch?v=importtest1",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
        "videos": [{
            "url": "https://www.youtube.com/watch?v=importtest1",
            "video_id": "importtest1",
            "title": "Imported Tutorial",
            "description": "desc",
            "duration": 300,
        }],
        "transcripts": [{
            "full_text": "[00:00:00] Imported text",
            "language": "en",
            "segments": [{
                "text": "Imported text",
                "start_time": 0.0,
                "end_time": 2.0,
                "sequence": 0,
            }],
        }],
        "snapshots": [{
            "file_path": "/old/path/snapshot_5.0s.jpg",
            "timestamp": 5.0,
            "image_base64": base64.b64encode(b"FAKE_IMG").decode(),
        }],
        "documents": [{
            "title": "Imported Tutorial",
            "content": "# Imported",
            "format": "summary",
        }],
        "logs": [{
            "level": "info",
            "message": "imported log",
            "step": "complete",
            "created_at": "2026-01-01T00:00:00",
        }],
    }
    payload.update(overrides)
    return payload


class TestImportJob:
    def test_import_creates_new_job(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload()
        resp = client.post("/api/jobs/import", json=payload, headers=auth_headers)

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "completed"
        assert data["job_id"] != "old-uuid"

    def test_import_recreates_all_relations(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload()
        resp = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        job_id = resp.json()["job_id"]

        detail = client.get(f"/api/jobs/{job_id}", headers=auth_headers).json()
        assert len(detail["videos"]) == 1
        assert detail["videos"][0]["title"] == "Imported Tutorial"
        assert len(detail["transcripts"]) == 1
        assert detail["transcripts"][0]["full_text"] == "[00:00:00] Imported text"
        assert len(detail["transcripts"][0]["segments"]) == 1
        assert len(detail["snapshots"]) == 1
        assert len(detail["documents"]) == 1

    def test_import_writes_snapshot_image_to_disk(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload()
        resp = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        job_id = resp.json()["job_id"]

        detail = client.get(f"/api/jobs/{job_id}", headers=auth_headers).json()
        snap_path = detail["snapshots"][0]["file_path"]
        assert Path(snap_path).exists()
        assert Path(snap_path).read_bytes() == b"FAKE_IMG"

        # Cleanup
        Path(snap_path).unlink(missing_ok=True)
        Path(snap_path).parent.rmdir()

    def test_import_rejects_bad_version(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload(export_version="99.0")
        resp = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        assert resp.status_code == 422

    def test_import_rejects_duplicate_video(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload()
        resp1 = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        assert resp1.status_code == 201

        resp2 = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        assert resp2.status_code == 422
        assert "already exists" in resp2.json()["message"]

    def test_import_without_snapshots(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        payload = _make_export_payload(snapshots=[])
        resp = client.post("/api/jobs/import", json=payload, headers=auth_headers)
        assert resp.status_code == 201

    def test_import_requires_auth(self, client: TestClient, test_db: Session):
        payload = _make_export_payload()
        resp = client.post("/api/jobs/import", json=payload)
        assert resp.status_code == 401


class TestImportJobUpload:
    def test_import_upload_queues_task(
        self,
        client: TestClient,
        test_db: Session,
        test_user: User,
        auth_headers: dict,
        monkeypatch,
    ):
        from app.routes import jobs as jobs_routes

        monkeypatch.setattr(
            jobs_routes.import_job_payload_file_task,
            "delay",
            lambda file_path, user_id: SimpleNamespace(id="task-123"),
        )

        resp = client.post(
            "/api/jobs/import-upload?filename=job-export.json",
            headers=auth_headers,
            data=b'{"export_version":"1.0","job":{}}',
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["task_id"] == "task-123"
        assert body["message"] == "Import queued"

    def test_import_upload_status_success(
        self,
        client: TestClient,
        test_db: Session,
        test_user: User,
        auth_headers: dict,
        monkeypatch,
    ):
        from app.routes import jobs as jobs_routes

        monkeypatch.setattr(
            jobs_routes.celery_app,
            "AsyncResult",
            lambda task_id: SimpleNamespace(status="SUCCESS", result={"job_id": "new-job-id"}),
        )

        resp = client.get("/api/jobs/import-upload/task-xyz", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "SUCCESS"
        assert body["result"]["job_id"] == "new-job-id"


# ===========================================================================
# ROUND-TRIP TEST
# ===========================================================================

class TestExportImportRoundTrip:
    def test_export_then_import_preserves_data(self, client: TestClient, test_db: Session, test_user: User, auth_headers: dict):
        original = _seed_job(test_db, user_id=test_user.id)
        export_resp = client.get(f"/api/jobs/{original.job_id}/export", headers=auth_headers)
        export_data = export_resp.json()

        # Delete original video to avoid unique constraint on re-import
        test_db.query(Video).filter(Video.job_id == original.id).delete()
        test_db.commit()

        import_resp = client.post("/api/jobs/import", json=export_data, headers=auth_headers)
        assert import_resp.status_code == 201
        new_job_id = import_resp.json()["job_id"]

        detail = client.get(f"/api/jobs/{new_job_id}", headers=auth_headers).json()
        assert detail["status"] == "completed"
        assert len(detail["videos"]) == len(export_data["videos"])
        assert len(detail["transcripts"]) == len(export_data["transcripts"])
        assert len(detail["snapshots"]) == len(export_data["snapshots"])
        assert len(detail["documents"]) == len(export_data["documents"])
        assert detail["videos"][0]["title"] == export_data["videos"][0]["title"]
        assert detail["transcripts"][0]["full_text"] == export_data["transcripts"][0]["full_text"]
