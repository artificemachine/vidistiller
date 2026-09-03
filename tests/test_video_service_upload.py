"""Unit tests for VideoService's upload:// (local file) branches."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.exceptions import VideoProcessingException
from app.services.source_resolver import build_upload_url
from app.services.video import VideoService


@pytest.fixture()
def service():
    with patch("app.services.video.VideoService._init_cache", return_value=None):
        return VideoService()


def test_download_video_returns_existing_upload_as_is(tmp_path, service):
    src = tmp_path / "abc.mp4"
    src.write_bytes(b"fake-video-bytes")
    url = build_upload_url(str(src), "clip.mp4")

    path, size = service.download_video(url)

    assert path == str(src)
    assert size == len(b"fake-video-bytes")


def test_download_video_missing_upload_raises(tmp_path, service):
    url = build_upload_url(str(tmp_path / "gone.mp4"), "clip.mp4")
    with pytest.raises(VideoProcessingException):
        service.download_video(url)


def test_download_audio_extracts_via_ffmpeg(tmp_path, service):
    src = tmp_path / "abc.mp4"
    src.write_bytes(b"fake-video-bytes")
    url = build_upload_url(str(src), "clip.mp4")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def fake_run(cmd, **kwargs):
        # ffmpeg's real output path is the last argument.
        dest = cmd[-1]
        with open(dest, "wb") as f:
            f.write(b"fake-mp3-bytes")
        return MagicMock(returncode=0, stderr="")

    with patch("app.services.video.subprocess.run", side_effect=fake_run) as mock_run:
        path, size = service.download_audio(url, output_path=str(out_dir))

    assert mock_run.call_args[0][0][0] == "ffmpeg"
    assert path.endswith(".mp3")
    assert size == len(b"fake-mp3-bytes")


def test_download_audio_raises_on_ffmpeg_failure(tmp_path, service):
    src = tmp_path / "abc.mp3"
    src.write_bytes(b"fake-audio-bytes")
    url = build_upload_url(str(src), "clip.mp3")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch(
        "app.services.video.subprocess.run",
        return_value=MagicMock(returncode=1, stderr="boom"),
    ):
        with pytest.raises(VideoProcessingException):
            service.download_audio(url, output_path=str(out_dir))


def test_download_audio_raises_when_ffmpeg_missing(tmp_path, service):
    src = tmp_path / "abc.mp3"
    src.write_bytes(b"fake-audio-bytes")
    url = build_upload_url(str(src), "clip.mp3")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with patch("app.services.video.subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(VideoProcessingException):
            service.download_audio(url, output_path=str(out_dir))


def test_get_video_metadata_never_calls_network(tmp_path, service):
    src = tmp_path / "abc.mp4"
    src.write_bytes(b"fake-video-bytes")
    url = build_upload_url(str(src), "My Talk.mp4")

    fake_probe = MagicMock(
        returncode=0, stdout=json.dumps({"format": {"duration": "42.5"}})
    )
    with patch("app.services.video.subprocess.run", return_value=fake_probe) as mock_run, \
         patch("app.services.video.yt_dlp.YoutubeDL") as mock_ydl:
        metadata = service.get_video_metadata(url)

    mock_ydl.assert_not_called()
    assert metadata["title"] == "My Talk.mp4"
    assert metadata["source_type"] == "upload"
    assert metadata["duration"] == 42
