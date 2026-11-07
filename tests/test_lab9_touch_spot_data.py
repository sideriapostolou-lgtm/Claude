"""Causal public spot features and archive integrity; fake network only."""
from __future__ import annotations

import importlib
import json
import math
from pathlib import Path

import pytest


@pytest.fixture
def spot(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "research/lab9"))
    return importlib.import_module("touch_spot_data")


def raw(start=0, close=100.0):
    return [start, close * .9, close * 1.1, close, close, 1.0]


def history(spot, n=722):
    return spot.parse_rows([raw(i * 3600, 100 * math.exp((i % 3) * .01)) for i in range(n)])


def envelope(spot, rows, *, received=10_000_000, requested=9_999_999, product="BTC-USD"):
    return {"url": f"{spot.ORIGIN}/products/{product}/candles?granularity=3600",
            "requested_at": requested, "received_at": received, "response": rows}


def test_candle_close_is_not_visible_at_start_or_before_end_plus_delay(spot):
    candles = history(spot)
    target = 721 * 3600
    before = spot.features_at(candles, target + 3604.999)
    after = spot.features_at(candles, target + 3605)
    assert before["close_start"] == target - 3600
    assert after["close_start"] == target
    assert before["eligible"] and after["eligible"]
    assert after["spot"] != before["spot"]
    assert after["returns"] == 720
    assert not after["touch_history_verified"]
    assert after["availability"] == "assumed_candle_end_plus_5s"


def test_missing_hour_rejects_instead_of_bridging_return_or_filling(spot):
    candles = history(spot)
    del candles[400 * 3600]
    features = spot.features_at(candles, 722 * 3600 + 5)
    assert not features["eligible"]
    assert features["reason"] == "incomplete_720_adjacent_hour_returns"
    assert features["returns"] == 718
    assert features["sigma_hour"] is None


def test_missing_latest_close_does_not_silently_use_older_price(spot):
    assert spot.features_at(history(spot), 723 * 3600 + 5)["reason"] == "missing_latest_closed_hour"


def test_zero_vol_and_719_returns_do_not_pass(spot):
    short = history(spot, 720)
    assert not spot.features_at(short, 720 * 3600 + 5)["eligible"]
    flat = spot.parse_rows([raw(i * 3600) for i in range(721)])
    assert spot.features_at(flat, 721 * 3600 + 5)["reason"] == "zero_realized_volatility"


@pytest.mark.parametrize("row", [raw(1), raw(-3600), raw(close=0), raw(close=float("nan")),
                                      [0, 101, 99, 100, 100, 1], [0, 90, 110, 100, 100, -1],
                                      [False, 90, 110, 100, 100, 1], [0, 100]])
def test_invalid_ohlc_is_not_research_evidence(spot, row):
    with pytest.raises((ValueError, TypeError)):
        spot.parse_rows([row])


def test_identical_duplicates_dedup_but_conflicts_abort(spot):
    assert len(spot.parse_rows([raw(), raw()])) == 1
    with pytest.raises(ValueError, match="Conflicting"):
        spot.parse_rows([raw(), raw(close=101)])


def test_archived_envelope_filters_candles_not_closed_at_request(spot, tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(envelope(spot, [raw(), raw(3600)], requested=3605, received=9000)))
    assert list(spot.load_envelopes([path], product="BTC-USD")) == [0]
    path.write_text(json.dumps(envelope(spot, [raw()], requested=9000, received=8000)))
    with pytest.raises(ValueError, match="receipt"):
        spot.load_envelopes([path], product="BTC-USD")


def test_cross_response_conflict_aborts(spot, tmp_path):
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    for path, price in zip(paths, [100, 101]):
        path.write_text(json.dumps(envelope(spot, [raw(close=price)])))
    with pytest.raises(ValueError, match="Conflicting"):
        spot.load_envelopes(paths, product="BTC-USD")


@pytest.mark.parametrize("url", ["http://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600",
                                        "https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=3600",
                                        "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60",
                                        "https://other.test/products/BTC-USD/candles?granularity=3600"])
def test_wrong_endpoint_or_granularity_cannot_be_reused(spot, url):
    with pytest.raises(ValueError):
        spot.validate_url(url, "BTC-USD")


class Clock:
    def __init__(self):
        self.at, self.waits = 10_000_000, []

    def __call__(self):
        return self.at

    def sleep(self, delay):
        self.waits.append(delay)
        self.at += delay


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}

    def json(self):
        return self.body


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_public_collector_honors_rate_limits_and_resumes_without_network(spot, tmp_path):
    clock = Clock()
    session = Session(Response({}, 429, {"Retry-After": "7"}), Response([raw(), raw(3600)]))
    reader = spot.PublicReader(session, clock, clock.sleep)
    report = spot.collect(tmp_path, "BTC-USD", 0, 7200, reader=reader)
    assert report["observed_hours"] == 2 and report["complete_hourly_grid"]
    assert report["requests_this_run"] == 2 and report["retries_this_run"] == 1
    assert clock.waits == [7, .35]
    assert session.calls[0][1]["allow_redirects"] is False
    assert "headers" not in session.calls[0][1]
    empty = Session()
    spot.collect(tmp_path, "BTC-USD", 0, 7200, reader=spot.PublicReader(empty, clock, clock.sleep))
    assert not empty.calls


def test_long_retry_after_stops_without_early_retry_or_long_block(spot):
    clock = Clock()
    session = Session(Response({}, 429, {"Retry-After": "120"}))
    with pytest.raises(ValueError, match="Long Retry-After"):
        spot.PublicReader(session, clock, clock.sleep).fetch("BTC-USD", 0, 3600)
    assert not clock.waits and len(session.calls) == 1
    assert spot.retry_delay("Thu, 01 Jan 1970 00:02:00 GMT", 0, 0) == 120


def test_redirect_is_never_followed(spot):
    session, clock = Session(Response({}, 302, {"Location": "https://other.test"})), Clock()
    with pytest.raises(ValueError, match="HTTP 302"):
        spot.PublicReader(session, clock, clock.sleep).fetch("BTC-USD", 0, 3600)
    assert len(session.calls) == 1


def test_cache_bounds_are_checked_before_reuse(spot, tmp_path):
    path = tmp_path / "BTC-USD/0-3600.json"
    path.parent.mkdir()
    path.write_text(json.dumps(envelope(spot, [raw()])))
    with pytest.raises(ValueError, match="different requested bounds"):
        spot.collect(tmp_path, "BTC-USD", 0, 3600)


def test_coverage_reports_real_gaps_without_outcome_or_touch_claim(spot):
    report = spot.coverage(spot.parse_rows([raw(), raw(3 * 3600)]), 0, 4 * 3600)
    assert report["missing_hours"] == report["longest_missing_run_hours"] == 2
    assert not report["complete_hourly_grid"] and not report["touch_history_verified"]
