"""Coinbase clock skew, dedupe, failover, reconnect replays and the stale-feed cancel (speed step 4).

The latency review of 2026-10-13, kept as regression tests. Two of its findings are fixed here: a copy refused for
its future stamp no longer uses up the trade id (a later copy inside the bound is delivered), and the stale-feed
cancel counts from the local receipt when a tick was stamped ahead of the local clock.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_coinbase import Replay
from test_speeddesk_live import TICKER, make_desk
from test_speeddesk_snapshot_cache import Companion, Feeds

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_feeds import (
    COINBASE_EXCHANGE_WS,
    COINBASE_WS,
    LiveFeeds,
)
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_metrics import TickReceipt
from nightcrawler.speeddesk_model import FUTURE_SKEW_S


def match(trade_id: int, at_iso: str, price: str = "83000.00", kind: str = "match") -> str:
    return json.dumps({"type": kind, "trade_id": trade_id, "price": price, "product_id": "BTC-USD",
                       "size": "0.001", "side": "buy", "time": at_iso})


def at_trade(trade_id: int, at_iso: str, price: str = "83000.00", kind: str = "update") -> str:
    return json.dumps({"channel": "market_trades", "events": [{"type": kind, "trades": [
        {"product_id": "BTC-USD", "trade_id": str(trade_id), "price": price, "size": "0.001", "time": at_iso,
         "side": "BUY"}]}]})


class Timed(Replay):
    """Replay whose recv advances the shared fake clock to each message's local receipt time first."""

    def __init__(self, rows: list[tuple[float, str]], clock: FakeClock, then: str = "open") -> None:
        super().__init__([message for _at, message in rows], then)
        self.times = [at for at, _message in rows]
        self.clock = clock

    async def recv(self) -> str:
        await asyncio.sleep(0)
        if self.rows:
            at = self.times.pop(0)
            if at > self.clock.now():
                self.clock.set(at)
            return self.rows.pop(0)
        return await super().recv()


def runner_with_feeds(tmp_path: Path, clock: FakeClock, sockets: dict[str, list[Any]], rounds: int = 200,
                      statuses: list[dict[str, Any]] | None = None) -> tuple[SpeedRunner, list[tuple[float, float, float]]]:
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=Feeds,
                         live_factory=Companion)
    delivered: list[tuple[float, float, float]] = []

    def on_tick(price: float, at: float, received: float) -> None:
        delivered.append((price, at, received))
        runner.on_tick(price, at, received)

    feed = LiveFeeds(Settings(), on_tick=on_tick, on_book=lambda _: None, on_trade=lambda _: None,
                     on_windows=lambda _: None,
                     on_status=(statuses.append if statuses is not None else lambda _: None), clock=clock.now,
                     coinbase_connect=lambda url, **_kw: sockets[url].pop(0))

    async def scenario() -> None:
        task = asyncio.create_task(feed._coinbase())
        for _ in range(rounds):
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    return runner, delivered


def test_a_copy_refused_for_its_future_stamp_does_not_use_up_the_trade_id(tmp_path: Path) -> None:
    """Local clock 300 ms behind Coinbase: both Exchange copies (40 ms wire) are 260 ms "early" and refused; the
    Advanced Trade copy of the same trade (100 ms wire) is 200 ms early and acceptable. Dedupe used to consume the
    id on the first refused copy, so the tick never arrived while the status read "connected"."""
    clock = FakeClock(1_791_917_600.0)
    stamp = 1_791_917_623.500
    iso = "2026-10-13T18:53:43.500000Z"
    local = stamp - 0.300
    sockets = {COINBASE_EXCHANGE_WS: [Timed([(local + .040, match(1, iso))], clock),
                                      Timed([(local + .041, match(1, iso))], clock)],
               COINBASE_WS: [Timed([(local + .100, at_trade(1, iso))], clock)]}
    statuses: list[dict[str, Any]] = []
    runner, delivered = runner_with_feeds(tmp_path, clock, sockets, statuses=statuses)
    try:
        assert len(delivered) == 1 and delivered[0][2] - delivered[0][1] == pytest.approx(-.20)
        assert runner.desk.tape.price == 83000  # the backup copy reached the runner
        # The refusals are counted per connection in the status (first one reported at once).
        reported = [status["coinbase_future_stamped"] for status in statuses if "coinbase_future_stamped" in status]
        assert reported and reported[0]["exchange_a"] + reported[0]["exchange_b"] >= 1
    finally:
        runner.close()


def test_reconnect_replays_are_not_ticks(tmp_path: Path) -> None:
    """Exchange reconnects (last_match repeats trade 2) and Advanced Trade reconnects (snapshot repeats 1-2)."""
    clock = FakeClock(1_791_917_600.0)
    base = 1_791_917_623.0
    iso = lambda s: f"2026-10-13T18:53:{43 + s:02d}.000000Z"
    first = [(base + .05, match(1, iso(0))), (base + 1.05, match(2, iso(1)))]
    again = [(base + 1.5, match(2, iso(1), kind="last_match")), (base + 2.05, match(3, iso(2)))]
    snap = json.dumps({"channel": "market_trades", "events": [{"type": "snapshot", "trades": [
        {"product_id": "BTC-USD", "trade_id": "2", "price": "83000", "size": "1", "time": iso(1), "side": "BUY"},
        {"product_id": "BTC-USD", "trade_id": "1", "price": "83000", "size": "1", "time": iso(0), "side": "BUY"}]}]})
    sockets = {COINBASE_EXCHANGE_WS: [Timed(first, clock, then="close"), Timed(again, clock),
                                      Timed([], clock)],
               COINBASE_WS: [Timed([(base + .2, snap)], clock, then="close"), Timed([(base + 2.2, snap)], clock)]}
    runner, delivered = runner_with_feeds(tmp_path, clock, sockets, rounds=400)
    try:
        assert sorted(at for _p, at, _r in delivered) == [base, base + 1, base + 2]
    finally:
        runner.close()


def test_a_future_stamped_last_tick_no_longer_delays_the_stale_feed_cancel(tmp_path: Path) -> None:
    """The newest tick was stamped 0.24 s after the local clock: the feed is stale 3 s after it was received
    (it read "fresh" until 3.25 s); with no receipt the stamp still decides."""
    desk, _, clock = make_desk(tmp_path)
    try:
        now = clock.now()
        window = desk.book.windows[TICKER]
        snap = desk.snapshot()

        def at(moment: float, bitcoin_at: float, receipt: TickReceipt | None) -> str:
            # Books are fresh at each check; only Bitcoin silence is tested.
            books = {key: type(book)(book.window, book.side, book.bids, book.asks, moment, book.sequence,
                                     source="rest", requested_at=moment) for key, book in snap.books.items()}
            view = LiveSnapshot(snap.windows, books, 80000, bitcoin_at, snap.sigma, snap.maker_windows,
                                tick_receipt=receipt)
            return desk._feed_reason(window, view, moment)

        stamp = now + FUTURE_SKEW_S - .01
        received = TickReceipt(stamp, now, 0.0)
        assert at(now + 2.99, stamp, received) == ""
        assert at(now + 3.01, stamp, received) == "Bitcoin feed stale"  # was "" until now + 3.25
        assert at(now + 3.2, stamp, None) == ""  # no receipt: the stamp decides
        # A tick stamped before its receipt (the usual case) still counts from its stamp.
        behind = TickReceipt(now - .1, now, 0.0)
        assert at(now + 2.85, now - .1, behind) == ""
        assert at(now + 2.95, now - .1, behind) == "Bitcoin feed stale"
    finally:
        desk.close()


def test_backup_fills_the_gap_while_both_exchange_feeds_are_connected_but_silent(tmp_path: Path) -> None:
    clock = FakeClock(1_791_917_600.0)
    base = 1_791_917_623.0
    iso = "2026-10-13T18:53:43.000000Z"
    heartbeats = [(base + i * .1, json.dumps({"type": "heartbeat", "product_id": "BTC-USD"})) for i in range(3)]
    sockets = {COINBASE_EXCHANGE_WS: [Timed(heartbeats, clock), Timed(heartbeats, clock)],
               COINBASE_WS: [Timed([(base + .12, at_trade(9, iso))], clock)]}
    runner, delivered = runner_with_feeds(tmp_path, clock, sockets)
    try:
        assert len(delivered) == 1 and runner.desk.tape.price == 83000
    finally:
        runner.close()
