"""Latency review (2026-10-13): the money math walked every order and window the desk ever had.

A restart merges the archive back into memory, so after a week the risk book holds thousands of finished orders.
Money at risk was summed over all of them five times per status and once per open order per cancel pass: a step
took 0.6 ms on a fresh book and 57 ms with a week of history (build machine), and a complete reconcile checked
every listed order against every order ever made (1.7 s with three days of history). The sums now use the book's
index of open windows; these tests pin that a step's money math and a complete reconcile do not grow with
finished history, and that the indexed answers are the full ones.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, make_desk

from nightcrawler.speeddesk_live import Intent
from nightcrawler.speeddesk_live_model import LiveIntent, LiveSettlement
from nightcrawler.speeddesk_model import Inventory, Window


def add_history(desk: Any, account: Any, days: int) -> None:
    """``days`` of settled windows, ten finished orders each, all listed by Kalshi (as after a restart)."""
    start = desk.clock() - 86_400 * (days + 1)
    count = 0
    for index in range(96 * days):
        slug, begin = f"KXBTC15M-OLD{index:05d}", start + 900 * index
        desk.book.windows[slug] = Window(slug, begin, begin + 900, 80000, venue="kalshi", taker_coefficient=.07,
                                         maker_coefficient=0)
        desk.book.inventory[slug] = Inventory()
        desk.book.settled[slug] = LiveSettlement(slug, f"s{index}", begin + 905, True, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        for _ in range(10):
            count += 1
            key, order_id = f"nc-speed-old{count}", f"old-order-{count}"
            desk.book.intents[key] = LiveIntent(key, slug, "up", "rest", .4, 5, begin, .4, order_id=order_id,
                                                reservation_active=False, status="canceled",
                                                last_snapshot_at=begin, venue_remaining_size=0)
            desk.intents[key] = Intent(key, slug, "up", "rest", .4, 5, .45, begin, order_id=order_id, terminal=True)
            account.orders.append({"order_id": order_id, "client_order_id": key, "ticker": slug,
                                   "status": "canceled", "fill_count_fp": "0.00", "remaining_count_fp": "0.00",
                                   "initial_count_fp": "5", "outcome_side": "yes", "book_side": "bid",
                                   "yes_price_dollars": "0.4", "no_price_dollars": "0.6"})


def reserved_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, days: int) -> tuple[int, Any]:
    """How many times thirty steps read an order's reservation, with ``days`` of finished history."""
    desk, account, clock = make_desk(tmp_path / f"days-{days}")
    asyncio.run(desk.step())  # the first order rests
    add_history(desk, account, days)
    reads = [0]
    original = LiveIntent.reserved

    def counted(self: LiveIntent) -> float:
        reads[0] += 1
        return original.fget(self)  # type: ignore[attr-defined,no-any-return]

    monkeypatch.setattr(LiveIntent, "reserved", property(counted))
    try:
        for _ in range(30):
            clock.advance(.02)
            asyncio.run(desk.step())
        return reads[0], desk
    finally:
        monkeypatch.setattr(LiveIntent, "reserved", original)
        desk.close()


def test_a_steps_money_math_does_not_grow_with_finished_history(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    fresh, _ = reserved_reads(tmp_path, monkeypatch, 0)
    week, _ = reserved_reads(tmp_path, monkeypatch, 7)  # 6,720 finished orders in memory
    assert fresh > 0
    # Before the index the week of history added about 6,720 reads per sum, dozens of sums per step.
    assert week <= fresh + 30, (fresh, week)


def test_a_complete_reconcile_does_not_check_each_listed_order_against_all_others(tmp_path: Path) -> None:
    """Each listed order's id was checked against every order ever made (quadratic in the history)."""
    desk, account, _clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        add_history(desk, account, 2)  # 1,920 finished orders, each listed by Kalshi
        scans = [0]

        class Counting(dict):  # type: ignore[type-arg]
            def values(self) -> Any:
                scans[0] += 1
                return super().values()

            def items(self) -> Any:
                scans[0] += 1
                return super().items()

        desk.book.intents = Counting(desk.book.intents)
        desk.full_scan_at = -float("inf")
        asyncio.run(desk._reconcile())
        assert desk.last_sync_report is not None and desk.last_sync_report["full"]
        assert not desk.last_sync_report["checks"] and desk.fatal_reason is None
        assert scans[0] <= 10, scans  # was one scan per listed order (1,921)
    finally:
        desk.close()


def test_the_unfinished_orders_come_from_open_windows_only_and_match_a_full_scan(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        add_history(desk, account, 1)
        active = desk._active()
        assert [intent.client_order_id for intent in active] == [
            key for key, intent in desk.intents.items() if not intent.terminal]
        assert [intent.window for intent in active] == [TICKER]
        # An integrity error falls back to the full scan (a settled window can hold a reservation only then).
        old = next(key for key in desk.book.intents if key.startswith("nc-speed-old"))
        desk.intents[old].terminal = False
        desk.book.integrity_error = "fill_after_terminal_confirmation"
        assert old in {intent.client_order_id for intent in desk._active()}
        _ = (account, clock)
    finally:
        desk.close()
