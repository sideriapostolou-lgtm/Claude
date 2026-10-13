"""Speed step 1: orders the recent (min_ts) reads cannot see are caught by the 60 s complete scan.

The caps review of 2026-10-13, kept as a regression test.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

from test_speeddesk_live import TICKER, steps
from test_speeddesk_live_reads import reads_desk, view

from nightcrawler.speeddesk_live import FULL_SCAN_S, RECENT_S


def resting(order_id: str, client_order_id: str, created_ts: float, ticker: str = TICKER) -> dict:
    return {"order_id": order_id, "client_order_id": client_order_id, "ticker": ticker, "status": "resting",
            "fill_count_fp": "0.00", "remaining_count_fp": "2.00", "initial_count_fp": "2.00",
            "outcome_side": "yes", "book_side": "bid", "yes_price_dollars": "0.30", "no_price_dollars": "0.70",
            "created_ts": created_ts}


def run_until_seen(desk, clock, predicate, limit_s: float) -> float:
    started = clock.now()
    while clock.now() - started <= limit_s:
        asyncio.run(desk.step())
        if predicate():
            return clock.now() - started
        clock.advance(.5)
    raise AssertionError("not caught within the limit")


def test_old_untracked_bot_order_is_caught_by_the_sixty_second_scan(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())  # startup (complete) read, first order goes out
        steps(desk, clock, 3)
        assert desk.fatal_reason is None
        # An untracked bot order Kalshi created long before the recent range (state rollback, lost ledger, ...).
        account.orders.append(resting("ghost", "nc-speed-ghost", clock.now() - 2 * RECENT_S))
        # Recent reads cannot see it ...
        asyncio.run(desk.step())
        assert desk.fatal_reason is None and "ghost" not in account.cancels
        # ... the next complete scan does, within FULL_SCAN_S (+ one step).
        took = run_until_seen(desk, clock, lambda: desk.fatal_reason is not None, FULL_SCAN_S + 2)
        assert took <= FULL_SCAN_S + 2 and "ghost" in account.cancels
        creates = len(account.creates)
        steps(desk, clock, 5)
        assert len(account.creates) == creates  # stopped for good
    finally:
        desk.close()


def test_old_owner_order_in_the_bots_window_is_caught_by_the_sixty_second_scan(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        steps(desk, clock, 3)
        account.orders.append(resting("owner-1", "", clock.now() - 2 * RECENT_S))
        asyncio.run(desk.step())
        assert TICKER not in desk.foreign_windows
        took = run_until_seen(desk, clock, lambda: TICKER in desk.foreign_windows, FULL_SCAN_S + 2)
        assert took <= FULL_SCAN_S + 2
        # The bot leaves the window: its own resting orders there are cancelled and no new ones go out.
        steps(desk, clock, 4)
        bot_resting = [o for o in account.orders if o["client_order_id"].startswith("nc-speed-") and o["status"] == "resting"]
        assert not bot_resting
    finally:
        desk.close()


def test_a_recent_untracked_bot_order_is_caught_at_the_next_recent_read(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        steps(desk, clock, 3)
        account.orders.append(resting("ghost2", "nc-speed-ghost2", clock.now() - 5))
        took = run_until_seen(desk, clock, lambda: desk.fatal_reason is not None, 3)
        assert took <= 2.0 and "ghost2" in account.cancels
    finally:
        desk.close()


def test_the_full_scan_still_happens_when_every_recent_read_is_fresh_and_trading(tmp_path: Path) -> None:
    """Continuous trading never postpones the complete scan beyond FULL_SCAN_S."""
    desk, account, clock = reads_desk(tmp_path)
    try:
        desk.snapshot = lambda: view(clock, desk.book.windows[TICKER])  # type: ignore[method-assign]
        asyncio.run(desk.step())
        full_at = []
        for _ in range(int(3 * FULL_SCAN_S / 1.1)):
            clock.advance(1.1)
            before = len(account.order_queries)
            asyncio.run(desk.step())
            if any(query == {} for query in account.order_queries[before:]):
                full_at.append(clock.now())
        gaps = [b - a for a, b in itertools.pairwise(full_at)]
        assert full_at and max(gaps) <= FULL_SCAN_S + 1.2, gaps
    finally:
        desk.close()
