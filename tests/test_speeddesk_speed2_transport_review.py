"""Independent combined stop/speed/pull transport attacks. All account data are invented; no network."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest
from test_speeddesk_live import TICKER, FakeAccount, make_desk
from test_speeddesk_live_pull import CAPS, MAKERS, market, starter_bid_filled
from test_speeddesk_live_stop_receipts_review import near_stop, stop_receipts

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import (
    JOURNAL_KEY,
    ORDER_LIST_LAG_S,
    STATE_KEY,
    KalshiLiveDesk,
)
from nightcrawler.speeddesk_model import utc_day

Stop = Literal["day", "total"]


def _filled(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    starter_bid_filled(desk, account, clock)
    asyncio.run(desk._reconcile())
    assert desk.book.inventory[TICKER].up.shares == 5
    assert desk.book.inventory[TICKER].down.shares == 0
    assert not desk.book.integrity_error
    return desk, account, clock


def _image(desk: KalshiLiveDesk, target: Path) -> None:
    # A committed database plus its WAL, copied while no worker is writing. Never close/checkpoint the source
    # first: that would hide a missing pre-crash save. Ignore the process-local account lock and shared memory.
    shutil.copytree(desk.directory, target, ignore=shutil.ignore_patterns("*-shm", "controller.lock"))


def _recover(desk: KalshiLiveDesk, target: Path, account: FakeAccount, clock: FakeClock) -> KalshiLiveDesk:
    return KalshiLiveDesk(replace(desk.settings, speeddesk_kalshi_mode="paper"), target, desk.snapshot,
                          clock=clock.now, client_factory=lambda: account, direct_member_verified=True)


@pytest.mark.parametrize("stop", ["day", "total"])
def test_settlement_checkpoint_before_heartbeat_keeps_stop_and_receipt_together(
    tmp_path: Path, stop: Stop,
) -> None:
    """Speed saves a real settlement immediately inside reconcile, before the ordinary heartbeat runs."""
    desk, account, clock = _filled(tmp_path / "run")
    restored: KalshiLiveDesk | None = None
    try:
        # The later $2.35 real-filled loss leaves 5c under the stop. These anchors represent earlier losses.
        if stop == "total":
            desk.book.stop_anchor = 7.60
        else:
            desk.book.day_anchor[utc_day(clock.now())] = 3.60
        desk.checkpoint(durable=True)
        assert not stop_receipts(desk, stop)
        close = desk.book.windows[TICKER].end
        clock.advance(close + 1 - clock.now())
        account.account_positions = []
        account.resolutions = [{"ticker": TICKER, "market_result": "no", "revenue": 0,
                                "settled_time": close + .5}]
        asyncio.run(desk._reconcile())  # Deliberately no step/heartbeat after this checkpoint.
        assert desk.book.realized_pnl == pytest.approx(-2.35)
        assert desk.book.halted if stop == "total" else desk.book.day_latched(clock.now())
        assert len(stop_receipts(desk, stop)) == 1
        _image(desk, tmp_path / "crash")
        restored = _recover(desk, tmp_path / "crash", account, clock)
        assert restored.book.halted if stop == "total" else restored.book.day_latched(clock.now())
        assert len(stop_receipts(restored, stop)) == 1
        restored._heartbeat()
        assert len(stop_receipts(restored, stop)) == 1
        assert len(account.creates) == 1
    finally:
        if restored is not None:
            restored.close()
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
@pytest.mark.parametrize("exit_path", ["paper", "backoff", "auth"])
def test_stop_in_same_clock_instant_as_last_save_bypasses_speed_save_throttle(
    tmp_path: Path, stop: Stop, exit_path: str,
) -> None:
    desk, account, clock = make_desk(tmp_path / "run", caps=CAPS,
                                    mode="paper" if exit_path == "paper" else "live")
    restored: KalshiLiveDesk | None = None
    syncs: list[bool] = []
    original = desk.ledger.set_synchronous

    def synchronous(full: bool) -> None:
        syncs.append(full)
        original(full)

    try:
        desk.last_status = clock.now()
        desk.checkpoint(durable=True)
        desk.ledger.set_synchronous = synchronous
        near_stop(desk, stop)
        if exit_path == "backoff":
            desk.retry_at = clock.now() + 10
        elif exit_path == "auth":
            account.balance_error = KalshiClientError("balance", "request rejected", status=401)
        else:
            desk.client_factory = lambda: pytest.fail("An empty paper desk constructed an account client")
        asyncio.run(desk.step())
        assert syncs and syncs[-1] is True  # A stop receipt requires synced storage, even with no clock advance.
        assert len(stop_receipts(desk, stop)) == 1
        _image(desk, tmp_path / "crash")
        restored = _recover(desk, tmp_path / "crash", account, clock)
        assert restored.book.halted if stop == "total" else restored.book.day_latched(clock.now())
        assert len(stop_receipts(restored, stop)) == 1
        assert not account.creates
    finally:
        if restored is not None:
            restored.close()
        desk.close()


class Crash(BaseException):
    """Escape the controller without its error handler or heartbeat saving the in-memory state."""


@pytest.mark.parametrize("stop", ["day", "total"])
def test_latched_hedge_journal_survives_crash_then_paper_recovery_without_a_create(
    tmp_path: Path, stop: Stop,
) -> None:
    desk, account, clock = _filled(tmp_path / "run")
    restored: KalshiLiveDesk | None = None
    try:
        near_stop(desk, stop)
        desk._heartbeat()

        async def crash_before_network(*_args: Any, **_kwargs: Any) -> None:
            raise Crash

        desk._submit = crash_before_network
        with pytest.raises(Crash):
            asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .47, 5, .5))
        identity = next(key for key, value in desk.intents.items() if value.side == "down")
        assert identity not in desk.ledger.get_kv(STATE_KEY)["intents"]
        assert identity in desk.ledger.get_kv(JOURNAL_KEY)["intents"]
        expected_reserve = desk.book.reserved_usd
        _image(desk, tmp_path / "crash")
        restored = _recover(desk, tmp_path / "crash", account, clock)
        assert restored.book.strictly_balancing_intent(identity)
        assert restored.book.reserved_usd == pytest.approx(expected_reserve)
        assert len(stop_receipts(restored, stop)) == 1
        asyncio.run(restored.step())
        assert restored.book.intents[identity].reservation_active  # Absence before the close proves nothing.
        assert len(account.creates) == 1
        close = restored.book.windows[TICKER].end
        clock.advance(close + 1 - clock.now())
        account.account_positions = []
        account.resolutions = [{"ticker": TICKER, "market_result": "yes", "revenue": 500,
                                "settled_time": close + .5}]
        asyncio.run(restored.step())
        assert restored.book.intents[identity].reservation_active
        clock.advance(ORDER_LIST_LAG_S + 1)
        asyncio.run(restored.step())
        assert not restored.book.intents[identity].reservation_active
        assert restored.book.intents[identity].uncertainty == "never_reached_venue"
        assert restored.book.inventory[TICKER].up.shares == 5
        assert restored.book.inventory[TICKER].down.shares == 0
        assert restored.book.reserved_usd == 0
        assert not restored.book.integrity_error
        assert restored.book.halted if stop == "total" else restored.book.day_latched(clock.now())
        assert len(stop_receipts(restored, stop)) == 1  # A later win never silently replenishes the budget.
        assert len(account.creates) == 1 and not account.cancels
    finally:
        if restored is not None:
            restored.close()
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
def test_pull_cancel_keeps_late_partial_fill_liability_until_real_execution_arrives(
    tmp_path: Path, stop: Stop,
) -> None:
    desk, account, clock = _filled(tmp_path)
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 2
        identity = account.creates[1]["client_order_id"]
        near_stop(desk, stop)
        desk._heartbeat()
        assert desk.book.strictly_balancing_intent(identity)
        original = account.cancel

        def cancel_with_racing_fill(order_id: str, *, ticker: str) -> dict[str, Any]:
            result = original(order_id, ticker=ticker)
            account.orders[1]["fill_count_fp"] = "2.25"
            account.account_positions = [{"ticker": TICKER, "position_fp": "2.75"}]
            return result

        account.cancel = cancel_with_racing_fill
        market(desk, clock, .52)
        reserved = desk.book.reserved_usd
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["order-2"]
        assert desk.book.reserved_usd == pytest.approx(reserved)
        asyncio.run(desk._reconcile())
        assert desk.book.intents[identity].reservation_active
        assert desk.book.reserved_usd == pytest.approx(reserved)
        assert desk.book.inventory[TICKER].down.shares == 0  # An order's filled count is not an execution.
        account.executions.append({"fill_id": "review-cancel-race", "order_id": "order-2", "ticker": TICKER,
                                   "outcome_side": "no", "book_side": "ask", "count_fp": "2.25",
                                   "no_price_dollars": ".47", "fee_cost": "0.0000", "ts": clock.now()})
        asyncio.run(desk._reconcile())
        assert desk.book.inventory[TICKER].down.shares == 2.25
        assert not desk.book.intents[identity].reservation_active
        assert desk.book.reserved_usd == 0
        assert desk.book.at_risk_usd == pytest.approx(5 * .47 + 2.25 * .47 - 2.25)
        assert len(account.creates) == 2
    finally:
        desk.close()
