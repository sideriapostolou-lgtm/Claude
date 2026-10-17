"""Exercise the live companion boundary inside the continuing public trial."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_model import Book, Level, Window


class PublicFeeds:
    def __init__(self, _settings: Settings, **_callbacks: Any) -> None:
        self.running = False

    def maker_windows(self) -> set[str]:
        return {"KXBTC15M-test", "us-test"}

    async def settlement(self, _slug: str) -> None:
        return None

    async def run(self, stop: threading.Event) -> None:
        self.running = True
        while not stop.is_set():
            await asyncio.sleep(0.001)


class FailedCompanion:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.shutdown_called = False
        self.closed = False

    def on_windows(self, _windows: list[Window]) -> None:
        pass

    def panel(self) -> dict[str, Any]:
        return {"mode": "live", "cash_usd": 25, "exposure_usd": 1.1}

    async def run(self, _stop: threading.Event) -> None:
        raise RuntimeError("synthetic companion failure")

    async def shutdown(self) -> None:
        self.shutdown_called = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("account_type,precision", [("unknown", .01), ("fcm", .01), ("direct", .0001)])
def test_account_fact_selects_fee_bound_without_enabling_money(
    tmp_path: Path, account_type: str, precision: float,
) -> None:
    settings = Settings.from_env({"DATA_DIR": str(tmp_path), "SPEEDDESK_KALSHI_ACCOUNT_TYPE": account_type})
    runner = SpeedRunner(settings, threading.Event(), clock=FakeClock(), feed_factory=PublicFeeds)
    try:
        assert runner.live is not None
        assert runner.live.book.limits.fee_precision == precision
        asyncio.run(runner.live.step())
        assert runner.live.client is None
        assert runner.live.panel()["mode"] == "paper"
    finally:
        runner.close()


def test_market_snapshot_cannot_borrow_practice_inventory_or_us_books(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=PublicFeeds)
    try:
        now = clock.now()
        runner.on_windows([Window("KXBTC15M-test", now, now + 900, 80_000, venue_start_price=80_000, venue="kalshi"),
                           Window("us-test", now, now + 900, 80_000)])
        runner.on_tick(80_000, now, now)
        for slug in ("KXBTC15M-test", "us-test"):
            for side in ("up", "down"):
                runner.on_book(Book(slug, side, (Level(0.3, 2),), (Level(0.6, 10),), now, "1"))
        runner.desk.place("us-test", "up", "rest", .4, 1, .5, now)
        snapshot = runner.live_snapshot()
        assert {item.slug for item in snapshot.windows} == {"KXBTC15M-test"}
        assert {key[0] for key in snapshot.books} == {"KXBTC15M-test"}
        assert snapshot.maker_windows == {"KXBTC15M-test"}
        assert snapshot.bitcoin_price == 80_000
        assert not hasattr(snapshot, "inventory") and not hasattr(snapshot, "cash")
        assert runner.live is not None
        assert not runner.live.book.intents
        assert not runner.live.twin.orders  # Public practice decisions never place companion orders.
        original = snapshot.windows[0]
        runner.desk.windows[original.slug].start_price = 81_000
        clock.advance(1)
        runner.on_tick(80_500, clock.now(), clock.now())
        refreshed = runner.live_snapshot()
        assert original.start_price == 80_000  # Published worker snapshots never change underneath it.
        assert snapshot.bitcoin_price == 80_000 and snapshot.bitcoin_at == now
        assert refreshed.bitcoin_price == 80_500 and refreshed.bitcoin_at == now + 1
    finally:
        runner.close()


def test_public_trial_continues_after_companion_fails_and_cleanup_runs(tmp_path: Path) -> None:
    stop = threading.Event()
    runner = SpeedRunner(Settings(data_dir=tmp_path), stop, clock=FakeClock(),
                         feed_factory=PublicFeeds, live_factory=FailedCompanion)

    async def exercise() -> None:
        task = asyncio.create_task(runner.run())
        try:
            for _ in range(100):
                if runner.live_problem:
                    break
                await asyncio.sleep(.001)
            assert runner.live_problem and not task.done()
            assert runner.feeds.running
            assert runner.live is not None and runner.live.shutdown_called
            panel = runner.panel(runner.clock.now())
            assert panel["mode"] == "paper" and panel["real_orders_available"] is False
            companion = panel["kalshi_live"]
            assert companion["mode"] == "paper" and companion["real_orders_available"] is False
            assert companion["exposure_unknown"] and companion["exposure_usd"] == 1.1
        finally:
            stop.set()
            await task

    try:
        asyncio.run(exercise())
        assert runner.problem is None
        assert runner.ledger.last_receipt("speeddesk_started") is not None
    finally:
        runner.close()


def test_companion_bad_state_is_visible_without_restarting_public_trial(tmp_path: Path) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("unreadable companion ledger")

    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=FakeClock(),
                         feed_factory=PublicFeeds, live_factory=broken)
    try:
        runner.step(runner.clock.now())
        companion = runner.panel(runner.clock.now())["kalshi_live"]
        assert companion["mode"] == "paper" and companion["exposure_unknown"]
        assert companion["real_orders_available"] is False
        assert "unavailable" in companion["reason"]
        assert runner.ledger.verify_chain() == (True, None)
    finally:
        runner.close()


def test_callback_fault_disables_sends_and_runs_cleanup_without_stopping_feeds(tmp_path: Path) -> None:
    class CallbackFailure(FailedCompanion):
        async def run(self, _stop: threading.Event) -> None:
            await asyncio.Future()

        def on_tick(self, *_args: Any) -> None:
            raise ValueError("synthetic callback failure")

    clock, stop = FakeClock(), threading.Event()
    runner = SpeedRunner(Settings(data_dir=tmp_path), stop, clock=clock,
                         feed_factory=PublicFeeds, live_factory=CallbackFailure)

    async def exercise() -> None:
        task = asyncio.create_task(runner.run())
        try:
            while not runner.live_started:
                await asyncio.sleep(.001)
            runner.on_tick(80_000, clock.now(), clock.now())
            assert runner.live is not None and runner.live.stopping
            for _ in range(100):
                if runner.live.shutdown_called:
                    break
                await asyncio.sleep(.001)
            assert runner.live.shutdown_called and not task.done()
            assert runner.live_problem and runner.feeds.running
            clock.advance(1)
            runner.on_tick(80_001, clock.now(), clock.now())
            assert runner.desk.tape.price == 80_001
        finally:
            stop.set()
            await task

    try:
        asyncio.run(exercise())
    finally:
        runner.close()


def test_panel_fault_retains_unknown_exposure_instead_of_claiming_zero(tmp_path: Path) -> None:
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=FakeClock(),
                         feed_factory=PublicFeeds)
    try:
        assert runner.live is not None
        runner.last_live_panel = {"at_risk_usd": 1.5}
        # A report failure is isolated just like a failed execution callback.
        runner.live.panel = lambda: (_ for _ in ()).throw(ValueError("bad report"))  # type: ignore[method-assign]
        result = runner.panel(runner.clock.now())
        assert result["kalshi_live"]["exposure_unknown"]
        assert result["kalshi_live"]["at_risk_usd"] == 1.5
        assert runner.live.stopping
        runner.step(runner.clock.now())
    finally:
        runner.close()


@pytest.mark.parametrize("change", ["gap", "fees"])
def test_known_gap_invalidates_send_snapshot_before_disk_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    clock = FakeClock()
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=PublicFeeds)
    try:
        window = Window("KXBTC15M-test", clock.now(), clock.now() + 900, 80_000, venue_start_price=80_000, venue="kalshi")
        runner.on_windows([window])
        runner.on_status({"coinbase": "connected", "trade_stream": True})
        runner.on_book(Book(window.slug, "up", (), (Level(.4, 3),), clock.now(), "1"))
        assert runner.live_snapshot().books
        snapshots = []
        original = runner.decisions

        def checkpoint_boundary(events: Any) -> None:
            snapshots.append(runner.live_snapshot())
            assert not runner.live_snapshot().books
            original(events)

        monkeypatch.setattr(runner, "decisions", checkpoint_boundary)
        if change == "gap":
            runner.on_status({"coinbase": "disconnected", "trade_stream": False})
        else:
            runner.on_windows([replace(window, taker_coefficient=.08)])
        assert snapshots
    finally:
        runner.close()
