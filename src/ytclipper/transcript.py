"""Transcript loading: SRT, WebVTT, and YouTube json3 caption formats.

All parsers normalize into a list of Cue(start, end, text) with seconds
as floats and whitespace-collapsed text.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
# VTT allows MM:SS.mmm (no hours) and trailing cue settings after the times.
_VTT_TIME_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def words(self) -> int:
        return len(self.text.split())


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _hms_ms(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(content: str) -> list[Cue]:
    """Parse SubRip (.srt) content."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln.strip("﻿").strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # Optional numeric index line, then the timing line.
        if lines[0].isdigit() and len(lines) > 1:
            lines = lines[1:]
        m = _SRT_TIME_RE.match(lines[0])
        if not m:
            continue
        start = _hms_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _hms_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        text = _clean(" ".join(lines[1:]))
        if text and end > start:
            cues.append(Cue(start, end, text))
    return cues


def parse_vtt(content: str) -> list[Cue]:
    """Parse WebVTT (.vtt) content, including yt-dlp auto-caption output."""
    cues: list[Cue] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        m = _VTT_TIME_RE.search(lines[i])
        if not m:
            i += 1
            continue
        start = _hms_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _hms_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        i += 1
        text_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and not _VTT_TIME_RE.search(lines[i]):
            text_lines.append(lines[i])
            i += 1
        text = _clean(" ".join(text_lines))
        # Rolling auto-captions repeat the previous line in consecutive
        # cues; drop consecutive duplicates.
        if text and end > start and (not cues or cues[-1].text != text):
            cues.append(Cue(start, end, text))
    return cues


def parse_json3(content: str) -> list[Cue]:
    """Parse YouTube's json3 timedtext format."""
    data = json.loads(content)
    cues: list[Cue] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs or "tStartMs" not in event:
            continue
        text = _clean("".join(seg.get("utf8", "") for seg in segs))
        if not text:
            continue
        start = event["tStartMs"] / 1000
        end = start + event.get("dDurationMs", 0) / 1000
        if end > start:
            cues.append(Cue(start, end, text))
    return cues


def load_transcript(path: str | Path) -> list[Cue]:
    """Load a transcript file, dispatching on extension (.srt/.vtt/.json)."""
    p = Path(path)
    content = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix == ".srt":
        return parse_srt(content)
    if suffix == ".vtt":
        return parse_vtt(content)
    if suffix in (".json", ".json3"):
        return parse_json3(content)
    raise ValueError(f"unsupported transcript format: {p.suffix!r} (use .srt, .vtt, or .json)")


def fetch_transcript(video_id: str, *, lang: str = "en", workdir: str | Path = ".") -> list[Cue]:
    """Fetch captions for a video via yt-dlp (network + yt-dlp required).

    Tries manual subtitles first, then auto-generated ones.
    """
    import subprocess
    import tempfile

    from .video import watch_url

    with tempfile.TemporaryDirectory(dir=str(workdir)) as tmp:
        out = Path(tmp) / "captions"
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            f"{lang}.*,{lang}",
            "--sub-format",
            "vtt",
            "-o",
            str(out),
            watch_url(video_id),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr.strip().splitlines()[-1:]}")
        vtt_files = sorted(Path(tmp).glob("captions*.vtt"))
        if not vtt_files:
            raise RuntimeError(f"no {lang!r} captions available for {video_id}")
        return load_transcript(vtt_files[0])
