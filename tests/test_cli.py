import json
from pathlib import Path

from ytclipper.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
VID = "dQw4w9WgXcQ"


def test_id_command(capsys):
    assert main(["id", f"https://youtu.be/{VID}"]) == 0
    assert capsys.readouterr().out.strip() == VID


def test_id_command_error(capsys):
    assert main(["id", "https://example.com/nope"]) == 1
    assert "error:" in capsys.readouterr().err


def test_transcript_from_file(capsys):
    assert main(["transcript", "--transcript", str(FIXTURES / "sample.srt")]) == 0
    cues = json.loads(capsys.readouterr().out)
    assert len(cues) == 14
    assert cues[0]["text"].startswith("Welcome back")


def test_suggest_from_file_json(capsys):
    assert main([
        "suggest", "--transcript", str(FIXTURES / "sample.srt"),
        "--count", "2", "--min-duration", "10", "--max-duration", "30", "--json",
    ]) == 0
    clips = json.loads(capsys.readouterr().out)
    assert 1 <= len(clips) <= 2
    assert {"start", "end", "score", "reasons", "preview"} <= set(clips[0])


def test_suggest_pretty_output(capsys):
    assert main(["suggest", "--transcript", str(FIXTURES / "sample.srt")]) == 0
    out = capsys.readouterr().out
    assert "score=" in out
    assert "-" in out


def test_cut_dry_run_manual_range(capsys):
    assert main([
        "cut", f"https://youtu.be/{VID}",
        "--start", "1:30", "--end", "2:00", "--dry-run",
    ]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("yt-dlp ")
    assert lines[1].startswith("ffmpeg ")
    assert "00:01:30.000" in lines[1]


def test_cut_dry_run_auto(capsys):
    assert main([
        "cut", f"https://youtu.be/{VID}",
        "--auto", "2", "--transcript", str(FIXTURES / "sample.srt"),
        "--dry-run", "--vertical",
    ]) == 0
    out = capsys.readouterr().out
    assert "crop=ih*9/16:ih" in out


def test_cut_rejects_inverted_range(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["cut", f"https://youtu.be/{VID}", "--start", "2:00", "--end", "1:30", "--dry-run"])
