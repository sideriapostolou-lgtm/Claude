import pytest

from ytclipper.timecode import format_timecode, parse_timecode


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90", 90.0),
        ("90.5", 90.5),
        ("90s", 90.0),
        ("1m30s", 90.0),
        ("1h2m3s", 3723.0),
        ("2h", 7200.0),
        ("1:30", 90.0),
        ("01:02:03", 3723.0),
        ("01:02:03.500", 3723.5),
        ("0:00", 0.0),
        (42, 42.0),
        (3.5, 3.5),
    ],
)
def test_parse_timecode(value, expected):
    assert parse_timecode(value) == expected


@pytest.mark.parametrize("bad", ["", "abc", "-5", "1:99:00", -1])
def test_parse_timecode_rejects(bad):
    with pytest.raises(ValueError):
        parse_timecode(bad)


def test_format_timecode():
    assert format_timecode(3723.5) == "01:02:03.500"
    assert format_timecode(90, millis=False) == "00:01:30"
    assert format_timecode(0) == "00:00:00.000"
    # rounding carries into the seconds place
    assert format_timecode(59.9996) == "00:01:00.000"


def test_round_trip():
    assert parse_timecode(format_timecode(3723.5)) == 3723.5
