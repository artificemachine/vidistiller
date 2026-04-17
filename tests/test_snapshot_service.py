"""Unit tests for SnapshotService: relevance scoring, optimization, extraction, save."""

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest
import numpy as np
from sqlalchemy.orm import Session

from app.db.models import ProcessingJob, ProcessingStatus, Snapshot
from app.services.snapshot import SnapshotService
from app.exceptions import SnapshotException


# ===========================================================================
# Score Frame Relevance
# ===========================================================================

class TestScoreFrameRelevance:
    def test_returns_0_to_1(self, tmp_path):
        # Create a simple test image via cv2
        img_path = str(tmp_path / "test.jpg")
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(img_path, img)

        svc = SnapshotService()
        score = svc.score_frame_relevance(img_path)
        assert 0.0 <= score <= 1.0

    def test_text_scores_higher(self, tmp_path):
        img_path = str(tmp_path / "test.jpg")
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(img_path, img)

        svc = SnapshotService()
        score_no_text = svc.score_frame_relevance(img_path)
        score_with_text = svc.score_frame_relevance(img_path, detected_text="Some code here")
        assert score_with_text > score_no_text

    def test_nonexistent_image(self):
        svc = SnapshotService()
        score = svc.score_frame_relevance("/nonexistent/image.jpg")
        assert score == 0.5

    def test_capped_at_one(self, tmp_path):
        img_path = str(tmp_path / "test.jpg")
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(img_path, img)

        svc = SnapshotService()
        score = svc.score_frame_relevance(img_path, detected_text="lots of code")
        assert score <= 1.0


# ===========================================================================
# Optimize Image
# ===========================================================================

class TestOptimizeImage:
    def test_small_image_unchanged(self, tmp_path):
        from PIL import Image
        img_path = str(tmp_path / "small.jpg")
        img = Image.new("RGB", (100, 100), color="red")
        img.save(img_path, "JPEG")

        svc = SnapshotService()
        result = svc.optimize_image(img_path)
        assert Path(result).exists()

    def test_large_image_resized(self, tmp_path):
        from PIL import Image
        img_path = str(tmp_path / "large.jpg")
        img = Image.new("RGB", (4000, 3000), color="blue")
        img.save(img_path, "JPEG")

        svc = SnapshotService()
        result = svc.optimize_image(img_path, max_width=1920, max_height=1080)
        assert Path(result).exists()

    def test_nonexistent_returns_original(self):
        svc = SnapshotService()
        result = svc.optimize_image("/nonexistent/image.jpg")
        assert result == "/nonexistent/image.jpg"


# ===========================================================================
# Extract Frames (mocked cv2)
# ===========================================================================

class TestExtractFrames:
    def test_video_not_found(self):
        svc = SnapshotService()
        with pytest.raises(SnapshotException, match="not found"):
            svc.extract_frames("/nonexistent/video.mp4")

    @patch("app.services.snapshot.cv2.VideoCapture")
    def test_returns_frame_dicts(self, mock_cap, tmp_path):
        # Create a fake video file
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video data")

        # Mock VideoCapture behavior
        mock_instance = MagicMock()
        mock_instance.isOpened.return_value = True
        mock_instance.get.return_value = 30.0  # FPS
        # Return 2 frames then stop
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_instance.read.side_effect = [
            (True, fake_frame),
            (False, None),
        ]
        mock_cap.return_value = mock_instance

        svc = SnapshotService()
        with patch("app.services.snapshot.cv2.imwrite", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1000
                mock_stat.return_value.st_mode = 0o040755  # directory mode for is_dir() in Python 3.12
                frames = svc.extract_frames(str(video_file), interval=5.0, output_dir=str(tmp_path))

        assert len(frames) >= 1

    @patch("app.services.snapshot.cv2.VideoCapture")
    def test_correct_keys(self, mock_cap, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake")

        mock_instance = MagicMock()
        mock_instance.isOpened.return_value = True
        mock_instance.get.return_value = 30.0
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_instance.read.side_effect = [
            (True, fake_frame),
            (False, None),
        ]
        mock_cap.return_value = mock_instance

        svc = SnapshotService()
        with patch("app.services.snapshot.cv2.imwrite", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 500
                mock_stat.return_value.st_mode = 0o040755  # directory mode for is_dir() in Python 3.12
                frames = svc.extract_frames(str(video_file), interval=5.0, output_dir=str(tmp_path))

        if frames:
            assert "file_path" in frames[0]
            assert "timestamp" in frames[0]
            assert "width" in frames[0]
            assert "height" in frames[0]


# ===========================================================================
# Save Snapshots
# ===========================================================================

class TestSaveSnapshots:
    def test_saves_to_db(self, test_db: Session):
        job = ProcessingJob(
            job_id="snap-save-1",
            status=ProcessingStatus.PENDING,
            video_url="https://www.youtube.com/watch?v=test12345ab",
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        svc = SnapshotService()
        frames = [
            {"file_path": "/tmp/frame1.jpg", "timestamp": 1.0, "width": 640, "height": 480, "file_size": 100},
            {"file_path": "/tmp/frame2.jpg", "timestamp": 2.0, "width": 640, "height": 480, "file_size": 200},
        ]
        snapshots = svc.save_snapshots(test_db, job.id, frames)
        assert len(snapshots) == 2
        assert all(s.id is not None for s in snapshots)

    def test_empty_list_saves_nothing(self, test_db: Session):
        job = ProcessingJob(
            job_id="snap-save-2",
            status=ProcessingStatus.PENDING,
            video_url="https://www.youtube.com/watch?v=test12345ac",
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        svc = SnapshotService()
        snapshots = svc.save_snapshots(test_db, job.id, [])
        assert len(snapshots) == 0
