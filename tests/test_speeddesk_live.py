"""Offline execution-controller checks; no account or network is accessed."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.clock import FakeClock
from nightcrawler.config import Secret, Settings
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot, durable_state
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


# The $5 per window / $10 open caps that were in force (the risk book's inner ceiling) until 2026-10-13 15:15 UTC;
# tests written against them keep them as their default, and the owner's $10 / $20 is tested on its own.
FIVE_DOLLAR_CAPS = {"speeddesk_kalshi_window_usd": 5.0, "speeddesk_kalshi_open_usd": 10.0}
# The caps before the owner's 2026-10-13 raise; mechanism tests that count contracts keep them.
SMALL_CAPS = {"speeddesk_kalshi_window_usd": 2.0, "speeddesk_kalshi_open_usd": 4.0,
              "speeddesk_kalshi_day_stop_usd": 3.0, "speeddesk_kalshi_total_stop_usd": 5.0}


def make_desk(tmp_path: Path, *, mode: str = "live", confirm: str | None = "yes",
              keys: bool = True, direct: bool = True, caps: dict[str, float] | None = None,
              extra: dict[str, Any] | None = None) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    clock = FakeClock()
    account = FakeAccount(clock)
    settings = Settings(data_dir=tmp_path, speeddesk_kalshi_mode=mode,
                        speeddesk_kalshi_live_confirm=Secret(confirm) if confirm else None,
                        kalshi_key_id=Secret("fake-key-id") if keys else None,
                        kalshi_private_key=Secret("fake-private-key") if keys else None, **(FIVE_DOLLAR_CAPS if caps is None else caps),
                        **(extra or {}))
    window = Window(TICKER, clock.now() - 10, clock.now() + 890, start_price=80000,
                    venue_start_price=80000, venue="kalshi", taker_coefficient=.07, maker_coefficient=0,
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
    desk, account, _ = make_desk(tmp_path, caps=SMALL_CAPS)
    original = account.create_order

    def inspect(**kwargs: Any) -> dict[str, Any]:
        saved = durable_state(desk.ledger)  # what a restart reads: the last full save plus the pre-send journal
        assert saved is not None
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
    desk, account, clock = make_desk(tmp_path, caps=SMALL_CAPS)
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
    desk, account, _ = make_desk(tmp_path, caps=SMALL_CAPS)
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
    row still pause between attempts, as every refusal did before (a lasting account problem such as no
    cash on the shard still retries, rate-limited by the pause and a fresh account read each time)."""
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
        assert [event["code"] for event in desk.latest_events if event["event"] == "speeddesk_live_reject"][-1] \
            == "post_only_cross"  # the pausing refusal keeps Kalshi's reason too
        assert desk.panel()["trading_now"] is False and "Paused" in desk.panel()["waiting"]
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


def test_cancel_404_for_an_order_already_gone_does_not_pause_trading(tmp_path: Path) -> None:
    """2026-10-12: a repeat cancel of an order Kalshi had already canceled returned 404 and the desk paused
    itself for minutes. A 404 means nothing of ours rests there: keep the reservation, let the order list
    confirm it, and do not count it as an account error."""
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert [order["status"] for order in account.orders] == ["resting"]

        def gone(order_id: str, *, ticker: str) -> dict[str, Any]:
            account.cancels.append(order_id)
            for order in account.orders:
                order.update(status="canceled", remaining_count_fp="0.00")
            raise KalshiClientError("cancel", "request rejected", status=404)

        account.cancel = gone  # type: ignore[method-assign]
        clock.advance(711)  # past the cutoff: the resting bid must be canceled
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert desk.errors == 0
        assert not any(event["event"] == "speeddesk_live_reject" for event in desk.latest_events)
        clock.advance(5)
        asyncio.run(desk.step())
        assert all(intent.terminal for intent in desk.intents.values())
    finally:
        desk.close()


def test_label_stays_real_money_between_orders(tmp_path: Path) -> None:
    """2026-10-13 00:15: after every order the desk briefly re-reads the account or waits for a cancel to
    confirm. The town showed "PRACTICE" in those seconds and the owner thought it had stopped. Real money is
    still on: keep the label and say what it is waiting for."""
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        panel = desk.panel()
        assert panel["mode"] == "live" and panel["status"] == "REAL MONEY (Kalshi)"
        assert panel["real_orders_available"] is True
        assert panel["trading_now"] is False and panel["waiting"] == "Kalshi account data stale"
    finally:
        desk.close()


# The locked-in rule (owner, 2026-10-13): near the close a half-filled pair is completed, never left as a coin flip.

def at_lock_time(desk: KalshiLiveDesk, clock: FakeClock, *, up_ask: float, down_ask: float,
                 before_close: float = 239) -> None:
    """Move to `before_close` seconds before the close with fresh books at these asks."""
    window = desk.book.windows[TICKER]
    clock.advance(window.end - before_close - clock.now())
    books = {(TICKER, side): Book(TICKER, side, (Level(round(ask - .02, 2), 10),), (Level(ask, 10),),
                                 clock.now(), "book", source="rest", requested_at=clock.now())
             for side, ask in (("up", up_ask), ("down", down_ask))}
    snapshot = LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}))
    desk.snapshot = lambda: snapshot  # type: ignore[method-assign]
    for book in books.values():
        desk.on_book(book)


def fill_order(account: FakeAccount, clock: FakeClock, index: int, *, side: str, price: float, size: int) -> None:
    order = account.orders[index]
    order.update(status="executed", fill_count_fp=f"{size:.2f}", remaining_count_fp="0.00")
    outcome = "yes" if side == "up" else "no"
    account.executions.append({"fill_id": f"fill-{index}", "order_id": order["order_id"], "ticker": TICKER,
                               "outcome_side": outcome, "book_side": "bid" if side == "up" else "ask",
                               "count_fp": f"{size:.2f}", f"{outcome}_price_dollars": f"{price:.2f}",
                               "fee_cost": f"{int(.07 * price * (1 - price) * size * 10000) / 10000:.4f}",
                               "ts": clock.now()})


def starter_filled(desk: KalshiLiveDesk, account: FakeAccount, clock: FakeClock) -> None:
    asyncio.run(desk.step())
    assert [(c["side"], c["kind"], c["price"], c["size"]) for c in account.creates] == [("up", "take", .4, 5)]
    fill_order(account, clock, 0, side="up", price=.4, size=5)
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]


def steps(desk: KalshiLiveDesk, clock: FakeClock, count: int = 3) -> None:
    for _ in range(count):
        asyncio.run(desk.step())
        clock.advance(.3)


def test_lock_completes_a_losing_half_pair_and_caps_the_loss(tmp_path: Path) -> None:
    """Bitcoin moved against the starter: the bot pays up to complete the pair instead of riding a coin flip."""
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.22, down_ask=.8)
        steps(desk, clock)
        assert len(account.creates) == 2
        lock = account.creates[1]
        assert (lock["side"], lock["kind"], lock["price"], lock["size"]) == ("down", "take", .8, 5)
        assert lock["expiration_ts"] is None  # immediate-or-cancel, never resting into the close
        # Edge, pair cap and buying cutoff would all have refused it as a normal buy.
        assert desk.book.can_buy(TICKER, "down", "take", .8, 5, clock.now()) == "cutoff"
        risk_before = desk.book.open_loss_usd
        fill_order(account, clock, 1, side="down", price=.8, size=5)
        account.account_positions = []  # Kalshi nets up+down into $1 each at once
        steps(desk, clock)
        assert desk.book.lock_side(TICKER) == (None, 0.0)
        assert len(account.creates) == 2
        # Locked: 5 x ($0.40 + $0.80) + $0.14 fees - $5 = $1.14 whatever happens, instead of up to $2.08.
        assert desk.book.open_loss_usd == pytest.approx(1.14) and risk_before == pytest.approx(2.084)
        assert desk.book.at_risk_usd == pytest.approx(desk.book.open_loss_usd)
        assert not desk.book.halted
        assert any(event.get("kind") == "lock" for event in desk.latest_events)
    finally:
        desk.close()


def test_lock_turns_a_winning_half_pair_into_locked_profit(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.9, down_ask=.08)
        steps(desk, clock)
        lock = account.creates[1]
        assert (lock["side"], lock["price"], lock["size"]) == ("down", .08, 5)
        fill_order(account, clock, 1, side="down", price=.08, size=5)
        account.account_positions = []
        steps(desk, clock)
        assert desk.book.open_loss_usd == 0  # $2.40 + fees paid for $5 guaranteed
    finally:
        desk.close()


def test_a_decided_window_or_the_final_seconds_are_left_alone(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.02, down_ask=.98)  # above the 97c lock price: already decided
        steps(desk, clock)
        assert len(account.creates) == 1
        assert any(event["event"] == "speeddesk_live_lock" and event["reason"] == "lock_price"
                   for event in desk.latest_events)
        at_lock_time(desk, clock, up_ask=.3, down_ask=.7, before_close=15)  # too close to the close
        steps(desk, clock)
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_lock_still_completes_during_a_money_stop_but_never_with_live_off(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.3, down_ask=.7)
        desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        steps(desk, clock)
        assert len(account.creates) == 1  # live switches off: nothing is ever sent
        desk.settings = replace(desk.settings, speeddesk_kalshi_mode="live")
        desk.book.day_pnl[utc_day(clock.now())] = -6  # daily loss stop is in force
        assert desk.book.risk_status(clock.now())["day_stopped"]
        steps(desk, clock)
        assert [(c["side"], c["price"]) for c in account.creates[1:]] == [("down", .7)]
    finally:
        desk.close()


def test_lock_guard_refuses_once_the_pair_is_already_complete(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.3, down_ask=.7)
        original = account.create_order

        def complete_first(**kwargs: Any) -> dict[str, Any]:
            # Another fill completes the pair between the decision and the send.
            desk.book.inventory[TICKER].down.shares = 5
            return original(**kwargs)

        account.create_order = complete_first  # type: ignore[method-assign]
        steps(desk, clock, 1)
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_lock_reporting_is_truthful(tmp_path: Path) -> None:
    """Review findings: after a lock the panel said "Practice; cancelling prior live bids", locks were counted as
    instant-order attempts, during a money stop the panel said "no new buys" while a lock could still run, the
    page's "Open position risk" showed gross cost, and an emergency stop did not stop a lock about to be sent."""
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.3, down_ask=.7)
        desk.book.day_pnl[utc_day(clock.now())] = -6  # a money stop with a half pair in its lock period
        steps(desk, clock, 2)
        assert [(c["side"], c["price"]) for c in account.creates[1:]] == [("down", .7)]
        panel = desk.panel()
        assert panel["status"] == "REAL MONEY (Kalshi)" and panel["real_orders_available"] is True
        assert panel["trading_now"] is False and "only completing half-filled pairs" in panel["waiting"]
        assert "cancelling prior live bids" not in (desk.reason or "")
        today = panel["today"]
        assert today["take_attempts"] == 1 and today["locks"] == 1  # the starter take, then one lock
        fill_order(account, clock, 1, side="down", price=.7, size=5)
        account.account_positions = []
        steps(desk, clock, 4)  # past the 1 s account read
        assert desk.book.lock_side(TICKER) == (None, 0.0)
        assert desk.panel()["open_risk_usd"] == pytest.approx(desk.book.open_loss_usd)
        assert desk.panel()["status"] == "PRACTICE"  # pair complete: the stop shows as a stop again
        desk.stopping = True
        intent = next(item for item in desk.intents.values() if item.lock)
        assert not desk._lock_guard(intent)
    finally:
        desk.close()


def test_lock_uses_a_penny_limit_for_sub_penny_asks_and_fits_the_cash(tmp_path: Path) -> None:
    """Simulator findings: a 90.5c ask was refused as an invalid price, and slightly too little cash locked
    nothing at all. A whole-cent IOC limit just above still fills at the better price; the lock takes as many
    contracts as the cash allows."""
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        at_lock_time(desk, clock, up_ask=.05, down_ask=.905)
        account.cash = 3.0  # enough for 3 of the 5 unpaired contracts at 91c plus fees
        steps(desk, clock, 2)
        lock = account.creates[1]
        assert (lock["side"], lock["price"], lock["size"]) == ("down", .91, 3)
    finally:
        desk.close()


# The owner's one-time reset of a reconciliation stop (owner, 2026-10-13: "Yes, reset it").

OWNER_TICKER = "KXBTC15M-26OCT121845-45"  # a window the owner traded by hand, not the bot's


def events(desk: KalshiLiveDesk, name: str) -> list[dict[str, Any]]:
    return [item for item in desk.latest_events if item["event"] == name]


def test_owner_day_reset_is_applied_at_startup_once_and_saved(tmp_path: Path) -> None:
    # The arithmetic with real settlements, restarts, the midnight lapse and the lifetime stop is covered in
    # test_speeddesk_live_model.py; this checks the setting reaches startup, is recorded and is spent.
    reset = {"speeddesk_kalshi_day_reset_token": Secret("owner-day-reset-1")}
    desk, _, clock = make_desk(tmp_path, extra=reset)
    try:
        today = utc_day(clock.now())
        assert [(item["state"], item["day"]) for item in events(desk, "speeddesk_live_day_reset")] == [
            ("fresh daily budget from now until 00:00 UTC; caps and lifetime stop unchanged", today)]
        assert desk.book.day_anchor == {today: 0.0}
        desk.book.day_pnl[today] = -2.5  # a loss after the reset counts against today's budget
        assert desk.book.day_loss(clock.now()) == 2.5
    finally:
        desk.close()
    again, _, clock = make_desk(tmp_path, extra=reset)
    try:
        assert events(again, "speeddesk_live_day_reset")[-1]["state"] == "ignored; this value was already used"
        assert again.book.day_anchor == {utc_day(clock.now()): 0.0}  # saved, never moved by a restart
    finally:
        again.close()
    plain, _, _ = make_desk(tmp_path / "plain")
    try:
        assert not events(plain, "speeddesk_live_day_reset") and plain.book.day_anchor == {}
    finally:
        plain.close()


def stopped_desk(tmp_path: Path, code: str) -> None:
    """A saved desk whose books hold a reconciliation stop, as the 02:00 UTC stop on 2026-10-13 left it."""
    desk, _, _ = make_desk(tmp_path)
    try:
        desk.book.integrity_error = code
        desk.checkpoint()
    finally:
        desk.close()


def test_reconciliation_stop_names_the_check_that_tripped(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        starter_filled(desk, account, clock)
        steps(desk, clock, 4)
        assert desk.book.integrity_error is None
        account.executions[0]["fee_cost"] = "0.0500"  # Kalshi now reports a different fee for a booked fill
        steps(desk, clock, 4)
        assert desk.book.integrity_error == "fill_changed"
        assert [item["code"] for item in events(desk, "speeddesk_live_integrity")] == ["fill_changed"]
        assert {item.get("code") for item in events(desk, "speeddesk_live_reject")} == {"fill_changed"}
        panel = desk.panel()
        assert panel["integrity_error"] == "fill_changed" and panel["mode"] == "paper"
        assert panel["integrity_reset"] is None
    finally:
        desk.close()
    restarted, _, _ = make_desk(tmp_path)
    try:  # every restart names the stop again, once
        assert [item["code"] for item in events(restarted, "speeddesk_live_integrity")] == ["fill_changed"] * 2
    finally:
        restarted.close()


def test_owner_reset_clears_a_stop_once_after_a_clean_reconcile(tmp_path: Path) -> None:
    stopped_desk(tmp_path, "settlement_net_payout_mismatch")
    reset = {"speeddesk_kalshi_integrity_reset_token": Secret("owner-reset-1")}
    desk, account, clock = make_desk(tmp_path, extra=reset)
    try:
        assert desk.panel()["integrity_reset"] == "armed"
        # The owner's own contracts and bid are still on the account: the stop stays until they are gone.
        account.account_positions = [{"ticker": OWNER_TICKER, "position_fp": "3.00"}]
        account.orders.append({"order_id": "owner-bid", "client_order_id": "", "ticker": OWNER_TICKER,
                               "status": "resting", "fill_count_fp": "0.00", "remaining_count_fp": "2.00"})
        steps(desk, clock, 8)
        assert desk.book.integrity_error == "settlement_net_payout_mismatch" and not account.creates
        assert desk.panel()["integrity_reset"] == "orders_open" and desk.panel()["mode"] == "paper"
        account.orders.clear()
        steps(desk, clock, 8)
        assert desk.panel()["integrity_reset"] == "positions_open" and not account.creates
        account.account_positions = []
        steps(desk, clock, 8)
        assert desk.book.integrity_error is None
        cleared = [item for item in events(desk, "speeddesk_live_integrity_reset") if item["state"].startswith("cleared")]
        assert [item["code"] for item in cleared] == ["settlement_net_payout_mismatch"]
        assert [item["reason"] for item in events(desk, "speeddesk_live_integrity_reset") if "reason" in item] == [
            "startup_pending", "orders_open", "positions_open"]
        panel = desk.panel()
        assert panel["mode"] == "live" and panel["integrity_error"] is None and panel["integrity_reset"] is None
        at_lock_time(desk, clock, up_ask=.4, down_ask=.6, before_close=desk.book.windows[TICKER].end - clock.now())
        steps(desk, clock, 1)  # a fresh feed (the test's went stale while waiting)
        assert account.creates  # real orders resume within the caps
    finally:
        desk.close()
    # The same value never clears a later stop, even after a restart.
    stopped_desk(tmp_path, "fill_changed")
    again, account, clock = make_desk(tmp_path, extra=reset)
    try:
        steps(again, clock, 8)
        assert again.book.integrity_error == "fill_changed" and again.panel()["integrity_reset"] is None
    finally:
        again.close()


def test_owner_reset_value_set_before_a_stop_is_spent_at_once(tmp_path: Path) -> None:
    reset = {"speeddesk_kalshi_integrity_reset_token": Secret("owner-reset-early")}
    desk, _, _ = make_desk(tmp_path, extra=reset)
    assert [item["state"] for item in events(desk, "speeddesk_live_integrity_reset")] == [
        "ignored; no stop to clear, so the value is spent"]
    desk.close()
    stopped_desk(tmp_path, "fill_changed")
    later, _, clock = make_desk(tmp_path, extra=reset)
    try:
        steps(later, clock, 8)
        assert later.book.integrity_error == "fill_changed" and later.panel()["integrity_reset"] is None
    finally:
        later.close()


def test_owner_reset_is_withdrawn_for_good_when_a_different_check_trips(tmp_path: Path) -> None:
    """Review finding: a withdrawn approval must not come back after a restart against the newer stop."""
    stopped_desk(tmp_path, "settlement_net_payout_mismatch")
    reset = {"speeddesk_kalshi_integrity_reset_token": Secret("r-2")}
    desk, account, clock = make_desk(tmp_path, extra=reset)
    try:
        desk.book.integrity_error = "fill_exceeded_reserved_terms"
        steps(desk, clock, 8)
        assert desk.book.integrity_error == "fill_exceeded_reserved_terms" and not account.creates
        assert desk.panel()["integrity_reset"] is None
        assert any(item["state"].startswith("disarmed") for item in events(desk, "speeddesk_live_integrity_reset"))
    finally:
        desk.close()
    again, account, clock = make_desk(tmp_path, extra=reset)  # a redeploy with the value still set
    try:
        steps(again, clock, 8)
        assert again.book.integrity_error == "fill_exceeded_reserved_terms" and not account.creates
        assert again.panel()["integrity_reset"] is None
    finally:
        again.close()


def test_owner_reset_approval_survives_a_restart_while_waiting(tmp_path: Path) -> None:
    stopped_desk(tmp_path, "settlement_net_payout_mismatch")
    reset = {"speeddesk_kalshi_integrity_reset_token": Secret("r-4")}
    desk, account, clock = make_desk(tmp_path, extra=reset)
    try:
        account.account_positions = [{"ticker": OWNER_TICKER, "position_fp": "1.00"}]
        steps(desk, clock, 8)
        assert desk.panel()["integrity_reset"] == "positions_open"
    finally:
        desk.close()
    again, account, clock = make_desk(tmp_path, extra=reset)
    try:
        assert again.panel()["integrity_reset"] == "armed"
        steps(again, clock, 8)
        assert again.book.integrity_error is None
    finally:
        again.close()


def test_owner_reset_is_not_blocked_by_an_old_cancelled_order(tmp_path: Path) -> None:
    """Review finding: a finished order keeps its cancel request on record; only open orders hold the reset."""
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())  # the starter rests, then the live switch goes off and it is cancelled
        desk.settings = desk.settings.replace(speeddesk_kalshi_mode="paper")
        steps(desk, clock, 8)
        assert account.cancels
        assert all(intent.terminal and intent.cancel_requested for intent in desk.intents.values())
        desk.book.integrity_error = "order_terminal_regressed"
        desk.checkpoint()
        history = (account.orders, account.creates)
    finally:
        desk.close()
    again, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_integrity_reset_token": Secret("r-3")})
    account.orders, account.creates = history  # Kalshi still lists the cancelled order
    try:
        steps(again, clock, 8)
        assert again.book.integrity_error is None
        assert any(item["state"].startswith("cleared") for item in events(again, "speeddesk_live_integrity_reset"))
    finally:
        again.close()


def test_owner_reset_shows_a_failing_account_read_as_waiting(tmp_path: Path) -> None:
    """Review finding: when the account read keeps failing, the panel must not keep saying "armed"."""
    stopped_desk(tmp_path, "fill_changed")
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_integrity_reset_token": Secret("r-5")})
    try:
        account.balance_error = KalshiClientError("balance", "request rejected", status=500)
        steps(desk, clock, 8)
        assert desk.panel()["integrity_reset"] == "account_unreconciled"
        assert desk.book.integrity_error == "fill_changed"
    finally:
        desk.close()


def test_owner_reset_shows_what_it_waits_for_when_startup_cannot_finish(tmp_path: Path) -> None:
    """Second review: a bid Kalshi keeps listing as resting keeps startup open; the panel must say so."""
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())  # the starter rests
        desk.book.integrity_error = "fill_exceeded_reserved_terms"
        desk.checkpoint()
        history = (account.orders, account.creates)
    finally:
        desk.close()
    again, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_integrity_reset_token": Secret("r-6")})
    account.orders, account.creates = history
    account.cancel = lambda order_id, *, ticker: {}  # type: ignore[method-assign]  # accepted, still resting
    try:
        steps(again, clock, 8)
        assert not again.startup_done and again.book.integrity_error == "fill_exceeded_reserved_terms"
        assert again.panel()["integrity_reset"] == "startup_pending"
    finally:
        again.close()


def test_owner_reset_shows_live_off_while_the_switches_are_off(tmp_path: Path) -> None:
    stopped_desk(tmp_path, "fill_changed")
    desk, account, clock = make_desk(tmp_path, mode="paper",
                                     extra={"speeddesk_kalshi_integrity_reset_token": Secret("r-7")})
    try:
        steps(desk, clock, 4)
        assert account.reads == 0 and desk.panel()["integrity_reset"] == "live_off"
        assert desk.book.integrity_error == "fill_changed"
    finally:
        desk.close()


# Kalshi's order list can trail its fills list (2026-10-13 02:00:03 UTC): wait for a fresh read, never stop for good.

def test_order_list_trailing_the_fills_pauses_one_read_and_never_stops_real_money(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        order = account.orders[0]
        size = float(order["remaining_count_fp"])
        account.executions.append({"fill_id": "fill-lag", "order_id": order["order_id"], "ticker": TICKER,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": f"{size:.2f}",
                                   "yes_price_dollars": ".40", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": f"{size:.2f}"}]
        steps(desk, clock, 4)  # the order list still shows it resting with nothing filled
        assert desk.book.integrity_error is None and desk.account_at is None
        assert desk.panel()["mode"] == "live" and desk.panel()["waiting"]
        order.update(status="executed", fill_count_fp=f"{size:.2f}", remaining_count_fp="0.00")
        steps(desk, clock, 4)
        assert desk.book.integrity_error is None and desk.account_at is not None
        first = next(intent for intent in desk.intents.values() if intent.order_id == order["order_id"])
        assert first.terminal and not desk.book.intents[first.client_order_id].reservation_active
    finally:
        desk.close()


def test_order_list_trailing_the_fills_for_too_long_still_stops(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        order = account.orders[0]
        size = float(order["remaining_count_fp"])
        account.executions.append({"fill_id": "fill-lag", "order_id": order["order_id"], "ticker": TICKER,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": f"{size:.2f}",
                                   "yes_price_dollars": ".40", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": f"{size:.2f}"}]
        for _ in range(40):
            asyncio.run(desk.step())
            clock.advance(1)
        # The order still listed as open (or listed as cancelled with nothing filled) against booked fills.
        assert desk.book.integrity_error in {"order_terminal_regressed", "order_fill_count_mismatch"}
    finally:
        desk.close()


def test_a_stale_report_of_a_finished_order_does_not_pause_trading(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        order = account.orders[0]
        size = float(order["remaining_count_fp"])
        account.executions.append({"fill_id": "fill-done", "order_id": order["order_id"], "ticker": TICKER,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": f"{size:.2f}",
                                   "yes_price_dollars": ".40", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": f"{size:.2f}"}]
        order.update(status="executed", fill_count_fp=f"{size:.2f}", remaining_count_fp="0.00")
        steps(desk, clock, 4)
        first = next(intent for intent in desk.intents.values() if intent.order_id == order["order_id"])
        assert first.terminal and desk.account_at is not None
        order.update(fill_count_fp="0.00")  # a stale copy of the finished order
        steps(desk, clock, 4)
        assert desk.book.integrity_error is None and desk.account_at is not None
    finally:
        desk.close()


def test_one_save_before_the_send_holds_the_intent_and_its_practice_twin(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path, caps=SMALL_CAPS)
    original_checkpoint, original_journal, original_create = desk.checkpoint, desk._journal_intent, account.create_order
    writes: list[str] = []

    def counting_checkpoint(**kwargs: Any) -> None:
        original_checkpoint(**kwargs)
        writes.append("full")

    def counting_journal(*args: Any, **kwargs: Any) -> None:
        original_journal(*args, **kwargs)
        writes.append("journal")

    def inspect(**kwargs: Any) -> dict[str, Any]:
        saved = durable_state(desk.ledger)
        assert saved is not None
        identity = kwargs["client_order_id"]
        assert saved["book"]["intents"][identity]["reservation_active"]
        twin_id = saved["intents"][identity]["twin_order_id"]
        assert twin_id and twin_id == desk.intents[identity].twin_order_id
        # One durable write between the decision and the send: the journal row, never the full state.
        assert writes == ["journal"]
        return original_create(**kwargs)

    desk.checkpoint = counting_checkpoint  # type: ignore[method-assign]
    desk._journal_intent = counting_journal  # type: ignore[method-assign,assignment]
    account.create_order = inspect  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_settlements_are_read_only_once_a_traded_window_has_ended_unsettled(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=SMALL_CAPS)
    original = account.settlements
    reads: list[float] = []

    def counting(**kwargs: Any) -> list[dict[str, Any]]:
        reads.append(clock.now())
        return original(**kwargs)

    account.settlements = counting  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1 and not reads  # nothing traded had ended yet
        clock.advance(1.5)
        asyncio.run(desk.step())
        assert not reads
        clock.advance(900)  # the traded window is over and not yet settled
        asyncio.run(desk.step())
        assert reads
    finally:
        desk.close()


def test_a_bitcoin_tick_wakes_the_live_loop_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    import nightcrawler.speeddesk_live as live

    monkeypatch.setattr(live, "IDLE_STEP_S", 5.0)  # only a wake, never the idle timer, can step again in time
    desk, _, clock = make_desk(tmp_path, mode="paper")
    stepped: list[float] = []

    async def scenario() -> None:
        second = asyncio.Event()

        async def fake_step() -> None:
            stepped.append(clock.now())
            if len(stepped) == 2:
                second.set()

        desk.step = fake_step  # type: ignore[method-assign]
        stop = threading.Event()
        task = asyncio.create_task(desk.run(stop))
        while not stepped:
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        assert len(stepped) == 1  # waiting for news, not spinning
        desk.on_tick(80001, clock.now(), clock.now())
        await asyncio.wait_for(second.wait(), 2.0)
        stop.set()
        desk.on_tick(80002, clock.now(), clock.now())
        await asyncio.wait_for(task, 2.0)

    try:
        asyncio.run(scenario())
        assert len(stepped) >= 2
    finally:
        desk.close()


def test_accepted_order_reports_where_its_time_went(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path, caps=SMALL_CAPS)
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        accepted = [item for item in events(desk, "speeddesk_live_order") if item.get("order_id")]
        stages = accepted[-1]["stages"]
        assert set(stages) == {"save_ms", "decision_to_send_ms", "send_to_ack_ms"}
        assert all(isinstance(value, float) and value >= 0 for value in stages.values())
        assert stages["decision_to_send_ms"] >= stages["save_ms"]
    finally:
        desk.close()


def reopen(tmp_path: Path, desk: KalshiLiveDesk, account: FakeAccount, clock: FakeClock,
           caps: dict[str, float] | None = None) -> KalshiLiveDesk:
    """The same saved desk started again on the same clock, as a redeploy does."""
    desk.close()
    settings = Settings(data_dir=tmp_path, speeddesk_kalshi_mode="live", speeddesk_kalshi_live_confirm=Secret("yes"),
                        kalshi_key_id=Secret("fake-key-id"), kalshi_private_key=Secret("fake-private-key"),
                        **(FIVE_DOLLAR_CAPS if caps is None else caps))
    return KalshiLiveDesk(settings, tmp_path / "live", desk.snapshot, clock=clock.now,
                          client_factory=lambda: account, direct_member_verified=True)


def settled_window(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    """One traded window that closed, settled at Kalshi and was booked; nothing is open."""
    desk, account, clock = make_desk(tmp_path)
    starter_filled(desk, account, clock)
    steps(desk, clock, 4)
    clock.advance(900)
    account.account_positions = []
    account.resolutions = [{"ticker": TICKER, "market_result": "yes", "revenue": 500, "settled_time": clock.now() - 5}]
    steps(desk, clock, 4)
    assert TICKER in desk.book.settled and not desk._active()
    return desk, account, clock


def full_state(desk: KalshiLiveDesk) -> tuple[dict[str, Any], dict[str, Any]]:
    from dataclasses import asdict
    return desk.book.window_parts(lambda _window: True), {key: asdict(value) for key, value in desk.intents.items()}


def test_a_finished_window_is_archived_once_and_restored_whole(tmp_path: Path) -> None:
    desk, account, clock = settled_window(tmp_path)
    desk.checkpoint()
    assert not desk.archived  # kept in every save until an hour after the close
    clock.advance(3600)
    desk.checkpoint()
    saved = desk.ledger.get_kv("kalshi_live_state")
    assert desk.archived == {TICKER} and saved["archived_windows"] == [TICKER] and saved["archive_chunks"] == 1
    assert TICKER not in saved["book"]["windows"] and not saved["book"]["intents"] and not saved["intents"]
    chunk = desk.ledger.get_kv("kalshi_live_archive/0")
    assert chunk["windows"] == [TICKER] and len(chunk["intents"]) == len(desk.intents) >= 1
    desk.checkpoint()
    assert desk.archive_chunks == 1  # write-once: later saves do not rewrite it
    before = full_state(desk)
    restarted = reopen(tmp_path, desk, account, clock)
    try:
        assert full_state(restarted) == before
        assert restarted.archived == {TICKER} and restarted.archive_chunks == 1
        assert restarted.book.realized_pnl == pytest.approx(5 - 2 - restarted.book.fills[next(iter(restarted.book.fills))].fee_usd)
    finally:
        restarted.close()


def test_a_missing_archive_chunk_stops_the_restart(tmp_path: Path) -> None:
    desk, account, clock = settled_window(tmp_path)
    clock.advance(3600)
    desk.checkpoint()
    desk.ledger.set_kv("kalshi_live_archive/0", None)
    with pytest.raises(ValueError, match="archive chunk missing"):
        reopen(tmp_path, desk, account, clock)


def test_an_archived_window_with_new_activity_is_saved_in_full_again(tmp_path: Path) -> None:
    desk, account, clock = settled_window(tmp_path)
    clock.advance(3600)
    desk.checkpoint()
    identity = next(iter(desk.intents))
    desk.intents[identity].uncertain = True  # activity came back: it must never hide in the archive
    desk.checkpoint()
    saved = desk.ledger.get_kv("kalshi_live_state")
    assert TICKER in saved["book"]["windows"] and saved["intents"][identity]["uncertain"] is True
    assert saved["archived_windows"] == [] and not desk.archived
    desk.intents[identity].uncertain = False
    desk.checkpoint()
    assert desk.archived == {TICKER} and desk.archive_chunks == 2
    before = full_state(desk)
    restarted = reopen(tmp_path, desk, account, clock)
    try:
        assert full_state(restarted) == before
    finally:
        restarted.close()


def test_saved_state_stays_small_however_many_windows_have_finished(tmp_path: Path) -> None:
    desk, _, clock = settled_window(tmp_path)
    clock.advance(3600)
    desk.checkpoint()
    size = len(json.dumps(desk.ledger.get_kv("kalshi_live_state")))
    from dataclasses import replace as clone
    identity = next(iter(desk.intents))
    for index in range(300):  # three hundred more finished orders in the archived window
        key = f"nc-speed-{index:032x}"
        desk.intents[key] = clone(desk.intents[identity], client_order_id=key)
        desk.book.intents[key] = clone(desk.book.intents[identity], client_order_id=key)
    desk.checkpoint()
    assert len(json.dumps(desk.ledger.get_kv("kalshi_live_state"))) <= size + 64
    desk.close()


def test_the_money_page_still_reads_the_whole_real_book_after_archiving(tmp_path: Path) -> None:
    from nightcrawler import moneyconnections

    desk, _, clock = settled_window(tmp_path)
    try:
        before = desk.book.window_parts(lambda _window: True)
        clock.advance(3600)
        desk.checkpoint()
        assert desk.archived == {TICKER}
        clock.advance(11)
        desk.checkpoint()  # the next display copy, after the window left the saved state
        mirror = json.loads(desk.path.read_text())
        assert TICKER not in desk.ledger.get_kv("kalshi_live_state")["book"]["windows"]
        assert {part: mirror["book"][part] for part in before} == json.loads(json.dumps(before))
        view = moneyconnections.kalshi_connection(mirror, clock.now(), lambda value, limit=300: str(value)[:limit])
        assert view["status"] == "ok"
        assert any(event["type"] == "settlement" for event in view["events"])  # the settled window is still shown
        stamp = desk.last_mirror
        clock.advance(2)
        desk.checkpoint()
        assert desk.last_mirror == stamp  # display copies are spaced out; the ledger save is not
    finally:
        desk.close()


def test_only_the_save_before_an_order_and_owner_actions_wait_for_the_disk(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=SMALL_CAPS)
    calls: list[bool] = []
    original_sync, original_create = desk.ledger.set_synchronous, account.create_order
    at_send: list[bool] = []

    def spy(full: bool) -> None:
        calls.append(full)
        original_sync(full)

    def inspect(**kwargs: Any) -> dict[str, Any]:
        at_send.append(calls[-1])  # the save that made this intent durable
        return original_create(**kwargs)

    desk.ledger.set_synchronous = spy  # type: ignore[method-assign]
    account.create_order = inspect  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert at_send == [True] and len(account.creates) == 1
        calls.clear()
        clock.advance(1.5)
        asyncio.run(desk.step())  # an account reconcile with no new order
        assert calls and not any(calls)
        desk._record("speeddesk_live_integrity_reset", state="an owner's one-time action")
        desk.checkpoint()
        assert calls[-1] is True
    finally:
        desk.close()


def test_the_owners_ten_dollar_windows_are_enforced_and_reported(tmp_path: Path) -> None:
    caps = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
            "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}
    desk, account, _ = make_desk(tmp_path, caps=caps)
    try:
        assert (desk.book.limits.window_usd, desk.book.limits.open_usd) == (10.0, 20.0)
        asyncio.run(desk.step())
        # The $10 window budget holds, but the first buy is 5 contracts: the owner's "never again" after two
        # 10-contract first buys were run over on 2026-10-13 (SPEEDDESK_KALSHI_CLIP).
        assert [creation["size"] for creation in account.creates] == [5.0]
        assert desk.book.limits.clip == 5.0
        assert desk.panel()["caps"] == {"window_usd": 10.0, "open_usd": 20.0, "day_stop_usd": 6.0,
                                        "total_stop_usd": 10.0, "clip": 5.0}
        assert desk.panel()["ladder"]["rung"] == 0  # the ladder starts at the owner's floor
    finally:
        desk.close()


def test_the_first_buy_follows_the_kalshi_contract_cap_inside_the_window_budget(tmp_path: Path) -> None:
    # An $8 window with the day stop at its $12 ceiling: a first buy must also leave room for its hedge under both
    # loss stops (2026-10-14), and eight hedged pairs cost about $8.19 (ten would cost $10.24, over the $10 lifetime
    # stop), so here the window budget is the cap this test is about.
    caps = {"speeddesk_kalshi_window_usd": 8.0, "speeddesk_kalshi_open_usd": 16.0, "speeddesk_kalshi_day_stop_usd": 12.0}
    for clip, expected in ((10.0, 8.0), (3.0, 3.0), (25.0, 8.0)):
        root = tmp_path / str(clip)
        root.mkdir()
        desk, account, _ = make_desk(root, caps={**caps, "speeddesk_kalshi_clip": clip})
        try:
            asyncio.run(desk.step())
            # A larger cap never lets one starter outgrow whole pairs at the pair cap ($8 / $0.99 -> 8).
            assert [creation["size"] for creation in account.creates] == [expected]
            assert desk.twin.config.clip == clip
        finally:
            desk.close()


def test_the_inner_ceiling_still_holds_above_the_owners_limits() -> None:
    from nightcrawler.speeddesk_live_model import LiveLimits

    limits = LiveLimits(window_usd=50, open_usd=99, day_loss_usd=60, total_loss_usd=99)
    assert (limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.total_loss_usd) == (20, 40, 12, 10)
