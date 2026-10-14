"""Independent cancellation attacks with a deliberately stuck account read.

No network: fake venue, fake account keys and bounded thread events only.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from test_speeddesk_live import make_desk
from test_speeddesk_live_stale_bid import view

from nightcrawler.speeddesk_kalshi_client import KalshiClientError


async def reached(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 2), "Expected fake operation did not arrive"


def test_cancel_ack_during_slow_read_keeps_reservation_until_terminal_evidence(tmp_path: Path) -> None:
    desk, account, clock = make_desk(
        tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_kalshi_pull": False}
    )
    entered, release, cancelled = (threading.Event() for _ in range(3))

    async def scenario() -> None:
        view(desk, clock, 80000)
        await desk.step()
        assert len(account.creates) == 1
        reserved = desk.book.reserved_usd
        original_orders = account.list_orders
        calls = 0

        def slow_orders(**kwargs: Any) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            rows = original_orders(**kwargs)
            if calls == 1:
                entered.set()
                assert release.wait(4)
            return rows

        def lagging_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            del ticker
            account.cancels.append(order_id)
            cancelled.set()
            return {}  # Successful DELETE; subsequent GET still reports resting.

        account.list_orders = slow_orders  # type: ignore[method-assign]
        account.cancel = lagging_cancel  # type: ignore[method-assign]
        pending = asyncio.create_task(desk._reconcile())
        try:
            await reached(entered)
            view(desk, clock, 80600)
            await reached(cancelled)
            assert not pending.done(), "The GET should still be held"
            assert desk.book.reserved_usd == reserved
            # Force the old two-second retry timer to expire without allowing GET
            # to return. An acknowledged cancel must not become a DELETE storm.
            clock.advance(2.1)
            await asyncio.sleep(.15)
            assert len(account.cancels) == 1
            release.set()
            await asyncio.wait_for(pending, 2)
            assert desk.book.reserved_usd == reserved
            assert desk._active()[0].cancel_requested
            assert desk._waiting_reason()
            await desk._decide()
            assert len(account.creates) == 1
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        desk.close()


def test_failed_cancel_during_slow_read_cannot_retry_without_new_order_evidence(tmp_path: Path) -> None:
    desk, account, clock = make_desk(
        tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_kalshi_pull": False}
    )
    entered, release, cancelled = (threading.Event() for _ in range(3))

    async def scenario() -> None:
        view(desk, clock, 80000)
        await desk.step()
        reserved = desk.book.reserved_usd
        original_orders = account.list_orders
        calls = 0

        def slow_orders(**kwargs: Any) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            rows = original_orders(**kwargs)
            if calls == 1:
                entered.set()
                assert release.wait(4)
            return rows

        def uncertain_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            del ticker
            account.cancels.append(order_id)
            cancelled.set()
            raise KalshiClientError("cancel", "transport failure", uncertain=True, timed_out=True)

        account.list_orders = slow_orders  # type: ignore[method-assign]
        account.cancel = uncertain_cancel  # type: ignore[method-assign]
        pending = asyncio.create_task(desk._reconcile())
        try:
            await reached(entered)
            view(desk, clock, 80600)
            await reached(cancelled)
            # Advancing time cannot substitute for a newly completed order read.
            clock.advance(5)
            await asyncio.sleep(.15)
            assert len(account.cancels) == 1
            assert not pending.done()
            assert desk.book.reserved_usd == reserved
            assert desk._active()[0].uncertain
            assert len(account.creates) == 1
            release.set()
            await asyncio.wait_for(pending, 2)
            assert desk.book.reserved_usd == reserved
            assert desk._waiting_reason()
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        desk.close()


def test_cancelled_step_shutdown_cancels_known_order_before_read_finishes(tmp_path: Path) -> None:
    desk, account, clock = make_desk(
        tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_kalshi_pull": False}
    )
    entered, release, cancelled = (threading.Event() for _ in range(3))

    async def scenario() -> None:
        view(desk, clock, 80000)
        await desk.step()
        assert len(account.creates) == 1
        original_orders, original_cancel = account.list_orders, account.cancel
        calls = 0

        def slow_orders(**kwargs: Any) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            rows = original_orders(**kwargs)
            if calls == 1:
                entered.set()
                assert release.wait(4)
            return rows

        def record_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            result = original_cancel(order_id, ticker=ticker)
            cancelled.set()
            return result

        account.list_orders = slow_orders  # type: ignore[method-assign]
        account.cancel = record_cancel  # type: ignore[method-assign]
        pending = asyncio.create_task(desk.step())
        shutdown: asyncio.Task[None] | None = None
        try:
            await reached(entered)
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            shutdown = asyncio.create_task(desk.shutdown())
            await reached(cancelled)
            assert not release.is_set(), "Shutdown cancel must overtake the account GET"
            assert not shutdown.done(), "Outstanding read must still drain before account lock release"
            assert desk.book.reserved_usd > 0
            assert len(account.creates) == 1
            release.set()
            await asyncio.wait_for(shutdown, 2)
            assert desk.shutdown_done
            assert not desk._workers
            assert not desk.book.reserved_usd
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        desk.close()
