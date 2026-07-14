"""Video metadata via YouTube's public oEmbed endpoint (no API key needed)."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen

from .video import watch_url

OEMBED_ENDPOINT = "https://www.youtube.com/oembed"


def fetch_metadata(video_id: str, *, timeout: float = 10.0) -> dict:
    """Return oEmbed metadata (title, author_name, thumbnail_url, ...)."""
    query = urlencode({"url": watch_url(video_id), "format": "json"})
    with urlopen(f"{OEMBED_ENDPOINT}?{query}", timeout=timeout) as resp:
        return json.load(resp)
