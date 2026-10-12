"""Causal context and explicit uncertainty for the public observation model."""

from __future__ import annotations

import pytest

from nightcrawler.skipwatch_model import SkipwatchModel


def model():
    value = SkipwatchModel(900)
    value.ingest("market", {"market_id": "m", "slug": "btc-window", "start": 900, "end": 1200,
                            "up_token": "u", "down_token": "d"}, 900)
    return value


def snapshot(value, at=1000):
    value.ingest("book_snapshot", {"token_id": "u", "exchange_at": at, "valid": True,
                                   "bids": [[.4, 10], [.39, 15]], "asks": [[.45, 8]]}, at)


def test_grouped_changes_reconstruct_exact_levels_and_invalidity_is_sticky_until_snapshot():
    value = model()
    snapshot(value)
    delta = {"exchange_at": 1001, "updates": [{"token_id": "u", "valid": True,
               "changes": [{"book_side": "bid", "price": .4, "size": 0},
                           {"book_side": "ask", "price": .44, "size": 3}]}]}
    value.ingest("book_deltas", delta, 1001)
    features = value.features("m", "up", 1001)
    assert (features["bid"], features["ask"], features["ask_top_size"]) == (.39, .44, 3)
    delta["updates"][0]["valid"] = False
    value.ingest("book_deltas", delta, 1001.1)
    delta["updates"][0]["valid"] = True
    value.ingest("book_deltas", delta, 1001.2)
    assert not value.features("m", "up", 1001.2)["coverage"]["book"]
    snapshot(value, 1002)
    assert value.features("m", "up", 1002)["coverage"]["book"]


def test_gap_invalidates_book_immediately_but_preserves_before_gap_context():
    value = model()
    snapshot(value)
    value.ingest("gap", {"source": "runtime"}, 1000.5)
    assert value.features("m", "up", 1000.25)["ask"] == .45
    assert value.features("m", "up", 1000.5)["ask"] is None
    assert not value.coverage(1000.5, "u")["book"]


def test_busy_book_retains_delayed_fill_context_beyond_old_2048_entry_limit():
    value = model()
    snapshot(value)
    for offset in range(3000):
        at = 1000 + (offset + 1) / 300
        value.ingest("book_delta", {"token_id": "u", "exchange_at": at,
                                    "valid": True, "changes": []}, at)
    assert value.features("m", "up", 1000)["ask"] == .45
    value.ingest("health", {"source": "wallet", "status": "connected"}, 1131)
    assert not value.book_history["u"]


@pytest.mark.parametrize("sizes,expected", [([10], "inferred"), ([10, 10], "ambiguous"), ([20], "unmatched")])
def test_exact_print_matches_remain_inferred_and_larger_print_is_not_exact(sizes, expected):
    value = model()
    for index, size in enumerate(sizes):
        value.ingest("public_trade", {"trade_id": str(index), "token_id": "u", "exchange_at": 1000,
                                      "price": .4, "size": size}, 1000.1)
    value.ingest("wallet_fill", {"fill_id": "f", "market_id": "m", "token_id": "u", "side": "up",
                                  "exchange_at": 1000, "price": .4, "size": 10}, 1002)
    observation = next(event.payload for event in value.due(1007) if event.kind == "wallet_observation")
    assert observation["confidence"] == expected
    assert observation["maker_taker"] == "unknown" and observation["cancellations"] == "unobservable"
    assert observation["prior_up"] is None


def test_quiet_windows_are_observed_and_missing_wallet_poll_never_counts_as_coverage():
    value = model()
    for event in value.due(1000):
        value.ingest(event.kind, event.payload, 1000)
    assert value.observed_windows == {"m"}
    assert not value.coverage(1000)["wallet"]
    value.ingest("health", {"source": "wallet", "status": "connected", "wallet_watermark": 1000}, 1000)
    assert value.coverage(1001)["wallet"]
    assert not value.coverage(1006)["wallet"]


def test_opening_price_requires_actual_knowledge_at_start_and_at_most_three_seconds_age():
    value = model()
    value.ingest("bitcoin_tick", {"exchange_at": 899, "price": 60_000}, 899.5)
    value.ingest("bitcoin_tick", {"exchange_at": 899.9, "price": 90_000}, 901)
    features = value.features("m", "up", 902)
    assert features["opening_price"] == 60_000
    assert features["opening_age_s"] == 1
    empty = model()
    empty.ingest("bitcoin_tick", {"exchange_at": 896, "price": 60_000}, 896)
    assert empty.features("m", "up", 902)["opening_price"] is None


def test_research_volatility_cannot_use_returns_outside_trailing_hour():
    value = model()
    value.seconds = {stamp: (60_000 + stamp % 2, float(stamp)) for stamp in range(300, 650)}
    assert value.features("m", "up", 1000)["sigma"] is not None
    assert value.features("m", "up", 4300)["sigma"] is None
