"""Historical admission fixtures exercise prior policy; they do not establish current production admission.

A cancel await must not lend old market inputs to the next resting bid.

Only fake venue acknowledgements are used; reservations remain real model state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, make_desk

from nightcrawler.speeddesk_live import Intent, LiveSnapshot
from nightcrawler.speeddesk_live_model import ActualFill, OrderSnapshot


@pytest.mark.parametrize("make_edge", [.02, .03])
@pytest.mark.parametrize("change", ["reversal", "stale", "cutoff", "missing", "unchanged", "shutdown", "no_cancel"])
def test_remaining_bid_uses_inputs_after_first_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_edge: float, change: str,
) -> None:
    desk, account, clock = make_historical_desk(
        tmp_path, extra={"speeddesk_make_edge": make_edge, "speeddesk_kalshi_pull": False},
    )
    try:
        desk.client = account
        desk.book.update_cash(25, clock.now())
        # Reconciled holdings permit two further resting legs under the real guards.
        for side in ("up", "down"):
            seed = f"nc-speed-seed-{side}"
            order_id = f"seed-{side}"
            size = 4 if side == "up" else 3
            desk.book.reserve_intent(TICKER, side, "rest", .4, size, clock.now(), seed, .5)
            desk.book.mark_submitted(seed, order_id)
            assert desk.book.record_fill(ActualFill(f"fill-{side}", order_id, seed, TICKER,
                                                   side, .4, size, 0, clock.now(), is_taker=False))
            assert desk.book.reconcile_order(OrderSnapshot(seed, order_id, "executed", size, 0, clock.now()),
                                             fills_complete=True)
            desk.intents[seed] = Intent(seed, TICKER, side, "rest", .4, size, .5, clock.now(),
                                        order_id=order_id, terminal=True)
        initial = replace(desk.snapshot(), bitcoin_price=80000 if change == "no_cancel" else 79990)
        current = initial
        snapshot_reads = 0

        def snapshot() -> LiveSnapshot:
            nonlocal snapshot_reads
            snapshot_reads += 1
            return current

        monkeypatch.setattr(desk, "snapshot", snapshot)
        # Insert Down first: the initial fair drop must still sort Up first.
        for side in ("down", "up"):
            key = f"nc-speed-fresh-{side}"
            desk.book.reserve_intent(TICKER, side, "rest", .48, 1, clock.now(), key, .5)
            desk.book.mark_submitted(key, f"order-{side}")
            desk.intents[key] = Intent(key, TICKER, side, "rest", .48, 1, .5, clock.now(),
                                       order_id=f"order-{side}")
        window = initial.windows[0]
        up, down = (desk.intents[f"nc-speed-fresh-{side}"] for side in ("up", "down"))
        edge = min(.02, make_edge)
        assert desk._stale_bid_reason(up, window, initial, clock.now(), edge) == (
            "" if change == "no_cancel" else "bid_above_fair")
        assert desk._stale_bid_reason(down, window, initial, clock.now(), edge) == ""
        reserved = desk.book.reserved_usd
        calls: list[str] = []

        async def fake_io(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            nonlocal current
            assert fn == account.cancel
            calls.append(args[0])
            await asyncio.sleep(0)  # Let market inputs change while the real cancel is in flight.
            reply = fn(*args, **kwargs)
            if len(calls) == 1:
                if change == "reversal":
                    clock.advance(1)
                    current = replace(initial, bitcoin_price=81000, bitcoin_at=clock.now(), books={
                        key: replace(book, at=clock.now(), requested_at=clock.now())
                        for key, book in initial.books.items()
                    })
                    assert desk._stale_bid_reason(down, window, current, clock.now(), edge) == "reprice"
                elif change == "stale":
                    clock.advance(4)  # Same snapshot object: only the wall clock changed.
                elif change == "cutoff":
                    clock.set(window.end - desk.book.limits.lock_s)
                elif change == "missing":
                    current = replace(initial, windows=())
                elif change == "shutdown":
                    desk.stopping = True
            return reply

        monkeypatch.setattr(desk, "_io", fake_io)
        asyncio.run(desk._cancel_unsafe())
        expected = ([] if change == "no_cancel" else ["order-up"]
                    if change == "unchanged"
                    else ["order-up", "order-down"])
        assert calls == expected
        assert account.cancels == expected
        assert snapshot_reads == (1 if change == "no_cancel" else 2)
        reasons = {payload["order_id"]: payload["reason"] for kind, payload in desk.pending
                   if kind == "speeddesk_live_cancel"}
        if expected:
            assert reasons["order-up"] == "bid_above_fair"
        if "order-down" in expected:
            assert reasons["order-down"] == {
                "reversal": "reprice", "stale": "Bitcoin feed stale",
                "cutoff": "Window cutoff", "missing": "Window missing", "shutdown": "shutdown",
            }[change]
        assert desk.book.reserved_usd == reserved
        assert all(desk.book.intents[intent.client_order_id].reservation_active for intent in (up, down))
        assert not up.terminal and not down.terminal
        assert not account.creates
        assert desk.account_at is None
        assert not desk.book.integrity_error
        assert desk.cancel_acked == {f"nc-speed-fresh-{order.removeprefix('order-')}" for order in expected}
        if change in ("unchanged", "reversal"):
            # With fresh feeds, an acknowledged stale bid stands down until reconciliation.
            asyncio.run(desk._cancel_unsafe())
            assert calls == expected
            assert desk.book.reserved_usd == reserved
    finally:
        desk.close()


@pytest.mark.parametrize("shutdown", [False, True])
def test_refresh_keeps_lock_exception_but_honors_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shutdown: bool,
) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_pull": False})
    try:
        desk.client = account
        initial = desk.snapshot()
        old = replace(initial.windows[0], slug="KXBTC15M-fresh-lock",
                      start=clock.now() - 670, end=clock.now() + 230)
        desk.on_windows([old])
        seed = "nc-speed-lock-seed"
        # The genuine seed fill predates the old window's lock interval.
        placed = old.start + 1
        desk.book.update_cash(25, placed)
        desk.book.reserve_intent(old.slug, "up", "rest", .4, 1, placed, seed, .5)
        desk.book.mark_submitted(seed, "seed")
        assert desk.book.record_fill(ActualFill("seed", "seed", seed, old.slug, "up", .4, 1, 0,
                                               placed, is_taker=False))
        assert desk.book.reconcile_order(OrderSnapshot(seed, "seed", "executed", 1, 0, clock.now()),
                                         fills_complete=True)
        desk.intents[seed] = Intent(seed, old.slug, "up", "rest", .4, 1, .5, placed,
                                    order_id="seed", terminal=True)
        desk.book.update_cash(25, clock.now())
        for key, window, side, kind, lock in (
            ("nc-speed-fresh-lock", old.slug, "down", "take", True),
            ("nc-speed-fresh-up", TICKER, "up", "rest", False),
        ):
            desk.book.reserve_intent(window, side, kind, .48, 1, clock.now(), key, .5, lock=lock)
            desk.book.mark_submitted(key, key)
            desk.intents[key] = Intent(key, window, side, kind, .48, 1, .5, clock.now(),
                                       order_id=key, lock=lock)
        current = replace(initial, windows=(*initial.windows, old), bitcoin_price=79990)
        monkeypatch.setattr(desk, "snapshot", lambda: current)
        reserved = desk.book.reserved_usd

        async def fake_io(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            nonlocal current
            await asyncio.sleep(0)
            reply = fn(*args, **kwargs)
            clock.advance(1000)
            current = replace(current, windows=())
            desk.stopping = shutdown
            return reply

        monkeypatch.setattr(desk, "_io", fake_io)
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == (["nc-speed-fresh-up", "nc-speed-fresh-lock"] if shutdown
                                   else ["nc-speed-fresh-up"])
        assert desk.intents["nc-speed-fresh-lock"].cancel_requested is shutdown
        assert desk.book.reserved_usd == reserved
        assert not account.creates
        if shutdown:
            assert desk.cancel_reasons["nc-speed-fresh-lock"] == "shutdown"
    finally:
        desk.close()


@pytest.mark.parametrize("interrupted", [False, True])
def test_final_cancel_does_not_read_snapshot_after_await(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_pull": False})
    try:
        desk.client = account
        desk.book.update_cash(25, clock.now())
        key = "nc-speed-fresh-only"
        desk.book.reserve_intent(TICKER, "up", "rest", .48, 1, clock.now(), key, .5)
        desk.book.mark_submitted(key, "only")
        desk.intents[key] = Intent(key, TICKER, "up", "rest", .48, 1, .5, clock.now(), order_id="only")
        initial = replace(desk.snapshot(), bitcoin_price=79990)
        reads = 0

        def snapshot() -> LiveSnapshot:
            nonlocal reads
            reads += 1
            assert reads == 1, "A final cancel must not add a snapshot callback failure"
            return initial

        async def fake_io(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(0)
            if interrupted:
                raise asyncio.CancelledError
            return fn(*args, **kwargs)

        monkeypatch.setattr(desk, "snapshot", snapshot)
        monkeypatch.setattr(desk, "_io", fake_io)
        reserved = desk.book.reserved_usd
        if interrupted:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(desk._cancel_unsafe())
        else:
            asyncio.run(desk._cancel_unsafe())
        assert reads == 1
        assert account.cancels == ([] if interrupted else ["only"])
        assert desk.book.reserved_usd == reserved
        assert desk.book.intents[key].reservation_active
        assert desk.intents[key].cancel_requested
    finally:
        desk.close()
