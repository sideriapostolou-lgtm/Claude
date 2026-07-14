from pathlib import Path

from ytclipper.segmenter import parse_chapters, suggest_clips
from ytclipper.transcript import Cue, load_transcript

FIXTURES = Path(__file__).parent / "fixtures"


def _cues():
    return load_transcript(FIXTURES / "sample.srt")


def test_suggest_clips_basic_shape():
    clips = suggest_clips(_cues(), count=2, min_duration=10, max_duration=30)
    assert 1 <= len(clips) <= 2
    for clip in clips:
        assert 10 <= clip.duration <= 30
        assert clip.score > 0
        assert clip.preview
    # returned in chronological order
    assert all(a.end <= b.start for a, b in zip(clips, clips[1:]))


def test_clips_do_not_overlap():
    clips = suggest_clips(_cues(), count=5, min_duration=10, max_duration=25)
    for a, b in zip(clips, clips[1:]):
        assert a.end <= b.start


def test_hooks_beat_boring_content():
    clips = suggest_clips(_cues(), count=1, min_duration=10, max_duration=30)
    assert len(clips) == 1
    # The admin-setup passage (27.5s-48.5s) is the only low-signal stretch;
    # the winner should come from a hook-dense passage instead.
    winner = clips[0]
    assert not (27.5 <= winner.start and winner.end <= 48.5)
    assert winner.reasons


def test_clips_respect_pause_boundaries():
    clips = suggest_clips(_cues(), count=5, min_duration=10, max_duration=60, pause_gap=1.5)
    # Pauses at 25.0->27.5 and 48.5->50.5 split the transcript into three
    # passages; no clip may straddle a pause.
    for clip in clips:
        assert not (clip.start < 25.0 < clip.end)
        assert not (clip.start < 49.0 < clip.end)


def test_empty_and_short_transcripts():
    assert suggest_clips([]) == []
    short = [Cue(0, 3, "hi there")]
    assert suggest_clips(short, min_duration=15) == []


def test_parse_chapters():
    description = """Great video!

Chapters:
0:00 Intro
1:30 The setup
12:45 - The payoff
1:02:03 Outro

Follow me on socials"""
    chapters = parse_chapters(description)
    assert [c.title for c in chapters] == ["Intro", "The setup", "The payoff", "Outro"]
    assert [c.start for c in chapters] == [0.0, 90.0, 765.0, 3723.0]


def test_parse_chapters_rules():
    # must start at 0:00
    assert parse_chapters("1:00 A\n2:00 B\n3:00 C") == []
    # must have at least 3 entries
    assert parse_chapters("0:00 A\n2:00 B") == []
    # must be strictly ascending
    assert parse_chapters("0:00 A\n5:00 B\n3:00 C") == []
    assert parse_chapters("") == []
