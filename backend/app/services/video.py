"""
Video Service

Generic video metadata retrieval, audio extraction, and download.
Supports any platform yt-dlp handles: YouTube, Vimeo, Twitch, Twitter/X, TikTok, etc.
"""

import json
import logging
import os
import subprocess
import tempfile
import time
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

VIDEO_DOWNLOAD_RETRY_DELAYS = (1.0, 4.0, 10.0)


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

        if source_type == SourceType.UPLOAD:
            return self._local_metadata(url, source_id)

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

        if source_type == SourceType.UPLOAD:
            return self._extract_local_audio(url, output_path, source_id)

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
        """Download video file with fresh-extraction retries.

        YouTube CDN URLs can fail transiently with HTTP 403 while a new
        extraction succeeds moments later. Each attempt creates a fresh
        ``YoutubeDL`` instance so signed media URLs are never reused.
        Returns ``(file_path, file_size_bytes)``.
        """
        source_type, source_id = VideoSourceResolver.resolve(url)

        if source_type == SourceType.UPLOAD:
            return self._local_video_file(url)

        if output_path is None:
            output_path = str(Path(tempfile.gettempdir()) / "video-dl")
        Path(output_path).mkdir(parents=True, exist_ok=True)

        quality_map = {
            "best": "best[ext=mp4]/best",
            "720p": "best[height<=720][ext=mp4]/best",
            "480p": "best[height<=480][ext=mp4]/best",
            "360p": "best[height<=360][ext=mp4]/best",
        }

        format_selector = quality_map.get(quality, "best[ext=mp4]/best")
        ydl_opts = {
            "format": format_selector,
            "outtmpl": str(Path(output_path) / "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
        }
        if source_type == SourceType.YOUTUBE:
            provider_url = os.getenv(
                "YOUTUBE_POT_PROVIDER_URL",
                "http://tutorial_bgutil_provider:4416",
            )
            ydl_opts.update({
                "remote_components": ["ejs:github"],
                "extractor_args": {
                    "youtube": {"player_client": ["mweb"]},
                    "youtubepot-bgutilhttp": {"base_url": [provider_url]},
                },
            })

        attempt_count = len(VIDEO_DOWNLOAD_RETRY_DELAYS) + 1
        last_error: Exception | None = None
        for attempt in range(1, attempt_count + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info(
                        "Downloading video (%s) for %s:%s (attempt %d/%d)...",
                        quality,
                        source_type.value,
                        source_id,
                        attempt,
                        attempt_count,
                    )
                    ydl.download([url])

                video_files = [
                    candidate
                    for candidate in self._source_download_files(
                        Path(output_path), source_id
                    )
                    if not candidate.name.endswith((".part", ".ytdl", ".temp"))
                ]
                if not video_files:
                    raise VideoProcessingException("Video file was not created")

                file_path = str(video_files[0])
                file_size = Path(file_path).stat().st_size
                logger.info(f"✓ Video downloaded: {file_path} ({file_size} bytes)")
                return file_path, file_size
            except Exception as exc:
                last_error = exc
                if attempt >= attempt_count:
                    break
                self._cleanup_partial_video_downloads(Path(output_path), source_id)
                delay = VIDEO_DOWNLOAD_RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "Video download attempt %d/%d failed for %s:%s; retrying in %.1fs: %s",
                    attempt,
                    attempt_count,
                    source_type.value,
                    source_id,
                    delay,
                    exc,
                )
                time.sleep(delay)

        logger.error("Video download failed after %d attempts: %s", attempt_count, last_error)
        if isinstance(last_error, VideoProcessingException):
            raise last_error
        raise VideoProcessingException(f"Failed to download video: {last_error}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _source_download_files(output_path: Path, source_id: str) -> list[Path]:
        """Return files whose names begin with the literal source ID."""
        filename_prefix = f"{source_id}."
        return [
            candidate
            for candidate in output_path.iterdir()
            if candidate.is_file() and candidate.name.startswith(filename_prefix)
        ]

    @staticmethod
    def _cleanup_partial_video_downloads(output_path: Path, source_id: str) -> None:
        """Remove only yt-dlp partials for this source before a fresh retry."""
        for candidate in VideoService._source_download_files(output_path, source_id):
            if candidate.name.endswith((".part", ".ytdl", ".temp")):
                candidate.unlink(missing_ok=True)

    def _local_video_file(self, url: str) -> Tuple[str, int]:
        """Return the already-saved upload as-is — no download needed."""
        local_path = Path(VideoSourceResolver.upload_local_path(url))
        if not local_path.is_file():
            raise VideoProcessingException(f"Uploaded file not found: {local_path}")
        return str(local_path), local_path.stat().st_size

    def _extract_local_audio(
        self, url: str, output_path: str, source_id: str
    ) -> Tuple[str, int]:
        """Extract/convert the uploaded file's audio track to MP3 via ffmpeg."""
        local_path = Path(VideoSourceResolver.upload_local_path(url))
        if not local_path.is_file():
            raise VideoProcessingException(f"Uploaded file not found: {local_path}")

        dest = Path(output_path) / f"{source_id}.mp3"
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(local_path),
                    "-vn", "-acodec", "libmp3lame", "-q:a", "2",
                    str(dest),
                ],
                capture_output=True,
                text=True,
                timeout=self.settings.service_timeouts.whisper_timeout,
            )
        except FileNotFoundError as e:
            raise VideoProcessingException(f"ffmpeg is not installed: {e}")
        except subprocess.TimeoutExpired as e:
            raise VideoProcessingException(f"Audio extraction timed out: {e}")

        if result.returncode != 0 or not dest.exists():
            raise VideoProcessingException(
                f"Failed to extract audio from upload: {result.stderr.strip()[-500:]}"
            )

        logger.info(f"✓ Audio extracted from upload: {dest} ({dest.stat().st_size} bytes)")
        return str(dest), dest.stat().st_size

    def _local_metadata(self, url: str, source_id: str) -> Dict:
        """Build metadata for an uploaded file without any network call."""
        local_path = Path(VideoSourceResolver.upload_local_path(url))
        display_name = VideoSourceResolver.upload_display_name(url)
        return {
            "video_id": source_id,
            "source_type": SourceType.UPLOAD.value,
            "title": display_name or local_path.name,
            "description": "",
            "duration": self._ffprobe_duration(local_path),
            "channel": "Local upload",
            "upload_date": None,
            "view_count": 0,
            "thumbnail_url": "",
            "chapters": [],
        }

    @staticmethod
    def _ffprobe_duration(path: Path) -> int:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "json", str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return 0
            return int(float(json.loads(result.stdout)["format"]["duration"]))
        except Exception as e:
            logger.warning(f"ffprobe duration lookup failed for {path}: {e}")
            return 0

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
