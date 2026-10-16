"""Production-default reduction-only checks using fake venue-confirmed obligations.

No containment gate is patched. Historical entry policy is used only to seed
already-existing actual fills/reservations, never to call controller admission.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, make_desk, reopen
from test_speeddesk_live_completion import seeded, view

from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import REDUCTION_ONLY_REASON, Intent, durable_state
from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_model import Level


@pytest.mark.parametrize("kind", ["rest", "take"])
@pytest.mark.parametrize("side", ["up", "down"])
def test_empty_inventory_cannot_send_a_first_leg(tmp_path: Path, kind: Any, side: Any) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk._ensure_client())
        asyncio.run(desk._startup())
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], side, kind, .1, 1, .8))
        assert desk.reason == REDUCTION_ONLY_REASON
        assert not account.creates and not desk.intents and not desk.twin.orders
    finally:
        desk.close()


def test_empty_decision_holds_without_inventing_practice_entries(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert not account.creates and not desk.twin.orders
        assert desk.reason == REDUCTION_ONLY_REASON
        assert desk.panel()["mode"] == "live" and not desk.panel()["trading_now"]
        assert desk.panel()["waiting"] == REDUCTION_ONLY_REASON
        policy = desk.panel()["pair_execution"]
        assert policy["policy"] == "reduction_only" and policy["status"] == "REDUCTION ONLY"
        assert policy["starter"] == "disabled" and policy["automatic_resume"] is False
        assert policy["expires_at"] is None and policy["practice_comparable"] is False
    finally:
        desk.close()


@pytest.mark.parametrize("kind", ["rest", "take"])
def test_confirmed_inventory_can_receive_an_ordinary_hedge(tmp_path: Path, kind: Any) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.1 if kind == "take" else .4, 20),))
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "down", kind, .1, 5, .2))
        assert [(row["side"], row["size"], row["kind"]) for row in account.creates] == [("down", 5, kind)]
        identity = account.creates[0]["client_order_id"]
        assert desk.book.strictly_balancing_intent(identity)
    finally:
        desk.close()


@pytest.mark.parametrize(("side", "size"), [("up", 1), ("down", 6)])
def test_cannot_increase_or_flip_the_confirmed_imbalance(tmp_path: Path, side: Any, size: int) -> None:
    desk, account, _ = seeded(tmp_path)
    try:
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], side, "rest", .1, size, .8))
        assert desk.reason == REDUCTION_ONLY_REASON and not account.creates
    finally:
        desk.close()


def test_balanced_inventory_cannot_restart_even_without_a_positive_pair_latch(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        identity = "nc-speed-existing-pair"
        desk.book.reserve_intent(TICKER, "down", "rest", .4, 5, clock.now(), identity, .8)
        desk.book.record_fill(ActualFill("pair-fill", "pair", identity, TICKER, "down", .4, 5, 0, clock.now()))
        desk.book.protected_windows.clear()  # covers a balanced legacy window with no persisted positive latch
        assert desk.book.lock_side(TICKER) == (None, 0)
        for side in ("up", "down"):
            assert not asyncio.run(desk._send(desk.book.windows[TICKER], side, "rest", .01, 1, .8))
        assert not account.creates
    finally:
        desk.close()


def test_pending_hedge_cannot_be_counted_twice(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        desk.book.reserve_intent(TICKER, "down", "rest", .1, 3, clock.now(), "nc-speed-pending", .2)
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, 3, .2))
        assert not account.creates
        assert desk.book.intents["nc-speed-pending"].reservation_active
    finally:
        desk.close()


@pytest.mark.parametrize("change", ["balanced", "competing", "partial_competing", "cancel_pending", "uncertain"])
@pytest.mark.parametrize("completion", [False, True])
def test_postjournal_transport_rechecks_every_remaining_contract(tmp_path: Path, change: str,
                                                               completion: bool) -> None:
    desk, account, clock = seeded(tmp_path)
    original = account.create_order
    view(desk, clock, up=(Level(.9, 20),), down=(Level(.1, 20),))

    def changed(**kwargs: Any) -> dict[str, Any]:
        identity = kwargs["client_order_id"]
        saved = durable_state(desk.ledger)
        assert saved is not None and saved["book"]["intents"][identity]["reservation_active"]
        if change == "balanced":
            # Adversarial actual-inventory update between admission and transport.
            desk.book.inventory[TICKER].down.shares = 5
        else:
            pending = replace(desk.book.intents[identity], client_order_id="nc-speed-competing",
                              size=3 if change == "partial_competing" else 1)
            desk.book.intents[pending.client_order_id] = pending
            desk.book.open_intent_ids()  # index rebuilding must not hide the injected competing reservation
            desk.intents[pending.client_order_id] = Intent(pending.client_order_id, TICKER, "down", "rest",
                                                           .1, 1, .2, clock.now(),
                                                           cancel_requested=change == "cancel_pending",
                                                           uncertain=change == "uncertain")
            if change == "partial_competing":
                desk.book.record_fill(ActualFill("partial-hedge", "hedge", pending.client_order_id, TICKER,
                                                 "down", .1, 2, 0, clock.now()))
        assert not desk.book.strictly_balancing_intent(identity)
        return original(**kwargs)

    account.create_order = changed
    try:
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "down", "take", .1, 5, .2,
                                      completion=completion))
        assert not account.creates
        attempted = next(item for key, item in desk.intents.items()
                         if key not in ("nc-speed-review-seed", "nc-speed-competing"))
        assert attempted.terminal and not attempted.uncertain
        assert not desk.book.intents[attempted.client_order_id].reservation_active
        assert not desk.fatal_reason and desk.errors == 0
        assert any(event.get("state") == "not sent; prices moved before send" for event in desk.latest_events)
        if change != "balanced":
            assert desk.book.intents["nc-speed-competing"].reservation_active
    finally:
        desk.close()


def test_partial_starter_cancels_even_while_hedge_depth_is_visible(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["seed"]
        assert desk.cancel_reasons["nc-speed-review-seed"] == "reduction_only"
        pending = desk.book.intents["nc-speed-review-seed"]
        assert pending.reservation_active and pending.remaining == 3
        asyncio.run(desk._reconcile())
        assert not desk.book.intents["nc-speed-review-seed"].reservation_active
        assert desk.book.inventory[TICKER].up.shares == 2
    finally:
        desk.close()


def test_restart_has_no_entry_escape_and_cancels_recovered_starter(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    desk.checkpoint(durable=True)
    restored = reopen(tmp_path, desk, account, clock)
    try:
        asyncio.run(restored._ensure_client())
        asyncio.run(restored._reconcile())
        asyncio.run(restored._cancel_unsafe())
        assert account.cancels == ["seed"]
        # Startup's complete reconciliation may already confirm the cancellation.
        assert restored.book.inventory[TICKER].up.shares == 2
        assert not asyncio.run(restored._send(restored.book.windows[TICKER], "up", "rest", .1, 1, .8))
        assert not account.creates
        assert restored.panel()["pair_execution"]["policy"] == "reduction_only"
    finally:
        restored.close()


def test_late_protective_lock_remains_available(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        clock.advance(780)
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
        asyncio.run(desk._reconcile())
        window = desk.book.windows[TICKER]
        assert asyncio.run(desk._send_lock(window, "down", .4, 5))
        assert len(account.creates) == 1
        assert desk.intents[account.creates[0]["client_order_id"]].lock
    finally:
        desk.close()


@pytest.mark.parametrize("status", [200, 404])
def test_acknowledged_containment_cancel_does_not_repeat_before_reconciliation(tmp_path: Path, status: int) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    original = account.cancel

    def cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
        reply = original(order_id, ticker=ticker)
        if status == 404:
            raise KalshiClientError("cancel", "already absent", status=404, uncertain=False)
        return reply

    account.cancel = cancel
    try:
        asyncio.run(desk._cancel_unsafe())
        clock.advance(3)
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["seed"]
        assert desk.book.intents["nc-speed-review-seed"].reservation_active
        assert desk.book.intents["nc-speed-review-seed"].remaining == 3
    finally:
        desk.close()


def test_failed_containment_cancel_retains_reservation_and_requires_new_read_before_retry(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    original = account.cancel
    attempts: list[str] = []

    def failed(order_id: str, *, ticker: str) -> dict[str, Any]:
        attempts.append(order_id)
        if len(attempts) == 1:
            raise KalshiClientError("cancel", "transport failure", uncertain=True)
        return original(order_id, ticker=ticker)

    account.cancel = failed
    try:
        asyncio.run(desk._cancel_unsafe())
        pending = desk.book.intents["nc-speed-review-seed"]
        assert pending.reservation_active and pending.remaining == 3
        clock.advance(10)
        asyncio.run(desk._cancel_unsafe())
        assert attempts == ["seed"]
        asyncio.run(desk._reconcile())
        asyncio.run(desk._cancel_unsafe())
        assert attempts == ["seed", "seed"]
        assert pending.reservation_active  # the successful retry is still only an acknowledgement
    finally:
        desk.close()


def test_valid_resting_hedge_is_retained_by_containment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk, account, clock = seeded(tmp_path)
    monkeypatch.setattr(type(desk), "_fair", staticmethod(lambda *_args: .8))
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, 5, .2))
        asyncio.run(desk._cancel_unsafe())
        assert not account.cancels
        assert desk.book.strictly_balancing_intent(account.creates[0]["client_order_id"])
    finally:
        desk.close()


@pytest.mark.parametrize("gate", ["paper", "stale_feed", "foreign", "shutdown", "integrity",
                                 "cash", "window_budget", "open_budget", "clip", "pair_cap"])
def test_confirmed_hedge_keeps_existing_admission_safeguards(tmp_path: Path, gate: str) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        if gate == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif gate == "stale_feed":
            clock.advance(4)
        elif gate == "foreign":
            desk.foreign_windows.add(TICKER)
        elif gate == "shutdown":
            desk.stopping = True
        elif gate == "integrity":
            desk.book.integrity_error = "test_existing_integrity_stop"
        elif gate == "cash":
            desk.book.cash_usd = .1
        else:
            limits = desk.book.limits_for(TICKER)
            field = {"window_budget": "window_usd", "open_budget": "open_usd",
                     "clip": "clip", "pair_cap": "pair_cap"}[gate]
            value = {"window_budget": 3.0, "open_budget": 3.0, "clip": 1, "pair_cap": .6}[gate]
            desk.book.window_limits = lambda _start: replace(limits, **{field: value})
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, 5, .2))
        assert not account.creates
        assert desk.book.inventory[TICKER].up.shares == 5
    finally:
        desk.close()


@pytest.mark.parametrize("gate", ["paper", "stale_feed", "foreign", "shutdown", "integrity"])
def test_ordinary_hedge_rechecks_existing_transport_safeguards(tmp_path: Path, gate: str) -> None:
    desk, account, clock = seeded(tmp_path)
    original = account.create_order

    def changed(**kwargs: Any) -> dict[str, Any]:
        if gate == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif gate == "stale_feed":
            clock.advance(4)
        elif gate == "foreign":
            desk.foreign_windows.add(TICKER)
        elif gate == "shutdown":
            desk.stopping = True
        else:
            desk.book.integrity_error = "test_existing_integrity_stop"
        return original(**kwargs)

    account.create_order = changed
    try:
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, 5, .2))
        assert not account.creates
        attempt = next(item for key, item in desk.intents.items() if key != "nc-speed-review-seed")
        assert attempt.terminal and not attempt.uncertain
        assert not desk.book.intents[attempt.client_order_id].reservation_active
    finally:
        desk.close()


def test_zero_fill_legacy_starter_is_cancelled_after_a_production_restart(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    identity = "nc-speed-existing-zero-fill"
    asyncio.run(desk._ensure_client())
    asyncio.run(desk._startup())
    # A pre-containment accepted venue order, with zero fills, is a liability
    # restored from disk. Controller admission is never bypassed or called here.
    desk.book.reserve_intent(TICKER, "up", "rest", .3, 5, clock.now(), identity, .5)
    desk.book.mark_submitted(identity, "legacy-zero")
    desk.intents[identity] = Intent(identity, TICKER, "up", "rest", .3, 5, .5, clock.now(),
                                    order_id="legacy-zero")
    account.orders.append({"order_id": "legacy-zero", "client_order_id": identity, "ticker": TICKER,
                           "status": "resting", "fill_count_fp": "0", "remaining_count_fp": "5",
                           "initial_count_fp": "5", "outcome_side": "yes", "book_side": "bid",
                           "yes_price_dollars": ".3", "no_price_dollars": ".7"})
    desk.checkpoint(durable=True)
    restored = reopen(tmp_path, desk, account, clock)
    original = account.cancel
    seen: list[float] = []

    def inspect(order_id: str, *, ticker: str) -> dict[str, Any]:
        seen.append(restored.book.intents[identity].reserved)
        reply = original(order_id, ticker=ticker)
        assert restored.book.intents[identity].reservation_active
        return reply

    account.cancel = inspect
    try:
        asyncio.run(restored._ensure_client())
        asyncio.run(restored._startup())
        assert account.cancels == ["legacy-zero"] and seen == [1.5]
        assert not account.creates and restored.book.inventory[TICKER].up.shares == 0
        assert restored.panel()["pair_execution"]["policy"] == "reduction_only"
        assert not asyncio.run(restored._send(restored.book.windows[TICKER], "up", "take", .1, 1, .8))
    finally:
        restored.close()
