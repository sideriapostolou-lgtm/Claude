"""Independent execution-boundary checks; every account operation is a fake."""

from __future__ import annotations

import asyncio
import copy
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import Settings
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import STATE_KEY, KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, Window


class SimulatedCrash(BaseException):
    """A process death bypasses the controller's ordinary exception handling."""


class Account:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.controller: KalshiLiveDesk | None = None
        self.creates: list[dict[str, Any]] = []
        self.cancels: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.prints: list[dict[str, Any]] = []
        self.holdings: list[dict[str, Any]] = []
        self.settled: list[dict[str, Any]] = []
        self.create_result = "accepted"
        self.cancel_timeout = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def create_order(self, **request: Any) -> dict[str, Any]:
        assert request["before_send"]()
        assert self.controller is not None
        saved = self.controller.ledger.get_kv(STATE_KEY)
        client_id = request["client_order_id"]
        # The network boundary must already have a durable owned reservation.
        assert saved["intents"][client_id]["order_id"] == ""
        assert saved["book"]["intents"][client_id]["reservation_active"] is True
        assert saved["book"]["intents"][client_id]["unit_reserve"] > 0
        self.creates.append(request)
        if self.create_result == "crash":
            raise SimulatedCrash()
        if self.create_result == "timeout":
            raise KalshiClientError("create_order", "transport failure", uncertain=True)
        if self.create_result == "blocked":
            self.entered.set()
            assert self.release.wait(3), "test did not release its fake transport"
        order_id = f"order-{len(self.creates)}"
        yes_price = request["price"] if request["side"] == "up" else 1 - request["price"]
        self.rows.append({"client_order_id": client_id, "order_id": order_id,
                          "ticker": request["ticker"], "status": "resting",
                          "outcome_side": "yes" if request["side"] == "up" else "no",
                          "book_side": "bid" if request["side"] == "up" else "ask",
                          "yes_price_dollars": f"{yes_price:.4f}", "no_price_dollars": f"{1 - yes_price:.4f}",
                          "initial_count_fp": f"{request['size']:.2f}",
                          "fill_count_fp": "0.00", "remaining_count_fp": f"{request['size']:.2f}"})
        return {"order_id": order_id}

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        self.cancels.append(order_id)
        if self.cancel_timeout:
            raise KalshiClientError("cancel", "transport failure", uncertain=True)
        for row in self.rows:
            if row["order_id"] == order_id:
                assert row["ticker"] == ticker
                row.update(status="canceled", remaining_count_fp="0.00")
        return {"order_id": order_id, "reduced_by": "1.00"}

    def list_orders(self, **_: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.rows)

    def fills(self, **_: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.prints)

    def positions(self, **_: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.holdings)

    def settlements(self, **_: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.settled)

    def balance(self) -> dict[str, Any]:
        return {"balance_dollars": "25.0000", "balance": 2500, "updated_ts": int(self.clock.now())}

    def subaccount_balances(self) -> list[dict[str, Any]]:
        # Primary subaccount access is not evidence of Direct fee precision.
        return [{"subaccount_number": 0, "exchange_index": 2, "balance": "25.0000",
                 "updated_ts": int(self.clock.now())}]

    def close(self) -> None:
        pass


def configured(**changes: Any) -> Settings:
    return Settings(speeddesk_kalshi_mode="live", speeddesk_kalshi_live_confirm="yes",
                    kalshi_key_id="fake-account-id", kalshi_private_key="fake-signing-material").replace(**changes)


def companion(path: Path, *, settings: Settings | None = None,
              account: Account | None = None) -> tuple[KalshiLiveDesk, Account, FakeClock, Window]:
    clock = account.clock if account is not None else FakeClock()
    account = account or Account(clock)
    window = Window("KXBTC15M-26OCT121500-00", clock.now() - 10, clock.now() + 890, 100,
                    venue="kalshi", taker_coefficient=.07, maker_coefficient=0, fee_rounding="kalshi")

    def snapshot() -> LiveSnapshot:
        books = {(window.slug, side): Book(window.slug, side, (Level(.3, 10),), (Level(.4, 10),),
                                          clock.now(), "fake-book", exchange_at=clock.now()) for side in ("up", "down")}
        return LiveSnapshot(windows=(window,), books=books, bitcoin_price=100, bitcoin_at=clock.now(),
                            sigma=.001, maker_windows=frozenset({window.slug}))

    desk = KalshiLiveDesk(settings or configured(), path, snapshot, clock=clock.now, client_factory=lambda: account)
    account.controller = desk
    desk.on_windows([window])
    desk.on_tick(100, clock.now(), clock.now())
    for book in snapshot().books.values():
        desk.on_book(book)
    return desk, account, clock, window


def arm_fake(desk: KalshiLiveDesk, account: Account, clock: FakeClock) -> None:
    # Account precision is an explicit test fixture. Production must prove it.
    desk.client = account
    desk.authenticated = desk.startup_done = desk.fee_verified = True
    desk.book.limits = replace(desk.book.limits, fee_precision=.0001)
    desk.account_at = clock.now()
    desk.book.update_cash(25, clock.now())


@pytest.mark.parametrize("changes", [
    {"speeddesk_kalshi_mode": "paper"},
    {"speeddesk_kalshi_live_confirm": None},
    {"kalshi_key_id": None},
    {"kalshi_private_key": None},
])
def test_fresh_paper_or_missing_gate_never_constructs_account_client(tmp_path: Path, changes: dict[str, Any]) -> None:
    desk, account, _, _ = companion(tmp_path, settings=configured(**changes))
    try:
        def forbidden() -> None:
            pytest.fail("A gated-off fresh process touched an account client")
        desk.client_factory = forbidden
        asyncio.run(desk.step())
        assert desk.client is None
        assert not account.creates
        assert desk.panel()["mode"] == "paper"
    finally:
        desk.close()


def test_primary_subaccount_and_fresh_balance_do_not_prove_fee_precision(tmp_path: Path) -> None:
    desk, account, _, _ = companion(tmp_path)
    try:
        asyncio.run(desk.step())
        assert desk.authenticated
        assert not desk.fee_verified
        assert not account.creates
        assert "fee precision" in desk.panel()["reason"]
    finally:
        desk.close()


def test_second_controller_cannot_share_the_live_ledger_lock(tmp_path: Path) -> None:
    desk, account, _, _ = companion(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="lock"):
            companion(tmp_path, account=account)
    finally:
        desk.close()
    replacement, _, _, _ = companion(tmp_path, account=account)
    replacement.close()


@pytest.mark.parametrize("failure", ["timeout", "crash"])
def test_unknown_create_is_durable_and_paper_restart_never_submits_again(tmp_path: Path, failure: str) -> None:
    desk, account, clock, window = companion(tmp_path)
    arm_fake(desk, account, clock)
    account.create_result = failure
    try:
        if failure == "crash":
            with pytest.raises(SimulatedCrash):
                asyncio.run(desk._send(window, "up", "rest", .3, 2, .6))
        else:
            assert asyncio.run(desk._send(window, "up", "rest", .3, 2, .6))
        assert len(account.creates) == 1
        reserved = desk.book.reserved_usd
        assert reserved == pytest.approx(.6)
        assert desk.book.inventory[window.slug].up.shares == 0
    finally:
        desk.close()
    restored, _, _, _ = companion(tmp_path, settings=configured(speeddesk_kalshi_mode="paper"), account=account)
    try:
        asyncio.run(restored.step())
        asyncio.run(restored.step())
        assert len(account.creates) == 1
        assert restored.book.reserved_usd == reserved
        assert all(intent.uncertain for intent in restored._active())
        assert not hasattr(restored.client, "create_order")
    finally:
        restored.close()


def test_partial_fill_and_failed_cancel_keep_cash_and_loss_risk_reserved(tmp_path: Path) -> None:
    desk, account, clock, window = companion(tmp_path, settings=configured(speeddesk_kalshi_window_usd=2, speeddesk_kalshi_open_usd=4, speeddesk_kalshi_day_stop_usd=3, speeddesk_kalshi_total_stop_usd=5))
    arm_fake(desk, account, clock)
    try:
        assert asyncio.run(desk._send(window, "up", "take", .4, 2, .6))
        intent = next(iter(desk.intents.values()))
        account.rows[0].update(fill_count_fp="0.50", remaining_count_fp="1.50")
        account.prints = [{"fill_id": "actual-half", "order_id": intent.order_id, "ticker": window.slug,
                           "outcome_side": "yes", "book_side": "bid", "yes_price_dollars": "0.4000",
                           "count_fp": "0.50", "fee_cost": "0.0084", "ts": clock.now()}]
        account.holdings = [{"ticker": window.slug, "position_fp": "0.50"}]
        asyncio.run(desk._reconcile())
        assert desk.book.inventory[window.slug].up.shares == .5
        assert desk.book.open_cost_usd == pytest.approx(.2084)
        assert desk.book.reserved_usd == pytest.approx(.63)
        account.cancel_timeout = True
        asyncio.run(desk._cancel(intent, "feed_gap"))
        assert desk.book.at_risk_usd == pytest.approx(.8384)
        other = replace(window, slug="KXBTC15M-26OCT121515-15")
        desk.book.add_window(other)
        desk.book.update_cash(.7, clock.now())
        assert desk.book.can_buy(other.slug, "up", "take", .4, 1, clock.now()) == "cash_budget"
        desk.book.update_cash(25, clock.now())
        desk.book.day_pnl[desk.panel()["today"]["day"]] = -2.3
        assert desk.book.can_buy(other.slug, "up", "take", .4, 1, clock.now()) == "day_stop"
        desk.book.realized_pnl = -4.3
        assert desk.book.risk_status(clock.now())["halted"]
        assert desk.book.at_risk_usd == pytest.approx(.8384)
    finally:
        desk.close()


@pytest.mark.parametrize("field,value", [
    ("ticker", "KXBTC15M-26OCT121515-15"),
    ("outcome_side", "no"),
    ("book_side", "ask"),
    ("initial_count_fp", "99.00"),
    ("yes_price_dollars", "0.7000"),
    ("order_id", "different-order"),
])
def test_same_client_id_cannot_confirm_an_order_with_different_terms(
    tmp_path: Path, field: str, value: str,
) -> None:
    desk, account, clock, window = companion(tmp_path)
    arm_fake(desk, account, clock)
    try:
        assert asyncio.run(desk._send(window, "up", "rest", .3, 2, .6))
        reserved = desk.book.reserved_usd
        account.rows[0].update(status="canceled", remaining_count_fp="0.00")
        account.rows[0][field] = value
        asyncio.run(desk.step())
        assert desk.account_at is None
        assert desk.book.reserved_usd == reserved
        assert not next(iter(desk.intents.values())).terminal
        assert len(account.creates) == 1
        assert not account.cancels
    finally:
        desk.close()


def test_delayed_settlement_keeps_the_venues_actual_utc_day(tmp_path: Path) -> None:
    midnight = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    account = Account(FakeClock(midnight - 1000))
    desk, _, clock, window = companion(tmp_path, account=account)
    arm_fake(desk, account, clock)
    try:
        assert asyncio.run(desk._send(window, "up", "take", .4, 2, .6))
        intent = next(iter(desk.intents.values()))
        account.rows[0].update(status="executed", fill_count_fp="2.00", remaining_count_fp="0.00")
        account.prints = [{"fill_id": "actual-two", "order_id": intent.order_id, "ticker": window.slug,
                           "outcome_side": "yes", "book_side": "bid", "yes_price_dollars": "0.4000",
                           "count_fp": "2.00", "fee_cost": "0.0336", "ts": clock.now() + .25}]
        settled_at = window.end + 5
        account.settled = [{"ticker": window.slug, "market_result": "yes", "revenue": 200,
                            "yes_count_fp": "2.00", "no_count_fp": "0.00",
                            "yes_total_cost_dollars": "0.8000", "no_total_cost_dollars": "0.0000",
                            "fee_cost": "0.0336", "settled_time": datetime.fromtimestamp(settled_at, UTC).isoformat()}]
        clock.set(midnight + 5)
        asyncio.run(desk._reconcile())
        result = desk.book.settled[window.slug]
        assert result.at == settled_at
        assert desk.book.day_pnl["2026-10-12"] == pytest.approx(1.1664)
        assert desk.book.day_pnl.get("2026-10-13", 0) == 0
        assert desk.panel()["today"]["pnl_usd"] == 0
    finally:
        desk.close()


def test_cancelled_caller_cannot_release_lock_or_leave_late_created_order_resting(tmp_path: Path) -> None:
    desk, account, clock, window = companion(tmp_path)
    arm_fake(desk, account, clock)
    account.create_result = "blocked"

    async def scenario() -> None:
        task = asyncio.create_task(desk._send(window, "up", "rest", .3, 2, .6))
        assert await asyncio.to_thread(account.entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(RuntimeError, match="lock"):
            desk.close()
        with pytest.raises(RuntimeError, match="lock"):
            companion(tmp_path, account=account)
        shutdown = asyncio.create_task(desk.shutdown())
        await asyncio.sleep(0)
        assert not shutdown.done()
        account.release.set()
        await asyncio.wait_for(shutdown, 3)
        assert account.cancels == ["order-1"]
        assert account.rows[0]["status"] == "canceled"
        assert desk.book.reserved_usd == 0
        assert len(account.creates) == 1

    try:
        asyncio.run(scenario())
    finally:
        account.release.set()
        desk.close()


def test_owner_trade_in_the_bots_window_neither_freezes_the_desk_nor_breaks_its_settlement(tmp_path: Path) -> None:
    """2026-10-13 00:51 and 01:13 UTC: the owner traded by hand in the window the bot was working. The venue
    position then includes the owner's contracts, every reconcile came back inconsistent, and every window froze
    until the close. The bot already leaves that window alone; it keeps its own books from its own fills, keeps
    trading the other windows, and settles from its own contracts (the venue revenue includes the owner's)."""
    desk, account, clock, window = companion(tmp_path)
    arm_fake(desk, account, clock)
    try:
        assert asyncio.run(desk._send(window, "up", "take", .4, 2, .6))
        intent = next(iter(desk.intents.values()))
        account.rows[0].update(status="executed", fill_count_fp="2.00", remaining_count_fp="0.00")
        bot_fill = {"fill_id": "bot-two", "order_id": intent.order_id, "ticker": window.slug,
                    "outcome_side": "yes", "book_side": "bid", "yes_price_dollars": "0.4000",
                    "count_fp": "2.00", "fee_cost": "0.0336", "ts": clock.now() + .25}
        owner_fill = {"fill_id": "owner-by-hand", "order_id": "owner-order", "ticker": window.slug,
                      "outcome_side": "no", "book_side": "ask", "no_price_dollars": "0.6000",
                      "count_fp": "3.00", "fee_cost": "0.0504", "ts": clock.now() + .5}
        account.prints = [bot_fill, owner_fill]
        account.holdings = [{"ticker": window.slug, "position_fp": "-1.00"}]  # bot +2 up, owner 3 down
        clock.advance(1)
        asyncio.run(desk._reconcile())
        assert window.slug in desk.foreign_windows
        assert desk.account_at is not None  # consistent: the other windows keep trading
        assert desk.book.inventory[window.slug].up.shares == 2 and desk.book.inventory[window.slug].down.shares == 0
        settled_at = window.end + 5
        account.holdings = []
        # Down won: the owner's 3 contracts pay $3 into the same market's settlement; the bot's 2 up lose.
        account.settled = [{"ticker": window.slug, "market_result": "no", "revenue": 300,
                            "yes_count_fp": "2.00", "no_count_fp": "3.00",
                            "yes_total_cost_dollars": "0.8000", "no_total_cost_dollars": "1.8000",
                            "fee_cost": "0.0840", "settled_time": datetime.fromtimestamp(settled_at, UTC).isoformat()}]
        clock.set(settled_at + 1)
        asyncio.run(desk._reconcile())
        assert desk.book.integrity_error is None and not desk.fatal_reason
        assert desk.book.settled[window.slug].pnl_usd == pytest.approx(-.8336)  # the bot's own result only
    finally:
        desk.close()


def test_an_unexplained_position_in_a_bot_window_still_stops_new_orders(tmp_path: Path) -> None:
    """The relaxation covers only windows with a fill that is provably not the bot's. A position change with no
    such fill (a fill not yet visible, or anything unexplained) still blocks every new order until it reconciles."""
    desk, account, clock, window = companion(tmp_path)
    arm_fake(desk, account, clock)
    try:
        assert asyncio.run(desk._send(window, "up", "take", .4, 2, .6))
        account.holdings = [{"ticker": window.slug, "position_fp": "2.00"}]  # position seen, fill not yet visible
        clock.advance(1)
        asyncio.run(desk._reconcile())
        assert window.slug not in desk.foreign_windows
        assert desk.account_at is None
    finally:
        desk.close()
