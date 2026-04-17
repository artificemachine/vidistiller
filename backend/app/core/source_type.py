from enum import Enum


class SourceType(str, Enum):
    YOUTUBE = "youtube"
    VIMEO = "vimeo"
    TWITCH = "twitch"
    TWITTER = "twitter"
    TIKTOK = "tiktok"
    REDDIT = "reddit"
    RUMBLE = "rumble"
    DIRECT = "direct"
    UNKNOWN = "unknown"
