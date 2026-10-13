"""Bounded Kalshi account reads (loss plan bug 3, speed plan step 1): offline, fake account only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from test_speeddesk_live import TICKER, FakeAccount, fill_order, make_desk, steps

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import (
    FULL_SCAN_S,
    READ_MARGIN_S,
    RECENT_S,
    KalshiLiveDesk,
    LiveSnapshot,
)
from nightcrawler.speeddesk_model import Book, Level, Window

NEXT = "KXBTC15M-26OCT121915-15"


class FilteringAccount(FakeAccount):
    """Applies Kalshi's min_ts like the venue: orders by creation time, fills by fill time."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__(clock)
        self.order_queries: list[dict[str, Any]] = []
        self.fill_queries: list[dict[str, Any]] = []

    def list_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.order_queries.append(kwargs)
        rows = super().list_orders()
        return [row for row in rows if row.get("created_ts", 0) >= kwargs.get("min_ts", 0)]

    def fills(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.fill_queries.append(kwargs)
        return [row for row in super().fills() if row["ts"] >= kwargs.get("min_ts", 0)]

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        reply = super().create_order(**kwargs)
        self.orders[-1]["created_ts"] = self.clock.now()
        return reply


def reads_desk(tmp_path: Path) -> tuple[KalshiLiveDesk, FilteringAccount, FakeClock]:
    desk, _, clock = make_desk(tmp_path)
    account = FilteringAccount(clock)
    desk.client_factory = lambda: account
    return desk, account, clock


def view(clock: FakeClock, *windows: Window) -> LiveSnapshot:
    """Fresh Bitcoin and books for these windows at the current time."""
    books = {(window.slug, side): Book(window.slug, side, (Level(.3, 2),), (Level(.4 if side == "up" else .6, 10),),
                                       clock.now(), "book", source="rest", requested_at=clock.now())
             for window in windows for side in ("up", "down")}
    return LiveSnapshot(windows, books, 80000, clock.now(), .001, frozenset(window.slug for window in windows))


def status_lines(desk: KalshiLiveDesk) -> list[dict[str, Any]]:
    desk.checkpoint()
    return [receipt.payload for receipt in desk.ledger.receipts() if receipt.kind == "speeddesk_live_status"]


def test_reads_between_complete_scans_ask_only_for_recent_orders_and_fills(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        start = clock.now()
        asyncio.run(desk.step())  # startup reads everything, then the first buy goes out
        assert account.creates and account.order_queries[0] == {}
        assert account.fill_queries[0] == {"min_ts": int(desk.started_at) - 60}
        complete = len(account.order_queries)
        clock.advance(1.1)
        asyncio.run(desk.step())  # the read right after the order is a recent one
        since = int(start + 1.1 - RECENT_S) - int(READ_MARGIN_S)
        assert account.order_queries[complete:] == [{"min_ts": since}, {"min_ts": since}]
        assert account.fill_queries[-1] == {"min_ts": since}
        clock.advance(FULL_SCAN_S)
        asyncio.run(desk.step())  # a minute later the complete history is read again
        assert account.order_queries[-1] == {} and account.fill_queries[-1] == {"min_ts": int(desk.started_at) - 60}
    finally:
        desk.close()


def test_an_old_unfinished_order_keeps_its_own_reads_in_range(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        intent.uncertain = True  # still unresolved a quarter of an hour later
        clock.advance(RECENT_S + 30)
        desk.full_scan_at = clock.now()  # isolate the recent read
        asyncio.run(desk.step())
        assert account.order_queries[-1] == {"min_ts": int(intent.at) - int(READ_MARGIN_S)}
    finally:
        desk.close()


def test_a_late_fill_outside_the_recent_range_is_caught_by_the_complete_scan(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        desk.snapshot = lambda: view(clock)  # type: ignore[method-assign]  # no further buys
        steps(desk, clock, 4)
        assert all(intent.terminal for intent in desk.intents.values()) and desk.book.integrity_error is None
        clock.advance(RECENT_S + 100)
        steps(desk, clock, 1)  # a complete scan, the minute's first read
        order = account.orders[0]
        late = {**account.executions[0], "fill_id": "late-fill", "count_fp": "1.00", "ts": order["created_ts"] + 1}
        account.executions.append(late)  # Kalshi reports one more fill, stamped back then
        steps(desk, clock, 3)
        assert desk.book.integrity_error is None  # outside the recent range: not seen yet
        clock.advance(FULL_SCAN_S)
        steps(desk, clock, 1)
        assert "late-fill" in desk.book.fills and desk.book.integrity_error is not None  # found; real orders stop
    finally:
        desk.close()


def next_window(clock: FakeClock, start: float) -> Window:
    return Window(NEXT, start, start + 900, start_price=80000, venue_start_price=80000, venue="kalshi",
                  taker_coefficient=.07, maker_coefficient=0, min_trade_qty=.01, fee_rounding="kalshi")


def opening_scenario(tmp_path: Path, owner_order: bool) -> tuple[KalshiLiveDesk, FilteringAccount]:
    """A new window opens 30 s after a complete read; the owner may have a bid there from long before."""
    desk, account, clock = reads_desk(tmp_path)
    first = desk.book.windows[TICKER]
    later = next_window(clock, first.end)
    desk.on_windows([later])
    desk.snapshot = lambda: view(clock)  # type: ignore[method-assign]  # nothing to trade before it opens
    clock.advance(later.start - 30 - clock.now())
    asyncio.run(desk.step())
    assert desk.startup_done and not account.creates and desk.full_scan_at == clock.now()
    if owner_order:
        account.orders.append({"order_id": "owner-early", "client_order_id": "", "ticker": NEXT, "status": "resting",
                               "fill_count_fp": "0.00", "remaining_count_fp": "2.00",
                               "created_ts": later.start - 2 * RECENT_S})
    clock.advance(31)
    desk.snapshot = lambda: view(clock, later)  # type: ignore[method-assign]
    desk.on_tick(80000, clock.now(), clock.now())
    asyncio.run(desk.step())
    return desk, account


def test_an_owner_bid_placed_before_a_window_opened_is_seen_before_the_first_buy_there(tmp_path: Path) -> None:
    desk, account = opening_scenario(tmp_path, owner_order=True)
    try:
        assert account.order_queries[-1] == {}  # the window's opening triggered a complete read
        assert NEXT in desk.foreign_windows and not account.creates
    finally:
        desk.close()
    control, account = opening_scenario(tmp_path / "control", owner_order=False)
    try:
        assert [create["ticker"] for create in account.creates] == [NEXT]
    finally:
        control.close()


def test_status_line_reports_reconcile_time_pages_and_the_failed_check(tmp_path: Path) -> None:
    desk, account, clock = reads_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        account.account_positions = [{"ticker": TICKER, "position_fp": "2.00"}]  # nothing booked explains it
        clock.advance(1.1)
        asyncio.run(desk.step())
        assert desk.account_at is None
        assert desk.last_sync_report is not None and desk.last_sync_report["checks"] == ["position_mismatch"]
        clock.advance(60)
        asyncio.run(desk.step())
        line = status_lines(desk)[-1]
        report = line["reconcile"]
        assert report["counts"]["check_position_mismatch"] >= 1 and report["counts"]["rows"] >= 1
        assert {"full_ms", "list_orders_ms", "fills_ms", "positions_ms", "balance_ms"} <= set(report["ms"])
        assert all(item["n"] >= 1 and item["max_ms"] >= item["median_ms"] >= 0 for item in report["ms"].values())
        assert report["last"]["full"] is True and [read["read"] for read in report["last"]["reads"]][:2] == [
            "list_orders", "fills"]
        json.dumps(line, allow_nan=False)  # what the log line and the deploy-log parsers read
    finally:
        desk.close()
