from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.speeddesk_kalshi import (
    KalshiFeeds,
    parse_books,
    parse_trades,
    parse_window,
)

START = datetime(2026, 10, 12, 18, 30, tzinfo=UTC).timestamp()
TICKER = "KXBTC15M-26OCT121445-45"
SERIES = {"ticker": "KXBTC15M", "fee_type": "quadratic", "fee_multiplier": 1, "frequency": "fifteen_min"}


def market() -> dict[str, Any]:
    return {"ticker": TICKER, "event_ticker": "KXBTC15M-26OCT121445", "open_time": "2026-10-12T18:30:00Z",
            "close_time": "2026-10-12T18:45:00Z", "expiration_time": "2026-10-19T18:45:00Z",
            "market_type": "binary", "notional_value_dollars": "1.0000", "status": "active",
            "strike_type": "greater_or_equal", "floor_strike": 82394.14,
            "rules_primary": "If the simple average of the sixty seconds of CF Benchmarks' BRTI at the end "
                             "is at least the start average, then the market resolves to Yes.",
            "price_ranges": [{"start": "0", "end": "0.1", "step": "0.001"},
                             {"start": "0.1", "end": "0.9", "step": "0.01"},
                             {"start": "0.9", "end": "1", "step": "0.001"}]}


def book() -> dict[str, Any]:
    return {"orderbook_fp": {"yes_dollars": [["0.39", "12.25"], ["0.40", "14.5"]],
                              "no_dollars": [["0.58", "12"], ["0.59", "20.5"]]}}


def trade(identity: str = "print-1", direction: str = "no") -> dict[str, Any]:
    return {"ticker": TICKER, "trade_id": identity, "created_time": "2026-10-12T18:30:00.5Z",
            "is_block_trade": False, "count_fp": "2.25", "yes_price_dollars": "0.4",
            "no_price_dollars": "0.6", "taker_outcome_side": direction,
            "taker_book_side": "ask" if direction == "no" else "bid"}


def test_actual_rules_and_series_fees_are_required_before_a_window_exists() -> None:
    window = parse_window(market(), SERIES, START + 1)
    assert window is not None
    assert (window.start, window.end) == (START, START + 900)
    assert window.venue_start_price == 82394.14 and window.start_price is None
    assert (window.taker_coefficient, window.maker_coefficient) == (0.07, 0)
    assert (window.venue, window.fee_rounding, window.min_trade_qty) == ("kalshi", "kalshi", 0.01)


@pytest.mark.parametrize("field,value", [("rules_primary", "Coinbase wins strictly above."),
                                         ("strike_type", "greater"), ("ticker", "KXETH15M-example-45"),
                                         ("market_type", "scalar"), ("notional_value_dollars", "100.0000")])
def test_unknown_or_wrong_rules_fail_closed(field: str, value: Any) -> None:
    raw = market()
    raw[field] = value
    assert parse_window(raw, SERIES, START) is None


def test_unknown_fee_scheme_fails_closed_but_documented_maker_fee_is_read() -> None:
    assert parse_window(market(), {**SERIES, "fee_type": "flat"}, START) is None
    window = parse_window(market(), {**SERIES, "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 2}, START)
    assert window is not None
    assert (window.taker_coefficient, window.maker_coefficient) == (0.14, 0.035)


def test_only_current_and_next_windows_are_selected() -> None:
    assert parse_window(market(), SERIES, START + 901) is None
    assert parse_window(market(), SERIES, START - 901) is None
    assert parse_window(market(), SERIES, START - 899) is not None


def test_books_use_fixed_point_bid_depth_and_complementary_asks() -> None:
    up, down = parse_books(book(), TICKER, START)
    assert (up.bids[0].price, up.bids[0].size) == (0.4, 14.5)
    assert (up.asks[0].price, up.asks[0].size) == (0.41, 20.5)
    assert (down.asks[0].price, down.asks[0].size) == (0.6, 14.5)
    assert up.source == "rest" and up.exchange_at is None
    assert parse_trades([book()], TICKER, START) == ()


def test_empty_side_and_crossed_book_do_not_invent_depth() -> None:
    raw = book()
    raw["orderbook_fp"]["yes_dollars"] = []
    up, down = parse_books(raw, TICKER, START)
    assert not up.bids and not down.asks
    raw["orderbook_fp"]["yes_dollars"] = [["0.5", "100"]]
    assert all(not side.bids and not side.asks for side in parse_books(raw, TICKER, START))
    raw["orderbook_fp"]["yes_dollars"] = [["0.4", "0.001"]]
    assert parse_books(raw, TICKER, START) == ()


@pytest.mark.parametrize("direction,up_sell", [("yes", False), ("no", True)])
def test_only_true_public_trade_prints_with_unambiguous_direction(direction: str, up_sell: bool) -> None:
    up, down = sorted(parse_trades([trade(direction=direction)], TICKER, START + 1), key=lambda x: x.side == "down")
    assert (up.side, up.price, up.size) == ("up", 0.4, 2.25)
    assert (up.aggressor == "sell") is up_sell
    assert (down.aggressor == "sell") is not up_sell
    assert up.trade_id == "kalshi:print-1:up"


@pytest.mark.parametrize("field,value", [("is_block_trade", True), ("taker_book_side", "bid"),
                                         ("trade_id", ""), ("count_fp", "NaN"), ("count_fp", "0.001"),
                                         ("no_price_dollars", "0.7")])
def test_block_or_ambiguous_prints_never_fill_queue(field: str, value: Any) -> None:
    raw = trade()
    raw[field] = value
    assert parse_trades([raw], TICKER, START + 1) == ()


def feeds(clock: FakeClock, get: Any, **callbacks: Any) -> KalshiFeeds:
    return KalshiFeeds(Settings(), on_tick=lambda *_: None, on_book=callbacks.get("on_book", lambda _: None),
                       on_trade=callbacks.get("on_trade", lambda _: None),
                       on_windows=callbacks.get("on_windows", lambda _: None),
                       on_status=callbacks.get("on_status", lambda _: None), clock=clock.now, rest_get=get)


def test_public_discovery_checks_event_overrides_and_never_calls_account_or_order_paths() -> None:
    calls: list[str] = []

    def get(path: str) -> Any:
        calls.append(path)
        if path == "/series/KXBTC15M":
            return {"series": SERIES}
        if path.startswith("/markets?"):
            return {"markets": [market()], "cursor": ""}
        if path.startswith("/events/fee_changes?"):
            return {"event_fee_changes": [], "cursor": ""}
        raise AssertionError("No other endpoint is allowed")

    feed = feeds(FakeClock(START), get)
    asyncio.run(feed.refresh_windows())
    assert list(feed.windows) == [TICKER]
    assert len(calls) == 3
    query = parse_qs(urlsplit(next(path for path in calls if path.startswith("/markets?"))).query)
    assert query["min_close_ts"] == [str(int(START) + 1)]
    assert query["max_close_ts"] == [str(int(START) + 1800)]


def test_unknown_event_fee_override_blocks_window() -> None:
    def get(path: str) -> Any:
        if path.startswith("/series/"):
            return {"series": SERIES}
        if path.startswith("/markets?"):
            return {"markets": [market()]}
        return {"event_fee_changes": [{"fee_type_override": "flat"}]}

    feed = feeds(FakeClock(START), get)
    asyncio.run(feed.refresh_windows())
    assert not feed.windows


def test_books_globally_at_most_two_requests_per_second_even_when_failing() -> None:
    clock = FakeClock(START + 1)
    calls: list[str] = []

    def get(path: str) -> Any:
        calls.append(path)
        raise TimeoutError

    feed = feeds(clock, get)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window

    async def run() -> None:
        assert await feed.poll_book()
        clock.advance(0.49)
        assert not await feed.poll_book()
        clock.advance(0.01)
        assert await feed.poll_book()

    asyncio.run(run())
    assert len(calls) == 2


def test_rest_confirmation_retains_request_start_and_receipt_clocks() -> None:
    clock = FakeClock(START + 1)
    received = []

    def get(_: str) -> Any:
        clock.advance(0.7)
        return book()

    feed = feeds(clock, get, on_book=received.append)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window
    assert asyncio.run(feed.poll_book())
    assert all(row.requested_at == START + 1 and row.at == START + 1.7 for row in received)


def test_trade_pages_are_completed_before_any_print_is_delivered() -> None:
    clock = FakeClock(START + 1)
    events: list[Any] = []
    calls: list[str] = []

    def get(path: str) -> Any:
        calls.append(path)
        assert not events
        if "cursor=" not in path:
            return {"trades": [trade("new")], "cursor": "next"}
        old = trade("old")
        old["created_time"] = "2026-10-12T18:30:00.1Z"
        return {"trades": [old], "cursor": ""}

    feed = feeds(clock, get, on_trade=events.append)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window
    assert asyncio.run(feed.poll_trades())
    assert len(calls) == 2 and len(events) == 4
    assert events[0].at < events[-1].at
    assert feed._status["trade_stream"] is True
    assert not asyncio.run(feed.poll_trades())


def test_missing_trade_page_disables_makers_without_replaying_partial_tape() -> None:
    events: list[Any] = []

    def get(path: str) -> Any:
        if "cursor=" not in path:
            return {"trades": [trade()], "cursor": "next"}
        raise TimeoutError

    feed = feeds(FakeClock(START + 1), get, on_trade=events.append)
    window = parse_window(market(), SERIES, START)
    assert window is not None
    feed.windows[TICKER] = window
    feed._status["trade_stream"] = True
    asyncio.run(feed.poll_trades())
    assert events == []
    assert feed._status["trade_stream"] is False
    assert feed._status["markets"] == "trade_tape_gap"


@pytest.mark.parametrize("status,result,value,expected", [("finalized", "yes", "1.0000", 1),
    ("finalized", "no", "0.0000", 0), ("closed", "yes", "1.0000", None),
    ("finalized", "no", "1.0000", None), ("finalized", "", "0.0000", None)])
def test_settlement_requires_final_venue_result_and_matching_payout(status: str, result: str,
                                                                  value: str, expected: Any) -> None:
    feed = feeds(FakeClock(START), lambda _: {"market": {"ticker": TICKER, "status": status,
                                                       "result": result, "settlement_value_dollars": value}})
    assert asyncio.run(feed.settlement(TICKER)) == expected
