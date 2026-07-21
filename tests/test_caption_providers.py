"""Tests for caption track selection.

The regression these guard against: an auto-dubbed YouTube video exposes a
manually-created caption track per dub language (Arabic, Bangla, ...) plus the
original as an auto-generated track. The provider used to hand every language
code to find_manually_created_transcript and take the first match, so it
returned a dub — e.g. Arabic — instead of the requested/original language.
"""

import sys
import types

import pytest

from app.services.caption_providers import YouTubeCaptionProvider


class _Snippet:
    def __init__(self, start, text):
        self.start = start
        self.text = text


class _FakeTranscript:
    def __init__(self, language_code, is_generated, snippets):
        self.language_code = language_code
        self.is_generated = is_generated
        self._snippets = snippets

    def fetch(self):
        return self._snippets


class _FakeTranscriptList:
    """Mimics youtube_transcript_api.TranscriptList selection semantics."""

    def __init__(self, transcripts):
        # order matters: the first manually-created track is what the old code
        # would have returned.
        self._transcripts = transcripts

    def __iter__(self):
        return iter(self._transcripts)

    def _find(self, language_codes, *, manual=None):
        for code in language_codes:
            for t in self._transcripts:
                if t.language_code != code:
                    continue
                if manual is True and t.is_generated:
                    continue
                if manual is False and not t.is_generated:
                    continue
                return t
        raise Exception("NoTranscriptFound")

    def find_transcript(self, language_codes):
        # real API prefers a manual track, then a generated one, per code.
        for code in language_codes:
            try:
                return self._find([code], manual=True)
            except Exception:
                pass
            try:
                return self._find([code], manual=False)
            except Exception:
                pass
        raise Exception("NoTranscriptFound")

    def find_manually_created_transcript(self, language_codes):
        return self._find(language_codes, manual=True)

    def find_generated_transcript(self, language_codes):
        return self._find(language_codes, manual=False)


def _install_fake_api(monkeypatch, transcript_list):
    """Install a fake youtube_transcript_api module the provider imports."""
    fake_mod = types.ModuleType("youtube_transcript_api")

    class _FakeApi:
        def list(self, source_id):
            return transcript_list

    fake_mod.YouTubeTranscriptApi = _FakeApi
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)


@pytest.fixture
def autodubbed_tracks():
    """Arabic dub as a manual track, English original as auto-generated.

    This is the exact shape that produced the Arabic transcript in prod.
    """
    return _FakeTranscriptList([
        _FakeTranscript("ar", is_generated=False, snippets=[_Snippet(0.0, "نص عربي")]),
        _FakeTranscript("en", is_generated=True, snippets=[_Snippet(0.0, "english text")]),
    ])


class TestYouTubeCaptionLanguageSelection:
    def test_prefers_requested_language_over_first_manual_track(
        self, monkeypatch, autodubbed_tracks
    ):
        _install_fake_api(monkeypatch, autodubbed_tracks)
        text, lang = YouTubeCaptionProvider().fetch(
            "https://youtu.be/x", "x", language="en"
        )
        assert lang == "en", "must pick the requested language, not the first dub"
        assert "english text" in text

    def test_honours_a_non_default_requested_language(
        self, monkeypatch, autodubbed_tracks
    ):
        _install_fake_api(monkeypatch, autodubbed_tracks)
        text, lang = YouTubeCaptionProvider().fetch(
            "https://youtu.be/x", "x", language="ar"
        )
        assert lang == "ar"
        assert "نص عربي" in text

    def test_falls_back_when_requested_language_absent(self, monkeypatch):
        tracks = _FakeTranscriptList([
            _FakeTranscript("ar", is_generated=False, snippets=[_Snippet(0.0, "نص")]),
        ])
        _install_fake_api(monkeypatch, tracks)
        text, lang = YouTubeCaptionProvider().fetch(
            "https://youtu.be/x", "x", language="en"
        )
        # only Arabic exists; returning it beats returning nothing.
        assert lang == "ar"
        assert text
