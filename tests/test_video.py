import pytest

from ytclipper.video import extract_start_time, extract_video_id, watch_url

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        VID,
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&list=PLx&index=2",
        f"http://m.youtube.com/watch?v={VID}",
        f"https://music.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?t=42",
        f"youtu.be/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}?feature=share",
        f"https://www.youtube-nocookie.com/embed/{VID}",
        f"https://www.youtube.com/v/{VID}",
    ],
)
def test_extract_video_id(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not a url",
        "https://example.com/watch?v=dQw4w9WgXcQ",  # wrong host
        "https://www.youtube.com/watch?v=tooshort",
        "https://www.youtube.com/watch",
        "https://vimeo.com/12345678901",
    ],
)
def test_extract_video_id_rejects(bad):
    with pytest.raises(ValueError):
        extract_video_id(bad)


def test_extract_start_time():
    assert extract_start_time(f"https://youtu.be/{VID}?t=90") == 90
    assert extract_start_time(f"https://www.youtube.com/watch?v={VID}&t=1m30s") == 90
    assert extract_start_time(f"https://www.youtube.com/watch?v={VID}") is None


def test_watch_url_round_trip():
    url = watch_url(VID, start=63.9)
    assert url == f"https://www.youtube.com/watch?v={VID}&t=63s"
    assert extract_video_id(url) == VID
    with pytest.raises(ValueError):
        watch_url("nope")
