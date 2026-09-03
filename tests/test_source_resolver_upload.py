"""Unit tests for VideoSourceResolver's upload:// handling."""

from app.core.source_type import SourceType
from app.services.source_resolver import VideoSourceResolver, build_upload_url


def test_build_upload_url_roundtrip():
    url = build_upload_url("/data/videos/abc/abc.mp4", "My Talk.mp4")
    assert url.startswith("upload:///data/videos/abc/abc.mp4#")
    assert VideoSourceResolver.upload_local_path(url) == "/data/videos/abc/abc.mp4"
    assert VideoSourceResolver.upload_display_name(url) == "My Talk.mp4"


def test_resolve_classifies_upload_offline():
    url = build_upload_url("/data/videos/abc/abc.mp4", "My Talk.mp4")
    source_type, source_id = VideoSourceResolver.resolve(url)
    assert source_type == SourceType.UPLOAD
    assert source_id == "abc"


def test_match_known_never_hits_network_for_upload():
    # Any garbage path should still classify as UPLOAD without raising or
    # attempting a network call — match_known is documented offline-only.
    url = build_upload_url("/nonexistent/path/x.wav", "clip.wav")
    result = VideoSourceResolver.match_known(url)
    assert result == (SourceType.UPLOAD, "x")


def test_display_name_url_encodes_special_characters():
    url = build_upload_url("/data/videos/x/x.mp4", "weird name #1 & more.mp4")
    assert VideoSourceResolver.upload_display_name(url) == "weird name #1 & more.mp4"


def test_display_name_falls_back_to_filename_without_fragment():
    # Defensive: a hand-built upload:// URL with no fragment still resolves.
    assert (
        VideoSourceResolver.upload_display_name("upload:///data/videos/x/x.mp4")
        == "x.mp4"
    )
