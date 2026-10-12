from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
import requests
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.speeddesk_feeds import (
    LiveFeeds,
    coinbase_ticks,
    parse_books,
    parse_trades,
    parse_window,
    window_slugs,
)

START = datetime(2026, 10, 12, 18, 30, tzinfo=UTC).timestamp()
SLUG = "cpc-btc-updown-15m-2026-10-12-1830z"


def market() -> dict[str, Any]:
    return {"market": {"slug": SLUG, "feeCoefficient": 0.0695, "comboEnabled": False,
                       "orderPriceMinTickSize": 0.01, "minimumTradeQty": 0.01,
                       "endDate": "2026-10-12T19:15:00Z",
                       "description": "This market will settle to Up if the price is greater than or equal to its start.",
                       "assetPriceTerms": {"asset": {"symbol": "btc"}, "indexSymbol": "BRTI",
                                           "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN", "horizon": "15m",
                                           "windowStart": "2026-10-12T18:30:00Z",
                                           "windowEnd": "2026-10-12T18:45:00Z",
                                           "priceToBeat": {"value": "82394.14", "currency": "USD"}}}}


def book() -> dict[str, Any]:
    return {"marketData": {"marketSlug": SLUG, "state": "MARKET_STATE_OPEN",
                           "bids": [{"px": {"value": "0.44"}, "qty": "10"},
                                    {"px": {"value": "0.43"}, "qty": "15"}],
                           "offers": [{"px": {"value": "0.45"}, "qty": "12"},
                                      {"px": {"value": "0.46"}, "qty": "20"}],
                           "transactTime": "2026-10-12T18:30:00.125Z",
                           "stats": {"lastTradePx": {"value": "0.01"}, "lastTradeQty": "99999"}}}


def trade(intent: str = "ORDER_INTENT_SELL_LONG") -> dict[str, Any]:
    return {"trade": {"marketSlug": SLUG, "price": {"value": "0.44", "currency": "USD"},
                      "quantity": {"value": "12.5"}, "tradeTime": "2026-10-12T18:30:00.25Z",
                      "maker": {"side": "ORDER_SIDE_BUY", "intent": "ORDER_INTENT_BUY_LONG"},
                      "taker": {"side": "ORDER_SIDE_SELL", "intent": intent}}}


def test_current_and_next_us_windows_only() -> None:
    assert window_slugs(START + 1) == [SLUG, "cpc-btc-updown-15m-2026-10-12-1845z",
                                     "cpc-btc-updown-1h-2026-10-12-1800z",
                                     "cpc-btc-updown-1h-2026-10-12-1900z"]
    midnight = datetime(2026, 10, 12, 23, 59, tzinfo=UTC).timestamp()
    assert "cpc-btc-updown-15m-2026-10-13-0000z" in window_slugs(midnight)


def test_metadata_uses_actual_window_end_and_verified_fee_schedule() -> None:
    window = parse_window(market(), SLUG)
    assert window is not None
    assert window.start == START
    assert window.end == START + 900  # Not the instrument's +30-minute endDate.
    assert window.venue_start_price == 82394.14
    assert window.start_price is None  # Never pass the BRTI strike off as a Coinbase start tick.
    assert window.maker_coefficient == -0.0125
    assert window.taker_coefficient == 0.0695
    assert window.min_trade_qty == 0.01


@pytest.mark.parametrize(("field", "value"), [("horizon", "5m"), ("indexSymbol", "BINANCE"),
                                             ("marketType", "OTHER"), ("windowEnd", None)])
def test_metadata_rejects_wrong_market(field: str, value: Any) -> None:
    raw = market()
    raw["market"]["assetPriceTerms"][field] = value
    assert parse_window(raw, SLUG) is None


def test_metadata_unknown_fee_does_not_guess_maker_rebate() -> None:
    raw = market()
    raw["market"]["feeCoefficient"] = 0.08
    window = parse_window(raw, SLUG)
    assert window is not None and window.maker_coefficient is None
    raw["market"]["description"] = "Up wins only strictly above."
    assert parse_window(raw, SLUG) is None


def test_books_are_complementary_depth_not_last_trade_stats() -> None:
    up, down = parse_books(book(), START + 0.5)
    assert (up.asks[0].price, up.asks[0].size) == (0.45, 12)
    assert (down.asks[0].price, down.asks[0].size) == (0.56, 10)
    assert (down.bids[0].price, down.bids[0].size) == (0.55, 12)
    assert up.at == START + 0.5 and up.exchange_at == START + 0.125
    assert up.sequence == down.sequence
    assert parse_trades(book(), START + 0.5) == ()


@pytest.mark.parametrize("field", ["bids", "offers", "transactTime"])
def test_partial_book_messages_are_not_full_snapshots(field: str) -> None:
    raw = book()
    del raw["marketData"][field]
    assert parse_books(raw, START) == ()


def test_closed_and_crossed_books_invalidate_earlier_quotes() -> None:
    raw = book()
    raw["marketData"]["state"] = "MARKET_STATE_SUSPENDED"
    assert all(not side.bids and not side.asks for side in parse_books(raw, START))
    raw = book()
    raw["marketData"]["offers"][0]["px"]["value"] = "0.40"
    assert all(not side.bids and not side.asks for side in parse_books(raw, START))


@pytest.mark.parametrize(("intent", "up_aggressor", "down_aggressor"), [
    ("ORDER_INTENT_SELL_LONG", "sell", "buy"), ("ORDER_INTENT_BUY_SHORT", "sell", "buy"),
    ("ORDER_INTENT_BUY_LONG", "buy", "sell"), ("ORDER_INTENT_SELL_SHORT", "buy", "sell"),
])
def test_trade_intent_maps_yes_and_no_conventions(intent: str, up_aggressor: str, down_aggressor: str) -> None:
    up, down = parse_trades(trade(intent), START + 0.75)
    assert (up.price, down.price, up.size) == (0.44, 0.56, 12.5)
    assert up.aggressor == up_aggressor and down.aggressor == down_aggressor
    assert up.at == START + 0.25 and up.received_at == START + 0.75
    assert up.trade_id != down.trade_id
    assert parse_trades(trade(intent), START + 1)[0].trade_id == up.trade_id


@pytest.mark.parametrize("mutate", ["intent", "quantity", "time", "price"])
def test_ambiguous_or_malformed_prints_cannot_fill_makers(mutate: str) -> None:
    raw = trade()
    if mutate == "intent":
        raw["trade"]["taker"]["intent"] = "ORDER_INTENT_UNSPECIFIED"
    elif mutate == "quantity":
        raw["trade"]["quantity"] = {"value": "NaN"}
    elif mutate == "time":
        raw["trade"]["tradeTime"] = "2026-10-12T18:30:00"  # No time zone.
    else:
        raw["trade"]["price"] = {"value": "1.01"}
    assert parse_trades(raw, START) == ()


def test_coinbase_uses_real_btc_usd_trade_timestamps_only() -> None:
    raw = {"channel": "market_trades", "events": [{"trades": [
        {"product_id": "BTC-USD", "price": "81001", "time": "2026-10-12T18:30:01Z"},
        {"product_id": "ETH-USD", "price": "4000", "time": "2026-10-12T18:30:00Z"},
        {"product_id": "BTC-USD", "price": "81000", "time": "2026-10-12T18:30:00Z"},
    ]}]}
    assert coinbase_ticks(raw) == [(81000, START), (81001, START + 1)]
    assert coinbase_ticks({"channel": "heartbeats", "timestamp": "2026-10-12T18:30:00Z"}) == []


def feeds(clock: FakeClock, rest_get: Any, **callbacks: Any) -> LiveFeeds:
    return LiveFeeds(Settings(), on_tick=callbacks.get("on_tick", lambda *_: None),
                     on_book=callbacks.get("on_book", lambda _: None),
                     on_trade=callbacks.get("on_trade", lambda _: None),
                     on_windows=callbacks.get("on_windows", lambda _: None),
                     on_status=callbacks.get("on_status", lambda _: None),
                     clock=clock.now, rest_get=rest_get)


def test_rest_book_fallback_has_one_global_request_per_second_and_no_trade_events() -> None:
    clock = FakeClock(START + 1)
    calls: list[str] = []
    books, trades = [], []

    def get(path: str) -> Any:
        calls.append(path)
        return book()

    feed = feeds(clock, get, on_book=books.append, on_trade=trades.append)
    window = parse_window(market(), SLUG)
    assert window is not None
    feed.windows = {SLUG: window}

    async def run() -> None:
        assert await feed.poll_book()
        assert not await feed.poll_book()
        clock.advance(0.99)
        assert not await feed.poll_book()
        clock.advance(0.01)
        assert await feed.poll_book()

    asyncio.run(run())
    assert len(calls) == 2 and len(books) == 4 and not trades
    assert all(row.source == "rest" for row in books)


def test_rest_failure_still_consumes_rate_limit() -> None:
    clock = FakeClock(START + 1)
    calls: list[str] = []

    def fail(path: str) -> Any:
        calls.append(path)
        raise TimeoutError("do not echo response details")

    feed = feeds(clock, fail)
    window = parse_window(market(), SLUG)
    assert window is not None
    feed.windows = {SLUG: window}
    assert asyncio.run(feed.poll_book())
    assert not asyncio.run(feed.poll_book())
    assert len(calls) == 1


def test_rest_book_records_request_start_separately_from_response_receipt() -> None:
    clock = FakeClock(START + 1)
    received = []

    def get(_: str) -> Any:
        clock.advance(0.75)
        return book()

    feed = feeds(clock, get, on_book=received.append)
    window = parse_window(market(), SLUG)
    assert window is not None
    feed.windows[SLUG] = window
    asyncio.run(feed.poll_book())
    assert all(row.requested_at == START + 1 and row.at == START + 1.75 for row in received)


def test_rate_limit_response_backs_off_without_logging_response_details(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock(START + 1)
    calls: list[str] = []

    def get(path: str) -> Any:
        calls.append(path)
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError("private response details", response=response)

    feed = feeds(clock, get)
    window = parse_window(market(), SLUG)
    assert window is not None
    feed.windows[SLUG] = window
    assert asyncio.run(feed.poll_book())
    clock.advance(29)
    assert not asyncio.run(feed.poll_book())
    clock.advance(1)
    assert asyncio.run(feed.poll_book())
    assert len(calls) == 2
    assert "http_status=429" in caplog.text
    assert "private response details" not in caplog.text


@pytest.mark.parametrize("reply,expected", [(None, None), ({"settlement": None}, None),
                                           ({"settlement": 0.5}, None), ({"settlement": 0}, 0),
                                           ({"settlement": 1}, 1),
                                           ({"settlement": 1, "slug": "wrong"}, None)])
def test_settlement_books_only_explicit_binary_venue_outcome(reply: Any, expected: Any) -> None:
    feed = feeds(FakeClock(START), lambda _: reply)
    assert asyncio.run(feed.settlement(SLUG)) == expected


def test_refresh_uses_only_current_next_metadata_and_no_orders_or_books() -> None:
    calls: list[str] = []
    windows: list[Any] = []

    def get(path: str) -> Any:
        calls.append(path)
        return deepcopy(market()) if path.endswith(SLUG) else None

    feed = feeds(FakeClock(START + 1), get, on_windows=windows.append)
    asyncio.run(feed.refresh_windows())
    assert len(calls) == 4
    assert all(path.startswith("/v1/market/slug/cpc-btc-updown-") for path in calls)
    assert [row.slug for row in windows[0]] == [SLUG]


def test_missing_market_credentials_explicitly_disable_trade_stream() -> None:
    statuses: list[Any] = []
    feed = feeds(FakeClock(START), lambda _: None, on_status=statuses.append)
    asyncio.run(feed._markets())
    assert statuses[-1]["markets"] == "missing_credentials_rest_only"
    assert statuses[-1]["trade_stream"] is False


def test_trade_stream_is_confirmed_by_a_current_print_and_disabled_immediately_on_close() -> None:
    statuses: list[Any] = []
    feed = feeds(FakeClock(START + 1), lambda _: None, on_status=statuses.append)
    window = parse_window(market(), SLUG)
    assert window is not None
    feed.windows = {SLUG: window}
    feed._market_connected = True
    old = trade()
    old["trade"]["tradeTime"] = "2026-10-12T18:29:00Z"
    feed._trade(old)
    assert statuses == []
    feed._trade(trade())
    assert statuses[-1]["trade_stream"] is True
    feed._ws_closed()
    assert statuses[-1]["trade_stream"] is False
    assert not feed._market_connected
