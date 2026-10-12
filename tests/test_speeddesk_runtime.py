"""Durable practice receipts, reporting days and reconnect behavior."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner, panel_state
from nightcrawler.speeddesk_model import Book, Level, Trade, Window


class LocalFeeds:
    def __init__(self, _settings: Settings, **callbacks: Any) -> None:
        self.callbacks = callbacks
        self.outcomes: dict[str, float | None] = {}
        self.settlement_calls: list[str] = []

    async def settlement(self, slug: str) -> float | None:
        self.settlement_calls.append(slug)
        return self.outcomes.get(slug)

    async def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.01)


def runner_at(path: Path, clock: FakeClock) -> SpeedRunner:
    return SpeedRunner(Settings(data_dir=path), threading.Event(), clock=clock, feed_factory=LocalFeeds)


def prepare(runner: SpeedRunner, clock: FakeClock, *, end: float | None = None) -> str:
    now = clock.now()
    slug = "cpc-btc-updown-15m-test"
    runner.on_windows([Window(slug, now, end or now + 900, 80000, maker_coefficient=0)])
    runner.on_tick(80000, now, now)
    runner.on_status({"coinbase": "connected", "trade_stream": True, "markets": "connected"})
    for side in ("up", "down"):
        runner.on_book(Book(slug, side, (Level(0.3, 2),), (Level(0.6, 10),), now, "first", now))
    return slug


def fill_maker(runner: SpeedRunner, clock: FakeClock, slug: str, quantity: float = 2) -> None:
    decision = runner.desk.place(slug, "up", "rest", 0.4, 5, 0.5, clock.now())
    assert decision.event == "speeddesk_rest"
    runner.decisions([decision])
    clock.advance(0.5)
    runner.on_trade(Trade(slug, "up", 0.39, quantity, clock.now(), "real-print", "sell", clock.now()))
    assert runner.desk.inventory[slug].up.shares == quantity


async def settlement_pass(runner: SpeedRunner) -> None:
    task = asyncio.create_task(runner._settlements())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_receipt_ledger_recovers_corrupt_json_without_losing_fills(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    slug = prepare(runner, clock)
    fill_maker(runner, clock, slug)
    cash_spent = runner.desk.inventory[slug].spent
    started_at = runner.started_at
    assert runner.ledger.verify_chain() == (True, None)
    runner.path.write_text("incomplete JSON cache", encoding="utf-8")
    runner.close()

    restored = runner_at(tmp_path, clock)
    try:
        assert restored.desk.inventory[slug].up.shares == 2
        assert restored.desk.inventory[slug].spent == cash_spent
        assert restored.started_at == started_at
        assert restored.desk.orders == {}  # A queue cannot survive a restart.
        restored.checkpoint(clock.now())
        report = panel_state(Settings(data_dir=tmp_path), clock.now())
        assert report["today"]["fills"] == 1
        assert report["today"]["windows"] == 1
        assert restored.ledger.verify_chain() == (True, None)
        cancellations = [receipt for receipt in restored.ledger.receipts() if receipt.kind == "speeddesk_cancel"]
        assert any(receipt.payload["reason"] == "restart" for receipt in cancellations)
    finally:
        restored.close()


def test_existing_report_without_ledger_refuses_to_reset_trial(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    runner.checkpoint(clock.now())
    runner.close()
    (tmp_path / "speeddesk" / "receipts.db").unlink()
    with pytest.raises(ValueError, match="receipt ledger missing"):
        runner_at(tmp_path, clock)


def test_changed_venue_fees_cancel_orders_without_rewriting_past_fills(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        fill_maker(runner, clock, slug)
        spent = runner.desk.inventory[slug].spent
        runner.on_windows([replace(runner.desk.windows[slug], maker_coefficient=0.02)])
        assert not runner.desk.orders
        assert not runner.desk.books
        assert runner.desk.inventory[slug].spent == spent
        assert runner.desk.windows[slug].maker_coefficient == 0.02
        receipt = runner.ledger.last_receipt("speeddesk_cancel")
        assert receipt is not None and receipt.payload["reason"] == "venue_terms_changed"
    finally:
        runner.close()


def test_feed_gap_cancels_pending_orders_and_discards_queue_snapshots(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        fill_maker(runner, clock, slug)
        assert runner.desk.orders
        runner.on_status({"coinbase": "connected", "trade_stream": False, "markets": "disconnected"})
        assert not runner.desk.orders
        assert not runner.desk.books
        receipt = runner.ledger.last_receipt("speeddesk_cancel")
        assert receipt is not None and receipt.payload["reason"] == "feed_gap"
        runner.on_trade(Trade(slug, "up", 0.39, 100, clock.now(), "after-disconnect", "sell", clock.now()))
        assert runner.desk.inventory[slug].up.shares == 2
    finally:
        runner.close()


def test_trade_cannot_borrow_another_venues_stream_permission(tmp_path: Path, monkeypatch: Any) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        decision = runner.desk.place(slug, "up", "rest", 0.4, 5, 0.5, clock.now())
        runner.decisions([decision])
        assert runner.desk.orders
        # The overall stream is up because another venue is healthy, but this
        # window lost tape continuity before the next strategy step ran.
        monkeypatch.setattr(runner.feeds, "maker_windows", lambda: {"a-different-venue-window"}, raising=False)
        clock.advance(0.5)
        runner.on_trade(Trade(slug, "up", 0.39, 5, clock.now(), "in-flight-after-gap", "sell", clock.now()))
        assert runner.desk.inventory[slug].up.shares == 0
        assert runner.ledger.last_receipt("speeddesk_fill") is None
    finally:
        runner.close()


def test_venue_settlement_is_idempotent_and_daily_report_uses_utc(tmp_path: Path) -> None:
    start = datetime(2026, 10, 12, 23, 58, tzinfo=UTC).timestamp()
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    clock = FakeClock(start)
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock, end=midnight)
        fill_maker(runner, clock, slug)
        runner.feeds.outcomes[slug] = 1
        clock.set(midnight + 1)
        asyncio.run(settlement_pass(runner))
        asyncio.run(settlement_pass(runner))
        assert len(runner.desk.closed) == 1
        assert runner.feeds.settlement_calls == [slug]
        assert len([r for r in runner.ledger.receipts() if r.kind == "speeddesk_window"]) == 1
        today = runner.summary("2026-10-13")
        yesterday = runner.reports["2026-10-12"]
        assert today["settled_windows"] == 1
        assert today["pnl_usd"] == pytest.approx(1.2)
        assert today["windows"] == 0 and today["fills"] == 0
        assert yesterday["windows"] == 1 and yesterday["fills"] == 1
        assert yesterday["pnl_usd"] == 0
        assert yesterday["partial_day"] is True
        runner.checkpoint(clock.now())
        assert len([r for r in runner.ledger.receipts() if r.kind == "speeddesk_daily"]) == 1
        assert runner.ledger.verify_chain() == (True, None)
        saved = json.loads(runner.path.read_text(encoding="utf-8"))
        assert saved["panel"]["today"]["day"] == "2026-10-13"
        assert saved["panel"]["real_orders_available"] is False
    finally:
        runner.close()


def test_missing_or_nonbinary_venue_outcome_leaves_window_unsettled(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        fill_maker(runner, clock, slug)
        clock.advance(901)
        asyncio.run(settlement_pass(runner))
        assert not runner.desk.closed
        runner.feeds.outcomes[slug] = 0.5
        asyncio.run(settlement_pass(runner))
        assert not runner.desk.closed
        assert runner.desk.inventory[slug].up.shares == 2
    finally:
        runner.close()


def test_missing_trade_stream_does_not_invent_maker_attempts(tmp_path: Path) -> None:
    from dataclasses import replace

    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=0)
        runner.desk.tick_btc(79999, clock.now() - 2)
        runner.desk.tick_btc(80000, clock.now() - 1)
        prepare(runner, clock)
        runner.feed_status["trade_stream"] = False
        runner.step(clock.now())
        assert not runner.desk.orders
        assert runner.summary(datetime.fromtimestamp(clock.now(), UTC).date().isoformat())["maker_orders"] == 0
        assert not [receipt for receipt in runner.ledger.receipts() if receipt.kind == "speeddesk_rest"]
    finally:
        runner.close()


@pytest.mark.parametrize("source", ["websocket", "rest"])
def test_failed_first_latency_recheck_cannot_be_replaced_by_later_good_book(
    tmp_path: Path, source: str,
) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        decision = runner.desk.place(slug, "up", "take", 0.6, 5, 0.8, clock.now())
        assert decision.event == "speeddesk_take"
        runner.decisions([decision])
        clock.advance(0.3)
        runner.on_book(Book(slug, "up", (Level(0.3, 2),), (Level(0.7, 10),),
                            clock.now(), "first-recheck-price-moved", clock.now(), source, clock.now()))
        assert not runner.desk.orders
        cancelled = runner.ledger.last_receipt("speeddesk_cancel")
        assert cancelled is not None
        assert cancelled.payload["order_id"] == decision.order_id
        assert cancelled.payload["reason"] == "ask_moved"

        # Two feed callbacks can arrive before a scheduled strategy step. The
        # second quote cannot erase the evidence that the first recheck failed.
        clock.advance(0.01)
        runner.on_book(Book(slug, "up", (Level(0.3, 2),), (Level(0.6, 10),),
                            clock.now(), "later-favorable-book", clock.now(), source, clock.now()))
        runner.step(clock.now())
        assert runner.desk.inventory[slug].up.shares == 0
        assert runner.ledger.last_receipt("speeddesk_fill") is None
        assert runner.ledger.verify_chain() == (True, None)
    finally:
        runner.close()
