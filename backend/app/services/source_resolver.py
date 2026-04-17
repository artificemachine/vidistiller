"""
Video Source Resolver

Detects the platform from a URL and extracts a platform-specific ID.
Used as the single entry point for URL parsing across all video sources.
"""

import hashlib
import logging
import re
from typing import Tuple

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


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


class VideoSourceResolver:
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
        for source_type, patterns in _PATTERNS:
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return source_type, match.group(1)

        if _DIRECT_EXTENSIONS.search(url):
            return SourceType.DIRECT, _url_hash(url)

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
