"""Integration tests for video API routes."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.exceptions import ValidationException, VideoProcessingException


# ===========================================================================
# Get Video Metadata — POST /api/videos/metadata
# ===========================================================================

class TestVideoEndpointsRequireAuth:
    """The metadata/captions/check endpoints trigger outbound fetches, so they
    must not be callable unauthenticated (they used to be)."""

    @pytest.mark.parametrize("path", ["metadata", "captions", "check"])
    def test_requires_auth(self, path, client: TestClient, test_db: Session):
        resp = client.post(f"/api/videos/{path}", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp.status_code == 401


class TestGetVideoMetadataEndpoint:
    @patch("app.routes.videos.youtube_service")
    def test_valid_url(self, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        mock_yt.get_video_metadata.return_value = {
            "video_id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "description": "Official music video",
            "duration": 212,
            "channel": "Rick Astley",
            "upload_date": "2009-10-25T00:00:00",
            "view_count": 1000000000,
            "thumbnail_url": "https://example.com/thumb.jpg",
        }
        resp = client.post("/api/videos/metadata", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["title"] == "Never Gonna Give You Up"

    def test_invalid_url_422(self, client: TestClient, test_db: Session, auth_headers: dict):
        resp = client.post("/api/videos/metadata", json={"url": ""}, headers=auth_headers)
        assert resp.status_code == 422

    @patch("app.routes.videos.youtube_service")
    def test_ytdlp_failure(self, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        mock_yt.get_video_metadata.side_effect = Exception("Network error")
        resp = client.post("/api/videos/metadata", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        # ValidationException wraps the error -> 422
        assert resp.status_code == 422


# ===========================================================================
# Get Captions — POST /api/videos/captions
# ===========================================================================

class TestGetCaptionsEndpoint:
    @patch("app.routes.videos.youtube_service")
    @patch("app.routes.videos.YouTubeService")
    def test_valid_captions(self, MockYTClass, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_yt.get_captions.return_value = "Hello world caption text"

        resp = client.post("/api/videos/captions", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert "Hello world" in data["captions"]

    @patch("app.routes.videos.youtube_service")
    @patch("app.routes.videos.YouTubeService")
    def test_no_captions_422(self, MockYTClass, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_yt.get_captions.return_value = None

        resp = client.post("/api/videos/captions", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 422


# ===========================================================================
# List Caption Tracks — POST /api/videos/caption-tracks
# ===========================================================================

class TestCaptionTracksEndpoint:
    URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_requires_auth(self, client: TestClient, test_db: Session):
        resp = client.post("/api/videos/caption-tracks", json={"url": self.URL})
        assert resp.status_code == 401

    @patch("app.routes.videos.list_youtube_caption_tracks")
    @patch("app.routes.videos.YouTubeService")
    def test_lists_available_tracks(
        self, MockYTClass, mock_list, client: TestClient, test_db: Session, auth_headers: dict
    ):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_list.return_value = [
            {"language_code": "ar", "language_name": "Arabic", "is_generated": False},
            {"language_code": "en", "language_name": "English (auto-generated)", "is_generated": True},
        ]
        resp = client.post("/api/videos/caption-tracks", json={"url": self.URL}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "dQw4w9WgXcQ"
        codes = [t["language_code"] for t in data["tracks"]]
        assert codes == ["ar", "en"]

    @patch("app.routes.videos.list_youtube_caption_tracks")
    @patch("app.routes.videos.YouTubeService")
    def test_empty_when_no_tracks(
        self, MockYTClass, mock_list, client: TestClient, test_db: Session, auth_headers: dict
    ):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_list.return_value = []
        resp = client.post("/api/videos/caption-tracks", json={"url": self.URL}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["tracks"] == []

    def test_invalid_url_422(self, client: TestClient, test_db: Session, auth_headers: dict):
        resp = client.post("/api/videos/caption-tracks", json={"url": ""}, headers=auth_headers)
        assert resp.status_code == 422


# ===========================================================================
# Check Video Availability — POST /api/videos/check
# ===========================================================================

class TestCheckVideoAvailability:
    @patch("app.routes.videos.youtube_service")
    @patch("app.routes.videos.YouTubeService")
    def test_accessible_true(self, MockYTClass, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_yt.get_video_metadata.return_value = {"title": "Test"}

        resp = client.post("/api/videos/check", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["available"] is True

    @patch("app.routes.videos.youtube_service")
    @patch("app.routes.videos.YouTubeService")
    def test_failed_false(self, MockYTClass, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        MockYTClass.extract_video_id.return_value = "dQw4w9WgXcQ"
        mock_yt.get_video_metadata.side_effect = Exception("Not found")

        resp = client.post("/api/videos/check", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["available"] is False


# ===========================================================================
# Input Validation
# ===========================================================================

class TestVideoRoutesInputValidation:
    def test_empty_url_rejected(self, client: TestClient, test_db: Session, auth_headers: dict):
        resp = client.post("/api/videos/metadata", json={"url": ""}, headers=auth_headers)
        assert resp.status_code == 422

    @patch("app.routes.videos.youtube_service")
    def test_unsupported_url_rejected(self, mock_yt, client: TestClient, test_db: Session, auth_headers: dict):
        mock_yt.get_video_metadata.side_effect = ValidationException("Unsupported URL")
        resp = client.post("/api/videos/metadata", json={
            "url": "https://example.com/not-supported",
        }, headers=auth_headers)
        assert resp.status_code == 422
