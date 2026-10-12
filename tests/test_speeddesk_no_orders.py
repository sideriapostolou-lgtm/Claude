"""The practice desk may read authenticated markets, never the order client."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from dataclasses import replace
from datetime import UTC, datetime
from types import ModuleType
from typing import Any, Self

from fakes import FakeClock

from nightcrawler import polymarket_us
from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_feeds import LiveFeeds, window_slugs
from nightcrawler.speeddesk_model import Book, Level, Trade, Window


class NoOrdersSDK:
    """Count forbidden access even if a reconnect loop catches the assertion."""

    def __init__(self, book: dict[str, Any], trade: dict[str, Any]) -> None:
        self.forbidden_accesses: list[str] = []
        self.ws = self
        self.book = book
        self.trade = trade
        self.handlers: dict[str, Any] = {}
        self.subscriptions: list[str] = []
        self.is_connected = False
        self.closed = False

    @property
    def orders(self) -> Any:
        self.forbidden_accesses.append("orders")
        raise AssertionError("Practice accessed the SDK order resource")

    def private(self) -> Any:
        self.forbidden_accesses.append("private")
        raise AssertionError("Practice accessed the private account stream")

    def markets(self) -> NoOrdersSDK:
        return self

    def on(self, event: str, handler: Any) -> NoOrdersSDK:
        self.handlers[event] = handler
        return self

    async def connect(self) -> None:
        self.is_connected = True

    async def subscribe_market_data(self, request_id: str, slugs: list[str]) -> None:
        self.subscriptions.append(request_id)
        assert self.book["marketData"]["marketSlug"] in slugs
        self.handlers["market_data"](self.book)

    async def subscribe_trades(self, request_id: str, slugs: list[str]) -> None:
        self.subscriptions.append(request_id)
        assert self.trade["trade"]["marketSlug"] in slugs
        self.handlers["trade"](self.trade)

    async def unsubscribe(self, request_id: str) -> None:
        self.subscriptions.remove(request_id)

    async def socket_close(self) -> None:
        self.is_connected = False

    def close(self) -> None:
        self.closed = True


class MarketSocket:
    """SDK client.close is synchronous; its markets socket.close is async."""

    def __init__(self, sdk: NoOrdersSDK) -> None:
        self.sdk = sdk

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sdk, name)

    async def close(self) -> None:
        await self.sdk.socket_close()


class CoinbaseSocket:
    def __init__(self, tick: dict[str, Any]) -> None:
        self.tick = tick
        self.sent: list[dict[str, Any]] = []
        self.received = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        if not self.received:
            self.received = True
            return json.dumps(self.tick)
        await asyncio.Future()
        raise AssertionError("Unreachable")


def test_live_practice_inputs_never_access_sdk_orders(monkeypatch: Any, tmp_path: Any) -> None:
    """Exercise real feed startup, both streams, REST fallback, settlement and shutdown."""
    clock = FakeClock()
    now = clock.now()
    slug = window_slugs(now)[0]
    stamp = datetime.fromtimestamp(now, UTC).isoformat()
    book = {"marketData": {
        "marketSlug": slug, "state": "MARKET_STATE_OPEN", "transactTime": stamp,
        "bids": [{"px": {"value": "0.45"}, "qty": "12"}],
        "offers": [{"px": {"value": "0.55"}, "qty": "15"}],
    }}
    trade = {"trade": {
        "marketSlug": slug, "price": {"value": "0.45"}, "quantity": {"value": "3"},
        "tradeTime": stamp, "taker": {"intent": "ORDER_INTENT_SELL_LONG", "side": "SELL"},
        "maker": {"intent": "ORDER_INTENT_BUY_LONG", "side": "BUY"},
    }}
    sdk = NoOrdersSDK(book, trade)
    monkeypatch.setattr(sdk, "markets", lambda: MarketSocket(sdk))
    forbidden_live_calls: list[str] = []

    def no_live_wrapper(*_: Any, **__: Any) -> Any:
        forbidden_live_calls.append("PolymarketUSClient")
        raise AssertionError("Practice imported the real-money order wrapper")

    monkeypatch.setattr(polymarket_us, "PolymarketUSClient", no_live_wrapper)
    rest_calls: list[str] = []

    def rest_get(path: str) -> Any:
        rest_calls.append(path)
        if path == f"/v1/market/slug/{slug}":
            return {"market": {
                "slug": slug, "description": "This market will settle to Up if greater than or equal.",
                "comboEnabled": False, "feeCoefficient": "0.0695", "orderPriceMinTickSize": "0.01",
                "minimumTradeQty": "0.01",
                "assetPriceTerms": {
                    "asset": {"symbol": "BTC"}, "indexSymbol": "BRTI", "horizon": "15m",
                    "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN", "windowStart": stamp,
                    "windowEnd": datetime.fromtimestamp(now + 900, UTC).isoformat(),
                    "priceToBeat": {"value": "80000"},
                },
            }}
        if path == f"/v1/markets/{slug}/book":
            return book
        if path == f"/v1/markets/{slug}/settlement":
            return {"slug": slug, "settlement": 1}
        assert path.startswith("/v1/market/slug/")
        return None

    coinbase = CoinbaseSocket({"channel": "market_trades", "events": [{"trades": [{
        "product_id": "BTC-USD", "price": "80001", "time": stamp,
    }]}]})
    ticks: list[Any] = []
    books: list[Any] = []
    trades: list[Any] = []
    statuses: list[Any] = []
    windows: list[Any] = []
    stop = threading.Event()

    def on_trade(value: Any) -> None:
        trades.append(value)
        stop.set()

    settings = Settings(data_dir=tmp_path, polymarket_us_key_id="test-only-id",
                        polymarket_us_secret_key="test-only-not-a-secret")
    feeds = LiveFeeds(settings, sdk_client=sdk, rest_get=rest_get, clock=clock.now,
                      coinbase_connect=lambda *_args, **_kwargs: coinbase,
                      on_tick=lambda *args: ticks.append(args), on_book=books.append,
                      on_trade=on_trade, on_windows=windows.append, on_status=statuses.append)

    async def scenario() -> None:
        await feeds.refresh_windows()
        assert await feeds.poll_book()
        assert await feeds.settlement(slug) == 1
        await asyncio.wait_for(feeds.run(stop), timeout=3)

    asyncio.run(scenario())
    assert sdk.forbidden_accesses == []
    assert forbidden_live_calls == []
    assert sdk.closed
    assert len(sdk.subscriptions) == 2
    assert ticks and books and trades and windows
    assert any(status.get("trade_stream") for status in statuses)
    assert any(status.get("trade_stream") is False for status in statuses)
    assert f"/v1/markets/{slug}/settlement" in rest_calls
    assert f"/v1/markets/{slug}/book" in rest_calls
    assert {message["channel"] for message in coinbase.sent} == {"market_trades", "heartbeats"}


def test_practice_strategy_takes_rests_cancels_and_settles_without_order_access(
    monkeypatch: Any, tmp_path: Any,
) -> None:
    """The runtime's active strategy paths face the same poisoned SDK resource."""
    clock = FakeClock()
    sdk = NoOrdersSDK({}, {})
    sdk_module = ModuleType("polymarket_us")
    monkeypatch.setattr(sdk_module, "PolymarketUS", lambda *_args, **_kwargs: sdk, raising=False)
    monkeypatch.setitem(sys.modules, "polymarket_us", sdk_module)
    forbidden_live_calls: list[str] = []

    def no_live_wrapper(*_: Any, **__: Any) -> Any:
        forbidden_live_calls.append("PolymarketUSClient")
        raise AssertionError("Practice accessed the existing real-order client")

    monkeypatch.setattr(polymarket_us, "PolymarketUSClient", no_live_wrapper)
    slug = window_slugs(clock.now())[0]

    def rest_get(path: str) -> Any:
        assert path == f"/v1/markets/{slug}/settlement"
        return {"slug": slug, "settlement": 1}

    def factory(settings: Settings, **callbacks: Any) -> LiveFeeds:
        return LiveFeeds(settings, sdk_client=sdk, rest_get=rest_get, **callbacks)

    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=factory)
    try:
        monkeypatch.setattr(runner.feeds, "maker_windows", lambda: {slug}, raising=False)
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=0)
        runner.desk.tick_btc(79999, clock.now() - 2)
        runner.desk.tick_btc(80000, clock.now() - 1)
        runner.on_windows([Window(slug, clock.now(), clock.now() + 900, maker_coefficient=0)])
        runner.on_tick(80000, clock.now(), clock.now())
        runner.on_status({"coinbase": "connected", "markets": "connected", "trade_stream": True})

        def books(sequence: str) -> None:
            runner.on_book(Book(slug, "up", (Level(0.39, 10),), (Level(0.4, 25),),
                                clock.now(), sequence, clock.now()))
            runner.on_book(Book(slug, "down", (Level(0.3, 10),), (Level(0.61, 25),),
                                clock.now(), sequence, clock.now()))

        books("decision")
        runner.step(clock.now())
        assert any(order.kind == "take" for order in runner.desk.orders.values())
        clock.advance(0.3)
        books("latency-recheck")
        runner.step(clock.now())
        assert runner.desk.inventory[slug].up.shares == 25
        assert any(order.kind == "rest" and order.side == "down" for order in runner.desk.orders.values())
        clock.advance(0.3)
        runner.on_trade(Trade(slug, "down", 0.46, 2, clock.now(), "genuine-print", "sell", clock.now()))
        assert runner.desk.inventory[slug].down.shares == 2
        runner.on_status({"coinbase": "connected", "markets": "disconnected", "trade_stream": False})
        assert not runner.desk.orders
        clock.advance(901)

        async def settle() -> None:
            task = asyncio.create_task(runner._settlements())
            try:
                for _ in range(100):
                    if runner.desk.closed:
                        break
                    await asyncio.sleep(0.001)
                assert len(runner.desk.closed) == 1
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        asyncio.run(settle())
        assert runner.ledger.verify_chain() == (True, None)
        assert sdk.forbidden_accesses == []
        assert forbidden_live_calls == []
        kinds = {receipt.kind for receipt in runner.ledger.receipts()}
        assert {"speeddesk_take", "speeddesk_rest", "speeddesk_fill", "speeddesk_cancel", "speeddesk_window"} <= kinds
    finally:
        runner.close()
