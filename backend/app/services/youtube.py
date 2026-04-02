"""
YouTube Service

Handles video metadata retrieval, audio extraction, and video downloading
from YouTube URLs. Provides caching and error handling for reliability.
"""

import re
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

from app.core.config import get_settings
from app.exceptions import ValidationException, VideoProcessingException
import redis

logger = logging.getLogger(__name__)


class YouTubeService:
    """Service for downloading and extracting metadata from YouTube videos."""

    # YouTube URL patterns
    YOUTUBE_URL_PATTERNS = [
        r'^https?://(www\.)?youtube\.com/watch\?v=([\w-]{11})',
        r'^https?://(www\.)?youtu\.be/([\w-]{11})',
        r'^https?://(www\.)?youtube\.com/embed/([\w-]{11})',
        r'^https?://(www\.)?youtube\.com/v/([\w-]{11})',
    ]

    def __init__(self):
        """Initialize YouTube service with optional Redis caching."""
        self.settings = get_settings()
        self.cache = self._init_cache()

    def _init_cache(self) -> Optional[redis.Redis]:
        """
        Initialize Redis cache connection.

        Returns:
            Redis client if configured, None otherwise
        """
        try:
            cache = redis.from_url(self.settings.cache.redis_url)
            cache.ping()
            logger.info("✓ Redis cache connected")
            return cache
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}. Using memory mode.")
            return None

    @staticmethod
    def extract_video_id(url: str) -> str:
        """
        Extract YouTube video ID from URL.

        Args:
            url: YouTube URL (various formats supported)

        Returns:
            Video ID string (11 characters)

        Raises:
            ValidationException: If URL is invalid
        """
        for pattern in YouTubeService.YOUTUBE_URL_PATTERNS:
            match = re.match(pattern, url)
            if match:
                return match.group(2) if match.lastindex >= 2 else match.group(1)

        raise ValidationException(
            "Invalid YouTube URL. Supported formats: "
            "youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID"
        )

    def get_video_metadata(self, url: str) -> Dict:
        """
        Get video metadata from YouTube.

        Uses yt-dlp to extract comprehensive video information.

        Args:
            url: YouTube URL

        Returns:
            Dictionary with video metadata:
            - video_id: YouTube video ID
            - title: Video title
            - description: Video description
            - duration: Duration in seconds
            - channel: Channel name
            - upload_date: Upload date (ISO format)
            - view_count: View count
            - thumbnail_url: Thumbnail image URL

        Raises:
            VideoProcessingException: If metadata extraction fails
        """
        video_id = self.extract_video_id(url)

        # Check cache first
        if self.cache:
            cached = self._get_from_cache(f"video_metadata:{video_id}")
            if cached:
                logger.info(f"Using cached metadata for {video_id}")
                return json.loads(cached)

        try:
            # Configure yt-dlp
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            # Extract and normalize metadata
            metadata = {
                "video_id": video_id,
                "title": info.get("title", "Unknown"),
                "description": info.get("description", ""),
                "duration": info.get("duration", 0),
                "channel": info.get("channel", "Unknown"),
                "upload_date": self._parse_upload_date(info.get("upload_date")),
                "view_count": info.get("view_count", 0),
                "thumbnail_url": info.get("thumbnail", ""),
                "chapters": info.get("chapters") or [],
            }

            # Cache metadata for 24 hours
            if self.cache:
                self._set_cache(
                    f"video_metadata:{video_id}",
                    json.dumps(metadata),
                    ttl=86400,  # 24 hours
                )

            logger.info(f"✓ Metadata retrieved for: {metadata['title']}")
            return metadata

        except Exception as e:
            logger.error(f"Failed to get metadata for {url}: {e}")
            raise VideoProcessingException(f"Failed to retrieve video metadata: {str(e)}")

    def download_audio(
        self,
        url: str,
        output_path: Optional[str] = None,
    ) -> Tuple[str, int]:
        """
        Download audio from YouTube video.

        Extracts audio track in MP3 format for transcription.

        Args:
            url: YouTube URL
            output_path: Optional path to save audio (defaults to temp directory)

        Returns:
            Tuple of (file_path, file_size_bytes)

        Raises:
            VideoProcessingException: If download fails
        """
        video_id = self.extract_video_id(url)

        try:
            # Create output directory if needed
            if output_path is None:
                output_path = str(Path(tempfile.gettempdir()) / "youtube-audio")
            Path(output_path).mkdir(parents=True, exist_ok=True)

            # Configure yt-dlp for audio extraction
            file_path = str(Path(output_path) / f"{video_id}.mp3")
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "outtmpl": str(Path(output_path) / "%(id)s"),
                "quiet": False,
                "no_warnings": False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Downloading audio for {video_id}...")
                ydl.download([url])

            # Verify file was created
            if not Path(file_path).exists():
                raise VideoProcessingException("Audio file was not created")

            file_size = Path(file_path).stat().st_size
            logger.info(f"✓ Audio downloaded: {file_path} ({file_size} bytes)")
            return file_path, file_size

        except Exception as e:
            logger.error(f"Failed to download audio: {e}")
            raise VideoProcessingException(f"Failed to download audio: {str(e)}")

    def download_video(
        self,
        url: str,
        output_path: Optional[str] = None,
        quality: str = "best",
    ) -> Tuple[str, int]:
        """
        Download video from YouTube.

        Downloads video file for snapshot extraction and processing.

        Args:
            url: YouTube URL
            output_path: Optional path to save video (defaults to temp directory)
            quality: Video quality ("best", "720p", "480p", etc.)

        Returns:
            Tuple of (file_path, file_size_bytes)

        Raises:
            VideoProcessingException: If download fails
        """
        video_id = self.extract_video_id(url)

        try:
            # Create output directory if needed
            if output_path is None:
                output_path = str(Path(tempfile.gettempdir()) / "youtube-video")
            Path(output_path).mkdir(parents=True, exist_ok=True)

            # Map quality names to yt-dlp format strings
            quality_map = {
                "best": "best[ext=mp4]/best",
                "720p": "best[height<=720][ext=mp4]/best",
                "480p": "best[height<=480][ext=mp4]/best",
                "360p": "best[height<=360][ext=mp4]/best",
            }

            format_string = quality_map.get(quality, "best[ext=mp4]/best")

            # Configure yt-dlp for video download
            file_path_pattern = str(Path(output_path) / "%(id)s.%(ext)s")
            ydl_opts = {
                "format": format_string,
                "outtmpl": file_path_pattern,
                "quiet": False,
                "no_warnings": False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Downloading video ({quality}) for {video_id}...")
                ydl.download([url])

            # Find the downloaded file
            output_dir = Path(output_path)
            video_files = list(output_dir.glob(f"{video_id}.*"))

            if not video_files:
                raise VideoProcessingException("Video file was not created")

            file_path = str(video_files[0])
            file_size = Path(file_path).stat().st_size

            logger.info(f"✓ Video downloaded: {file_path} ({file_size} bytes)")
            return file_path, file_size

        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            raise VideoProcessingException(f"Failed to download video: {str(e)}")

    def get_captions(self, url: str, language: str = "en") -> Optional[str]:
        """
        Extract captions from YouTube video.

        Attempts to get captions in specified language as fallback
        for transcription.

        Args:
            url: YouTube URL
            language: Language code (e.g., 'en', 'es')

        Returns:
            Formatted caption text or None if unavailable

        Raises:
            VideoProcessingException: If caption extraction fails
        """
        video_id = self.extract_video_id(url)

        # Check cache first
        if self.cache:
            cached = self._get_from_cache(f"captions:{video_id}:{language}")
            if cached:
                logger.info(f"Using cached captions for {video_id}")
                return cached

        try:
            # Get available transcripts
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            # Try to get transcript in specified language
            try:
                transcript = transcript_list.find_transcript([language])
            except Exception:
                # Fallback to first available transcript
                transcript = transcript_list.find_transcript(
                    transcript_list.auto_generated_transcripts[0].language
                    if transcript_list.auto_generated_transcripts
                    else [language]
                )

            # Format as text
            formatter = TextFormatter()
            captions_text = formatter.format_transcript(transcript.fetch())

            # Cache captions for 7 days
            if self.cache:
                self._set_cache(
                    f"captions:{video_id}:{language}",
                    captions_text,
                    ttl=604800,  # 7 days
                )

            logger.info(f"✓ Captions retrieved for {video_id}")
            return captions_text

        except Exception as e:
            logger.warning(f"Failed to get captions for {video_id}: {e}")
            return None

    def get_captions_ytdlp(self, url: str, language: str = "en") -> Optional[str]:
        """
        Extract captions using yt-dlp subtitle download (fallback for youtube-transcript-api).

        Uses yt-dlp with skip_download to fetch subtitles without downloading video.
        Parses VTT/SRT into timestamped plain text matching the format used elsewhere.

        Args:
            url: YouTube URL
            language: Language code (e.g., 'en', 'es')

        Returns:
            Formatted caption text or None if unavailable
        """
        video_id = self.extract_video_id(url)

        # Check cache first
        if self.cache:
            cached = self._get_from_cache(f"captions_ytdlp:{video_id}:{language}")
            if cached:
                logger.info(f"Using cached yt-dlp captions for {video_id}")
                return cached

        sub_dir = Path(tempfile.gettempdir()) / "youtube-subs"
        sub_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(sub_dir / "%(id)s")

        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [language, f"{language}.*"],
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Fetching subtitles via yt-dlp for {video_id}...")
                ydl.download([url])

            # Find the downloaded subtitle file
            sub_file = None
            for ext in ("vtt", "srt"):
                candidates = list(sub_dir.glob(f"{video_id}*.{ext}"))
                if candidates:
                    sub_file = candidates[0]
                    break

            if not sub_file or not sub_file.exists():
                logger.warning(f"yt-dlp did not produce a subtitle file for {video_id}")
                return None

            raw = sub_file.read_text(encoding="utf-8")
            lines = self._parse_vtt_to_lines(raw)

            if not lines:
                logger.warning(f"yt-dlp subtitle file was empty for {video_id}")
                return None

            captions = "\n".join(lines)

            # Cache for 7 days
            if self.cache:
                self._set_cache(f"captions_ytdlp:{video_id}:{language}", captions, ttl=604800)

            logger.info(f"✓ yt-dlp captions retrieved for {video_id} ({len(captions)} chars)")
            return captions

        except Exception as e:
            logger.warning(f"yt-dlp caption extraction failed for {video_id}: {e}")
            return None
        finally:
            # Clean up subtitle files
            for f in sub_dir.glob(f"{video_id}*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    @staticmethod
    def _parse_vtt_to_lines(raw: str) -> list[str]:
        """Parse VTT/SRT content into '[HH:MM:SS] text' lines, deduplicating."""
        lines: list[str] = []
        seen_texts: set[str] = set()
        ts_pattern = re.compile(
            r"(\d{1,2}):(\d{2}):(\d{2})[.,]\d+\s*-->"
        )

        current_ts = None
        for line in raw.splitlines():
            line = line.strip()
            # Skip VTT header, NOTE blocks, and style blocks
            if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE"):
                continue
            # Skip cue identifiers (pure numbers or containing -->)
            if line.isdigit():
                continue

            ts_match = ts_pattern.match(line)
            if ts_match:
                h, m, s = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                current_ts = f"[{h:02d}:{m:02d}:{s:02d}]"
                continue

            # Strip VTT tags like <c>, </c>, <00:00:01.234>
            text = re.sub(r"<[^>]+>", "", line).strip()
            if not text or text in seen_texts:
                continue

            seen_texts.add(text)
            if current_ts:
                lines.append(f"{current_ts} {text}")
            else:
                lines.append(text)

        return lines

    # ===========================================================================
    # HELPER METHODS
    # ===========================================================================

    def _parse_upload_date(self, date_str: Optional[str]) -> Optional[str]:
        """Parse YouTube date format (YYYYMMDD) to ISO format."""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            return dt.isoformat()
        except Exception:
            return None

    def _get_from_cache(self, key: str) -> Optional[str]:
        """Get value from Redis cache."""
        if not self.cache:
            return None
        try:
            return self.cache.get(key).decode() if self.cache.get(key) else None
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
            return None

    def _set_cache(self, key: str, value: str, ttl: int = 3600) -> None:
        """Set value in Redis cache with TTL."""
        if not self.cache:
            return
        try:
            self.cache.setex(key, ttl, value)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
