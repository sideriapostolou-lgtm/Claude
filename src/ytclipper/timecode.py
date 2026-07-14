"""Timestamp parsing and formatting.

Accepted input forms: "90", "90.5", "90s", "1m30s", "1h2m3s",
"1:30", "01:02:03", "01:02:03.500". Output is ffmpeg-friendly
HH:MM:SS.mmm.
"""

from __future__ import annotations

import re

_CLOCK_RE = re.compile(
    r"^(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)$"
)
_UNITS_RE = re.compile(
    r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+(?:\.\d+)?)s?)?$"
)


def parse_timecode(value: str | int | float) -> float:
    """Parse a human timestamp into seconds. Raises ValueError on junk."""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError("timestamp must be non-negative")
        return seconds

    text = value.strip().lower()
    if not text:
        raise ValueError("empty timestamp")

    m = _CLOCK_RE.match(text)
    if m:
        h = int(m.group("h") or 0)
        mins = int(m.group("m"))
        secs = float(m.group("s"))
        if mins >= 60 and h:
            raise ValueError(f"invalid minutes in {value!r}")
        return h * 3600 + mins * 60 + secs

    m = _UNITS_RE.match(text)
    if m and any(m.group(g) for g in ("h", "m", "s")):
        h = int(m.group("h") or 0)
        mins = int(m.group("m") or 0)
        secs = float(m.group("s") or 0)
        return h * 3600 + mins * 60 + secs

    raise ValueError(f"unrecognized timestamp: {value!r}")


def format_timecode(seconds: float, *, millis: bool = True) -> str:
    """Format seconds as HH:MM:SS(.mmm)."""
    if seconds < 0:
        raise ValueError("timestamp must be non-negative")
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total = total_ms // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    base = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{base}.{ms:03d}" if millis else base
