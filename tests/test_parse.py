"""Foundation tests: defensive parsing helpers (sources/_parse.py)."""

from __future__ import annotations

import pytest

from fakes import load_fixture
from nightcrawler.sources._parse import (
    chunks,
    first_not_none,
    get_path,
    parse_ts,
    strip_gt_id,
    to_bool,
    to_float,
    to_int,
)


@pytest.mark.parametrize("value,expected", [
    ("0.0006507656584", 0.0006507656584), (12, 12.0), (1.5, 1.5), ("1,234.5", 1234.5), (" 7 ", 7.0),
    (None, None), ("", None), ("null", None), ("NaN", None), (float("inf"), None), (True, None),
    ("abc", None), ({}, None),
])
def test_to_float(value, expected) -> None:
    assert to_float(value) == expected


def test_to_float_default() -> None:
    assert to_float(None, 0.0) == 0.0


@pytest.mark.parametrize("value,expected", [
    ("18298969251", 18298969251), ("994092192206734", 994092192206734), (5, 5), (5.0, 5), ("12.9", 12),
    ("-3", -3), (None, None), ("", None), (False, None), ("x", None),
])
def test_to_int(value, expected) -> None:
    assert to_int(value) == expected


def test_to_int_big_strings_are_exact() -> None:
    assert to_int("123456789012345678901234567890") == 123456789012345678901234567890


@pytest.mark.parametrize("value,expected", [
    (True, True), ("no", False), ("yes", True), ("TRUE", True), (0, False), (1, True), ("unknown", None),
    (None, None),
])
def test_to_bool(value, expected) -> None:
    assert to_bool(value) is expected


@pytest.mark.parametrize("value,expected", [
    ("2026-10-08T15:32:10Z", 1791473530.0),
    ("2026-10-08T15:38:11.750362685Z", 1791473891.750362),
    ("2026-10-08T13:28:26.000Z", 1791466106.0),
    ("2026-10-08T15:32:10+00:00", 1791473530.0),
    ("2026-10-08T15:32:10", 1791473530.0),
    (1791117376000, 1791117376.0),  # DexScreener pairCreatedAt (ms)
    (1791117376, 1791117376.0),
    ("1791117376", 1791117376.0),
    (None, None), ("", None), ("garbage", None), (0, None),
])
def test_parse_ts(value, expected) -> None:
    out = parse_ts(value)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, abs=1e-5)


def test_get_path_on_real_fixture() -> None:
    gt = load_fixture("gt_token_info")
    assert get_path(gt, "data.attributes.holders.distribution_percentage.top_10") == "7.3843"
    assert get_path(gt, "data.attributes.missing.deep", "dflt") == "dflt"
    assert get_path(gt, "data.attributes.banner_image_url", "x") == "x"  # None -> default
    trades = load_fixture("gt_trades")
    assert get_path(trades, ["data", 0, "attributes", "kind"]) == "buy"
    assert get_path(trades, "data.0.attributes.kind") == "buy"
    assert get_path(trades, "data.999.attributes") is None


def test_misc_helpers() -> None:
    assert first_not_none(None, 0, 5) == 0 and first_not_none(None, None) is None
    assert strip_gt_id("solana_2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1") == \
        "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"
    assert strip_gt_id("pumpswap") == "pumpswap" and strip_gt_id(None) is None
    assert list(chunks(list(range(65)), 30)) == [list(range(30)), list(range(30, 60)), list(range(60, 65))]
    assert list(chunks([], 30)) == []
    with pytest.raises(ValueError):
        list(chunks([1], 0))
