"""ytclipper command-line interface.

Subcommands:
  id          extract the video ID from a URL
  info        fetch title/author via oEmbed
  transcript  fetch or parse a transcript, print as JSON
  suggest     score a transcript and print the best clip segments
  cut         build (and optionally run) the yt-dlp/ffmpeg cut plan
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .cutter import build_cut_plan, execute_plan
from .metadata import fetch_metadata
from .segmenter import Clip, suggest_clips
from .timecode import format_timecode, parse_timecode
from .transcript import Cue, fetch_transcript, load_transcript
from .video import extract_video_id


def _load_cues(args: argparse.Namespace) -> list[Cue]:
    if args.transcript:
        return load_transcript(args.transcript)
    video_id = extract_video_id(args.url)
    return fetch_transcript(video_id, lang=args.lang)


def _print_clips(clips: list[Clip], as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(c) for c in clips], indent=2))
        return
    if not clips:
        print("no clip candidates found (transcript too short?)")
        return
    for i, clip in enumerate(clips, 1):
        span = f"{format_timecode(clip.start, millis=False)} - {format_timecode(clip.end, millis=False)}"
        reasons = ", ".join(clip.reasons) or "-"
        print(f"{i}. [{span}] score={clip.score} ({reasons})")
        print(f"   {clip.preview}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ytclipper", description=__doc__)
    parser.add_argument("--version", action="version", version=f"ytclipper {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_id = sub.add_parser("id", help="extract the video ID from a URL")
    p_id.add_argument("url")

    p_info = sub.add_parser("info", help="fetch title/author via oEmbed")
    p_info.add_argument("url")

    p_tr = sub.add_parser("transcript", help="fetch or parse a transcript as JSON")
    p_tr.add_argument("url", nargs="?", default="")
    p_tr.add_argument("--transcript", help="local .srt/.vtt/.json file instead of fetching")
    p_tr.add_argument("--lang", default="en")

    p_suggest = sub.add_parser("suggest", help="suggest highlight clips")
    p_suggest.add_argument("url", nargs="?", default="")
    p_suggest.add_argument("--transcript", help="local .srt/.vtt/.json file instead of fetching")
    p_suggest.add_argument("--lang", default="en")
    p_suggest.add_argument("--count", type=int, default=5)
    p_suggest.add_argument("--min-duration", type=float, default=15.0)
    p_suggest.add_argument("--max-duration", type=float, default=60.0)
    p_suggest.add_argument("--json", action="store_true", dest="as_json")

    p_cut = sub.add_parser("cut", help="cut clips (or print the command plan)")
    p_cut.add_argument("url")
    p_cut.add_argument("--start", help="clip start (e.g. 1:23 or 83s); requires --end")
    p_cut.add_argument("--end", help="clip end")
    p_cut.add_argument("--auto", type=int, metavar="N", help="auto-suggest N clips from the transcript")
    p_cut.add_argument("--transcript", help="local transcript for --auto")
    p_cut.add_argument("--lang", default="en")
    p_cut.add_argument("--source", help="already-downloaded local video file")
    p_cut.add_argument("--outdir", default="clips")
    p_cut.add_argument("--reencode", action="store_true", help="frame-accurate cuts")
    p_cut.add_argument("--vertical", action="store_true", help="crop to 9:16 for Shorts")
    p_cut.add_argument("--dry-run", action="store_true", help="print commands, run nothing")

    args = parser.parse_args(argv)

    try:
        if args.command == "id":
            print(extract_video_id(args.url))

        elif args.command == "info":
            meta = fetch_metadata(extract_video_id(args.url))
            print(json.dumps(meta, indent=2))

        elif args.command == "transcript":
            if not args.transcript and not args.url:
                parser.error("provide a URL or --transcript FILE")
            cues = _load_cues(args)
            print(json.dumps([asdict(c) for c in cues], indent=2))

        elif args.command == "suggest":
            if not args.transcript and not args.url:
                parser.error("provide a URL or --transcript FILE")
            cues = _load_cues(args)
            clips = suggest_clips(
                cues,
                count=args.count,
                min_duration=args.min_duration,
                max_duration=args.max_duration,
            )
            _print_clips(clips, args.as_json)

        elif args.command == "cut":
            video_id = extract_video_id(args.url)
            if args.auto:
                cues = _load_cues(args)
                clips = suggest_clips(cues, count=args.auto)
            elif args.start and args.end:
                start, end = parse_timecode(args.start), parse_timecode(args.end)
                if end <= start:
                    parser.error("--end must be after --start")
                clips = [Clip(start=start, end=end, score=0.0)]
            else:
                parser.error("use --start/--end or --auto N")
            plan = build_cut_plan(
                video_id,
                clips,
                outdir=args.outdir,
                source=args.source,
                reencode=args.reencode,
                vertical=args.vertical,
            )
            if args.dry_run:
                for job in plan:
                    print(job.command())
            else:
                for output in execute_plan(plan, outdir=args.outdir):
                    print(output)

    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
