from ytclipper.cutter import build_cut_plan, clip_command, download_command
from ytclipper.segmenter import Clip

VID = "dQw4w9WgXcQ"
CLIP = Clip(start=90.0, end=120.5, score=3.2, preview="The secret is...")


def test_download_command():
    job = download_command(VID, "clips/video.mp4")
    assert job.argv[0] == "yt-dlp"
    assert f"https://www.youtube.com/watch?v={VID}" in job.argv
    assert job.output == "clips/video.mp4"


def test_clip_command_stream_copy():
    job = clip_command("in.mp4", CLIP, "out.mp4")
    argv = list(job.argv)
    assert argv[0] == "ffmpeg"
    assert argv[argv.index("-ss") + 1] == "00:01:30.000"
    assert argv[argv.index("-to") + 1] == "00:02:00.500"
    assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"


def test_clip_command_vertical_reencodes():
    job = clip_command("in.mp4", CLIP, "out.mp4", vertical=True)
    argv = list(job.argv)
    assert "libx264" in argv
    assert any("9/16" in a for a in argv)
    assert "copy" not in argv


def test_build_cut_plan_includes_download():
    plan = build_cut_plan(VID, [CLIP, Clip(start=200, end=230, score=1.0)])
    assert len(plan) == 3
    assert plan[0].argv[0] == "yt-dlp"
    assert plan[1].argv[0] == plan[2].argv[0] == "ffmpeg"
    # every ffmpeg job reads the downloaded source
    assert plan[0].output in plan[1].argv
    # outputs are distinct and slugged from the preview
    assert plan[1].output != plan[2].output
    assert "the-secret-is" in plan[1].output


def test_build_cut_plan_with_local_source_skips_download():
    plan = build_cut_plan(VID, [CLIP], source="local.mp4")
    assert len(plan) == 1
    assert plan[0].argv[0] == "ffmpeg"
    assert "local.mp4" in plan[0].argv


def test_command_shell_quoting():
    job = clip_command("my video.mp4", CLIP, "out.mp4")
    assert "'my video.mp4'" in job.command()
