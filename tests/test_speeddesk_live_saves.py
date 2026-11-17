"""Historical factory cases are HISTORICAL ENTRY MECHANISM ONLY; they do not prove current
entry authority or profitability. Other cases retain the production factory.

Latency review minor (2026-10-13): every reconcile marked the state dirty, so a quiet desk rewrote its whole
state (up to 31 days of metrics, 7 to 69 ms each on the build machine) every second on the shared event loop.

A reconcile that changes nothing of record now waits for the five-second save; one that does (an order id found, a
status, a window marked as the owner's) is saved within a second as before, and fills, settlements and stops at once.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any

from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, make_desk


def count_saves(desk: Any) -> list[float]:
    saves: list[float] = []
    original = desk.checkpoint

    def counting(durable: bool = False) -> None:
        saves.append(desk.clock())
        original(durable)

    desk.checkpoint = counting
    return saves


def test_a_quiet_desk_saves_every_five_seconds_not_every_second(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    try:
        asyncio.run(desk.step())  # one resting bid, then nothing changes
        assert account.creates and account.creates[0]["kind"] == "rest"
        for _ in range(8):  # its reply and the first reads are saved
            clock.advance(.25)
            asyncio.run(desk.step())
        saves = count_saves(desk)
        reads = account.reads
        for _ in range(240):  # one minute of quarter-second steps: about 60 reconciles
            clock.advance(.25)
            asyncio.run(desk.step())
        assert account.reads - reads >= 100  # it kept reading the account (positions read separately)
        assert len(saves) <= 14, len(saves)  # was about 60: one per reconcile
        assert all(later - earlier >= 1 for earlier, later in itertools.pairwise(saves))
    finally:
        desk.close()


def test_a_change_of_record_is_still_saved_within_a_second(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    try:
        asyncio.run(desk.step())
        for _ in range(8):
            clock.advance(.25)
            asyncio.run(desk.step())
        clock.advance(5.1)
        asyncio.run(desk.step())  # the five-second save
        saves = count_saves(desk)
        account.orders.append({"order_id": "owner-1", "client_order_id": "", "ticker": TICKER, "status": "resting",
                               "fill_count_fp": "0.00", "remaining_count_fp": "1.00", "initial_count_fp": "1.00",
                               "outcome_side": "yes", "book_side": "bid", "yes_price_dollars": "0.2",
                               "no_price_dollars": "0.8"})
        seen_at = None
        for _ in range(8):
            clock.advance(.25)
            asyncio.run(desk.step())
            if seen_at is None and TICKER in desk.foreign_windows:
                seen_at = clock.now()
        assert seen_at is not None
        assert any(seen_at <= at <= seen_at + 1.25 for at in saves), (seen_at, saves)
    finally:
        desk.close()
