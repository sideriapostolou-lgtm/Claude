# ytclipper

Parse YouTube videos and clip the best moments.

Give it a YouTube URL (or a local transcript), and it:

1. **Parses** the URL into a video ID (all URL shapes: `watch?v=`, `youtu.be`, `shorts/`, `embed/`, `live/`, bare IDs)
2. **Loads the transcript** — fetched via `yt-dlp` captions, or from a local `.srt` / `.vtt` / `.json3` file
3. **Scores highlight segments** with a deterministic, offline heuristic (hook phrases, questions, superlatives, numbers, direct address, speech density, natural pause boundaries)
4. **Builds a cut plan** — `yt-dlp` download + `ffmpeg` cut commands you can run directly or dry-run and ship elsewhere

No API keys required. The only runtime dependencies are optional: `yt-dlp` for fetching, `ffmpeg` for cutting.

## Install

```bash
pip install -e .            # library + `ytclipper` CLI
pip install -e '.[fetch]'   # + yt-dlp for fetching captions/video
```

## Usage

```bash
# Extract the video ID from any YouTube URL shape
ytclipper id 'https://youtu.be/dQw4w9WgXcQ?t=42'

# Title/author via YouTube's public oEmbed endpoint (no key needed)
ytclipper info 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

# Fetch captions (yt-dlp) or parse a local transcript, as JSON
ytclipper transcript 'https://youtu.be/VIDEO_ID'
ytclipper transcript --transcript talk.srt

# Suggest the 5 best clip segments (15-60s, non-overlapping)
ytclipper suggest --transcript talk.vtt --count 5
ytclipper suggest 'https://youtu.be/VIDEO_ID' --min-duration 20 --max-duration 45 --json

# Cut a manual range — or auto-pick the best moments
ytclipper cut 'https://youtu.be/VIDEO_ID' --start 1:30 --end 2:00
ytclipper cut 'https://youtu.be/VIDEO_ID' --auto 3 --vertical      # 9:16 Shorts crops
ytclipper cut 'https://youtu.be/VIDEO_ID' --auto 3 --dry-run       # print commands only
ytclipper cut 'https://youtu.be/VIDEO_ID' --start 90s --end 2m --source local.mp4
```

`--dry-run` prints the exact `yt-dlp`/`ffmpeg` commands without running anything, so the plan can be generated on one machine and executed wherever the tools (and network access) live.

## How segment scoring works

The segmenter is deterministic and fully offline (`src/ytclipper/segmenter.py`):

- The transcript is split into **passages at natural pauses** (default gap ≥ 1.5s); clips never straddle a pause, so they start and end on clean boundaries.
- A window slides over each passage, bounded by `--min-duration`/`--max-duration`.
- Each window's text is scored on hook signals: questions, exclamations, hook words (*secret, mistake, never, nobody...*), superlatives, hook phrases (*"here's why", "the real reason"*), direct address (*you/your*), numbers, and contrast turns (*but, actually, turns out*). Each signal is capped so one repeated marker can't dominate.
- The score is weighted by **speech density** relative to the video average and normalized to prefer tighter clips.
- The top non-overlapping windows win, returned in chronological order with the matched signals as `reasons`.

Chapter markers in video descriptions (`0:00 Intro` lists) are parsed with YouTube's own validity rules (starts at 0:00, 3+ ascending entries) via `parse_chapters`.

## Library use

```python
from ytclipper import extract_video_id, load_transcript, suggest_clips, build_cut_plan

video_id = extract_video_id("https://youtu.be/dQw4w9WgXcQ")
cues = load_transcript("talk.srt")
clips = suggest_clips(cues, count=3, min_duration=20, max_duration=45)
for job in build_cut_plan(video_id, clips, vertical=True):
    print(job.command())
```

## Tests

```bash
pip install pytest
python -m pytest -q     # 67 tests, hermetic (no network, no ffmpeg needed)
```

## Notes and limitations

- Fetching captions or video from datacenter IPs often triggers YouTube's bot check; yt-dlp's error (with its cookie-passing suggestions) is surfaced verbatim. Local transcript files and `--dry-run` plans work everywhere.
- Stream-copy cuts (`-c copy`) snap to keyframes; use `--reencode` (or `--vertical`, which implies it) for frame-accurate cuts.
- Scoring is heuristic and English-leaning; the hook-pattern table is one place to extend per language or niche.
