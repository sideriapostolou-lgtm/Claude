"""ytclipper — parse YouTube videos and clip the best moments.

Pipeline: URL -> video ID -> transcript (fetched or local) -> scored
highlight segments -> ffmpeg cut plan.
"""

__version__ = "0.1.0"

from .video import extract_video_id, watch_url
from .timecode import parse_timecode, format_timecode
from .transcript import Cue, load_transcript, parse_srt, parse_vtt, parse_json3
from .segmenter import Clip, suggest_clips, parse_chapters
from .cutter import CutJob, build_cut_plan

__all__ = [
    "extract_video_id",
    "watch_url",
    "parse_timecode",
    "format_timecode",
    "Cue",
    "load_transcript",
    "parse_srt",
    "parse_vtt",
    "parse_json3",
    "Clip",
    "suggest_clips",
    "parse_chapters",
    "CutJob",
    "build_cut_plan",
]
