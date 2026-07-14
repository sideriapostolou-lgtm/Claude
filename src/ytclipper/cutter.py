"""Cut plan generation: yt-dlp download + ffmpeg clip commands.

The plan is plain data (argv lists) so it can be printed as a dry run,
executed here, or shipped to wherever ffmpeg lives.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .segmenter import Clip
from .timecode import format_timecode
from .video import watch_url


@dataclass(frozen=True)
class CutJob:
    output: str
    argv: tuple[str, ...]

    def command(self) -> str:
        return " ".join(_shquote(a) for a in self.argv)


def _shquote(arg: str) -> str:
    if re.fullmatch(r"[\w@%+=:,./-]+", arg):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return slug or fallback


def download_command(video_id: str, source: str | Path) -> CutJob:
    """yt-dlp command that downloads the source video as mp4."""
    return CutJob(
        output=str(source),
        argv=(
            "yt-dlp",
            "-f",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "--merge-output-format",
            "mp4",
            "-o",
            str(source),
            watch_url(video_id),
        ),
    )


def clip_command(
    source: str | Path,
    clip: Clip,
    output: str | Path,
    *,
    reencode: bool = False,
    vertical: bool = False,
) -> CutJob:
    """ffmpeg command cutting [clip.start, clip.end) from source.

    Stream copy by default (fast, keyframe-snapped). `reencode` gives
    frame-accurate cuts; `vertical` also crops to 9:16 for Shorts and
    implies re-encoding.
    """
    argv: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss",
        format_timecode(clip.start),
        "-to",
        format_timecode(clip.end),
        "-i",
        str(source),
    ]
    if vertical:
        argv += ["-vf", "crop=ih*9/16:ih,scale=1080:1920", "-c:v", "libx264", "-c:a", "aac"]
    elif reencode:
        argv += ["-c:v", "libx264", "-c:a", "aac"]
    else:
        argv += ["-c", "copy"]
    argv.append(str(output))
    return CutJob(output=str(output), argv=tuple(argv))


def build_cut_plan(
    video_id: str,
    clips: list[Clip],
    *,
    outdir: str | Path = "clips",
    source: str | Path | None = None,
    reencode: bool = False,
    vertical: bool = False,
) -> list[CutJob]:
    """Full plan: download (unless a local source is given) + one cut per clip."""
    outdir = Path(outdir)
    jobs: list[CutJob] = []
    if source is None:
        source = outdir / f"{video_id}.mp4"
        jobs.append(download_command(video_id, source))
    for i, clip in enumerate(clips, 1):
        name = _slug(clip.preview, f"clip-{i}")
        output = outdir / f"{video_id}-{i:02d}-{name}.mp4"
        jobs.append(clip_command(source, clip, output, reencode=reencode, vertical=vertical))
    return jobs


def execute_plan(jobs: list[CutJob], *, outdir: str | Path = "clips") -> list[str]:
    """Run each job, returning output paths. Fails fast with a clear error."""
    Path(outdir).mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for job in jobs:
        tool = job.argv[0]
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"{tool!r} is not installed — dry-run the plan and execute it "
                f"where {tool} is available"
            )
        result = subprocess.run(job.argv, capture_output=True, text=True)
        if result.returncode != 0:
            tail = "\n".join(result.stderr.strip().splitlines()[-5:])
            raise RuntimeError(f"{tool} failed for {job.output}:\n{tail}")
        outputs.append(job.output)
    return outputs
