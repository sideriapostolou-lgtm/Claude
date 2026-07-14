"""YouTube URL parsing: extract video IDs and start-time hints."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# YouTube video IDs are exactly 11 chars of this alphabet.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

# Path prefixes that carry the ID as the next path segment.
_PATH_PREFIXES = ("/embed/", "/shorts/", "/live/", "/v/")


def extract_video_id(url_or_id: str) -> str:
    """Return the 11-char video ID from a YouTube URL or a bare ID.

    Raises ValueError if no valid ID can be found.
    """
    candidate = url_or_id.strip()
    if _ID_RE.match(candidate):
        return candidate

    # Be forgiving about missing schemes ("youtu.be/xyz").
    if "//" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()

    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        if _ID_RE.match(vid):
            return vid
    elif host in _HOSTS:
        if parsed.path == "/watch":
            for vid in parse_qs(parsed.query).get("v", []):
                if _ID_RE.match(vid):
                    return vid
        for prefix in _PATH_PREFIXES:
            if parsed.path.startswith(prefix):
                vid = parsed.path[len(prefix):].split("/")[0]
                if _ID_RE.match(vid):
                    return vid

    raise ValueError(f"could not extract a YouTube video ID from {url_or_id!r}")


def extract_start_time(url: str) -> float | None:
    """Return the start-time hint (seconds) from a URL's t= param, if any."""
    if "//" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("t") or parse_qs(parsed.query).get("start")
    if not values:
        return None
    from .timecode import parse_timecode

    try:
        return parse_timecode(values[0])
    except ValueError:
        return None


def watch_url(video_id: str, start: float | None = None) -> str:
    """Canonical watch URL for a video ID, optionally with a start time."""
    if not _ID_RE.match(video_id):
        raise ValueError(f"invalid video ID: {video_id!r}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    if start is not None and start > 0:
        url += f"&t={int(start)}s"
    return url
