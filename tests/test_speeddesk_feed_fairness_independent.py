"""Independent message-boundary checks with inline buffered Coinbase transports."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self

import pytest

from nightcrawler.config import Settings
from nightcrawler.speeddesk_feeds import COINBASE_EXCHANGE_WS, COINBASE_WS, LiveFeeds

NOW = 1792019700.0


def stamp(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat()


def match(identity: int, at: float = NOW, price: float = 80000) -> str:
    return json.dumps({"type": "match", "product_id": "BTC-USD", "trade_id": identity,
                       "price": str(price), "time": stamp(at)})


def batch(rows: list[tuple[int, float, float]]) -> str:
    return json.dumps({"channel": "market_trades", "events": [{"type": "update", "trades": [
        {"product_id": "BTC-USD", "trade_id": str(identity), "price": str(price), "time": stamp(at)}
        for identity, at, price in rows]}]})


class Buffered:
    def __init__(self, messages: list[str]) -> None:
        self.messages = deque(messages)
        self.received = 0
        self.sent: list[str] = []
        self.on_receive: Callable[[], None] = lambda: None
        self.drained = asyncio.Event()
        self.closed = asyncio.Event()
        self.exit_exception: BaseException | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _kind: object, error: BaseException | None, _traceback: object) -> None:
        self.exit_exception = error
        self.closed.set()

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if self.messages:
            self.received += 1
            self.on_receive()
            return self.messages.popleft()
        self.drained.set()
        await asyncio.Future()
        raise AssertionError("unreachable")


def make_feed(socket: Buffered, ticks: list[tuple[float, float, float]], *,
              clock: Callable[[], float] = lambda: NOW) -> LiveFeeds:
    return LiveFeeds(Settings(), on_tick=lambda *args: ticks.append(args), on_book=lambda _: None,
                     on_trade=lambda _: None, on_windows=lambda _: None, on_status=lambda _: None,
                     clock=clock, coinbase_connect=lambda *_args, **_kwargs: socket)


@pytest.mark.parametrize("kind", ["heartbeat", "duplicate", "future", "other_product"])
def test_nondelivering_buffered_messages_still_allow_ready_work(kind: str) -> None:
    async def scenario() -> None:
        payload = {"heartbeat": json.dumps({"type": "heartbeat"}), "duplicate": match(7),
                   "future": match(7, NOW + 1),
                   "other_product": match(7).replace("BTC-USD", "ETH-USD")}[kind]
        socket = Buffered([payload] * 16)
        ticks: list[tuple[float, float, float]] = []
        feed = make_feed(socket, ticks)
        if kind == "duplicate":
            feed._seen_trades.add(7)
        ready = asyncio.get_running_loop().create_future()
        socket.on_receive = lambda: ready.set_result(None) if not ready.done() else None

        async def observer() -> int:
            await ready
            return socket.received

        observing = asyncio.create_task(observer())
        await asyncio.sleep(0)
        task = asyncio.create_task(feed._coinbase_feed("exchange_a", COINBASE_EXCHANGE_WS))
        try:
            assert await asyncio.wait_for(observing, 2) == 1
            await asyncio.wait_for(socket.drained.wait(), 2)
            assert socket.received == 16 and not ticks
            if kind == "future":
                assert 7 not in feed._seen_trades
                assert feed._future_stamped["exchange_a"] == 16
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_advanced_message_finishes_sorted_ticks_on_one_receipt_before_yield() -> None:
    async def scenario() -> None:
        socket = Buffered([batch([(3, NOW, 80003), (1, NOW - .2, 80001), (2, NOW - .1, 80002)]),
                           batch([(4, NOW, 80004)])])
        ticks: list[tuple[float, float, float]] = []
        clock = [NOW]
        ready = asyncio.get_running_loop().create_future()
        feed = make_feed(socket, ticks, clock=lambda: clock[0])

        def on_tick(price: float, at: float, received: float) -> None:
            ticks.append((price, at, received))
            clock[0] += .125
            if not ready.done():
                ready.set_result(None)

        feed.on_tick = on_tick

        async def observer() -> tuple[int, list[tuple[float, float, float]]]:
            await ready
            return socket.received, list(ticks)

        observing = asyncio.create_task(observer())
        await asyncio.sleep(0)
        task = asyncio.create_task(feed._coinbase_feed("advanced_trade", COINBASE_WS))
        try:
            received, first = await asyncio.wait_for(observing, 2)
            assert received == 1
            assert [row[0] for row in first] == [80001, 80002, 80003]
            assert [row[2] for row in first] == [NOW] * 3
            await asyncio.wait_for(socket.drained.wait(), 2)
            assert ticks[-1] == (80004, NOW, NOW + .375)
            assert feed._seen_trades == {1, 2, 3, 4}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancellation_at_boundary_keeps_whole_message_and_leaves_next_unread() -> None:
    async def scenario() -> None:
        socket = Buffered([batch([(1, NOW, 80001), (2, NOW, 80002)]), batch([(3, NOW, 80003)])])
        ticks: list[tuple[float, float, float]] = []
        feed = make_feed(socket, ticks)
        ready = asyncio.get_running_loop().create_future()
        task: asyncio.Task[None]

        def on_tick(*values: float) -> None:
            ticks.append(values)
            if not ready.done():
                ready.set_result(None)

        feed.on_tick = on_tick

        async def cancel_at_boundary() -> None:
            await ready
            task.cancel()

        cancelling = asyncio.create_task(cancel_at_boundary())
        await asyncio.sleep(0)
        task = asyncio.create_task(feed._coinbase_feed("advanced_trade", COINBASE_WS))
        with pytest.raises(asyncio.CancelledError):
            await task
        await cancelling
        assert [row[0] for row in ticks] == [80001, 80002]
        assert socket.received == 1 and len(socket.messages) == 1
        assert isinstance(socket.exit_exception, asyncio.CancelledError)
        assert socket.closed.is_set()
        # Existing cancellation semantics: no invented connection-error transition.
        assert feed._coinbase_up["advanced_trade"] is True

    asyncio.run(scenario())


def test_callback_failure_reaches_socket_exit_before_reconnect_and_next_message() -> None:
    async def scenario() -> None:
        socket = Buffered([batch([(1, NOW, 80001), (2, NOW, 80002)]), batch([(3, NOW, 80003)])])
        ticks: list[tuple[float, float, float]] = []
        feed = make_feed(socket, ticks)
        error = RuntimeError("synthetic callback failure")

        def fail(*_values: float) -> None:
            raise error

        feed.on_tick = fail
        task = asyncio.create_task(feed._coinbase_feed("advanced_trade", COINBASE_WS))
        try:
            await asyncio.wait_for(socket.closed.wait(), 2)
            assert socket.exit_exception is error
            assert socket.received == 1 and len(socket.messages) == 1
            assert feed._seen_trades == {1}
            assert not feed._coinbase_up["advanced_trade"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
