"""Unit tests for YouTubeService: URL extraction, VTT parsing, metadata."""

from unittest.mock import patch, MagicMock

import pytest

from app.services.youtube import YouTubeService
from app.exceptions import ValidationException, VideoProcessingException


# ===========================================================================
# Extract Video ID
# ===========================================================================

class TestExtractVideoId:
    def test_standard_url(self):
        vid = YouTubeService.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_short_url(self):
        vid = YouTubeService.extract_video_id("https://youtu.be/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_embed_url(self):
        vid = YouTubeService.extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_v_url(self):
        vid = YouTubeService.extract_video_id("https://www.youtube.com/v/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationException):
            YouTubeService.extract_video_id("https://example.com/video")

    def test_empty_string_raises(self):
        with pytest.raises(ValidationException):
            YouTubeService.extract_video_id("")

    def test_missing_id_raises(self):
        with pytest.raises(ValidationException):
            YouTubeService.extract_video_id("https://www.youtube.com/watch?v=")


# ===========================================================================
# Parse VTT to Lines
# ===========================================================================

class TestParseVttToLines:
    def test_basic_vtt(self):
        raw = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "Hello world\n\n"
            "00:00:04.000 --> 00:00:06.000\n"
            "Second line\n"
        )
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert len(lines) == 2
        assert "[00:00:01]" in lines[0]
        assert "Hello world" in lines[0]

    def test_html_tags_stripped(self):
        raw = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<c>Hello</c> <b>world</b>\n"
        )
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert "<c>" not in lines[0]
        assert "<b>" not in lines[0]
        assert "Hello world" in lines[0]

    def test_duplicates_removed(self):
        raw = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "Repeated\n\n"
            "00:00:04.000 --> 00:00:06.000\n"
            "Repeated\n"
        )
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert len(lines) == 1

    def test_note_blocks_skipped(self):
        raw = (
            "WEBVTT\n\n"
            "NOTE This is a comment\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "Actual text\n"
        )
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert len(lines) == 1
        assert "Actual text" in lines[0]

    def test_empty_vtt(self):
        raw = "WEBVTT\n\n"
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert len(lines) == 0

    def test_cue_ids_skipped(self):
        raw = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "Line one\n\n"
            "2\n"
            "00:00:04.000 --> 00:00:06.000\n"
            "Line two\n"
        )
        lines = YouTubeService._parse_vtt_to_lines(raw)
        assert len(lines) == 2
        assert all("Line" in l for l in lines)


# ===========================================================================
# Get Video Metadata (mocked)
# ===========================================================================

class TestGetVideoMetadata:
    @patch("app.services.youtube.redis")
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_normalized_metadata(self, MockYDL, mock_redis):
        mock_redis.from_url.return_value.ping.side_effect = Exception("no redis")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.extract_info.return_value = {
            "title": "My Video",
            "description": "Desc",
            "duration": 120,
            "channel": "MyChannel",
            "upload_date": "20240115",
            "view_count": 5000,
            "thumbnail": "https://example.com/thumb.jpg",
            "chapters": [],
        }
        MockYDL.return_value = mock_ctx

        svc = YouTubeService()
        meta = svc.get_video_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert meta["video_id"] == "dQw4w9WgXcQ"
        assert meta["title"] == "My Video"
        assert meta["duration"] == 120

    @patch("app.services.youtube.redis")
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_ytdlp_failure(self, MockYDL, mock_redis):
        mock_redis.from_url.return_value.ping.side_effect = Exception("no redis")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.extract_info.side_effect = Exception("Network error")
        MockYDL.return_value = mock_ctx

        svc = YouTubeService()
        with pytest.raises(VideoProcessingException):
            svc.get_video_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    @patch("app.services.youtube.redis")
    def test_cache_hit(self, mock_redis):
        import json
        cached_data = {
            "video_id": "cached123",
            "title": "Cached",
            "description": "",
            "duration": 60,
            "channel": "Ch",
            "upload_date": None,
            "view_count": 0,
            "thumbnail_url": "",
            "chapters": [],
        }
        mock_cache = MagicMock()
        mock_cache.ping.return_value = True
        mock_cache.get.return_value = json.dumps(cached_data).encode()
        mock_redis.from_url.return_value = mock_cache

        svc = YouTubeService()
        meta = svc.get_video_metadata("https://www.youtube.com/watch?v=cached12345")
        assert meta["video_id"] == "cached123"


# ===========================================================================
# Parse Upload Date
# ===========================================================================

class TestParseUploadDate:
    @patch("app.services.youtube.redis")
    def test_valid_date(self, mock_redis):
        mock_redis.from_url.return_value.ping.side_effect = Exception("no redis")
        svc = YouTubeService()
        result = svc._parse_upload_date("20240115")
        assert result == "2024-01-15T00:00:00"

    @patch("app.services.youtube.redis")
    def test_none_input(self, mock_redis):
        mock_redis.from_url.return_value.ping.side_effect = Exception("no redis")
        svc = YouTubeService()
        assert svc._parse_upload_date(None) is None
