"""Loss plan bug 2 after the rebase: the deploy branch's bba948a fixes are kept (caps review 2, 2026-10-13).

Once Kalshi has accepted a stale-bid cancel the rule stands down (with a lagging order list it re-sent the cancel
five times and read the account 400 times in 10 s), and the stale-bid threshold respects a small make edge.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from test_speeddesk_live import TICKER, make_desk

from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level


def view(desk, clock, bitcoin: float) -> None:
    window = desk.book.windows[TICKER]

    def snapshot() -> LiveSnapshot:
        books = {(TICKER, side): Book(TICKER, side, (Level(.2, 2),), (Level(.9, 10),), clock.now(), "book",
                                      source="rest", requested_at=clock.now()) for side in ("up", "down")}
        return LiveSnapshot((window,), books, bitcoin, clock.now(), .001, frozenset({TICKER}))
    desk.snapshot = snapshot  # type: ignore[method-assign]


def test_acknowledged_stale_bid_cancel_with_a_lagging_order_list(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    try:
        view(desk, clock, 80000)
        asyncio.run(desk.step())
        assert account.creates and account.creates[0]["kind"] == "rest"
        # Kalshi accepts every cancel, but its order list keeps showing the bid resting for 10 s.
        lagging: dict[str, float] = {}
        real_cancel = account.cancel

        def cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            account.cancels.append(order_id)
            lagging.setdefault(order_id, clock.now())
            return {}
        account.cancel = cancel  # type: ignore[method-assign]
        view(desk, clock, 80600)  # fair moves several cents: the bid is stale
        reads_before = account.reads
        for _ in range(100):  # 10 s of 0.1 s steps
            asyncio.run(desk.step())
            clock.advance(.1)
        assert len(account.cancels) <= 1, account.cancels
        assert account.reads - reads_before <= 60, account.reads - reads_before  # was 400 in 10 s
        _ = real_cancel
    finally:
        desk.close()


def test_small_make_edge_bid_is_not_cancelled_on_sight(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_make_edge": .015})
    try:
        view(desk, clock, 80100)
        for _ in range(20):
            asyncio.run(desk.step())
            clock.advance(.3)
        assert account.creates and len(account.cancels) == 0, (len(account.creates), len(account.cancels))
    finally:
        desk.close()
