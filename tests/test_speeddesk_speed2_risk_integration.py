"""Speed optimizations must keep the deployed stop policy and exact reservation ownership. Offline only."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_speeddesk_live_stop_model_review import NOW, buy_up, prepared, restored

from nightcrawler.speeddesk_live_model import ActualFill, LiveIntent, LiveRejected
from nightcrawler.speeddesk_model import (
    Holding,
    Inventory,
    PracticeDesk,
    SpeedConfig,
    utc_day,
)


def test_balancing_still_requires_full_cost_room_in_live_and_practice_open_budget():
    book, window = prepared()
    buy_up(book, window)
    book.limits = replace(book.limits, open_usd=3)
    # This hedge adds no worst-case loss. Its entire $2.25 still has to fit beside the existing $2 risk.
    assert book.worst_loss(window.slug, ("down", 5, 2.25)) == book.worst_loss(window.slug) == 2
    assert book.can_buy(window.slug, "down", "rest", .45, 5, NOW) == "open_budget"
    practice = PracticeDesk(SpeedConfig(window_usd=10, open_usd=3, day_stop_usd=6,
                                       hedged_open_budget=True, day_stop_counts_risk=True))
    practice.add_window(replace(window))
    practice.inventory[window.slug] = Inventory(Holding(5, 2), Holding())
    assert practice.can_buy(window.slug, "down", .45, 5, 0, NOW) == "open_budget"


def test_conservative_pending_cost_is_preserved_when_both_sides_have_bids():
    book, window = prepared()
    for side in ("up", "down"):
        key = f"nc-speed-{side}-pair"
        intent = book.reserve_intent(window.slug, side, "rest", .49, 5, NOW, key)
        book.record_fill(ActualFill(f"fill-{key}", f"venue-{key}", key, window.slug, side, .49, 5, 0, NOW))
        assert not intent.reservation_active
    for side in ("up", "down"):
        book.reserve_intent(window.slug, side, "rest", .50, 3, NOW, f"nc-speed-{side}-more")
    assert book.worst_loss(window.slug) == pytest.approx(1.4)
    assert book.at_risk_usd == pytest.approx(3)  # full new-risk reservation cost, not incremental exact loss
    assert not book.lowers_risk("nc-speed-up-more")
    assert not book.lowers_risk("nc-speed-down-more")
    assert restored(book).at_risk_usd == pytest.approx(3)


def test_old_speed_exception_cannot_bypass_aggregate_hedge_reservations():
    book, window = prepared()
    buy_up(book, window)
    hedge = book.reserve_intent(window.slug, "down", "rest", .45, 5, NOW, "nc-speed-hedge")
    assert book.lowers_risk(hedge.client_order_id)
    # A recovered uncertain lock claims the same final share, even when cancellation has been requested.
    extra = LiveIntent("nc-speed-extra", window.slug, "down", "take", .45, 1, NOW, .47,
                       status="uncertain", uncertainty="timeout", cancel_requested=True, lock=True)
    book.intents[extra.client_order_id] = extra
    assert not book.lowers_risk(hedge.client_order_id)
    assert not book.lowers_risk(extra.client_order_id)
    book.release_unsent(extra.client_order_id)
    assert book.lowers_risk(hedge.client_order_id)


def test_unsent_release_preserves_latched_stops_and_spent_resume_values():
    book, window = prepared()
    pending = book.reserve_intent(window.slug, "up", "rest", .4, 1, NOW, "nc-speed-unsent")
    assert book.resume("synthetic-before-stop") == "not_halted"
    book.stop_anchor = 9.5
    book.day_anchor[utc_day(NOW)] = 5.5
    assert book.latch_bound_stops(NOW) == ["total", "day"]
    book.release_unsent(pending.client_order_id)
    book = restored(book)
    assert book.reserved_usd == 0
    assert book.halted and book.day_latched(NOW)
    assert book.resume("synthetic-before-stop") == "used"
    assert book.halted
    assert book.apply_day_reset("synthetic-daily-only", NOW) == "reset"
    assert not book.day_latched(NOW) and book.halted


def test_unsent_release_does_not_release_a_real_order_or_fill():
    book, window = prepared()
    pending = book.reserve_intent(window.slug, "up", "rest", .4, 5, NOW, "nc-speed-submitted")
    book.mark_submitted(pending.client_order_id, "venue-real")
    with pytest.raises(LiveRejected, match="release_unproven"):
        book.release_unsent(pending.client_order_id)
    assert book.reserved_usd == 2
    book.record_fill(ActualFill("partial", "venue-real", pending.client_order_id, window.slug,
                                "up", .4, 1.25, 0, NOW))
    with pytest.raises(LiveRejected, match="release_unproven"):
        book.release_unsent(pending.client_order_id)
    assert book.at_risk_usd == 2


def test_indexed_settlement_removes_finished_risk_and_keeps_order_identity():
    book, window = prepared()
    first = buy_up(book, window)
    assert book.open_windows() == {window.slug}
    assert book.open_intent_ids() == [first.client_order_id]
    book.settle(window.slug, True, window.end, "settlement")
    assert not book.open_windows() and not book.open_intent_ids()
    assert book.at_risk_usd == book.reserved_usd == book.open_cost_usd == 0
    following = replace(window, slug="KXBTC15M-FOLLOWING", start=window.end, end=window.end + 900)
    book.add_window(following)
    book.update_cash(100, window.end)
    fresh = book.reserve_intent(following.slug, "up", "rest", .4, 1, window.end, "nc-speed-fresh")
    with pytest.raises(LiveRejected, match="order_identity_duplicate"):
        book.mark_submitted(fresh.client_order_id, "first")
    assert book.integrity_error == "order_identity_duplicate"
    assert book.reserved_usd == .4
