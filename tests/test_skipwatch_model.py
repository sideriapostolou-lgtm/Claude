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
    assert observation["causal_fit_eligible"] is False
    assert observation["execution_time_inferred"] is False


def linked_trade(value, at=1000.25, *, observed_at=None, **changes):
    data = {"trade_id": "print", "market_id": "m", "token_id": "u", "side": "up",
            "exchange_at": at, "price": .4, "size": 10, "transaction_hash": "settling-transaction",
            **changes}
    value.ingest("public_trade", data, observed_at if observed_at is not None else at + .1)


def linked_fill(value, at=1003, *, observed_at=1006, **changes):
    value.ingest("wallet_fill", {"fill_id": "f", "market_id": "m", "token_id": "u", "side": "up",
                                  "exchange_at": at, "block_at": at, "timestamp_domain": "block",
                                  "price": .4, "size": 10, "transaction_hash": "settling-transaction",
                                  **changes}, observed_at)


def observed_fill(value, now=1011):
    return next(event.payload for event in value.due(now) if event.kind == "wallet_observation")


@pytest.mark.parametrize("block_at", [1003, 1050])
def test_unique_transaction_link_uses_print_context_without_tuned_block_lag_limit(block_at):
    value = model()
    snapshot(value, 1000)
    value.ingest("bitcoin_tick", {"exchange_at": 1000, "price": 60_000}, 1000)
    linked_trade(value)
    # Later context was unknown at the inferred print time and must be excluded.
    value.ingest("book_snapshot", {"token_id": "u", "exchange_at": 1002, "valid": True,
                                   "bids": [[.5, 30]], "asks": [[.55, 30]]}, 1002)
    value.ingest("bitcoin_tick", {"exchange_at": 1002, "price": 61_000}, 1002)
    linked_fill(value, at=block_at, observed_at=block_at + 3)
    observation = observed_fill(value, block_at + 8)
    assert observation["confidence"] == "inferred"
    assert observation["match_method"] == "transaction_token_price_size"
    assert observation["block_at"] == block_at and observation["block_timestamp_domain"] == "block"
    assert observation["matched_event_at"] == observation["at"] == 1000.25
    assert observation["matched_event_timestamp_domain"] == "clob_event"
    assert observation["timestamp_domain"] == "clob_event_inferred"
    assert observation["execution_time_inferred"] is True
    assert observation["execution_identity_verified"] is False
    assert observation["causal_fit_eligible"] is False
    assert observation["bid"] == .4 and observation["btc_price"] == 60_000
    assert observation["candidate_evidence"][0]["transaction_hash"] == "settling-transaction"


@pytest.mark.parametrize("trade_changes", [
    {"transaction_hash": "different-transaction"},
    {"market_id": "other-window"},
    {"token_id": "d", "side": "down", "price": .6},
    {"size": 20},
    {"price": .41},
])
def test_hash_does_not_override_window_token_price_or_quantity_identity(trade_changes):
    value = model()
    linked_trade(value, at=1002.5, **trade_changes)
    linked_fill(value)
    observation = observed_fill(value)
    assert observation["confidence"] == "unmatched"
    assert observation["matched_event_at"] is None
    assert observation["timestamp_domain"] == "block"


@pytest.mark.parametrize("trade_at,expected", [(1003.999, "inferred"), (1004.001, "unmatched")])
def test_transaction_link_cannot_use_event_after_block_second_upper_bound(trade_at, expected):
    value = model()
    linked_trade(value, at=trade_at)
    linked_fill(value)
    assert observed_fill(value)["confidence"] == expected


def test_multiple_economically_identical_transaction_prints_remain_ambiguous():
    value = model()
    linked_trade(value, at=1000.25, trade_id="print-1")
    linked_trade(value, at=1000.5, trade_id="print-2")
    linked_fill(value)
    observation = observed_fill(value)
    assert observation["confidence"] == "ambiguous" and observation["candidate_prints"] == 2
    assert observation["matched_event_at"] is None and observation["execution_time_inferred"] is False
    assert observation["at"] == observation["block_at"] == 1003


@pytest.mark.parametrize("trade_at,expected", [(1002.5, "inferred"), (1000.25, "unmatched")])
def test_no_hash_heuristic_keeps_old_range_but_cannot_infer_execution_time(trade_at, expected):
    value = model()
    linked_trade(value, at=trade_at, transaction_hash=None)
    linked_fill(value)
    observation = observed_fill(value)
    assert observation["confidence"] == expected
    assert observation["matched_event_at"] is None and observation["execution_time_inferred"] is False
    assert observation["causal_fit_eligible"] is False
    assert observation["at"] == observation["block_at"] == 1003


def test_retention_and_observation_start_bound_transaction_links():
    value = model()
    linked_trade(value, at=1000, observed_at=1000.1)
    linked_fill(value, at=1050, observed_at=1115)
    assert observed_fill(value, 1120.2)["confidence"] == "unmatched"
    prior = model()
    prior.started_at = 1001
    linked_trade(prior, at=1000, observed_at=1001.1)
    linked_fill(prior)
    assert observed_fill(prior)["confidence"] == "unmatched"


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
