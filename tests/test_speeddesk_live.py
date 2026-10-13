"""Offline execution-controller checks; no account or network is accessed."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.clock import FakeClock
from nightcrawler.config import Secret, Settings
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, Window, utc_day

TICKER = "KXBTC15M-26OCT121900-00"


class FakeAccount:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.orders: list[dict[str, Any]] = []
        self.executions: list[dict[str, Any]] = []
        self.account_positions: list[dict[str, Any]] = []
        self.resolutions: list[dict[str, Any]] = []
        self.creates: list[dict[str, Any]] = []
        self.cancels: list[str] = []
        self.cash = 25.0
        self.reads = 0
        self.balance_error: Exception | None = None
        self.create_error: Exception | None = None

    def balance(self) -> dict[str, Any]:
        self.reads += 1
        if self.balance_error:
            raise self.balance_error
        return {"balance_dollars": f"{self.cash:.4f}"}

    def list_orders(self, **_kwargs: Any) -> list[dict[str, Any]]:
        self.reads += 1
        return [dict(order) for order in self.orders]

    def fills(self, **_kwargs: Any) -> list[dict[str, Any]]:
        self.reads += 1
        return [dict(fill) for fill in self.executions]

    def positions(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return self.account_positions

    def settlements(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return self.resolutions

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        guard = kwargs.pop("before_send")
        if not guard():
            raise KalshiClientError("create_order", "send_guard_rejected", uncertain=False)
        self.creates.append(kwargs)
        if self.create_error:
            raise self.create_error
        order_id = f"order-{len(self.creates)}"
        self.orders.append({"order_id": order_id, "client_order_id": kwargs["client_order_id"],
                            "ticker": kwargs["ticker"], "status": "resting", "fill_count_fp": "0.00",
                            "remaining_count_fp": str(kwargs["size"]), "initial_count_fp": str(kwargs["size"]),
                            "outcome_side": "yes" if kwargs["side"] == "up" else "no",
                            "book_side": "bid" if kwargs["side"] == "up" else "ask",
                            "yes_price_dollars": str(kwargs["price"] if kwargs["side"] == "up" else 1 - kwargs["price"]),
                            "no_price_dollars": str(kwargs["price"] if kwargs["side"] == "down" else 1 - kwargs["price"])})
        return {"order_id": order_id}

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        self.cancels.append(order_id)
        for order in self.orders:
            if order["order_id"] == order_id:
                assert order["ticker"] == ticker
                order.update(status="canceled", remaining_count_fp="0.00")
        return {}

    def close(self) -> None:
        pass


def make_desk(tmp_path: Path, *, mode: str = "live", confirm: str | None = "yes",
              keys: bool = True, direct: bool = True) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    clock = FakeClock()
    account = FakeAccount(clock)
    settings = Settings(data_dir=tmp_path, speeddesk_kalshi_mode=mode,
                        speeddesk_kalshi_live_confirm=Secret(confirm) if confirm else None,
                        kalshi_key_id=Secret("fake-key-id") if keys else None,
                        kalshi_private_key=Secret("fake-private-key") if keys else None)
    window = Window(TICKER, clock.now() - 10, clock.now() + 890, start_price=80000,
                    venue="kalshi", taker_coefficient=.07, maker_coefficient=0,
                    min_trade_qty=.01, fee_rounding="kalshi")
    books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),),
                                 (Level(.4 if side == "up" else .6, 10),), clock.now(), "book",
                                 source="rest", requested_at=clock.now()) for side in ("up", "down")}
    snapshot = LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}))
    desk = KalshiLiveDesk(settings, tmp_path / "live", lambda: snapshot, clock=clock.now,
                          client_factory=lambda: account, direct_member_verified=direct)
    desk.on_windows([window])
    desk.on_tick(80000, clock.now(), clock.now())
    for book in books.values():
        desk.on_book(book)
    return desk, account, clock


@pytest.mark.parametrize(("mode", "confirm", "keys"), [("paper", "yes", True), ("live", None, True),
                                                          ("live", "YES", True), ("live", "yes", False)])
def test_missing_gate_never_constructs_account_client(tmp_path: Path, mode: str, confirm: str | None,
                                                      keys: bool) -> None:
    desk, account, _ = make_desk(tmp_path, mode=mode, confirm=confirm, keys=keys)
    try:
        desk.client_factory = lambda: pytest.fail("An incomplete live gate touched the account client")
        asyncio.run(desk.step())
        assert desk.client is None
        assert desk.panel()["mode"] == "paper"
        assert account.reads == 0
    finally:
        desk.close()


def test_balance_authentication_failure_prevents_live_order(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    account.balance_error = KalshiClientError("balance", "request rejected", status=401)
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk.auth_failed
        assert not desk.panel()["authenticated"]
        assert "authentication" in desk.panel()["reason"]
    finally:
        desk.close()


def test_fee_precision_is_never_guessed_from_account_access(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path, direct=False)
    try:
        asyncio.run(desk.step())
        assert desk.authenticated
        assert not account.creates
        assert desk.book.limits.fee_precision == .01
        assert "fee precision" in desk.panel()["reason"]
    finally:
        desk.close()


def test_intent_is_durable_before_real_order_and_twin_has_no_authority(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    original = account.create_order

    def inspect(**kwargs: Any) -> dict[str, Any]:
        saved = desk.ledger.get_kv("kalshi_live_state")
        identity = kwargs["client_order_id"]
        assert identity in saved["book"]["intents"]
        assert saved["book"]["intents"][identity]["reservation_active"]
        return original(**kwargs)

    account.create_order = inspect  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert desk.book.at_risk_usd <= 2
        assert desk.book.inventory[TICKER].up.shares == 0  # acceptance is not a fill
        assert desk.twin.orders
        assert desk.ledger.verify_chain() == (True, None)
    finally:
        desk.close()


def test_unknown_create_never_retries_or_releases_reservation(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True)
    try:
        asyncio.run(desk.step())
        reserved = desk.book.reserved_usd
        assert reserved > 0
        for _ in range(3):
            clock.advance(.25)
            asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert desk.book.reserved_usd == reserved
        assert any(intent.uncertain for intent in desk.intents.values())
    finally:
        desk.close()


def test_actual_fill_drives_inventory_and_partial_reservation(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        original_risk = desk.book.at_risk_usd
        account.orders[0].update(fill_count_fp="1.00", remaining_count_fp=str(intent.size - 1))
        account.executions.append({"fill_id": "real-fill", "order_id": intent.order_id, "ticker": TICKER,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": "1.00",
                                   "yes_price_dollars": ".40", "fee_cost": ".0168", "ts": desk.clock()})
        account.account_positions = [{"ticker": TICKER, "position_fp": "1.00"}]
        asyncio.run(desk._reconcile())
        assert desk.book.inventory[TICKER].up.shares == 1
        assert desk.book.inventory[TICKER].up.fees == pytest.approx(.0168)
        assert 0 < desk.book.reserved_usd < original_risk
        assert desk.panel()["today"]["fills"] == 1
        assert desk.twin.inventory[TICKER].up.shares == 0
    finally:
        desk.close()


@pytest.mark.parametrize("trigger", ["stale", "cutoff", "mode", "shutdown"])
def test_real_orders_cancel_for_required_triggers(tmp_path: Path, trigger: str) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        if trigger == "shutdown":
            asyncio.run(desk.shutdown())
        else:
            if trigger == "stale":
                clock.advance(4)
            elif trigger == "cutoff":
                clock.advance(711)
            else:
                desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
            asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_startup_paper_recovery_only_cancels_and_reconciles(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    asyncio.run(desk.step())
    settings, snapshot = replace(desk.settings, speeddesk_kalshi_mode="paper"), desk.snapshot
    desk.close()
    restored = KalshiLiveDesk(settings, tmp_path / "live", snapshot, clock=clock.now,
                              client_factory=lambda: account)
    try:
        account.create_order = lambda **_kwargs: pytest.fail("Paper recovery created an order")  # type: ignore[method-assign]
        asyncio.run(restored.step())
        assert account.cancels == ["order-1"]
        assert restored.book.reserved_usd == 0
        assert not hasattr(restored.client, "create_order")
        assert restored.panel()["mode"] == "paper"
    finally:
        restored.close()


def test_polymarket_windows_cannot_reach_order_client(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    snapshot = desk.snapshot()
    desk.snapshot = lambda: replace(snapshot, windows=(replace(snapshot.windows[0], venue="polymarket_us"),))
    try:
        asyncio.run(desk.step())
        assert not account.creates
    finally:
        desk.close()


def test_owner_order_is_not_canceled_or_adopted(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    account.orders.append({"order_id": "owner-order", "client_order_id": "owner-client", "ticker": TICKER,
                           "status": "resting", "fill_count_fp": "0.00", "remaining_count_fp": "2.00"})
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert not account.cancels
        assert TICKER in desk.foreign_windows
    finally:
        desk.close()


def test_paper_restart_reconciles_filled_exposure_without_resting_orders(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    asyncio.run(desk.step())
    intent = next(iter(desk.intents.values()))
    account.orders[0].update(status="executed", fill_count_fp=str(intent.size), remaining_count_fp="0.00")
    account.executions.append({"fill_id": "full-real-fill", "order_id": intent.order_id, "ticker": TICKER,
                               "outcome_side": "yes", "book_side": "bid", "count_fp": str(intent.size),
                               "yes_price_dollars": ".40", "fee_cost": str(intent.size * .0168), "ts": desk.clock()})
    account.account_positions = [{"ticker": TICKER, "position_fp": str(intent.size)}]
    asyncio.run(desk._reconcile())
    assert not desk._active()
    assert desk.book.open_cost_usd > 0
    settings, snapshot = replace(desk.settings, speeddesk_kalshi_mode="paper"), desk.snapshot
    desk.close()
    restored = KalshiLiveDesk(settings, tmp_path / "live", snapshot, clock=clock.now,
                              client_factory=lambda: account)
    try:
        reads = account.reads
        asyncio.run(restored.step())
        assert account.reads > reads
        assert not hasattr(restored.client, "create_order")
        assert restored.panel()["positions"] == 1
        assert len(account.creates) == 1
    finally:
        restored.close()


def test_changed_fee_terms_cancel_and_block_that_window(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        desk.on_windows([replace(desk.snapshot().windows[0], taker_coefficient=.08)])
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert TICKER in desk.changed_windows
        assert len(account.creates) == 1
    finally:
        desk.close()


@pytest.mark.parametrize("flag", ["speeddesk_enabled", "speeddesk_kalshi_enabled"])
def test_disabled_desk_never_initializes_real_client(tmp_path: Path, flag: str) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        desk.settings = replace(desk.settings, **{flag: False})
        desk.client_factory = lambda: pytest.fail("Disabled desk constructed account client")
        asyncio.run(desk.step())
        assert desk.client is None
        assert not account.creates
    finally:
        desk.close()


def test_eventually_visible_create_id_is_resolved_without_adopting_foreign_fills(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True)
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        row = {"order_id": "late-order", "client_order_id": intent.client_order_id, "ticker": TICKER,
               "status": "resting", "fill_count_fp": "0.00", "remaining_count_fp": str(intent.size),
               "initial_count_fp": str(intent.size), "outcome_side": "yes", "book_side": "bid",
               "yes_price_dollars": str(intent.price), "no_price_dollars": str(1 - intent.price)}
        calls = 0

        def delayed_orders(**_kwargs: Any) -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            return [] if calls == 1 else [row]

        account.list_orders = delayed_orders  # type: ignore[method-assign]
        asyncio.run(desk._reconcile())
        assert intent.order_id == "late-order"
        assert desk.book.integrity_error is None
        assert desk.account_at is None
        asyncio.run(desk._reconcile())
        assert not intent.uncertain
        assert desk.account_at is not None
        assert TICKER not in desk.foreign_windows
        assert len(account.creates) == 1
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total", "integrity"])
def test_financial_stop_also_cancels_existing_real_orders(tmp_path: Path, stop: str) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        if stop == "day":
            desk.book.day_pnl[utc_day(clock.now())] = -3
        elif stop == "total":
            desk.book.halted, desk.book.halt_reason = True, "total_loss"
        else:
            desk.book.integrity_error = "fill_exceeded_reserved_terms"
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert len(account.creates) == 1
        assert desk.panel()["mode"] == "paper"
    finally:
        desk.close()


def test_starter_leaves_budget_for_a_balancing_whole_pair(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        assert intent.size == 2  # Four affordable Up contracts would strand the hedge.
        account.orders[0].update(status="executed", fill_count_fp="2.00", remaining_count_fp="0.00")
        account.executions.append({"fill_id": "starter-fill", "order_id": intent.order_id, "ticker": TICKER,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": "2.00",
                                   "yes_price_dollars": ".40", "fee_cost": ".0336", "ts": desk.clock()})
        account.account_positions = [{"ticker": TICKER, "position_fp": "2.00"}]
        asyncio.run(desk.step())
        assert len(account.creates) == 2
        assert account.creates[1]["side"] == "down"
        assert account.creates[1]["size"] == 2
        assert desk.book.at_risk_usd <= 2
    finally:
        desk.close()


def test_one_refused_order_keeps_trading_but_three_refusals_in_a_row_pause(tmp_path: Path) -> None:
    """2026-10-12 23:39: one create_order 400 paused new orders as an "account reconciliation" failure.
    A single definite refusal is about that one order: record Kalshi's code and keep trading. Three in a
    row still pause, so a real account problem (no cash on the shard) cannot spam orders."""
    desk, account, clock = make_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "request rejected", status=400,
                                             code="post_only_cross")
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert desk.errors == 0 and desk.clock() >= desk.retry_at
        refused = [event for event in desk.latest_events if event["event"] == "speeddesk_live_reject"]
        assert refused and refused[-1]["code"] == "post_only_cross" and refused[-1]["status"] == 400
        assert desk.book.reserved_usd == 0
        for _ in range(2):
            clock.advance(1.1)
            asyncio.run(desk.step())
        assert len(account.creates) == 3
        assert desk.errors == 1 and desk.clock() < desk.retry_at
    finally:
        desk.close()


def test_send_guard_stop_is_not_an_account_error(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    account.create_order = lambda **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        KalshiClientError("create_order", "send_guard_rejected"))
    try:
        for _ in range(4):
            asyncio.run(desk.step())
            clock.advance(1.1)
        assert desk.errors == 0 and desk.clock() >= desk.retry_at
        assert not any(event["event"] == "speeddesk_live_reject" for event in desk.latest_events)
        assert desk.book.reserved_usd == 0
    finally:
        desk.close()
