"""Integration tests for snapshot API routes."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ProcessingJob, ProcessingStatus, Snapshot


# ===========================================================================
# Get Job Snapshots — GET /api/snapshots/job/{job_id}
# ===========================================================================

class TestGetJobSnapshots:
    def test_returns_list(self, client: TestClient, test_db: Session, seeded_job, auth_headers):
        resp = client.get(f"/api/snapshots/job/{seeded_job.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_ordered_by_timestamp(self, client: TestClient, test_db: Session, seeded_job, auth_headers):
        # Add a second snapshot with earlier timestamp
        snap = Snapshot(
            job_id=seeded_job.id,
            file_path="/tmp/early.jpg",
            timestamp=1.0,
            image_width=100,
            image_height=100,
        )
        test_db.add(snap)
        test_db.commit()

        resp = client.get(f"/api/snapshots/job/{seeded_job.id}", headers=auth_headers)
        data = resp.json()
        timestamps = [s["timestamp"] for s in data["snapshots"]]
        assert timestamps == sorted(timestamps)

    def test_empty_result(self, client: TestClient, test_db: Session, auth_headers, test_user):
        job = ProcessingJob(
            job_id="empty-snap",
            status=ProcessingStatus.PENDING,
            video_url="https://www.youtube.com/watch?v=empty1234567",
            user_id=test_user.id,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        resp = client.get(f"/api/snapshots/job/{job.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ===========================================================================
# Get Single Snapshot — GET /api/snapshots/{snapshot_id}
# ===========================================================================

class TestGetSingleSnapshot:
    def test_200(self, client: TestClient, test_db: Session, seeded_job, auth_headers):
        snap = test_db.query(Snapshot).filter(Snapshot.job_id == seeded_job.id).first()
        resp = client.get(f"/api/snapshots/{snap.id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_404(self, client: TestClient, test_db: Session, auth_headers):
        resp = client.get("/api/snapshots/99999", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# Delete Snapshot — DELETE /api/snapshots/{snapshot_id}
# ===========================================================================

class TestDeleteSnapshot:
    def test_204(self, client: TestClient, test_db: Session, seeded_job, auth_headers):
        snap = test_db.query(Snapshot).filter(Snapshot.job_id == seeded_job.id).first()
        resp = client.delete(f"/api/snapshots/{snap.id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_404(self, client: TestClient, test_db: Session, auth_headers):
        resp = client.delete("/api/snapshots/99999", headers=auth_headers)
        assert resp.status_code == 404

    def test_removed_from_db(self, client: TestClient, test_db: Session, seeded_job, auth_headers):
        snap = test_db.query(Snapshot).filter(Snapshot.job_id == seeded_job.id).first()
        snap_id = snap.id
        client.delete(f"/api/snapshots/{snap_id}", headers=auth_headers)
        # Expire session cache to see fresh state
        test_db.expire_all()
        assert test_db.query(Snapshot).filter(Snapshot.id == snap_id).first() is None


# ===========================================================================
# Capture Snapshot — POST /api/snapshots/capture
# ===========================================================================

class TestCaptureSnapshot:
    def test_job_not_found(self, client: TestClient, test_db: Session, auth_headers):
        resp = client.post("/api/snapshots/capture", json={
            "job_id": "nonexistent-uuid",
            "timestamp": 5.0,
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_no_video_url(self, client: TestClient, test_db: Session, auth_headers, test_user):
        job = ProcessingJob(
            job_id="no-url-job",
            status=ProcessingStatus.PENDING,
            user_id=test_user.id,
        )
        test_db.add(job)
        test_db.commit()

        resp = client.post("/api/snapshots/capture", json={
            "job_id": "no-url-job",
            "timestamp": 5.0,
        }, headers=auth_headers)
        assert resp.status_code == 400

    @patch("app.routes.snapshots.SnapshotService")
    @patch("app.routes.snapshots.YouTubeService", create=True)
    def test_valid_returns_snapshot(self, MockYT, MockSnap, client: TestClient, test_db: Session, auth_headers, test_user):
        import tempfile, os
        from pathlib import Path

        job = ProcessingJob(
            job_id="capture-test",
            status=ProcessingStatus.COMPLETED,
            video_url="https://www.youtube.com/watch?v=cap12345678",
            video_file_path="/tmp/fake_video.mp4",
            user_id=test_user.id,
        )
        test_db.add(job)
        test_db.commit()

        # Create fake video file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake video")
            video_path = f.name

        job.video_file_path = video_path
        test_db.commit()

        mock_svc = MagicMock()
        mock_svc.extract_frame_at_timestamp.return_value = {
            "file_path": "/tmp/snapshot.jpg",
            "timestamp": 5.0,
            "width": 1920,
            "height": 1080,
            "file_size": 50000,
        }
        MockSnap.return_value = mock_svc

        # Patch _snapshots_base() to return /tmp so relative_to() resolves correctly
        with patch("app.routes.snapshots._snapshots_base", return_value=Path("/tmp")):
            resp = client.post("/api/snapshots/capture", json={
                "job_id": "capture-test",
                "timestamp": 5.0,
            }, headers=auth_headers)

        # Cleanup
        os.unlink(video_path)

        assert resp.status_code == 200

    def test_negative_timestamp_rejected(self, client: TestClient, test_db: Session, auth_headers):
        resp = client.post("/api/snapshots/capture", json={
            "job_id": "any-job",
            "timestamp": -1.0,
        }, headers=auth_headers)
        assert resp.status_code == 422
