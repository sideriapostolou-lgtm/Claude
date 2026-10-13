"""Actual-fill accounting and hard live limits, using synthetic venue replies."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_CEILING, Decimal

import pytest

from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
    OrderSnapshot,
    reserve_unit_cost,
)
from nightcrawler.speeddesk_model import Window, utc_day

WINDOW = "KXBTC15M-TEST-A"


# The caps before the owner's 2026-10-13 raise; mechanism tests keep these exact numbers.
SMALL = LiveLimits(window_usd=2, open_usd=4, day_loss_usd=3, total_loss_usd=5, fee_precision=.0001)


def make_book(*, limits: LiveLimits | None = None, cash: float = 100) -> LiveRiskBook:
    book = LiveRiskBook(limits or LiveLimits(fee_precision=.0001))
    book.add_window(Window(WINDOW, 1000, 1900, 100, taker_coefficient=.07,
                           maker_coefficient=0, venue="kalshi"))
    book.update_cash(cash, 1010)
    return book


def reserve(book: LiveRiskBook, *, window: str = WINDOW, side="up", kind="take",
            price=.4, size=1, at=1010, name="first"):
    return book.reserve_intent(window, side, kind, price, size, at, f"nc-speed-{name}", .6)


def actual_fill(book: LiveRiskBook, intent, *, size=None, price=None, fee=.01, at=1011, name=None):
    row = ActualFill(name or f"fill-{len(book.fills)}", f"venue-{intent.client_order_id}", intent.client_order_id,
                     intent.window, intent.side, intent.price if price is None else price,
                     intent.size if size is None else size, fee, at)
    assert book.record_fill(row)
    return row


def snapshot(intent, *, filled=0, remaining=0, status="canceled", at=1012):
    return OrderSnapshot(intent.client_order_id, f"venue-{intent.client_order_id}", status, filled, remaining, at)


def losing_window(book: LiveRiskBook, index: int, start: float, *, size=4, price=.4, fee=0):
    slug = f"KXBTC15M-LOSS-{index}"
    book.add_window(Window(slug, start, start + 900, 100, taker_coefficient=.07,
                           maker_coefficient=0, venue="kalshi"))
    book.update_cash(100, start + 10)
    order = reserve(book, window=slug, at=start + 10, size=size, price=price, name=f"loss-{index}")
    actual_fill(book, order, fee=fee, at=start + 11)
    return book.settle(slug, False, start + 900, f"settlement-{index}", net_payout_usd=0)


def test_hard_limits_can_only_be_reduced_and_cutoff_never_below_one_minute():
    limits = LiveLimits(window_usd=200, open_usd=400, day_loss_usd=300, total_loss_usd=500,
                        pair_cap=1, max_imbalance=1, cutoff_s=0)
    assert (limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.total_loss_usd) == (5, 10, 6, 10)
    assert limits.pair_cap == .99 and limits.max_imbalance == .25 and limits.cutoff_s == 60
    # New buys never outlast the lock period, and a lock never pays a dollar.
    assert LiveLimits(cutoff_s=300, lock_s=100).lock_s == 300 and LiveLimits(lock_max_price=1).lock_max_price == .99
    assert LiveLimits(window_usd=.5).window_usd == .5
    with pytest.raises(ValueError):
        LiveLimits(open_usd=float("nan"))
    with pytest.raises(ValueError):
        LiveLimits(fee_precision=.001)
    with pytest.raises(ValueError):
        LiveLimits(min_fill_qty=1)  # whole requests do not guarantee whole partial executions


@pytest.mark.parametrize("precision", [.0001, .01])
@pytest.mark.parametrize("price", [.01, .1, .4, .5, .99])
def test_fee_reserve_covers_fragmented_fills_and_price_improvement_without_rebates(precision, price):
    bound = reserve_unit_cost(price, .07, precision)
    for fragments in ([1], [.13, .27, .60], [.01] * 100):
        for executed in (price, round(price * .7, 4)):
            total = Decimal(0)
            for quantity in fragments:
                q, p, grid = Decimal(str(quantity)), Decimal(str(executed)), Decimal(str(precision))
                raw_fee = Decimal(".07") * q * p * (1 - p)
                trade_fee = raw_fee.quantize(Decimal(".000001"), rounding=ROUND_CEILING)
                total += ((q * p + trade_fee) / grid).to_integral_value(rounding=ROUND_CEILING) * grid
            assert float(total) <= bound + 1e-9


def test_unknown_member_precision_is_conservative_and_never_assumed_direct():
    unknown = LiveRiskBook()
    direct = make_book()
    assert unknown.limits.fee_precision == .01
    assert reserve_unit_cost(.4, .07) == 1
    assert direct.unit_reserve(WINDOW, .4, "take") == .42
    assert direct.unit_reserve(WINDOW, .4, "rest") == .4


def test_intent_reservation_precedes_submission_and_survives_uncertainty_restart():
    book = make_book()
    intent = reserve(book, size=3)
    assert book.reserved_usd == pytest.approx(1.26)
    assert intent.order_id is None and not book.fills and book.open_cost_usd == 0
    book.mark_uncertain(intent.client_order_id, "create_timeout")
    restored = LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())))
    assert restored.reserved_usd == pytest.approx(1.26)
    assert restored.intents[intent.client_order_id].status == "uncertain"
    assert restored.cash_at is None and restored.cash_usd is None
    restored.update_cash(100, 1011)
    assert restored.can_buy(WINDOW, "up", "take", .4, 1, 1011) == "order_pending"


def test_cancel_request_and_timeout_never_release_money_at_risk():
    book = make_book()
    intent = reserve(book, kind="rest", size=4)
    book.mark_submitted(intent.client_order_id, f"venue-{intent.client_order_id}")
    book.request_cancel(intent.client_order_id)
    book.mark_uncertain(intent.client_order_id, "cancel_timeout")
    assert book.reserved_usd == pytest.approx(1.6)
    assert not book.reconcile_order(snapshot(intent), fills_complete=False)
    assert book.reserved_usd == pytest.approx(1.6)
    assert book.reconcile_order(snapshot(intent), fills_complete=True)
    assert book.reserved_usd == 0


def test_cancel_confirmation_keeps_reservation_until_reported_fills_are_booked():
    book = make_book()
    intent = reserve(book, size=4)
    observed = snapshot(intent, filled=1.25)
    assert not book.reconcile_order(observed, fills_complete=True)
    assert book.reserved_usd == pytest.approx(1.68)
    actual_fill(book, intent, size=1.25, fee=.021, at=1011)
    assert book.open_cost_usd == pytest.approx(.521)
    assert book.reserved_usd == pytest.approx(2.75 * .42)
    assert book.reconcile_order(observed, fills_complete=True)
    assert book.reserved_usd == 0 and book.open_cost_usd == pytest.approx(.521)


def test_regressed_fill_count_cannot_release_uncertain_reservation():
    book = make_book()
    intent = reserve(book, size=4)
    assert not book.reconcile_order(snapshot(intent, filled=1), fills_complete=True)
    assert not book.reconcile_order(snapshot(intent, filled=0, at=1013), fills_complete=True)
    assert intent.reservation_active and book.reserved_usd == pytest.approx(1.68)
    assert intent.uncertainty == "order_fill_count_regressed"


def test_terminal_status_with_remaining_contracts_cannot_release_exposure():
    book = make_book()
    intent = reserve(book, size=4)
    assert not book.reconcile_order(snapshot(intent, remaining=4), fills_complete=True)
    assert intent.reservation_active


def test_only_definitive_never_accepted_create_rejection_can_release_intent():
    book = make_book()
    intent = reserve(book)
    with pytest.raises(LiveRejected, match="rejection_unconfirmed"):
        book.reject_intent(intent.client_order_id, "http_400")
    assert book.reject_intent(intent.client_order_id, "http_400", confirmed=True)
    assert not book.reject_intent(intent.client_order_id, "http_400", confirmed=True)
    assert book.reserved_usd == 0
    ambiguous = reserve(book, name="ambiguous")
    book.mark_uncertain(ambiguous.client_order_id, "create_timeout")
    with pytest.raises(LiveRejected, match="rejection_unconfirmed"):
        book.reject_intent(ambiguous.client_order_id, "http_400", confirmed=True)
    assert ambiguous.reserved > 0


def test_new_fill_after_terminal_proof_keeps_actual_cost_and_restores_unknown_exposure():
    book = make_book()
    intent = reserve(book, size=4)
    assert book.reconcile_order(snapshot(intent), fills_complete=True)
    actual_fill(book, intent, size=1, fee=.0168)
    assert book.open_cost_usd == pytest.approx(.4168)
    assert book.reserved_usd == pytest.approx(1.26)
    assert book.integrity_error == "fill_after_terminal_confirmation"
    assert book.can_buy(WINDOW, "down", "take", .4, 1, 1012) == "reconciliation_error"
    assert LiveRiskBook.from_state(book.to_state()).at_risk_usd == pytest.approx(1.6768)


def test_active_snapshot_after_terminal_proof_cannot_leave_released_exposure():
    book = make_book()
    intent = reserve(book, size=4)
    assert book.reconcile_order(snapshot(intent), fills_complete=True)
    with pytest.raises(LiveRejected, match="order_terminal_regressed"):
        book.reconcile_order(snapshot(intent, status="resting", remaining=4, at=1013), fills_complete=True)
    assert book.reserved_usd == pytest.approx(1.68)
    assert book.integrity_error == "order_terminal_regressed"


def test_repeated_order_discovery_preserves_terminal_evidence_across_restart():
    book = make_book()
    intent = reserve(book, size=4)
    actual_fill(book, intent, size=1, fee=.0168)
    assert book.reconcile_order(snapshot(intent, filled=1), fills_complete=True)
    book.mark_submitted(intent.client_order_id, intent.order_id)
    assert intent.status == "canceled" and not intent.reservation_active
    restored = LiveRiskBook.from_state(book.to_state())
    assert restored.reserved_usd == 0 and restored.open_cost_usd == pytest.approx(.4168)


def test_window_open_day_and_cash_caps_include_fee_reservations():
    book = make_book(limits=SMALL)
    assert book.can_buy(WINDOW, "up", "take", .4, 5, 1010) == "window_budget"
    book.limits = replace(book.limits, open_usd=.8)
    assert book.can_buy(WINDOW, "up", "take", .4, 2, 1010) == "open_budget"
    book = make_book(limits=SMALL, cash=.8)
    assert book.can_buy(WINDOW, "up", "take", .4, 2, 1010) == "cash_budget"
    first = reserve(book)
    actual_fill(book, first, fee=.0168)
    # Its last cash snapshot predated the fill; receipt costs remain debited
    # until another actual balance read, even though the reservation is gone.
    assert book.risk_status(1011)["available_cash_usd"] == pytest.approx(.3832)
    assert book.can_buy(WINDOW, "down", "take", .4, 1, 1011) == "cash_budget"


def test_fresh_cash_required_and_new_process_never_reuses_old_balance():
    book = make_book()
    assert book.can_buy(WINDOW, "up", "take", .4, 1, 1016) == "cash_stale"
    restored = LiveRiskBook.from_state(book.to_state())
    assert restored.can_buy(WINDOW, "up", "take", .4, 1, 1010) == "cash_stale"
    restored.update_cash(1, 1010)
    assert restored.can_buy(WINDOW, "up", "take", .4, 1, 1010) == ""


def test_inventory_changes_only_from_idempotent_owned_actual_fills_and_exact_fees():
    book = make_book()
    intent = reserve(book, size=2)
    assert book.inventory[WINDOW].up.shares == 0
    owner = ActualFill("owner-fill", "owner-order", "owner-id", WINDOW, "up", .4, 100, 1, 1011)
    assert not book.record_fill(owner)
    assert not book.fills and book.inventory[WINDOW].up.shares == 0
    row = actual_fill(book, intent, size=.25, fee=.0042)
    assert not book.record_fill(row)
    assert book.inventory[WINDOW].up.shares == .25
    assert book.inventory[WINDOW].up.fees == .0042
    assert book.open_cost_usd == pytest.approx(.1042)
    assert book.reserved_usd == pytest.approx(1.75 * .42)
    with pytest.raises(LiveRejected, match="fill_changed"):
        book.record_fill(replace(row, fee_usd=.001))


def test_actual_fill_exceeding_reserved_terms_is_booked_truthfully_and_halts_new_orders():
    book = make_book()
    intent = reserve(book)
    actual_fill(book, intent, price=.45, fee=.02)
    assert book.inventory[WINDOW].up.cost == .45
    assert book.integrity_error == "fill_exceeded_reserved_terms"
    assert book.can_buy(WINDOW, "down", "take", .4, 1, 1011) == "reconciliation_error"
    book.halted = True
    assert not book.apply_resume_token("cannot_clear_integrity_error")


def test_live_starter_then_balancing_uses_actual_partial_inventory_and_pending_orders():
    book = make_book()
    first = reserve(book, kind="rest", price=.3, size=4)
    assert book.can_buy(WINDOW, "down", "rest", .3, 1, 1010) == "starter_pending"
    actual_fill(book, first, size=1.5, fee=0)
    assert book.can_buy(WINDOW, "up", "rest", .3, 1, 1011) == "order_pending"
    assert book.can_buy(WINDOW, "down", "rest", .3, 2, 1011) == "balancing_size"
    opposite = reserve(book, side="down", kind="rest", price=.3, size=1, at=1011, name="opposite")
    actual_fill(book, opposite, fee=0, at=1012)
    assert book.expected_position(WINDOW) == .5
    assert book.can_buy(WINDOW, "down", "rest", .3, 1, 1012) == "balancing_size"


def test_matched_pair_cap_includes_actual_fees_and_conservative_pending_fee_bound():
    book = make_book()
    first = reserve(book, price=.5)
    actual_fill(book, first, fee=.0175)
    assert book.can_buy(WINDOW, "down", "take", .47, 1, 1011) == "pair_cap"
    assert book.can_buy(WINDOW, "down", "take", .45, 1, 1011) == ""


def test_partial_actual_fills_reduce_reservations_without_exceeding_hard_budget():
    book = make_book()
    order = reserve(book, size=4)
    for index in range(400):
        actual_fill(book, order, size=.01, fee=.0002, at=1011, name=str(index))
        assert book.at_risk_usd <= 1.68 + 1e-9
    assert book.reserved_usd == 0
    assert book.inventory[WINDOW].up.shares == pytest.approx(4)
    assert book.inventory[WINDOW].up.fees == pytest.approx(.08)


def test_settlement_accounts_netted_pair_credit_once_and_only_net_final_payout():
    book = make_book()
    up = reserve(book, kind="rest", price=.3, size=2)
    actual_fill(book, up, fee=0)
    down = reserve(book, side="down", kind="rest", price=.3, size=1, at=1011, name="down")
    actual_fill(book, down, fee=0, at=1012)
    assert book.expected_position(WINDOW) == 1
    result = book.settle(WINDOW, True, 1900, "settled", net_payout_usd=1)
    assert result is not None
    assert result.paired_credit_usd == 1 and result.net_payout_usd == 1 and result.payout_usd == 2
    assert result.cost_usd == pytest.approx(.9)
    assert result.locked_usd == pytest.approx(.4)
    assert result.direction_usd == pytest.approx(.7)
    assert result.pnl_usd == pytest.approx(1.1)
    assert book.settle(WINDOW, True, 1900, "settled", net_payout_usd=1) is None
    assert book.realized_pnl == pytest.approx(1.1) and book.expected_position(WINDOW) == 0


def test_fully_netted_window_needs_no_fictitious_gross_settlement_payout():
    book = make_book()
    up = reserve(book, kind="rest", price=.3, size=2)
    actual_fill(book, up, fee=0)
    down = reserve(book, side="down", kind="rest", price=.3, size=2, at=1011, name="down")
    actual_fill(book, down, fee=0, at=1012)
    assert book.expected_position(WINDOW) == 0
    result = book.settle(WINDOW, False, 1900, "final-public-market", net_payout_usd=0)
    assert result is not None
    assert result.net_payout_usd == 0 and result.paired_credit_usd == 2
    assert result.pnl_usd == pytest.approx(.8)
    assert result.locked_usd == pytest.approx(.8)
    assert result.direction_usd == pytest.approx(0)


def test_settlement_waits_for_cancelled_unknown_orders_and_checks_venue_net_revenue():
    book = make_book()
    order = reserve(book, size=2)
    actual_fill(book, order, size=1, fee=.0168)
    with pytest.raises(LiveRejected, match="settlement_orders_unreconciled"):
        book.settle(WINDOW, True, 1900, "settled")
    book.reconcile_order(snapshot(order, filled=1), fills_complete=True)
    with pytest.raises(LiveRejected, match="settlement_net_payout_mismatch"):
        book.settle(WINDOW, True, 1900, "settled", net_payout_usd=2)
    assert not book.settled


def test_day_stop_includes_settled_losses_and_old_open_exposure_across_midnight():
    book = make_book(limits=SMALL)
    losing_window(book, 1, 1000)
    later = "KXBTC15M-LATER"
    book.add_window(Window(later, 1900, 2800, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(100, 1910)
    assert book.can_buy(later, "up", "take", .4, 4, 1910) == "day_stop"
    order = reserve(book, window=later, size=3, at=1910, name="later")
    actual_fill(book, order, fee=.0504, at=1911)
    assert book.risk_status(1911)["day_at_risk_usd"] == pytest.approx(2.8504)
    tomorrow = book.risk_status(86401)
    assert tomorrow["day_loss_usd"] == 0
    assert tomorrow["at_risk_usd"] == pytest.approx(1.2504)
    assert tomorrow["total_loss_usd"] == pytest.approx(1.6)


def test_total_halt_survives_restart_and_requires_new_hash_without_erasing_history():
    book = make_book()
    assert not book.apply_resume_token("original-token")
    losing_window(book, 1, 1000)
    losing_window(book, 2, 86400)
    # A lowered configured stop also applies to previously realized losses.
    book.limits = replace(book.limits, total_loss_usd=3)
    assert book.risk_status(87300)["halted"]
    old_pnl = book.realized_pnl
    encoded = json.dumps(book.to_state())
    assert "original-token" not in encoded
    restored = LiveRiskBook.from_state(json.loads(encoded))
    assert restored.halted
    assert not restored.apply_resume_token("original-token")
    assert restored.apply_resume_token("new-owner-acknowledgement")
    assert restored.realized_pnl == old_pnl and len(restored.settled) == 2
    assert restored.stop_anchor == old_pnl
    assert restored.day_pnl == book.day_pnl
    assert not restored.risk_status(87300)["halted"]
    assert "new-owner-acknowledgement" not in json.dumps(restored.to_state())
    restored.halted = True
    assert not restored.apply_resume_token("new-owner-acknowledgement")
    assert not restored.apply_resume_token("original-token")
    assert restored.halted  # an older, already-used value is not a NEW token


@pytest.mark.parametrize("change", ["inventory", "order", "pnl", "day", "nonfinite"])
def test_corrupt_actual_accounting_fails_closed_on_restore(change):
    book = make_book()
    order = reserve(book)
    actual_fill(book, order)
    state = json.loads(json.dumps(book.to_state()))
    if change == "inventory":
        state["inventory"][WINDOW]["up"]["cost"] = 0
    elif change == "order":
        state["intents"][order.client_order_id]["filled_size"] = 0
    elif change == "pnl":
        state["realized_pnl"] = 100
    elif change == "day":
        state["day_pnl"][utc_day(1010)] = 100
    else:
        state["inventory"][WINDOW]["up"]["fees"] = float("nan")
    with pytest.raises(ValueError):
        LiveRiskBook.from_state(state)


def test_good_actual_accounting_roundtrip_keeps_uncertain_reservation_and_fee_bound():
    book = make_book()
    order = reserve(book, size=4)
    actual_fill(book, order, size=1, fee=.0168)
    book.mark_uncertain(order.client_order_id, "cancel_timeout")
    restored = LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())), LiveLimits(fee_precision=.01))
    assert restored.inventory == book.inventory
    assert restored.intents[order.client_order_id].unit_reserve == .42
    assert restored.reserved_usd == pytest.approx(1.26)
    assert restored.cash_at is None


@pytest.mark.parametrize("change", ["reservation", "missing_inventory", "token", "side", "unit"])
def test_corrupt_reservation_and_identity_evidence_fails_closed(change):
    book = make_book()
    order = reserve(book)
    state = json.loads(json.dumps(book.to_state()))
    if change == "reservation":
        state["intents"][order.client_order_id]["reservation_active"] = False
    elif change == "missing_inventory":
        del state["inventory"][WINDOW]
    elif change == "token":
        state["resume_token_hash"] = "unhashed-secret"
    elif change == "side":
        state["intents"][order.client_order_id]["side"] = "owner"
    else:
        state["intents"][order.client_order_id]["unit_reserve"] = 0
    with pytest.raises(ValueError):
        LiveRiskBook.from_state(state)


@pytest.mark.parametrize("field,value", [("paired_credit_usd", 100), ("net_payout_usd", 100),
                                         ("pnl_usd", float("nan")), ("at", 1000), ("up_wins", "false")])
def test_settled_actual_money_and_netting_fields_are_checked_on_restart(field, value):
    book = make_book()
    losing_window(book, 1, 1000)
    assert LiveRiskBook.from_state(book.to_state()).realized_pnl == book.realized_pnl
    state = json.loads(json.dumps(book.to_state()))
    state["settled"]["KXBTC15M-LOSS-1"][field] = value
    with pytest.raises(ValueError):
        LiveRiskBook.from_state(state)


def test_nonfinite_settlement_time_is_rejected_before_any_accounting_mutation():
    book = make_book()
    order = reserve(book)
    actual_fill(book, order)
    with pytest.raises(LiveRejected, match="settlement_invalid"):
        book.settle(WINDOW, True, float("nan"), "settled")
    assert not book.settled and book.realized_pnl == 0 and not book.day_pnl


def test_only_verified_kalshi_fifteen_minute_windows_and_safe_client_ids_can_enter():
    book = make_book()
    with pytest.raises(LiveRejected, match="kalshi_15m_only"):
        book.add_window(Window("cpc-btc-updown-15m", 1000, 1900, venue="polymarket_us"))
    with pytest.raises(LiveRejected, match="kalshi_15m_only"):
        book.add_window(Window("KXBTC15M-HOUR", 1000, 4600, venue="kalshi"))
    with pytest.raises(LiveRejected, match="client_order_id"):
        book.reserve_intent(WINDOW, "up", "take", .4, 1, 1010, "owner-order")
    first = reserve(book)
    with pytest.raises(LiveRejected, match="client_order_id"):
        reserve(book)
    book.mark_uncertain(first.client_order_id, "unsafe dynamic exception with auth contents")
    assert first.uncertainty == "unknown_request_outcome"


def test_live_cutoff_and_tick_quantity_validation_are_fail_closed():
    book = make_book()
    book.update_cash(100, 1720)
    assert book.can_buy(WINDOW, "up", "take", .4, 1, 1720) == "cutoff"
    assert book.can_buy(WINDOW, "up", "take", .405, 1, 1010) == "invalid_order"
    assert book.can_buy(WINDOW, "up", "take", .4, .5, 1010) == "invalid_order"


def test_a_complete_pair_risks_nothing_and_only_unpaired_cost_counts():
    book = make_book()
    up = reserve(book, size=3)
    actual_fill(book, up, fee=.02)
    assert book.open_cost_usd == pytest.approx(1.22) and book.open_loss_usd == pytest.approx(1.22)
    down = reserve(book, side="down", price=.5, size=3, name="down")
    actual_fill(book, down, fee=.01)
    # Gross cost stays visible, but 3 up + 3 down pay $3 whatever happens: nothing is at risk.
    assert book.open_cost_usd == pytest.approx(2.73)
    assert book.open_loss_usd == 0 and book.at_risk_usd == 0


def test_lock_only_completes_reconciled_unpaired_contracts_near_the_close():
    book = make_book()
    actual_fill(book, reserve(book, size=3), fee=.01)
    book.update_cash(100, 1700)
    assert book.lock_side(WINDOW) == ("down", 3)
    assert book.can_lock(WINDOW, "down", .8, 3, 1650) == "not_lock_time"  # lock period starts 240 s out
    assert book.can_lock(WINDOW, "down", .8, 3, 1885) == "not_lock_time"  # never in the final 20 s
    assert book.can_lock(WINDOW, "up", .3, 1, 1700) == "lock_size"  # the heavy side never grows
    assert book.can_lock(WINDOW, "down", .8, 4, 1700) == "lock_size"  # never more than is unpaired
    assert book.can_lock(WINDOW, "down", .98, 3, 1700) == "lock_price"  # a decided window is left alone
    assert book.can_buy(WINDOW, "down", "take", .8, 3, 1700) == "cutoff"  # a normal buy is refused here
    # Money stops bound loss, and a lock only lowers it, so they do not block it.
    book.day_pnl[utc_day(1700)] = -6
    book.halted = True
    assert book.can_lock(WINDOW, "down", .8, 3, 1700) == ""
    lock = book.reserve_intent(WINDOW, "down", "take", .8, 3, 1700, "nc-speed-lock", lock=True)
    assert lock.lock and book.reserved_usd == pytest.approx(3 * reserve_unit_cost(.8, .07, .0001))  # it holds cash
    assert book.at_risk_usd == pytest.approx(book.open_loss_usd)  # but is not counted as new risk
    assert book.can_lock(WINDOW, "down", .8, 1, 1701) == "order_pending"
    with pytest.raises(LiveRejected):
        book.reserve_intent(WINDOW, "down", "rest", .8, 1, 1701, "nc-speed-rest-lock", lock=True)
    book.integrity_error = "fill_changed"
    assert book.can_lock(WINDOW, "down", .8, 1, 1701) == "reconciliation_error"


def test_state_saved_before_locks_existed_still_loads():
    book = make_book()
    reserve(book)
    state = json.loads(json.dumps(book.to_state()))
    for value in state["intents"].values():
        del value["lock"]
    assert not next(iter(LiveRiskBook.from_state(state).intents.values())).lock
