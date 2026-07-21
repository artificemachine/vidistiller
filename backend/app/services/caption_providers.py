"""
Caption Providers

Pluggable caption/subtitle fetchers with a common interface.
Fallback chain: platform-native → yt-dlp subtitles → (caller falls back to Whisper)
"""

import logging
import re
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp

logger = logging.getLogger(__name__)


class CaptionProvider(ABC):
    @abstractmethod
    def fetch(self, url: str, source_id: str, language: str = "en") -> Tuple[Optional[str], str]:
        """
        Fetch caption text for a video.

        Returns (text, detected_language). text is None when unavailable.
        detected_language defaults to the requested language on failure.
        """
        ...


class YouTubeCaptionProvider(CaptionProvider):
    """Native YouTube captions via youtube-transcript-api. YouTube only."""

    def fetch(self, url: str, source_id: str, language: str = "en") -> Tuple[Optional[str], str]:
        def _fmt(seconds: float) -> str:
            h, rem = divmod(int(seconds), 3600)
            m, s = divmod(rem, 60)
            return f"[{h:02d}:{m:02d}:{s:02d}]"

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(source_id)

            # Selection priority:
            #   1. the requested language, manual or auto-generated;
            #   2. any manually-created track;
            #   3. whatever the list yields first.
            # Step 1 is what stops an auto-dubbed video (which exposes a manual
            # caption track per dub language) from returning a dub — e.g.
            # Arabic — in place of the requested original language.
            try:
                obj = transcript_list.find_transcript([language])
            except Exception:
                try:
                    obj = transcript_list.find_manually_created_transcript(
                        [t.language_code for t in transcript_list]
                    )
                except Exception:
                    obj = next(iter(transcript_list))

            detected = obj.language_code
            lines = [f"{_fmt(s.start)} {s.text.replace(chr(10), ' ')}" for s in obj.fetch()]
            text = "\n".join(lines)

            if text.strip():
                logger.info(f"YouTube captions retrieved ({len(text)} chars, lang={detected})")
                return text, detected

        except Exception as e:
            logger.warning(f"YouTubeCaptionProvider failed for {source_id}: {e}")

        return None, language


class YtdlpCaptionProvider(CaptionProvider):
    """
    Subtitle download via yt-dlp.
    Works for Vimeo, Twitch, Twitter/X, TikTok, and others.
    """

    def fetch(self, url: str, source_id: str, language: str = "en") -> Tuple[Optional[str], str]:
        sub_dir = Path(tempfile.gettempdir()) / "video-subs"
        sub_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [language, f"{language}.*"],
            "subtitlesformat": "vtt",
            "outtmpl": str(sub_dir / "%(id)s"),
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            sub_file = None
            for ext in ("vtt", "srt"):
                candidates = list(sub_dir.glob(f"{source_id}*.{ext}"))
                if candidates:
                    sub_file = candidates[0]
                    break

            if not sub_file or not sub_file.exists():
                logger.debug(f"YtdlpCaptionProvider: no subtitle file for {source_id}")
                return None, language

            raw = sub_file.read_text(encoding="utf-8")
            lines = _parse_vtt(raw)

            if not lines:
                return None, language

            text = "\n".join(lines)
            logger.info(f"yt-dlp captions retrieved ({len(text)} chars)")
            return text, language

        except Exception as e:
            logger.warning(f"YtdlpCaptionProvider failed: {e}")
            return None, language

        finally:
            for f in sub_dir.glob(f"{source_id}*"):
                try:
                    f.unlink()
                except OSError:
                    pass


def _parse_vtt(raw: str) -> list[str]:
    """Parse VTT/SRT into '[HH:MM:SS] text' lines, deduplicating adjacent repeats."""
    lines: list[str] = []
    seen: set[str] = set()
    ts_re = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,]\d+\s*-->")
    current_ts: Optional[str] = None

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        if line.isdigit():
            continue

        m = ts_re.match(line)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
            current_ts = f"[{h:02d}:{mi:02d}:{s:02d}]"
            continue

        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or text in seen:
            continue

        seen.add(text)
        lines.append(f"{current_ts} {text}" if current_ts else text)

    return lines
