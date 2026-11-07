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
from nightcrawler.speeddesk import STATE_KEY, SpeedRunner, panel_state
from nightcrawler.speeddesk_model import Book, Level, Trade, Window, utc_day


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


def prepare_kalshi(runner: SpeedRunner, clock: FakeClock, *, end: float | None = None) -> str:
    now = clock.now()
    slug = "KXBTC15M-test"
    runner.on_windows([Window(slug, now, end or now + 900, 80000, taker_coefficient=.07,
                              maker_coefficient=0, venue_start_price=80000, venue="kalshi", fee_rounding="kalshi")])
    for side in ("up", "down"):
        runner.on_book(Book(slug, side, (Level(.3, 2),), (Level(.6, 10),), now, "kalshi-first", now))
    return slug


def test_daily_venue_results_and_receipts_survive_restart(tmp_path: Path) -> None:
    start = datetime(2026, 10, 12, 23, 58, tzinfo=UTC).timestamp()
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    clock = FakeClock(start)
    runner = runner_at(tmp_path, clock)
    us = prepare(runner, clock, end=midnight)
    kalshi = prepare_kalshi(runner, clock, end=midnight)
    fill_maker(runner, clock, us, 2)
    fill_maker(runner, clock, kalshi, 3)
    runner.feeds.outcomes = {us: 1, kalshi: 0}
    clock.set(midnight + 1)
    asyncio.run(settlement_pass(runner))
    today = runner.summary("2026-10-13")
    assert today["venues"]["polymarket_us"]["pnl_usd"] == pytest.approx(1.2)
    assert today["venues"]["kalshi"]["pnl_usd"] == pytest.approx(-1.2)
    assert today["pnl_usd"] == pytest.approx(0)
    yesterday = runner.reports["2026-10-12"]
    assert yesterday["venues"]["polymarket_us"]["fills"] == 1
    assert yesterday["venues"]["kalshi"]["fills"] == 1
    for receipt in runner.ledger.receipts():
        if receipt.kind in {"speeddesk_rest", "speeddesk_fill", "speeddesk_cancel", "speeddesk_window"}:
            assert receipt.payload["venue"] == ("kalshi" if receipt.payload["window"] == kalshi else "polymarket_us")
    runner.close()
    restored = runner_at(tmp_path, clock)
    try:
        assert restored.summary("2026-10-13") == today
        assert restored.reports["2026-10-12"] == yesterday
        assert restored.ledger.verify_chain() == (True, None)
    finally:
        restored.close()


def test_venue_coverage_requires_its_own_fresh_books_and_trade_stream(tmp_path: Path, monkeypatch: Any) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        us = prepare(runner, clock)
        prepare_kalshi(runner, clock)
        monkeypatch.setattr(runner.feeds, "maker_windows", lambda: {us}, raising=False)
        runner.step(clock.now())
        clock.advance(.5)
        runner.step(clock.now())
        first = runner.summary(utc_day(clock.now()))
        assert first["venues"]["polymarket_us"]["fresh_data_seconds"] == .5
        assert first["venues"]["kalshi"]["fresh_data_seconds"] == .5
        assert first["venues"]["polymarket_us"]["maker_data_seconds"] == .5
        assert first["venues"]["kalshi"]["maker_data_seconds"] == 0
        runner.desk.books = {key: book for key, book in runner.desk.books.items() if key[0] == us}
        clock.advance(.5)
        runner.step(clock.now())
        second = runner.summary(utc_day(clock.now()))
        assert second["venues"]["polymarket_us"]["fresh_data_seconds"] == 1
        assert second["venues"]["kalshi"]["fresh_data_seconds"] == .5
        clock.advance(4)
        runner.step(clock.now())
        stale = runner.summary(utc_day(clock.now()))
        assert stale["observed_seconds"] == 2  # Offline gaps never count as runtime.
        assert stale["venues"]["polymarket_us"]["fresh_data_seconds"] == 1
        assert stale["venues"]["kalshi"]["fresh_data_seconds"] == .5
        runner.checkpoint(clock.now())
        runner.close()
        runner = runner_at(tmp_path, clock)
        assert runner.summary(utc_day(clock.now())) == stale
    finally:
        runner.close()


def test_observation_crossing_utc_midnight_is_split_without_invented_venue_coverage(tmp_path: Path) -> None:
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    clock = FakeClock(midnight - .25)
    runner = runner_at(tmp_path, clock)
    try:
        clock.advance(.5)
        runner.step(clock.now())
        assert runner.observed == {"2026-10-12": .25, "2026-10-13": .25}
        old = runner.reports["2026-10-12"]
        assert old["venues"]["kalshi"]["fresh_data_seconds"] == 0
        assert old["venues"]["kalshi"]["partial_day"] is True
        assert old["venues"]["kalshi"]["avg_latency_ms"] is None
        heartbeat = runner.ledger.last_receipt("speeddesk_status")
        assert heartbeat is not None and "reports" not in heartbeat.payload
        assert "kalshi" in heartbeat.payload["today"]["venues"]
        assert "2026-10-12" in runner.panel(clock.now())["reports"]
    finally:
        runner.close()


@pytest.mark.parametrize("source", ["websocket", "rest"])
def test_received_but_old_book_does_not_count_as_fresh_venue_coverage(tmp_path: Path, source: str) -> None:
    clock = FakeClock()
    runner = runner_at(tmp_path, clock)
    try:
        slug = prepare(runner, clock)
        now = clock.now()
        for side in ("up", "down"):
            runner.desk.books[(slug, side)] = Book(slug, side, (), (), now, "old", now - 10, source, now - 10)
        runner.step(now)
        clock.advance(.5)
        runner.step(clock.now())
        venue = runner.summary(utc_day(now))["venues"]["polymarket_us"]
        assert venue["observed_seconds"] == .5
        assert venue["fresh_data_seconds"] == 0
    finally:
        runner.close()


def test_legacy_combined_reports_never_gain_invented_venue_history(tmp_path: Path) -> None:
    start = datetime(2026, 10, 12, 23, 58, tzinfo=UTC).timestamp()
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    clock = FakeClock(start)
    runner = runner_at(tmp_path, clock)
    slug = prepare(runner, clock)
    fill_maker(runner, clock, slug)
    clock.set(midnight + 1)
    runner.checkpoint(clock.now())
    saved = runner.ledger.get_kv(STATE_KEY)
    # Recreate the previous release's state, which knew only aggregate counts.
    saved.pop("venue_reporting_started_at", None)
    saved.pop("venue_coverage", None)
    for key in list(saved["model"]):
        if key.startswith("venue_") or key == "legacy_incomplete_days":
            saved["model"].pop(key)
    saved["reports"]["2026-10-12"].pop("venues")
    with runner.ledger.transaction():
        runner.ledger.set_kv(STATE_KEY, saved)
    runner.close()
    restored = runner_at(tmp_path, clock)
    try:
        old = restored.reports["2026-10-12"]
        assert old["fills"] == 1
        for venue in ("kalshi", "polymarket_us"):
            report = old["venues"][venue]
            assert report["reporting_complete"] is False
            assert report["fills"] is None and report["take_attempts"] is None
            assert report["fresh_data_seconds"] is None
            assert report["coverage_started_at"] == clock.now()
        assert restored.desk.inventory[slug].up.shares == 2
    finally:
        restored.close()


def test_late_fill_revises_the_venue_placement_day_rate_with_an_audited_correction(tmp_path: Path) -> None:
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    clock = FakeClock(midnight - .5)
    runner = runner_at(tmp_path, clock)
    try:
        # Current venues align expiry to midnight; this deliberately crossing
        # fixture also protects any future venue/window from >100% daily rates.
        slug = prepare(runner, clock, end=midnight + 900)
        decision = runner.desk.place(slug, "up", "rest", .4, 5, .5, clock.now())
        runner.decisions([decision])
        clock.set(midnight)
        runner.checkpoint(clock.now())
        assert runner.reports["2026-10-12"]["venues"]["polymarket_us"]["maker_fills"] == 0
        clock.advance(.25)
        runner.on_trade(Trade(slug, "up", .39, 2, clock.now(), "late-print", "sell", clock.now()))
        prior = runner.reports["2026-10-12"]["venues"]["polymarket_us"]
        today = runner.summary("2026-10-13")["venues"]["polymarket_us"]
        assert prior["maker_fill_rate_pct"] == 100 and prior["fills"] == 0
        assert today["fills"] == 1 and today["maker_orders"] == 0
        assert today["maker_fill_rate_pct"] is None
        corrections = [r for r in runner.ledger.receipts() if r.kind == "speeddesk_daily_correction"]
        assert len(corrections) == 1
        assert corrections[0].payload["venues"]["polymarket_us"]["maker_fills"] == 1
        runner.checkpoint(clock.now())
        assert len([r for r in runner.ledger.receipts() if r.kind == "speeddesk_daily_correction"]) == 1
    finally:
        runner.close()
