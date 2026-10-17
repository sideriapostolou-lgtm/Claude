"""Executable exit evidence uses the first timely book, never a later lucky price.

All fixtures are invented, with no account, transport, keys, or order interface.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Any

import pytest

from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_markouts import FillMarkouts
from nightcrawler.speeddesk_model import Book, Level, Window

AT = 1_792_000_000.0
MONO = 100.0
TICKER = "KXBTC15M-markout-test"


def window(**changes: Any) -> Window:
    return replace(Window(TICKER, AT, AT + 900, 80_000, venue="kalshi",
                          taker_coefficient=.07, maker_coefficient=0,
                          min_trade_qty=.01, fee_rounding="kalshi"), **changes)


def fill(**changes: Any) -> ActualFill:
    return replace(ActualFill("fill-1", "order-1", "speeddesk-test-1", TICKER,
                              "up", .4, 5, .01, AT + 1, is_taker=False), **changes)


def book(seconds: float, bids: tuple[Level, ...] = (Level(.7, 10),), **changes: Any) -> Book:
    return replace(Book(TICKER, "up", bids, (Level(.9, 20),), AT + seconds,
                        f"sequence-{seconds}", exchange_at=AT + seconds), **changes)


def observed(tracker: FillMarkouts, actual: ActualFill | None = None,
             spec: Window | None = None, **changes: Any) -> list[dict[str, Any]]:
    args = {"observed_at": AT + 1, "observed_mono": MONO + 1,
            "fee_precision": .0001, "fee_verified": True, **changes}
    return tracker.observe_fill(actual or fill(), spec or window(), **args)


def quote(tracker: FillMarkouts, seconds: float, actual: Book | None = None,
          **changes: Any) -> list[dict[str, Any]]:
    args = {"now": AT + seconds, "mono": MONO + seconds, "own_bids": {}, **changes}
    return tracker.on_book(actual or book(seconds), **args)


def horizons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if "horizon_s" in row]


def test_three_horizons_use_first_update_not_the_best_update_and_never_realize_profit():
    tracker = FillMarkouts(AT, MONO)
    start = observed(tracker)
    assert len(start) == 1 and start[0]["event"] == "speeddesk_fill_observed"
    assert start[0]["mode"] == "diagnostic" and start[0]["fill_source"] == "real"
    assert quote(tracker, 1.9) == []
    got = []
    for seconds, price in ((2, .3), (6, .6), (31, .7)):
        rows = horizons(quote(tracker, seconds, book(seconds, (Level(price, 5),))))
        assert len(rows) == 1
        got.extend(rows)
        assert quote(tracker, seconds + .1, book(seconds + .1, (Level(.89, 50),))) == []
    assert [row["horizon_s"] for row in got] == [1, 5, 30]
    assert [row["gross_proceeds_usd"] for row in got] == pytest.approx([1.5, 3, 3.5])
    assert got[0]["hypothetical_net_usd"] < 0
    assert all(row["reason"] is None for row in got)
    assert all(row["mode"] == "diagnostic" and row["fill_source"] == "real" for row in got)
    assert all(row["sampling_method"] == "first_post_horizon_websocket_update" for row in got)
    assert all("realized_pnl" not in row for row in got)


def test_fill_timestamp_is_not_the_late_account_batch_receipt_clock():
    tracker = FillMarkouts(AT, MONO)
    row = observed(tracker, observed_at=AT + 4, observed_mono=MONO + 4)[0]
    assert row["actual_fill_at"] == AT + 1
    assert row["fills_batch_returned_at"] == AT + 4
    assert row["detection_delay_s"] == 3
    # Measurement deliberately starts at detection: no invented historical quote.
    assert quote(tracker, 4.5) == []
    first = horizons(quote(tracker, 5))[0]
    assert first["horizon_s"] == 1 and first["target_at"] == AT + 5


def test_two_price_levels_have_quantity_weighted_proceeds_and_conservative_fee_bound():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(2, (Level(.6, 3), Level(.7, 2)))))[0]
    assert row["filled_size"] == 5 and row["unfilled_size"] == 0
    assert row["gross_proceeds_usd"] == pytest.approx(3.2)
    assert row["allocated_entry_fee_usd"] == .01
    # 2 @ 70c and 3 @ 60c; pessimistically round every possible .01-contract fill.
    assert row["exit_fee_bound_usd"] == pytest.approx(.1298)
    assert row["partial_hypothetical_net_usd"] == pytest.approx(1.0602)
    assert row["hypothetical_net_usd"] == pytest.approx(1.0602)
    assert row["consumed_depth"] == [{"price": .7, "size": 2}, {"price": .6, "size": 3}]


def test_partial_liquidity_does_not_claim_full_position_exit_or_allocate_all_entry_fees():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(2, (Level(.6, 2),))))[0]
    assert row["filled_size"] == 2 and row["unfilled_size"] == 3
    assert row["gross_proceeds_usd"] == pytest.approx(1.2)
    assert row["allocated_entry_fee_usd"] == pytest.approx(.004)
    assert row["exit_fee_bound_usd"] == pytest.approx(.0536)
    assert row["partial_hypothetical_net_usd"] == pytest.approx(.3424)
    assert row["hypothetical_net_usd"] is None


def test_entry_maker_fee_does_not_make_an_immediate_sale_fee_free():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker, fill(fee_usd=0, is_taker=False))
    row = horizons(quote(tracker, 2))[0]
    assert row["allocated_entry_fee_usd"] == 0
    assert row["exit_fee_bound_usd"] > 0
    assert row["hypothetical_net_usd"] < row["gross_proceeds_usd"] - 2


def test_same_sale_method_prices_down_contracts_without_flipping_the_bid_again():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker, fill(side="down"))
    row = horizons(quote(tracker, 2, book(2, (Level(.7, 5),), side="down")))[0]
    assert row["side"] == "down"
    assert row["gross_proceeds_usd"] == 3.5
    assert row["hypothetical_net_usd"] > 0


def test_no_buyers_means_no_possible_exit_not_a_zero_profit_full_exit():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(2, ())))[0]
    assert row["filled_size"] == 0 and row["unfilled_size"] == 5
    assert row["gross_proceeds_usd"] == 0
    assert row["hypothetical_net_usd"] is None


def test_own_resting_bids_are_not_exit_liquidity_even_if_cancel_has_been_requested():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(2, (Level(.7, 5), Level(.6, 5))),
                         own_bids={.7: 5, .6: 2}))[0]
    assert row["filled_size"] == 3 and row["unfilled_size"] == 2
    assert row["gross_proceeds_usd"] == pytest.approx(1.8)
    assert row["consumed_depth"] == [{"price": .6, "size": 3}]
    assert row["hypothetical_net_usd"] is None


def test_self_only_book_never_looks_like_a_profitable_exit():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(2, (Level(.8, 5),)), own_bids={.8: 10}))[0]
    assert row["filled_size"] == 0 and row["unfilled_size"] == 5
    assert row["hypothetical_net_usd"] is None


@pytest.mark.parametrize("kwargs", [
    {"source": "rest"},
    {"at": AT + 1.99},
    {"exchange_at": AT + 1.49},
    {"exchange_at": None},
    {"at": AT + 3},
    {"exchange_at": AT + 3},
    {"bids": (Level(.7, math.nan),)},
    {"bids": (Level(math.nan, 5),)},
    {"bids": (Level(.7, -1),)},
    {"bids": (Level(.7, 2), Level(.7, 3))},
    {"asks": (Level(.6, 20),)},
])
def test_first_bad_observation_is_final_not_replaced_by_a_later_good_quote(kwargs):
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    rows = horizons(quote(tracker, 2, replace(book(2), **kwargs)))
    assert len(rows) == 1 and rows[0]["horizon_s"] == 1
    assert rows[0]["reason"]
    assert rows[0].get("hypothetical_net_usd") is None
    json.dumps(rows, allow_nan=False)
    assert quote(tracker, 2.1) == []


def test_old_and_opposite_side_books_cannot_satisfy_a_fill_horizon():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    assert quote(tracker, 1.5) == []
    assert quote(tracker, 2, book(2, side="down")) == []
    assert quote(tracker, 2, book(2, window="another-window")) == []
    row = horizons(quote(tracker, 2))[0]
    assert row["side"] == "up" and row["horizon_s"] == 1


def test_timely_received_update_can_have_a_slightly_earlier_exchange_timestamp():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2.01, book(2.01, exchange_at=AT + 1.98)))[0]
    assert row["reason"] is None
    assert row["book_source_age_s"] == pytest.approx(.03, abs=.000001)
    assert row["book_received_at"] >= row["target_at"]


def test_late_first_quote_is_missing_evidence_and_never_a_profitable_sample():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2.51))[0]
    assert row["horizon_s"] == 1 and row["reason"] == "observation_late"
    assert row.get("hypothetical_net_usd") is None
    assert quote(tracker, 2.6) == []


def test_monotonic_target_does_not_turn_wall_clock_jump_into_elapsed_market_time():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, book(60), now=AT + 60))[0]
    assert row["reason"] == "clock_change"
    assert row.get("hypothetical_net_usd") is None


def test_expired_horizon_is_explicit_and_cannot_be_filled_retroactively():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    rows = horizons(tracker.expire(now=AT + 2.51, mono=MONO + 2.51))
    assert len(rows) == 1 and rows[0]["horizon_s"] == 1
    assert rows[0]["reason"] == "no_post_horizon_book"
    assert quote(tracker, 2.6) == []
    assert horizons(quote(tracker, 6))[0]["horizon_s"] == 5


@pytest.mark.parametrize("reason", ["shutdown", "feed_gap", "window_end"])
def test_terminal_lifecycle_events_preserve_missing_horizons(reason):
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    first = horizons(quote(tracker, 2))
    assert len(first) == 1
    rows = horizons(tracker.expire(now=AT + 3, mono=MONO + 3, reason=reason, window=TICKER))
    assert [row["horizon_s"] for row in rows] == [5, 30]
    assert all(row["reason"] == reason and row.get("hypothetical_net_usd") is None for row in rows)
    assert tracker.expire(now=AT + 4, mono=MONO + 4, reason=reason) == []
    assert quote(tracker, 6) == []


def test_explicit_window_gap_does_not_erase_other_markets():
    tracker = FillMarkouts(AT, MONO)
    other = "KXBTC15M-other"
    observed(tracker)
    observed(tracker, fill(fill_id="fill-2", window=other), window(slug=other))
    gaps = horizons(tracker.expire(now=AT + 1.5, mono=MONO + 1.5,
                                  reason="feed_gap", window=TICKER))
    assert len(gaps) == 3 and {row["window"] for row in gaps} == {TICKER}
    assert quote(tracker, 2) == []
    assert horizons(quote(tracker, 2, book(2, window=other)))[0]["reason"] is None


def test_unknown_own_account_liquidity_cannot_be_counted_as_external_buyers():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    row = horizons(quote(tracker, 2, ownership_unknown=True))[0]
    assert row["reason"] and row.get("hypothetical_net_usd") is None
    assert quote(tracker, 2.1) == []


def test_unverified_account_fees_cannot_produce_a_net_profit_number():
    tracker = FillMarkouts(AT, MONO)
    rows = observed(tracker, fee_verified=False)
    rows += quote(tracker, 2)
    gaps = horizons(rows)
    assert gaps and gaps[0]["reason"] == "fee_unverified"
    assert all(row.get("hypothetical_net_usd") is None for row in gaps)


@pytest.mark.parametrize("fee_precision", [0, -.01, math.nan, math.inf, .001])
def test_unknown_fee_precision_never_produces_net_evidence(fee_precision):
    tracker = FillMarkouts(AT, MONO)
    rows = observed(tracker, fee_precision=fee_precision)
    rows += quote(tracker, 2)
    gaps = horizons(rows)
    assert gaps and all(row.get("hypothetical_net_usd") is None for row in gaps)
    assert all(row["reason"] for row in gaps)
    json.dumps(rows, allow_nan=False)


def test_historical_fill_is_not_backfilled_with_current_book_and_duplicates_are_ignored():
    tracker = FillMarkouts(AT, MONO)
    old = fill(at=AT - 100)
    rows = observed(tracker, old)
    assert rows and any(row.get("reason") == "prior_session_fill" for row in rows)
    assert observed(tracker, old) == []
    assert quote(tracker, 2) == []


def test_completed_fill_stays_deduplicated_across_repeated_account_snapshots():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    assert observed(tracker) == []
    for seconds in (2, 6, 31):
        assert len(horizons(quote(tracker, seconds))) == 1
    assert observed(tracker, observed_at=AT + 40, observed_mono=MONO + 40) == []
    assert quote(tracker, 41) == []


def test_pending_capacity_overflow_is_counted_and_never_rearmed_after_capacity_frees():
    tracker = FillMarkouts(AT, MONO, max_pending=1)
    observed(tracker)
    second = fill(fill_id="fill-overflow")
    gaps = horizons(observed(tracker, second))
    assert len(gaps) == 3 and all(row["reason"] == "pending_overflow" for row in gaps)
    tracker.expire(now=AT + 1.5, mono=MONO + 1.5, reason="feed_gap")
    assert observed(tracker, second, observed_at=AT + 2, observed_mono=MONO + 2) == []
    assert quote(tracker, 3) == []


def test_dedup_memory_is_bounded_and_evicted_fills_cannot_start_again():
    tracker = FillMarkouts(AT, MONO, max_pending=1)
    capacity = tracker.status()["dedup_capacity"]
    assert 0 < capacity <= 32_768
    for index in range(capacity + 1):
        seconds = 1 + index / 100
        observed(tracker, fill(fill_id=f"fill-{index}", at=AT + seconds),
                 observed_at=AT + seconds, observed_mono=MONO + seconds)
        tracker.expire(now=AT + seconds, mono=MONO + seconds, reason="feed_gap")
    status = tracker.status()
    assert status["dedup_entries"] == capacity
    assert status["pending_fills"] == 0
    assert status["counts"]["dedup_evictions"] == 1
    replay = observed(tracker, fill(fill_id="fill-0"),
                      observed_at=AT + 100, observed_mono=MONO + 100)
    assert len(horizons(replay)) == 3
    assert all(row["reason"] == "dedup_retention_boundary" for row in horizons(replay))
    assert quote(tracker, 101) == []
    assert tracker.status()["pending_fills"] == 0


def test_book_admission_query_only_requests_depth_for_due_pending_market_and_side():
    tracker = FillMarkouts(AT, MONO)
    assert not tracker.needs_book(TICKER, "up", MONO + 2)
    observed(tracker)
    assert not tracker.needs_book(TICKER, "up", MONO + 1.99)
    assert not tracker.needs_book(TICKER, "down", MONO + 2)
    assert not tracker.needs_book("KXBTC15M-other", "up", MONO + 2)
    assert tracker.needs_book(TICKER, "up", MONO + 2)
    quote(tracker, 2)
    assert not tracker.needs_book(TICKER, "up", MONO + 2.1)
    assert tracker.needs_book(TICKER, "up", MONO + 6)


def test_horizons_at_or_after_market_close_are_missing_from_admission():
    tracker = FillMarkouts(AT, MONO)
    rows = observed(tracker, spec=window(end=AT + 6))
    gaps = horizons(rows)
    assert [row["horizon_s"] for row in gaps] == [5, 30]
    assert all(row["reason"] == "market_closed" for row in gaps)
    assert horizons(quote(tracker, 2))[0]["reason"] is None
    assert quote(tracker, 6) == []


def test_status_keeps_restart_coverage_and_execution_assumptions_explicit():
    tracker = FillMarkouts(AT, MONO)
    status = tracker.status()
    assert status["session_only"] is True and status["earlier_pending_unknown"] is True
    assert status["restored_pending"] is False
    assert status["not_realized_pnl"] is True and status["exit_latency_not_simulated"] is True
    assert status["pending_fills"] == 0
    assert status["mode"] == "diagnostic" and status["fill_source"] == "real"
    json.dumps(status, allow_nan=False)


@pytest.mark.parametrize("owned", [{.7: math.nan}, {.7: -1}, {math.inf: 5}])
def test_invalid_own_depth_is_missing_not_external_liquidity(owned):
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    rows = horizons(quote(tracker, 2, own_bids=owned))
    assert len(rows) == 1 and rows[0]["reason"] == "own_depth_unknown"
    assert rows[0]["hypothetical_net_usd"] is None
    json.dumps(rows, allow_nan=False)


def test_book_work_bound_rejects_excess_depth_without_a_partial_profit_claim():
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    limit = tracker.status()["max_levels_per_side"]
    bids = tuple(Level(.6 - index * .001, 10) for index in range(limit + 1))
    row = horizons(quote(tracker, 2, book(2, bids)))[0]
    assert row["reason"] == "depth_work_bound" and row["hypothetical_net_usd"] is None
    assert row["book_bid_levels"] == limit + 1
    assert row["protocol_version"] == 2 and row["max_levels_per_side"] == limit


@pytest.mark.parametrize("levels", [154, 512])
def test_deep_fractional_price_book_is_measured_within_the_explicit_bound(levels):
    tracker = FillMarkouts(AT, MONO)
    observed(tracker)
    bids = tuple(Level(round(.7 - index * .001, 8), 10) for index in range(levels))
    row = horizons(quote(tracker, 2, book(2, bids)))[0]
    assert row["reason"] is None and row["filled_size"] == 5
    assert row["consumed_depth"] == [{"price": .7, "size": 5}]
    assert row["book_bid_levels"] == levels and row["book_ask_levels"] == 1
    assert row["own_bid_levels"] == 0 and row["protocol_version"] == 2


def test_busy_book_callback_has_bounded_measurements_and_explicit_unretryable_gaps():
    tracker = FillMarkouts(AT, MONO)
    limit = tracker.status()["max_measurements_per_book"]
    for index in range(limit + 1):
        observed(tracker, fill(fill_id=f"fill-{index}", size=1))
    rows = horizons(quote(tracker, 2))
    assert len(rows) == limit + 1
    measured = [row for row in rows if row["reason"] is None]
    gaps = [row for row in rows if row["reason"] == "callback_work_bound"]
    assert len(measured) == limit and len(gaps) == 1
    assert gaps[0]["hypothetical_net_usd"] is None
    assert quote(tracker, 2.1) == []
    assert tracker.status()["gap_reasons"]["callback_work_bound"] == 1


@pytest.mark.parametrize("changes", [
    {"at": math.nan}, {"price": math.nan}, {"size": math.inf},
    {"fee_usd": math.nan}, {"price": -.1}, {"size": 0},
])
def test_invalid_fill_never_poison_json_or_becomes_profit(changes):
    tracker = FillMarkouts(AT, MONO)
    rows = observed(tracker, fill(**changes))
    rows += quote(tracker, 2)
    json.dumps(rows, allow_nan=False)
    assert rows and all(row.get("hypothetical_net_usd") is None for row in rows)
    assert any(row.get("reason") for row in rows)


def test_future_fill_is_not_silently_retimed_as_received_now():
    tracker = FillMarkouts(AT, MONO)
    rows = observed(tracker, fill(at=AT + 10))
    assert any(row.get("reason") == "fill_timestamp_future" for row in rows)
    assert quote(tracker, 2) == []
