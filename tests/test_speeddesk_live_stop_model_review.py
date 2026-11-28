"""Stop review regressions: temporary reservations, real hedges and persistent owner resets. No network."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRiskBook,
    OrderSnapshot,
)
from nightcrawler.speeddesk_model import Window, utc_day

NOW = 1_791_475_210.0
LIMITS = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10,
                    clip=5, fee_precision=.0001)


def prepared() -> tuple[LiveRiskBook, Window]:
    book = LiveRiskBook(LIMITS)
    window = Window("KXBTC15M-REVIEW", NOW - 10, NOW + 890, 100,
                    venue="kalshi", taker_coefficient=.07, maker_coefficient=0)
    book.add_window(window)
    book.update_cash(100, NOW)
    return book, window


def buy_up(book: LiveRiskBook, window: Window, size: float = 5) -> LiveIntent:
    intent = book.reserve_intent(window.slug, "up", "rest", .4, size, NOW, "nc-speed-first")
    book.mark_submitted(intent.client_order_id, "first")
    book.record_fill(ActualFill("first-fill", "first", intent.client_order_id, window.slug,
                                "up", .4, size, 0, NOW))
    return intent


def restored(book: LiveRiskBook) -> LiveRiskBook:
    return LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())), LIMITS)


def test_an_unfilled_starter_does_not_spend_a_permanent_stop():
    book, window = prepared()
    book.stop_anchor = 8.7
    assert book.starter_fit(window.slug, "up", "rest", .4, 5, NOW) == (1, "")
    pending = book.reserve_intent(window.slug, "up", "rest", .4, 1, NOW, "nc-speed-pending")
    assert book.starter_fit(window.slug, "down", "rest", .4, 5, NOW) == (0, "total_budget")
    assert book.latch_bound_stops(NOW) == []
    assert not book.halted
    book = restored(book)
    assert not book.halted
    book.mark_submitted(pending.client_order_id, "pending")
    book.reconcile_order(OrderSnapshot(pending.client_order_id, "pending", "canceled", 0, 0, NOW),
                         fills_complete=True)
    book.update_cash(100, NOW)
    assert book.starter_fit(window.slug, "up", "rest", .4, 5, NOW) == (1, "")
    assert not book.halted


@pytest.mark.parametrize("stop", ["total", "day"])
def test_an_open_winning_window_does_not_leave_a_false_permanent_stop(stop: str):
    book, window = prepared()
    if stop == "total":
        book.stop_anchor = 7.0
    else:
        book.day_anchor[utc_day(NOW)] = 3.0
    buy_up(book, window)
    next_window = replace(window, slug="KXBTC15M-NEXT")
    book.add_window(next_window)
    assert book.starter_fit(next_window.slug, "up", "rest", .4, 1, NOW)[0] == 0
    assert book.latch_bound_stops(NOW) == []
    assert not book.halted and not book.day_latched(NOW)
    book = restored(book)
    book.settle(window.slug, True, window.end, "won")
    book.update_cash(100, window.end)
    future = replace(window, slug="KXBTC15M-FUTURE", start=window.end, end=window.end + 900)
    book.add_window(future)
    assert book.starter_fit(future.slug, "up", "rest", .4, 1, window.end) == (1, "")
    assert not book.halted and not book.day_latched(window.end)


def test_risk_status_full_exposure_is_temporary_even_if_a_budget_is_reduced():
    book, window = prepared()
    buy_up(book, window)
    book.stop_anchor = 8.1  # a changed budget while an earlier position is still unsettled
    status = book.risk_status(NOW)
    assert status["total_at_risk_usd"] > LIMITS.total_loss_usd
    assert not status["halted"]
    assert book.latch_bound_stops(NOW) == []
    assert book.can_buy(window.slug, "up", "rest", .4, 1, NOW) == "total_budget"
    assert not book.halted


def test_price_specific_hedge_fee_refusal_never_changes_the_permanent_entry_floor():
    book, window = prepared()
    book.stop_anchor = 9.0  # $1 room exceeds policy floor $.98, but a .42 starter + hedge costs more than $1
    assert book.starter_fit(window.slug, "up", "rest", .42, 1, NOW) == (0, "total_budget")
    assert book.latch_bound_stops(NOW) == [] and not book.halted
    book = restored(book)
    assert book.latch_bound_stops(NOW) == [] and not book.halted
    book.update_cash(100, NOW)
    assert book.starter_fit(window.slug, "up", "rest", .42, 1, NOW) == (0, "total_budget")
    assert not book.halted


@pytest.mark.parametrize("stop", ["total", "day"])
def test_tiny_new_risk_latches_from_settled_loss_at_the_same_floor(stop: str):
    book, window = prepared()
    if stop == "total":
        book.stop_anchor = 9.9421
    else:
        book.day_anchor[utc_day(NOW)] = 5.5
    assert book.can_buy(window.slug, "up", "rest", .01, 1, NOW)
    assert book.halted if stop == "total" else book.day_latched(NOW)
    book = restored(book)
    assert book.halted if stop == "total" else book.day_latched(NOW)


@pytest.mark.parametrize("stop", ["total", "day", "both"])
def test_a_latched_financial_stop_allows_only_strictly_balancing_new_orders(stop: str):
    book, window = prepared()
    buy_up(book, window)
    if stop in ("total", "both"):
        book.stop_anchor = 10.0
    if stop in ("day", "both"):
        book.day_anchor[utc_day(NOW)] = 6.0
    book.latch_bound_stops(NOW)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW) == ""
    assert book.can_buy(window.slug, "up", "rest", .01, 1, NOW)
    assert book.can_buy(window.slug, "down", "rest", .60, 5, NOW) == "pair_cap"
    book.update_cash(1, NOW)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW) == "cash_budget"
    book.update_cash(100, NOW)
    book.limits = replace(LIMITS, window_usd=3)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW) == "window_budget"
    book.limits = replace(LIMITS, open_usd=3)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW) == "open_budget"


@pytest.mark.parametrize("halt_reason", [None, "unknown_stop", "total_loss"])
def test_nonfinancial_halts_and_integrity_failures_never_allow_hedges(halt_reason: str | None):
    book, window = prepared()
    buy_up(book, window)
    book.halted, book.halt_reason = True, halt_reason
    if halt_reason == "total_loss":
        book.integrity_error = "fill_changed"
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW)


def test_balancing_classifier_rechecks_partial_fills_and_terminal_evidence():
    book, window = prepared()
    buy_up(book, window)
    hedge = book.reserve_intent(window.slug, "down", "rest", .45, 5, NOW, "nc-speed-hedge")
    book.mark_submitted(hedge.client_order_id, "hedge")
    assert book.strictly_balancing_intent(hedge.client_order_id)
    book.record_fill(ActualFill("partial", "hedge", hedge.client_order_id, window.slug,
                                "down", .45, 2.5, 0, NOW))
    assert hedge.remaining == 2.5
    assert book.strictly_balancing_intent(hedge.client_order_id)
    hedge.cancel_requested, hedge.uncertainty = True, "timeout"
    assert book.strictly_balancing_intent(hedge.client_order_id)
    book.reconcile_order(OrderSnapshot(hedge.client_order_id, "hedge", "canceled", 2.5, 0, NOW),
                         fills_complete=True)
    assert not book.strictly_balancing_intent(hedge.client_order_id)
    assert not book.strictly_balancing_intent("nc-speed-unknown")


@pytest.mark.parametrize("other_kind", ["normal", "lock", "uncertain", "cancel_requested"])
def test_balancing_classifier_never_double_counts_an_unpaired_contract(other_kind: str):
    book, window = prepared()
    buy_up(book, window)
    hedge = book.reserve_intent(window.slug, "down", "rest", .45, 5, NOW, "nc-speed-hedge")
    # Simulate two authoritative reservations in a recovered journal. Neither may claim the same last share.
    other = LiveIntent("nc-speed-other", window.slug, "down", "take", .45, 1, NOW, .47)
    other.lock = other_kind == "lock"
    other.uncertainty = "timeout" if other_kind == "uncertain" else None
    other.cancel_requested = other_kind == "cancel_requested"
    book.intents[other.client_order_id] = other
    assert not book.strictly_balancing_intent(hedge.client_order_id)
    assert not book.strictly_balancing_intent(other.client_order_id)
    other.reservation_active = False  # only terminal confirmation releases it
    assert book.strictly_balancing_intent(hedge.client_order_id)


def test_balancing_classifier_never_exempts_a_dollar_or_a_heavy_side():
    book, window = prepared()
    buy_up(book, window)
    hedge = book.reserve_intent(window.slug, "down", "rest", .45, 5, NOW, "nc-speed-hedge")
    hedge.unit_reserve = 1.0
    assert not book.strictly_balancing_intent(hedge.client_order_id)
    hedge.unit_reserve, hedge.side = .45, "up"
    assert not book.strictly_balancing_intent(hedge.client_order_id)


def test_early_resume_token_cannot_clear_a_later_realized_stop_after_restart():
    book, window = prepared()
    assert book.resume("before-stop") == "not_halted"
    book = restored(book)
    book.stop_anchor = 9.9421
    assert book.latch_bound_stops(NOW) == ["total"]
    book = restored(book)
    assert book.resume("before-stop") == "used"
    assert book.halted
    assert book.resume("after-stop") == "applied"
    assert not book.halted and book.stop_anchor == book.realized_pnl
    assert book.resume("after-stop") == "used"
    book.update_cash(100, NOW)
    assert book.starter_fit(window.slug, "up", "rest", .4, 1, NOW) == (1, "")
