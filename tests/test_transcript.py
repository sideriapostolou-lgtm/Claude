from pathlib import Path

import pytest

from ytclipper.transcript import load_transcript, parse_srt, parse_vtt

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_srt_fixture():
    cues = load_transcript(FIXTURES / "sample.srt")
    assert len(cues) == 14
    assert cues[0].start == 0.0
    assert cues[0].end == 4.5
    assert cues[0].text.startswith("Welcome back")
    assert cues[-1].end == 77.0
    # multi-line blocks are joined and whitespace collapsed
    assert "\n" not in cues[0].text


def test_parse_vtt_fixture():
    cues = load_transcript(FIXTURES / "sample.vtt")
    assert len(cues) == 4
    # cue settings after the arrow are ignored
    assert cues[0].start == 0.0 and cues[0].end == 4.5
    # inline <c> tags stripped, entities unescaped
    assert "completely wrong" in cues[1].text
    assert cues[2].text.startswith("Here's why")
    # hours field is optional in VTT but honored when present
    assert cues[3].start == 3614.2


def test_parse_json3_fixture():
    cues = load_transcript(FIXTURES / "sample.json3")
    assert len(cues) == 3  # newline-only and seg-less events dropped
    assert cues[0].text == "Welcome back to the channel, today we're covering something big."
    assert cues[2].start == 9.0 and cues[2].end == 14.2


def test_vtt_dedupes_rolling_auto_captions():
    content = (
        "WEBVTT\n\n"
        "00:00.000 --> 00:02.000\nhello world\n\n"
        "00:01.000 --> 00:04.000\nhello world\n\n"
        "00:02.000 --> 00:04.000\nsecond line\n"
    )
    # consecutive duplicate text (rolling captions) is dropped
    assert [c.text for c in parse_vtt(content)] == ["hello world", "second line"]
    # non-consecutive repeats are kept
    repeat = content + "\n00:05.000 --> 00:06.000\nhello world\n"
    assert [c.text for c in parse_vtt(repeat)] == ["hello world", "second line", "hello world"]


def test_srt_skips_malformed_blocks():
    content = "1\nnot a timestamp\ntext\n\n2\n00:00:01,000 --> 00:00:02,000\nok\n"
    cues = parse_srt(content)
    assert len(cues) == 1
    assert cues[0].text == "ok"


def test_unknown_extension_rejected(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("hello")
    with pytest.raises(ValueError, match="unsupported"):
        load_transcript(p)
