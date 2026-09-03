"""
Video Source Resolver

Detects the platform from a URL and extracts a platform-specific ID.
Used as the single entry point for URL parsing across all video sources.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Tuple
from urllib.parse import quote, unquote

from app.core.source_type import SourceType

logger = logging.getLogger(__name__)

# (SourceType, list-of-regex-patterns)
# Each pattern must have exactly one capture group: the platform-native ID.
_PATTERNS: list[tuple[SourceType, list[str]]] = [
    (SourceType.YOUTUBE, [
        r'(?:youtube\.com/watch\?.*?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([\w-]{11})',
    ]),
    (SourceType.VIMEO, [
        r'vimeo\.com/(?:video/)?(\d+)',
    ]),
    (SourceType.TWITCH, [
        r'twitch\.tv/videos/(\d+)',
        r'clips\.twitch\.tv/([\w-]+)',
        r'twitch\.tv/\w+/clip/([\w-]+)',
    ]),
    (SourceType.TWITTER, [
        r'(?:twitter|x)\.com/\w+/status/(\d+)',
    ]),
    (SourceType.TIKTOK, [
        r'tiktok\.com/@[\w.]+/video/(\d+)',
        r'vm\.tiktok\.com/([\w]+)',
    ]),
    (SourceType.REDDIT, [
        r'reddit\.com/r/\w+/comments/([\w]+)',
        r'redd\.it/([\w]+)',
    ]),
    (SourceType.RUMBLE, [
        r'rumble\.com/(?:embed/)?(v\w+)',
    ]),
]

_DIRECT_EXTENSIONS = re.compile(
    r'\.(mp4|webm|mov|mkv|avi|m3u8|m4v|ogv)(\?|$)', re.IGNORECASE
)

# Locally uploaded files are addressed as upload://<absolute-path>, never a
# real network URL — the path is always one this service wrote itself
# (see routes/jobs.py upload endpoint), never taken verbatim from user input.
UPLOAD_SCHEME = "upload://"


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:16]


def build_upload_url(local_path: str, display_name: str) -> str:
    """Build the synthetic video_url for an uploaded file.

    The display name (the user's original filename) rides in the fragment so
    it survives being threaded through video_url everywhere without ever
    becoming part of a filesystem path.
    """
    return f"{UPLOAD_SCHEME}{local_path}#{quote(display_name)}"


class VideoSourceResolver:
    @classmethod
    def match_known(cls, url: str) -> Tuple[SourceType, str] | None:
        """
        Offline-only platform ID extraction: known regex patterns plus direct
        file extensions. Never hits the network. Returns None when the URL
        matches no known platform (caller should fall back to comparing the
        raw URL string in that case).
        """
        if url.startswith(UPLOAD_SCHEME):
            return SourceType.UPLOAD, Path(cls.upload_local_path(url)).stem

        for source_type, patterns in _PATTERNS:
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return source_type, match.group(1)

        if _DIRECT_EXTENSIONS.search(url):
            return SourceType.DIRECT, _url_hash(url)

        return None

    @classmethod
    def resolve(cls, url: str) -> Tuple[SourceType, str]:
        """
        Detect platform and extract a platform-native ID from a URL.

        Resolution order:
        1. Known platform regex patterns (fast, offline)
        2. Direct video file extensions
        3. yt-dlp extractor metadata (network call, covers long-tail platforms)
        4. Unknown fallback with URL hash as ID
        """
        known = cls.match_known(url)
        if known is not None:
            return known

        # Ask yt-dlp — covers Dailymotion, Streamable, Odysee, etc.
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
            if info:
                extractor = (info.get("extractor_key") or "").lower()
                source_id = str(info.get("id") or _url_hash(url))
                for st in SourceType:
                    if st.value in extractor:
                        return st, source_id
                return SourceType.UNKNOWN, source_id
        except Exception as e:
            logger.debug(f"yt-dlp extractor probe failed for {url}: {e}")

        return SourceType.UNKNOWN, _url_hash(url)

    @staticmethod
    def upload_local_path(url: str) -> str:
        """Strip the upload:// scheme and #display-name fragment, leaving the on-disk path."""
        without_scheme = url[len(UPLOAD_SCHEME):] if url.startswith(UPLOAD_SCHEME) else url
        return without_scheme.split("#", 1)[0]

    @staticmethod
    def upload_display_name(url: str) -> str:
        """Return the original filename recorded for an upload:// video_url."""
        without_scheme = url[len(UPLOAD_SCHEME):] if url.startswith(UPLOAD_SCHEME) else url
        if "#" in without_scheme:
            return unquote(without_scheme.split("#", 1)[1])
        return Path(without_scheme).name
