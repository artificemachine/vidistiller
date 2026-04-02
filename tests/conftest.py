"""Shared test fixtures for the backend test suite.

Provides database, client, auth, and seeded-data fixtures used by all test files.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.db.models import (
    ProcessingJob, ProcessingStatus, Video, Transcript,
    TranscriptSegment, Snapshot, Document, JobLog, LogLevel, User,
    Slide, SlideDetectionMetadata,
)
from app.main import app
from app.services.auth import AuthService
from app.core.rate_limit import auth_rate_limit, strict_auth_rate_limit, job_submit_rate_limit
from app.routes.jobs import verify_import_task_ownership


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_engine():
    """Create a fresh in-memory SQLite engine for each test."""
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
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def test_db(test_engine):
    """Session-scoped DB with dependency override for FastAPI."""
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)
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


@pytest.fixture()
def client(test_db):
    """FastAPI TestClient wired to the test database with rate limiting disabled."""
    app.dependency_overrides[auth_rate_limit] = lambda: None
    app.dependency_overrides[strict_auth_rate_limit] = lambda: None
    app.dependency_overrides[job_submit_rate_limit] = lambda: None
    app.dependency_overrides[verify_import_task_ownership] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(auth_rate_limit, None)
    app.dependency_overrides.pop(strict_auth_rate_limit, None)
    app.dependency_overrides.pop(job_submit_rate_limit, None)
    app.dependency_overrides.pop(verify_import_task_ownership, None)


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_user(test_db) -> User:
    """Seed a User row directly via AuthService.hash_password."""
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
    """Login and return Authorization headers with a valid access token."""
    resp = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "TestPass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def refresh_headers(client, test_user) -> dict:
    """Login and return Authorization headers with a valid refresh token."""
    resp = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "TestPass123",
    })
    token = resp.json()["refresh_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Seeded data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_job(test_db, test_user) -> ProcessingJob:
    """Seed a complete ProcessingJob with all child records, owned by test_user."""
    job = ProcessingJob(
        job_id="aaaa-bbbb-cccc",
        status=ProcessingStatus.COMPLETED,
        youtube_url="https://www.youtube.com/watch?v=test12345",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()

    test_db.add(Video(
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
    test_db.add(transcript)
    test_db.flush()

    test_db.add(TranscriptSegment(
        transcript_id=transcript.id,
        text="Hello world",
        start_time=0.0,
        end_time=3.0,
        sequence=0,
    ))

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.write(b"\xff\xd8\xff\xe0FAKE_JPEG_DATA")
    tmp.close()

    test_db.add(Snapshot(
        job_id=job.id,
        file_path=tmp.name,
        timestamp=5.0,
        relevance_score=0.8,
        image_width=1920,
        image_height=1080,
        file_size=1234,
    ))

    test_db.add(Document(
        job_id=job.id,
        title="Test Tutorial",
        content="# Summary\nHello world",
        format="summary",
    ))

    test_db.add(JobLog(
        job_id=job.id,
        level=LogLevel.INFO,
        message="Job completed",
        step="complete",
    ))

    test_db.commit()
    test_db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Celery mock
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_slide_job(test_db, test_user) -> ProcessingJob:
    """Seed a ProcessingJob in slide_aware mode with slides and metadata, owned by test_user."""
    job = ProcessingJob(
        job_id="slide-job-1234",
        status=ProcessingStatus.COMPLETED,
        youtube_url="https://www.youtube.com/watch?v=slide12345",
        processing_mode="slide_aware",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()

    test_db.add(Video(
        job_id=job.id,
        url="https://www.youtube.com/watch?v=slide12345",
        video_id="slide12345a",
        title="Slide Tutorial",
        description="A slide tutorial",
        duration=300,
        channel_name="TestChannel",
    ))

    transcript = Transcript(
        job_id=job.id,
        full_text="[00:00:00] Welcome to the presentation",
        language="en",
        source="youtube_captions",
    )
    test_db.add(transcript)
    test_db.flush()

    test_db.add(TranscriptSegment(
        transcript_id=transcript.id,
        text="Welcome to the presentation",
        start_time=0.0,
        end_time=10.0,
        sequence=0,
    ))

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.write(b"\xff\xd8\xff\xe0FAKE_SLIDE_DATA")
    tmp.close()

    slide1 = Slide(
        job_id=job.id,
        slide_number=1,
        start_timestamp=0.0,
        end_timestamp=60.0,
        final_frame_path=tmp.name,
        ocr_text="Title Slide",
        transcript_text="Welcome to the presentation",
        layout_type="full_frame",
        ssim_transition_score=0.0,
        is_incremental_build=False,
        image_width=1920,
        image_height=1080,
        file_size=5000,
    )
    test_db.add(slide1)
    test_db.flush()

    slide2 = Slide(
        job_id=job.id,
        slide_number=2,
        start_timestamp=60.0,
        end_timestamp=120.0,
        final_frame_path=tmp.name,
        ocr_text="Content Slide",
        transcript_text="Here is the main content",
        layout_type="full_frame",
        ssim_transition_score=0.72,
        is_incremental_build=False,
        image_width=1920,
        image_height=1080,
        file_size=6000,
    )
    test_db.add(slide2)
    test_db.flush()

    metadata = SlideDetectionMetadata(
        job_id=job.id,
        total_frames_sampled=300,
        sampling_fps=1.0,
        ssim_threshold=0.85,
        ssim_ambiguous_low=0.85,
        ssim_ambiguous_high=0.93,
        layout_type_detected="full_frame",
        total_slides=2,
        total_transitions=1,
        llm_classifications_count=0,
        ocr_enabled=True,
        processing_time_seconds=15.5,
    )
    test_db.add(metadata)

    test_db.commit()
    test_db.refresh(job)
    return job


@pytest.fixture()
def mock_celery(monkeypatch):
    """Patch process_transcript.delay, summarize_transcript_task.delay, and process_slides.delay so Celery is never invoked."""
    from unittest.mock import MagicMock
    mock_process = MagicMock()
    mock_process.return_value.id = "fake-task-id"
    monkeypatch.setattr("app.routes.jobs.process_transcript.delay", mock_process)

    mock_summarize = MagicMock()
    mock_summarize.return_value.id = "fake-summarize-task-id"
    monkeypatch.setattr("app.routes.jobs.summarize_transcript_task.delay", mock_summarize)

    # Also mock process_slides in tasks module (dispatched from process_transcript)
    mock_slides = MagicMock()
    mock_slides.return_value.id = "fake-slides-task-id"
    try:
        monkeypatch.setattr("app.tasks.process_slides.delay", mock_slides)
    except AttributeError:
        pass

    return mock_process


@pytest.fixture()
def mock_celery_control(monkeypatch):
    """Mock celery_app.control.revoke so Celery control is never invoked."""
    from unittest.mock import MagicMock
    mock_revoke = MagicMock()
    monkeypatch.setattr("app.routes.jobs.celery_app.control.revoke", mock_revoke)
    return mock_revoke
