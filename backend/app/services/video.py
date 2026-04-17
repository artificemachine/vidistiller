"""
Video Service

Generic video metadata retrieval, audio extraction, and download.
Supports any platform yt-dlp handles: YouTube, Vimeo, Twitch, Twitter/X, TikTok, etc.
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import yt_dlp

from app.core.config import get_settings
from app.core.source_type import SourceType
from app.exceptions import VideoProcessingException
from app.services.source_resolver import VideoSourceResolver

try:
    import redis as _redis
except ImportError:
    _redis = None  # type: ignore

logger = logging.getLogger(__name__)


class VideoService:
    """Generic video service backed by yt-dlp. No platform-specific guards."""

    def __init__(self):
        self.settings = get_settings()
        self.cache = self._init_cache()

    def _init_cache(self):
        if _redis is None:
            return None
        try:
            cache = _redis.from_url(self.settings.cache.redis_url)
            cache.ping()
            return cache
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}")
            return None

    def resolve(self, url: str) -> Tuple[SourceType, str]:
        return VideoSourceResolver.resolve(url)

    def get_video_metadata(self, url: str) -> Dict:
        """
        Extract metadata from any supported video URL.

        Returns a dict with: video_id, source_type, title, description,
        duration, channel, upload_date, view_count, thumbnail_url, chapters.
        """
        source_type, source_id = VideoSourceResolver.resolve(url)
        cache_key = f"video_metadata:{source_type.value}:{source_id}"

        if self.cache:
            cached = self._cache_get(cache_key)
            if cached:
                logger.info(f"Cache hit: metadata for {source_type.value}:{source_id}")
                return json.loads(cached)

        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            metadata = {
                "video_id": source_id,
                "source_type": source_type.value,
                "title": info.get("title") or "Unknown",
                "description": info.get("description") or "",
                "duration": info.get("duration") or 0,
                "channel": info.get("channel") or info.get("uploader") or "Unknown",
                "upload_date": self._parse_date(info.get("upload_date")),
                "view_count": info.get("view_count") or 0,
                "thumbnail_url": info.get("thumbnail") or "",
                "chapters": info.get("chapters") or [],
            }

            if self.cache:
                self._cache_set(cache_key, json.dumps(metadata), ttl=86400)

            logger.info(f"✓ Metadata: '{metadata['title']}' ({source_type.value})")
            return metadata

        except Exception as e:
            logger.error(f"Metadata extraction failed for {url}: {e}")
            raise VideoProcessingException(f"Failed to retrieve video metadata: {e}")

    def download_audio(self, url: str, output_path: Optional[str] = None) -> Tuple[str, int]:
        """Download audio track as MP3. Returns (file_path, file_size_bytes)."""
        source_type, source_id = VideoSourceResolver.resolve(url)

        if output_path is None:
            output_path = str(Path(tempfile.gettempdir()) / "video-audio")
        Path(output_path).mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": str(Path(output_path) / "%(id)s"),
            "quiet": False,
            "no_warnings": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Downloading audio for {source_type.value}:{source_id}...")
                ydl.download([url])

            # FFmpeg appends .mp3 to the outtmpl stem
            expected = Path(output_path) / f"{source_id}.mp3"
            if expected.exists():
                file_path = str(expected)
            else:
                candidates = list(Path(output_path).glob(f"{source_id}*"))
                if not candidates:
                    raise VideoProcessingException("Audio file was not created")
                file_path = str(candidates[0])

            file_size = Path(file_path).stat().st_size
            logger.info(f"✓ Audio downloaded: {file_path} ({file_size} bytes)")
            return file_path, file_size

        except VideoProcessingException:
            raise
        except Exception as e:
            logger.error(f"Audio download failed: {e}")
            raise VideoProcessingException(f"Failed to download audio: {e}")

    def download_video(
        self, url: str, output_path: Optional[str] = None, quality: str = "best"
    ) -> Tuple[str, int]:
        """Download video file. Returns (file_path, file_size_bytes)."""
        source_type, source_id = VideoSourceResolver.resolve(url)

        if output_path is None:
            output_path = str(Path(tempfile.gettempdir()) / "video-dl")
        Path(output_path).mkdir(parents=True, exist_ok=True)

        quality_map = {
            "best": "best[ext=mp4]/best",
            "720p": "best[height<=720][ext=mp4]/best",
            "480p": "best[height<=480][ext=mp4]/best",
            "360p": "best[height<=360][ext=mp4]/best",
        }

        ydl_opts = {
            "format": quality_map.get(quality, "best[ext=mp4]/best"),
            "outtmpl": str(Path(output_path) / "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Downloading video ({quality}) for {source_type.value}:{source_id}...")
                ydl.download([url])

            video_files = list(Path(output_path).glob(f"{source_id}.*"))
            if not video_files:
                raise VideoProcessingException("Video file was not created")

            file_path = str(video_files[0])
            file_size = Path(file_path).stat().st_size
            logger.info(f"✓ Video downloaded: {file_path} ({file_size} bytes)")
            return file_path, file_size

        except VideoProcessingException:
            raise
        except Exception as e:
            logger.error(f"Video download failed: {e}")
            raise VideoProcessingException(f"Failed to download video: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y%m%d").isoformat()
        except Exception:
            return None

    def _cache_get(self, key: str) -> Optional[str]:
        if not self.cache:
            return None
        try:
            value = self.cache.get(key)
            return value.decode() if value else None
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
            return None

    def _cache_set(self, key: str, value: str, ttl: int = 3600) -> None:
        if not self.cache:
            return
        try:
            self.cache.setex(key, ttl, value)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
