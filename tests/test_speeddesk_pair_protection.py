"""Historical admission fixtures exercise prior policy; they do not establish current production admission.

After a confirmed positive full pair, retain liabilities and permit only risk reduction. Offline fakes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, FakeAccount, fill_order, reopen
from test_speeddesk_live_pull import CAPS, MAKERS, market, run, starter_bid_filled

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import Intent, KalshiLiveDesk
from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
)
from nightcrawler.speeddesk_model import Window

SLUG = "KXBTC15M-PAIR-PROTECTION"
LIMITS = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)


def book_with_first(*, price: float = .49, size: float = 5, filled: float = 5) -> LiveRiskBook:
    book = LiveRiskBook(LIMITS)
    book.add_window(Window(SLUG, 1000, 1900, 100, venue="kalshi", taker_coefficient=.07, maker_coefficient=0))
    book.update_cash(30, 1010)
    first = book.reserve_intent(SLUG, "down", "rest", price, size, 1010, "nc-speed-first", .6)
    book.record_fill(ActualFill("fill-first", "order-first", first.client_order_id, SLUG, "down", price, filled, 0, 1010))
    return book


def legacy_order(book: LiveRiskBook, side: str, price: float, size: float, key: str) -> LiveIntent:
    """An already-existing liability, not an admission allowed by the new policy."""
    order = LiveIntent("nc-speed-" + key, SLUG, side, "rest", price, size, 1010, price, .6)  # type: ignore[arg-type]
    book.intents[order.client_order_id] = order
    return order


def fill(book: LiveRiskBook, order: LiveIntent, *, size: float | None = None, fee: float = 0, key: str = "fill") -> None:
    assert book.record_fill(ActualFill(key, "order-" + order.client_order_id, order.client_order_id,
                                       order.window, order.side, order.price, order.size if size is None else size, fee, 1011))


def positive_pair() -> LiveRiskBook:
    book = book_with_first()
    hedge = book.reserve_intent(SLUG, "up", "rest", .45, 5, 1010, "nc-speed-hedge", .5)
    fill(book, hedge)
    assert book.protected_windows == {SLUG}
    return book


@pytest.mark.parametrize("side", ["up", "down"])
@pytest.mark.parametrize("kind", ["rest", "take"])
def test_positive_full_pair_refuses_ordinary_directional_exposure(side: str, kind: str) -> None:
    book = positive_pair()
    assert book.can_buy(SLUG, side, kind, .51, 3, 1011) == "pair_protected"  # type: ignore[arg-type]
    with pytest.raises(LiveRejected, match="pair_protected"):
        book.reserve_intent(SLUG, side, kind, .51, 3, 1011, "nc-speed-extra", .6)  # type: ignore[arg-type]
    assert book.reserved_usd == 0
    assert book.worst_loss(SLUG) == 0
    # Selected historical arithmetic, not a counterfactual fill/queue claim: Down5@.49 + Up5@.45.
    assert min(book.inventory[SLUG].up.shares, book.inventory[SLUG].down.shares) - book.inventory[SLUG].spent == pytest.approx(.30)
    assert 5 - (4.70 + 3 * .51) == pytest.approx(-1.23)  # avoided adverse outcome if the new bid filled
    assert 8 - (4.70 + 3 * .51) == pytest.approx(1.77)  # favorable outcome forgone by this restriction
    assert 3 * (1 - .51) == pytest.approx(1.47)  # favorable incremental gain forgone


@pytest.mark.parametrize(("first_price", "hedge_price", "fee", "expected"), [
    (.49, .49, 0, True), (.49, .49, .10, False), (.49, .49, .11, False),
    (.50, .50, 0, False), (.50, .51, 0, False), (.49, .49, .0999999999, False),
])
def test_trigger_uses_actual_fee_inclusive_positive_margin(
    first_price: float, hedge_price: float, fee: float, expected: bool,
) -> None:
    book = book_with_first(price=first_price)
    # Legacy opposite-side fills may include a late loss-reducing lock above the ordinary pair cap.
    hedge = legacy_order(book, "up", hedge_price, 5, "old-hedge")
    hedge.unit_reserve += fee / 5
    fill(book, hedge, fee=fee)
    assert (SLUG in book.protected_windows) is expected
    assert not book.integrity_error


def test_trigger_latches_at_intermediate_partial_equality_before_later_same_batch_fill() -> None:
    book = book_with_first(filled=3)
    hedge = book.reserve_intent(SLUG, "up", "rest", .45, 3, 1010, "nc-speed-hedge", .5)
    fill(book, hedge)
    assert SLUG in book.protected_windows
    # The first order's remaining two contracts were already reserved when the pair completed.
    assert book.reserved_usd == pytest.approx(.98)
    first = book.intents["nc-speed-first"]
    assert book.record_fill(ActualFill("late-first", "order-first", first.client_order_id,
                                       SLUG, "down", .49, 2, 0, 1011))
    assert book.lock_side(SLUG) == ("up", 2)
    assert book.can_buy(SLUG, "down", "rest", .40, 1, 1011) == "pair_protected"
    assert book.can_buy(SLUG, "up", "rest", .45, 2, 1011) == ""
    assert book.can_buy(SLUG, "up", "rest", .45, 3, 1011) == "pair_protected"
    restored = LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())))
    assert restored.protected_windows == {SLUG}
    assert restored.can_buy(SLUG, "down", "rest", .4, 1, 1011) == "cash_stale"
    restored.update_cash(30, 1011)
    assert restored.can_buy(SLUG, "down", "rest", .4, 1, 1011) == "pair_protected"


def test_unequal_partial_pair_and_first_entry_are_unchanged() -> None:
    book = book_with_first()
    hedge = book.reserve_intent(SLUG, "up", "rest", .45, 5, 1010, "nc-speed-hedge", .5)
    fill(book, hedge, size=4)
    assert not book.protected_windows
    assert book.strictly_balancing_intent(hedge.client_order_id)
    assert book.reserved_usd == pytest.approx(.45)


@pytest.mark.parametrize("bad", [None, True, "wrong", {}, [SLUG, SLUG], [17], ["unknown"]])
def test_malformed_present_protection_state_is_rejected(bad: Any) -> None:
    state = positive_pair().to_state()
    state["protected_windows"] = bad
    with pytest.raises(ValueError, match="pair protection"):
        LiveRiskBook.from_state(state)


def test_legacy_restore_seeds_only_current_confirmed_positive_equal_holdings() -> None:
    book = positive_pair()
    state = book.to_state()
    state.pop("protected_windows")
    assert LiveRiskBook.from_state(state).protected_windows == {SLUG}
    old = legacy_order(book, "down", .4, 1, "late")
    fill(book, old, key="late-fill")
    state = book.to_state()
    state.pop("protected_windows")
    # There may have been an earlier pair, but old snapshots do not persist that observation. Do not guess it.
    assert not LiveRiskBook.from_state(state).protected_windows
    assert LiveRiskBook.from_state(book.to_state()).protected_windows == {SLUG}


def pair_desk(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    desk, account, clock = make_historical_desk(tmp_path, caps=CAPS, extra=MAKERS)
    starter_bid_filled(desk, account, clock)
    asyncio.run(desk._reconcile())
    asyncio.run(desk.step())
    assert len(account.creates) == 2
    fill_order(account, clock, 1, side="down", price=.47, size=5)
    account.executions[-1]["fee_cost"] = "0.0000"
    account.account_positions = []
    asyncio.run(desk._reconcile())
    assert desk.book.protected_windows == {TICKER}
    return desk, account, clock


def old_bid(desk: KalshiLiveDesk, account: FakeAccount, *, side: str = "down", size: int = 3) -> str:
    key = "nc-speed-old-" + str(len(account.creates))
    now = desk.clock()
    # Simulate a liability admitted before this policy, retaining its full original identity/terms.
    desk.book.intents[key] = LiveIntent(key, TICKER, side, "rest", .47, size, now, .47, .5)  # type: ignore[arg-type]
    desk.intents[key] = Intent(key, TICKER, side, "rest", .47, size, .5, now)  # type: ignore[arg-type]
    reply = account.create_order(ticker=TICKER, side=side, kind="rest", price=.47, size=size,
                                 client_order_id=key, before_send=lambda: True)
    desk.intents[key].order_id = reply["order_id"]
    desk.book.mark_submitted(key, reply["order_id"])
    return key


def test_live_loop_stops_new_directional_buys_and_records_one_trigger(tmp_path: Path) -> None:
    desk, account, clock = pair_desk(tmp_path)
    try:
        run(desk, clock, 2)
        assert len(account.creates) == 2 and not account.cancels
        assert desk.reason == "pair_protected"
        panel = desk.panel()["pair_protection"]
        assert panel == {"protected_windows": [TICKER], "total_windows": 1}
        rows = [r for r in desk.ledger.iter_receipts() if r.kind == "speeddesk_live_pair_protected"]
        assert len(rows) == 1 and rows[0].payload["inventory_floor_usd"] == pytest.approx(.30)
        desk = reopen(tmp_path, desk, account, clock, caps=CAPS)
        assert desk.book.protected_windows == {TICKER}
        asyncio.run(desk.step())
        assert len(account.creates) == 2
    finally:
        desk.close()


@pytest.mark.parametrize("response", ["ack", "404", "timeout"])
def test_cancel_never_releases_existing_reservation_until_reconciliation(tmp_path: Path, response: str) -> None:
    desk, account, _ = pair_desk(tmp_path)
    try:
        key = old_bid(desk, account)
        def cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
            account.cancels.append(order_id)
            if response != "ack":
                raise KalshiClientError("cancel", response, status=404 if response == "404" else None,
                                        uncertain=response == "timeout")
            return {}  # lagging list deliberately keeps it resting
        account.cancel = cancel
        before = desk.book.reserved_usd
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == [desk.intents[key].order_id]
        assert desk.book.reserved_usd == before == pytest.approx(1.41)
        assert desk.book.intents[key].reservation_active and desk.intents[key].cancel_requested
        assert desk.cancel_reasons[key] == "pair_protected"
        assert not desk._send_guard(key)
    finally:
        desk.close()


def test_uncertain_create_without_order_id_is_kept_reserved_and_marked_for_cancel(tmp_path: Path) -> None:
    desk, account, _ = pair_desk(tmp_path)
    try:
        key = old_bid(desk, account)
        account.orders.pop()
        desk.intents[key].order_id = ""
        desk.intents[key].uncertain = True
        desk.book.intents[key].order_id = None
        desk.book.mark_uncertain(key, "create_timeout")
        asyncio.run(desk._cancel_unsafe())
        assert not account.cancels
        assert desk.intents[key].cancel_requested
        assert desk.book.intents[key].reservation_active
        assert desk.book.reserved_usd == pytest.approx(1.41)
        assert desk.book.intents[key].uncertainty == "cancel_needs_order_id"
    finally:
        desk.close()


def test_race_fill_keeps_latch_and_only_strict_balancing_pending_bid_survives(tmp_path: Path) -> None:
    desk, account, clock = pair_desk(tmp_path)
    try:
        heavy = old_bid(desk, account, side="down", size=3)
        fill_order(account, clock, 2, side="down", price=.47, size=3)
        account.executions[-1]["fee_cost"] = "0.0000"
        account.account_positions = [{"ticker": TICKER, "position_fp": "-3.00"}]
        asyncio.run(desk._reconcile())
        assert not desk.book.intents[heavy].reservation_active
        assert desk.book.protected_windows == {TICKER}
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "up", "rest", .47, 3, .5))
        hedge = account.creates[-1]["client_order_id"]
        asyncio.run(desk._reconcile())  # a create invalidates the account clock until this complete read
        assert desk.book.strictly_balancing_intent(hedge)
        cancels_before = list(account.cancels)  # the old heavy bid was canceled during the responsive read
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == cancels_before and desk._send_guard(hedge)
        competing = old_bid(desk, account, side="up", size=1)
        desk.book.mark_uncertain(competing, "create_timeout")
        assert not desk.book.strictly_balancing_intent(hedge)
        assert not desk._send_guard(hedge)
        asyncio.run(desk._cancel_unsafe())
        assert set(account.cancels) - set(cancels_before) == {desk.intents[hedge].order_id, desk.intents[competing].order_id}
        assert desk.book.reserved_usd == pytest.approx(4 * .47)
    finally:
        desk.close()


def test_transport_guard_rechecks_new_pair_after_wait(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        starter_bid_filled(desk, account, clock)
        asyncio.run(desk._reconcile())
        original = account.create_order
        def complete_other_fills_then_send(**kwargs: Any) -> dict[str, Any]:
            # This ordinary hedge was reserved against five Up: buying Down was balancing
            # at admission. Old opposite fills finish the actual pair before its transport guard runs.
            key = "nc-speed-old-other-fill"
            desk.book.intents[key] = LiveIntent(key, TICKER, "down", "rest", .47, 5, clock.now(), .47, .5)
            desk.intents[key] = Intent(key, TICKER, "down", "rest", .47, 5, .5, clock.now(), terminal=True)
            desk.book.record_fill(ActualFill("wait-fill", "old-other-order", key, TICKER, "down", .47, 5, 0, clock.now()))
            return original(**kwargs)
        account.create_order = complete_other_fills_then_send
        asyncio.run(desk.step())
        assert len(account.creates) == 1  # the newly reserved hedge would now add directional risk
        assert desk.book.protected_windows == {TICKER}
        refused = [key for key, intent in desk.book.intents.items() if intent.status == "rejected"]
        assert len(refused) == 1 and not desk.book.intents[refused[0]].reservation_active
        assert desk.book.reserved_usd == 0
    finally:
        desk.close()


@pytest.mark.parametrize("gate", ["paper", "disabled", "shutdown", "integrity", "foreign", "stale", "pull", "cutoff"])
def test_protection_never_bypasses_existing_gates_for_a_balancing_order(tmp_path: Path, gate: str) -> None:
    desk, account, clock = pair_desk(tmp_path)
    try:
        old_bid(desk, account, size=3)
        fill_order(account, clock, 2, side="down", price=.47, size=3)
        account.executions[-1]["fee_cost"] = "0.0000"
        account.account_positions = [{"ticker": TICKER, "position_fp": "-3.00"}]
        asyncio.run(desk._reconcile())
        if gate == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif gate == "disabled":
            desk.settings = replace(desk.settings, speeddesk_kalshi_enabled=False)
        elif gate == "shutdown":
            desk.stopping = True
        elif gate == "integrity":
            desk.book.integrity_error = "fixture"
        elif gate == "foreign":
            desk.foreign_windows.add(TICKER)
        elif gate == "stale":
            old = replace(desk.snapshot(), bitcoin_at=clock.now() - 4)
            desk.snapshot = lambda: old
        elif gate == "pull":
            market(desk, clock, .52)
        elif gate == "cutoff":
            clock.advance(desk.book.windows[TICKER].end - desk.book.limits.lock_s - clock.now())
            market(desk, clock, .5)
        before = len(account.creates)
        if gate == "cutoff":
            # Ordinary admission is closed; the unchanged late lock is allowed by the full step.
            assert not asyncio.run(desk._send(desk.book.windows[TICKER], "up", "rest", .47, 3, .5))
        else:
            asyncio.run(desk.step())
        assert len(account.creates) == before
        assert desk.book.protected_windows == {TICKER}
    finally:
        desk.close()


def test_late_lock_stays_available_after_cancel_race_even_over_ordinary_budgets() -> None:
    book = positive_pair()
    old = legacy_order(book, "down", .51, 3, "old-down")
    fill(book, old, key="race-fill")
    at = book.windows[SLUG].end - book.limits.lock_s
    book.update_cash(30, at)
    book.halted, book.halt_reason = True, "total_loss"
    assert book.can_lock(SLUG, "up", .97, 3, at) == ""
    lock = book.reserve_intent(SLUG, "up", "take", .97, 3, at, "nc-speed-lock", lock=True)
    assert lock.lock and book.strictly_balancing_intent(lock.client_order_id)
    assert SLUG in book.protected_windows
