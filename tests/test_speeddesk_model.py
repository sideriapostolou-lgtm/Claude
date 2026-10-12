"""Deterministic evidence and accounting tests: no network and no real orders."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest
from fakes import FakeClock

from nightcrawler.speeddesk_model import (
    BitcoinTape,
    Book,
    Holding,
    Inventory,
    Level,
    PracticeDesk,
    SpeedConfig,
    Trade,
    Window,
    fair_up,
    fill_fee,
    reserved_per_share,
    settlement,
    utc_day,
)


def desk(*, config: SpeedConfig | None = None, seeded: bool = False) -> PracticeDesk:
    result = PracticeDesk(config or SpeedConfig(window_usd=100, open_usd=100))
    result.add_window(Window("btc15m", 1000, 1900, 100, taker_coefficient=0, maker_coefficient=0))
    if seeded:
        result.inventory["btc15m"] = Inventory(Holding(10, 4), Holding(10, 4))
    refresh(result, 1010)
    return result


def refresh(model: PracticeDesk, now: float, *, ask: float = 0.4, ask_size: float = 100,
            bid: float = 0.3, bid_size: float = 10, sequence: str = "a") -> None:
    model.tick_btc(100, now)
    for side in ("up", "down"):
        model.on_book(Book("btc15m", side, (Level(bid, bid_size),), (Level(ask, ask_size),), now, sequence))


@pytest.mark.parametrize(("spot", "opening", "sigma", "left", "expected"), [
    (100, 100, .01, 60, .5),
    (100, 100, 0, 60, .5),
    (101, 100, 0, 60, 1),
    (99, 100, 0, 60, 0),
    (100, 100, .01, 0, 1),
    (99, 100, .01, 0, 0),
    (0, 100, .01, 60, None),
    (100, 0, .01, 60, None),
    (100, 100, -.01, 60, None),
    (100, 100, .01, -1, None),
    (math.nan, 100, .01, 60, None),
    (100, 100, math.inf, 60, None),
])
def test_fair_value_edges(spot, opening, sigma, left, expected):
    assert fair_up(spot, opening, sigma, left) == expected


def test_fair_value_normal_cdf_and_extreme_finite_inputs():
    assert fair_up(math.exp(.02) * 100, 100, .01, 4) == pytest.approx(.841344746)
    assert fair_up(1e-300, 1e300, .01, 10) == 0
    assert fair_up(1e300, 1e-300, .01, 10) == 1


def test_sigma_uses_complete_one_second_returns_and_exact_hour():
    tape = BitcoinTape()
    for second in range(3602):
        tape.tick(math.exp(second * .001), second + .1)
    assert tape.sigma(3601.5) == pytest.approx(.001)
    tape.prices.pop(2000)
    assert tape.sigma(3601.5, 3600) is None
    assert tape.sigma(3601.5, 3598) == pytest.approx(.001)


def test_tape_does_not_backfill_opening_or_accept_out_of_order_ticks():
    model = PracticeDesk()
    model.add_window(Window("late", 1000, 1900))
    model.tick_btc(100, 1001)
    model.tick_btc(99, 1000)
    assert model.windows["late"].start_price is None
    model.add_window(Window("next", 1002, 1902))
    model.tick_btc(101, 1002.2)
    model.tick_btc(103, 1002.7)
    assert model.windows["next"].start_price == 101
    assert model.tape.price == 103


def test_delayed_metadata_uses_observed_start_second_without_inventing_missing_open():
    model = PracticeDesk()
    model.tick_btc(100, 1000.1)
    model.tick_btc(101, 1000.8)
    model.tick_btc(103, 1002)
    model.add_window(Window("known", 1000, 1900))
    model.add_window(Window("missing", 1001, 1901))
    assert model.windows["known"].start_price == 100  # same first tick as eager metadata
    assert model.windows["missing"].start_price is None
    restored = PracticeDesk.from_state(json.loads(json.dumps(model.to_state())))
    restored.add_window(Window("another_known", 1000, 1900))
    assert restored.windows["another_known"].start_price == 100


def test_fee_rounding_and_rebate_from_documented_schedule():
    assert fill_fee(.5, 25, .0695) == .43
    assert fill_fee(.5, 25, -.0125) == -.08
    assert fill_fee(.5, 1, .02) == 0  # exact half cent rounds to even
    assert fill_fee(.5, 3, .02) == .02
    assert reserved_per_share(.5, -.0125) == .5


def test_partial_fee_reservation_bounds_every_fractional_fill():
    for coefficient in (0, .0695, -.0125):
        for size in (.01, .1, .29, .3, .5, 1, 3, 25):
            fee = fill_fee(.5, size, coefficient)
            assert size * .5 + fee <= size * reserved_per_share(.5, coefficient) + 1e-9


def test_first_clip_permitted_but_second_pending_leg_cannot_claim_starter():
    model = desk()
    assert model.place("btc15m", "up", "take", .4, 25, .6, 1010).event == "speeddesk_take"
    assert model.place("btc15m", "down", "take", .4, 25, .6, 1010).reason == "starter_pending"
    assert len(model.orders) == 1


def test_starter_cannot_exceed_one_clip():
    model = desk()
    assert model.can_buy("btc15m", "up", .4, 26, 0) == "starter_clip"


def test_partial_starter_allows_only_current_light_side_then_regular_cap():
    model = desk()
    model.place("btc15m", "up", "rest", .3, 25, .5, 1010)
    refresh(model, 1011)
    events = model.on_trade(Trade("btc15m", "up", .3, 15, 1011, "t1", "sell"))
    assert [event.size for event in events if event.event == "speeddesk_fill"] == [5]
    assert model.can_buy("btc15m", "up", .3, 1, 0) == "balancing_only"
    assert model.can_buy("btc15m", "down", .3, 6, 0) == "balancing_size"
    assert model.can_buy("btc15m", "down", .3, 5, 0) == ""
    model.cancel(1011, reason="test_end_starter")
    model.place("btc15m", "down", "rest", .3, 5, .5, 1011)
    refresh(model, 1012)
    model.on_trade(Trade("btc15m", "down", .3, 15, 1012, "t2", "sell"))
    assert model.inventory["btc15m"].down.shares == 5
    assert model.can_buy("btc15m", "up", .3, 3, 0) == ""
    assert model.can_buy("btc15m", "up", .3, 4, 0) == "imbalance"


def test_imbalance_pending_reservations_cannot_offset_each_other():
    model = desk(seeded=True)
    model.place("btc15m", "up", "rest", .3, 6, .5, 1010)
    assert model.can_buy("btc15m", "up", .3, 1, 0) == "imbalance"
    assert model.can_buy("btc15m", "down", .3, 6, 0) == ""


def test_pair_cap_includes_fees_and_reserves_partial_fee_rounding():
    model = desk(seeded=True)
    model.inventory["btc15m"] = Inventory(Holding(10, 4.9), Holding(10, 4.9))
    assert model.can_buy("btc15m", "up", .5, 1, 0) == ""
    assert model.can_buy("btc15m", "up", .7, 1, .0695) == "pair_cap"
    model.inventory["btc15m"] = Inventory(Holding(10, 4.9), Holding(10, 4.99))
    assert model.can_buy("btc15m", "up", .5, 1, .0695) == "pair_cap"


def test_window_budget_includes_pending_dollars_and_fees():
    model = desk(config=SpeedConfig(window_usd=10, open_usd=20))
    model.windows["btc15m"].taker_coefficient = .0695
    assert model.can_buy("btc15m", "up", .4, 25, .0695) == "window_budget"
    model.place("btc15m", "up", "take", .4, 20, .6, 1010)
    assert model.can_buy("btc15m", "down", .4, 10, .6) == "window_budget"


def test_open_budget_includes_other_windows_and_pending_orders():
    model = desk(config=SpeedConfig(window_usd=20, open_usd=20))
    model.inventory["old"] = Inventory(Holding(30, 15), Holding())
    assert model.can_buy("btc15m", "up", .4, 15, 0) == "open_budget"


@pytest.mark.parametrize("cause", ["cutoff", "bitcoin_stale", "book_stale", "opening_price_missing", "not_started"])
def test_cutoff_and_staleness_prevent_orders_and_cancel_resting(cause):
    model = desk()
    model.place("btc15m", "up", "rest", .3, 5, .5, 1010)
    now = 1011.0
    if cause == "cutoff":
        now = 1840
        refresh(model, now)
    elif cause == "bitcoin_stale":
        now = 1014
    elif cause == "book_stale":
        now = 1014
        model.tick_btc(100, now)
    elif cause == "opening_price_missing":
        model.windows["btc15m"].start_price = None
    else:
        now = 999
    events = model.advance(now)
    assert not model.orders
    assert events[0].reason == cause
    assert model.place("btc15m", "down", "rest", .3, 5, .5, now).reason == cause


def test_taker_waits_delay_and_fills_only_rechecked_same_price_depth():
    clock = FakeClock(1010)
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, clock.now())
    assert model.advance(1010.249) == []
    refresh(model, 1010.25, ask_size=4, sequence="b")
    events = model.advance(1010.25)
    assert len(events) == 1 and events[0].event == "speeddesk_fill"
    assert events[0].size == 4 and events[0].latency_ms == 250
    assert model.inventory["btc15m"].up.shares == 4
    assert not model.orders


def test_taker_will_not_wait_for_disappeared_ask_to_return():
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    refresh(model, 1010.25, ask=.5)
    assert model.advance(1010.25)[0].reason == "ask_moved"
    refresh(model, 1010.5)
    assert model.advance(1010.5) == []
    assert model.inventory["btc15m"].spent == 0


def test_ask_missing_before_delay_rejects_old_decision_before_later_rebound():
    model = desk()
    original = model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    refresh(model, 1010.1, ask=.5)
    assert model.advance(1010.2) == []
    assert model.advance(1010.25)[0].reason == "ask_moved"
    refresh(model, 1010.5)
    assert model.advance(1010.5) == []
    assert model.inventory["btc15m"].spent == 0
    replacement = model.place("btc15m", "up", "take", .4, 10, .6, 1010.5)
    assert replacement.order_id != original.order_id
    assert model.advance(1010.74) == []
    refresh(model, 1010.75)
    event = model.advance(1010.75)[0]
    assert event.event == "speeddesk_fill" and event.order_id == replacement.order_id
    assert event.latency_ms == 250


def test_taker_waits_for_first_async_recheck_and_records_real_latency():
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    assert model.advance(1010.25) == [] and model.orders
    refresh(model, 1010.5)
    events = model.advance(1010.5)
    assert events[0].event == "speeddesk_fill" and events[0].latency_ms == 500
    assert not model.orders


def test_taker_missing_recheck_expires_on_staleness_and_never_backdates_late_book():
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    assert model.advance(1010.25) == []
    assert model.advance(1011) == []
    model.tick_btc(100, 1013.1)
    assert model.advance(1013.1)[0].reason == "book_stale"
    refresh(model, 1014)
    assert model.advance(1014) == [] and not model.orders
    assert model.inventory["btc15m"].spent == 0


def test_taker_late_first_recheck_past_deadline_cannot_fill():
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    refresh(model, 1013.3)
    assert model.advance(1013.3)[0].reason == "latency_recheck_missing"
    assert model.inventory["btc15m"].spent == 0


@pytest.mark.parametrize("source", ["rest", "websocket"])
def test_pre_delay_request_or_exchange_event_is_not_a_post_delay_recheck(source):
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    refresh(model, 1010.5)
    book = model.books[("btc15m", "up")]
    model.on_book(replace(book, source=source, requested_at=1010.2, exchange_at=1010.2))
    assert model.advance(1010.5) == [] and model.orders
    model.on_book(replace(book, source=source, at=1011, requested_at=1010.7, exchange_at=1010.7,
                          asks=(Level(.5, 100),)))
    assert model.advance(1011)[0].reason == "ask_moved"
    refresh(model, 1011.5)
    assert model.advance(1011.5) == []
    assert model.inventory["btc15m"].spent == 0


def test_slow_rest_response_is_stale_even_though_it_just_arrived():
    model = desk()
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    refresh(model, 1011)
    model.on_book(replace(model.books[("btc15m", "up")], source="rest", requested_at=1007.9))
    assert model.advance(1011)[0].reason == "book_stale"
    assert model.inventory["btc15m"].spent == 0


def test_consumed_ask_not_reused_on_unrelated_book_update_or_restart():
    model = desk(config=SpeedConfig(max_imbalance=1, window_usd=100, open_usd=100))
    refresh(model, 1010, ask_size=5)
    model.place("btc15m", "up", "take", .4, 5, .6, 1010)
    refresh(model, 1010.25, ask_size=5, sequence="b")
    model.advance(1010.25)
    refresh(model, 1010.5, ask_size=5, bid=.2, sequence="changed-bid-only")
    assert model.place("btc15m", "up", "take", .4, 1, .6, 1010.5).reason == "ask_depth"
    restored = PracticeDesk.from_state(json.loads(json.dumps(model.to_state())))
    refresh(restored, 1011, ask_size=5, sequence="restart")
    assert restored.place("btc15m", "up", "take", .4, 1, .6, 1011).reason == "ask_depth"
    refresh(restored, 1011.1, ask_size=7, sequence="two-added")
    assert restored.place("btc15m", "up", "take", .4, 2, .6, 1011.1).event == "speeddesk_take"


def test_price_touch_book_update_and_wrong_trade_side_do_not_fill_maker():
    model = desk()
    model.place("btc15m", "up", "rest", .3, 5, .5, 1010)
    refresh(model, 1011, ask=.3)
    assert model.advance(1011) == []
    for direction in ("buy", "unknown"):
        assert model.on_trade(Trade("btc15m", "up", .3, 100, 1011, direction, direction)) == []
    assert model.inventory["btc15m"].spent == 0


def test_maker_queue_consumes_prints_before_fill_and_deduplicates():
    model = desk()
    model.place("btc15m", "up", "rest", .3, 5, .5, 1010)
    refresh(model, 1011)
    assert model.on_trade(Trade("btc15m", "up", .3, 7, 1011, "a", "sell")) == []
    assert model.on_trade(Trade("btc15m", "up", .3, 7, 1011, "a", "sell")) == []
    fill = model.on_trade(Trade("btc15m", "up", .29, 5, 1011.1, "b", "sell"))
    assert len(fill) == 1 and fill[0].size == 2
    assert next(iter(model.orders.values())).remaining == 3
    fill = model.on_trade(Trade("btc15m", "up", .3, 10, 1011.2, "c", "sell"))
    assert fill[0].size == 3 and not model.orders
    summary = model.daily_summary(1011)
    assert summary["fills"] == 2 and summary["maker_fills"] == 1
    assert summary["maker_fill_rate"] == 1 and summary["windows"] == 1


def test_preplacement_delayed_and_future_prints_cannot_fill():
    model = desk()
    model.place("btc15m", "up", "rest", .3, 5, .5, 1010)
    refresh(model, 1011)
    for at in (1009, 1010.1, 1012):
        events = model.on_trade(Trade("btc15m", "up", .3, 100, at, str(at), "sell"), now=1011)
        assert not any(event.event == "speeddesk_fill" for event in events)
    assert model.inventory["btc15m"].spent == 0


def test_maker_unknown_fee_or_crossing_ask_is_blocked():
    model = desk()
    model.windows["btc15m"].maker_coefficient = None
    assert model.place("btc15m", "up", "rest", .3, 5, .5, 1010).reason == "maker_fee_unknown"
    model.windows["btc15m"].maker_coefficient = -.0125
    assert model.place("btc15m", "up", "rest", .4, 5, .5, 1010).reason == "maker_would_cross"


def test_settlement_splits_fee_inclusive_locked_and_directional_profit():
    holdings = Inventory(Holding(10, 4, .17), Holding(6, 2.4, .10))
    result = settlement("btc", holdings, True, 2000)
    assert result.locked_usd == pytest.approx(6 * (1 - .417 - 2.5 / 6))
    assert result.direction_usd == pytest.approx(4 * (1 - .417))
    assert result.pnl_usd == pytest.approx(result.locked_usd + result.direction_usd)
    losing = settlement("btc", holdings, False, 2000)
    assert losing.direction_usd == pytest.approx(-4 * .417)
    assert losing.locked_usd == result.locked_usd


def test_settlement_is_idempotent_venue_outcome_only_and_stops_day():
    model = desk()
    model.inventory["btc15m"] = Inventory(Holding(25, 10), Holding())
    with pytest.raises(ValueError):
        model.settle("btc15m", False, 1800)
    result = model.settle("btc15m", False, 1900)
    assert result is not None and result.pnl_usd == -10
    assert model.settle("btc15m", True, 1901) is None
    model.add_window(Window("next", 1900, 2800, 100))
    assert model.blocked(model.windows["next"], 1901) == "day_stop"
    assert model.daily_summary(1901)["worst_usd"] == -10
    tomorrow = 86400.0
    model.add_window(Window("tomorrow", tomorrow, tomorrow + 900, 100))
    assert model.blocked(model.windows["tomorrow"], tomorrow) != "day_stop"
    assert utc_day(tomorrow) != utc_day(1900)


def test_state_restore_cancels_old_orders_and_preserves_accounting_and_unique_ids():
    model = desk()
    model.place("btc15m", "up", "rest", .3, 5, .5, 1010)
    refresh(model, 1011)
    model.on_trade(Trade("btc15m", "up", .3, 12, 1011, "a", "sell"))
    state = json.loads(json.dumps(model.to_state()))
    restored = PracticeDesk.from_state(state)
    assert not restored.orders
    assert restored.inventory == model.inventory
    assert restored.daily_summary(1011) == model.daily_summary(1011)
    assert restored.next_order_id == model.next_order_id
    assert restored.bootstrap_side == model.bootstrap_side
    state["inventory"]["btc15m"]["up"]["cost"] = math.nan
    with pytest.raises(ValueError):
        PracticeDesk.from_state(state)


def test_out_of_order_or_invalid_book_is_rejected():
    model = desk()
    old = model.books[("btc15m", "up")]
    assert not model.on_book(replace(old, at=1009))
    assert not model.on_book(replace(old, asks=(Level(.4, math.nan),)))
    assert model.books[("btc15m", "up")] == old


def test_full_hour_warmup_with_observed_seconds_coverage_not_synthetic_returns():
    tape = BitcoinTape()
    for second in range(3601):
        if second % 20:  # occasional missing seconds, never forward-filled
            tape.tick(math.exp(second * .001), second)
    assert tape.sigma(3600) is None  # first accepted tick was at second 1
    assert tape.sigma(3601) == pytest.approx(.001)
    for second in range(1000):
        tape.prices.pop(second, None)
    assert tape.sigma(3601) is None


def test_fresh_rest_observation_proves_quiet_book_without_old_event_becoming_fresh_ws():
    model = desk()
    for side in ("up", "down"):
        book = model.books[("btc15m", side)]
        model.on_book(replace(book, exchange_at=900, source="rest"))
    assert model.blocked(model.windows["btc15m"], 1010) == ""
    book = model.books[("btc15m", "up")]
    model.on_book(replace(book, source="websocket"))
    assert model.blocked(model.windows["btc15m"], 1010) == "book_stale"


def warmed(*, maker: bool = False) -> PracticeDesk:
    model = desk(config=SpeedConfig(sigma_min_samples=2, sigma_warmup_s=0, window_usd=100, open_usd=100))
    for second in (1011, 1012, 1013):
        refresh(model, second, ask=.8 if maker else .4)
    return model


def test_strategy_take_threshold_is_after_fee_and_honors_starter_once():
    model = warmed()
    events = model.evaluate(1013)
    assert len(events) == 1 and events[0].event == "speeddesk_take"
    assert events[0].side == "up" and events[0].size == 25
    assert len(model.orders) == 1
    model = warmed()
    model.windows["btc15m"].taker_coefficient = .0695
    refresh(model, 1013, ask=.47)
    # The .03 nominal edge is less than .02 + the taker fee; maker cannot
    # cross that ask and must not claim a maker rebate for a taking order.
    assert not any(event.event == "speeddesk_take" for event in model.evaluate(1013))


def test_strategy_maker_price_and_reprice_threshold():
    model = warmed(maker=True)
    events = model.evaluate(1013)
    rest = next(event for event in events if event.event == "speeddesk_rest")
    assert rest.price == pytest.approx(.47) and rest.side == "up"
    window = model.windows["btc15m"]
    assert model._evaluate_side(window, "up", .51, 1013.1) == []
    events = model._evaluate_side(window, "up", .511, 1013.1)
    assert events[0].reason == "reprice"
    assert events[1].event == "speeddesk_rest" and events[1].price == .48


def test_no_verified_trade_stream_disables_maker_strategy_without_fake_orders():
    model = warmed(maker=True)
    assert model.evaluate(1013, makers_enabled=False) == []
    assert not model.orders
    assert model.last_reason["btc15m"] == "trade_stream_missing"


def test_outstanding_order_and_partial_fees_cannot_overspend_budget():
    model = desk(config=SpeedConfig(window_usd=11, open_usd=11))
    model.windows["btc15m"].maker_coefficient = .0695
    event = model.place("btc15m", "up", "rest", .3, 25, .5, 1010)
    assert event.event == "speeddesk_rest"
    refresh(model, 1011)
    model.on_trade(Trade("btc15m", "up", .3, 10, 1011, "queue", "sell"))
    for index in range(50):
        model.on_trade(Trade("btc15m", "up", .3, .5, 1011 + index / 100, str(index), "sell"))
        outstanding = sum(order.reserved for order in model.orders.values())
        assert model.inventory["btc15m"].spent + outstanding <= 11
    assert model.inventory["btc15m"].up.shares == 25
    assert model.inventory["btc15m"].up.fees == pytest.approx(.5)


def test_settled_windows_release_only_practice_open_budget():
    model = desk(config=SpeedConfig(window_usd=20, open_usd=20))
    model.inventory["btc15m"] = Inventory(Holding(25, 10), Holding())
    model.add_window(Window("second", 1900, 2800, 100))
    assert model.can_buy("second", "up", .5, 25, 0) == "open_budget"
    model.settle("btc15m", True, 1900)
    assert model.can_buy("second", "up", .5, 25, 0) == ""


def test_best_fee_adjusted_take_starts_first_instead_of_always_up():
    model = warmed()
    down = model.books[("btc15m", "down")]
    model.on_book(replace(down, asks=(Level(.35, 100),)))
    events = model.evaluate(1013)
    assert events[0].event == "speeddesk_take" and events[0].side == "down"
    assert len(model.orders) == 1


def test_fractional_depth_is_traded_and_partial_inventory_can_balance():
    model = warmed()
    refresh(model, 1013, ask_size=.55)
    events = model.evaluate(1013)
    assert events[0].size == .55
    refresh(model, 1013.25, ask_size=.55, sequence="recheck")
    model.advance(1013.25)
    refresh(model, 1013.5, ask_size=.55, sequence="next")
    events = model.evaluate(1013.5)
    assert next(event for event in events if event.event == "speeddesk_take").side == "down"
    assert next(event for event in events if event.event == "speeddesk_take").size == .55


def test_new_taker_opportunity_replaces_resting_bid_even_without_fair_move():
    model = warmed(maker=True)
    model.evaluate(1013)
    refresh(model, 1013.1, ask=.4)
    events = model.evaluate(1013.1)
    assert events[0].reason == "take_available"
    assert events[1].event == "speeddesk_take"
    assert len(model.orders) == 1


def test_maker_permission_is_per_window_and_revocation_cancels_existing_rest():
    model = warmed(maker=True)
    assert model.evaluate(1013, maker_windows=set()) == []
    assert not model.orders
    model.evaluate(1013, maker_windows={"btc15m"})
    assert len(model.orders) == 1
    events = model.evaluate(1013.1, maker_windows=set())
    assert events[0].reason == "trade_stream_missing"
    assert not model.orders


def test_kalshi_current_fee_rounds_position_plus_fee_to_centicent():
    # .05555 position cost plus .0034957615 raw fee rounds .0590457615 up to
    # .0591 total. Rounding only the fee, or to a cent, would be incorrect.
    assert fill_fee(.101, .55, .07, "kalshi") == pytest.approx(.00355)
    assert fill_fee(.101, .55, 0, "kalshi") == 0
    assert fill_fee(.5, 25, .07, "kalshi") == .4375
    assert fill_fee(.5, 25, .0695) == .43


def test_kalshi_reservations_cover_centicent_partial_fees_and_survive_restart():
    model = desk(config=SpeedConfig(window_usd=20, open_usd=20))
    model.windows["btc15m"].fee_rounding = "kalshi"
    model.windows["btc15m"].venue = "kalshi"
    model.windows["btc15m"].taker_coefficient = .07
    for price in (.001, .1, .501, .999):
        for quantity in (.01, .03, .55, 25):
            actual = price * quantity + fill_fee(price, quantity, .07, "kalshi")
            assert actual <= quantity * reserved_per_share(price, .07, "kalshi", .01) + 1e-9
    model.place("btc15m", "up", "take", .4, 10, .6, 1010)
    assert next(iter(model.orders.values())).fee_rounding == "kalshi"
    refresh(model, 1010.25, sequence="later")
    events = model.advance(1010.25)
    assert events[0].fee_usd == fill_fee(.4, 10, .07, "kalshi")
    restored = PracticeDesk.from_state(json.loads(json.dumps(model.to_state())))
    assert restored.windows["btc15m"].fee_rounding == "kalshi"
    assert restored.inventory == model.inventory


def test_multiday_history_is_preserved_without_reconsidering_every_closed_window(monkeypatch):
    model = desk()
    for index in range(1000):
        name = f"settled-{index}"
        model.add_window(Window(name, 0, 900, 100))
        model.closed.append(settlement(name, Inventory(), True, 900))
    checked = []
    original = model.blocked

    def count(window, now):
        checked.append(window.slug)
        return original(window, now)

    monkeypatch.setattr(model, "blocked", count)
    model.evaluate(1010)
    assert checked == ["btc15m", "btc15m"]
    state = model.to_state()
    assert len(state["closed"]) == 1000
    assert len(state["windows"]) == 1001
    assert len(state["inventory"]) == 1001


def both_venues() -> PracticeDesk:
    model = desk()
    model.add_window(Window("kalshi15m", 1000, 1900, 100, taker_coefficient=0,
                            maker_coefficient=0, venue="kalshi"))
    refresh_both(model, 1010)
    return model


def refresh_both(model: PracticeDesk, now: float) -> None:
    refresh(model, now)
    for side in ("up", "down"):
        model.on_book(replace(model.books[("btc15m", side)], window="kalshi15m"))


def trade_both_venues() -> PracticeDesk:
    model = both_venues()
    model.place("btc15m", "up", "take", .4, 5, .6, 1010)
    refresh_both(model, 1010.25)
    model.advance(1010.25)
    model.place("btc15m", "down", "take", .4, 5, .6, 1010.25)
    refresh_both(model, 1010.5)
    model.advance(1010.5)
    model.place("kalshi15m", "up", "rest", .3, 5, .5, 1010.5)
    refresh_both(model, 1011)
    model.on_trade(Trade("kalshi15m", "up", .3, 15, 1011, "up-fill", "sell"))
    model.place("kalshi15m", "down", "rest", .3, 3, .5, 1011)
    refresh_both(model, 1011.5)
    model.on_trade(Trade("kalshi15m", "down", .3, 13, 1011.5, "down-fill", "sell"))
    return model


def legacy_state(model: PracticeDesk) -> dict:
    state = json.loads(json.dumps(model.to_state()))
    for name in ("venue_reporting_version", "venue_days", "venue_incomplete_days",
                 "venue_filled_orders", "window_venues"):
        state.pop(name)
    return state


def test_daily_counters_and_settlements_are_attributed_to_their_actual_venue():
    model = trade_both_venues()
    model.settle("btc15m", True, 1900)
    model.settle("kalshi15m", True, 1900)
    us = model.daily_summary(1900, "polymarket_us")
    kalshi = model.daily_summary(1900, "kalshi")
    total = model.daily_summary(1900)
    assert us["windows"] == kalshi["windows"] == 1
    assert us["fills"] == kalshi["fills"] == 2
    assert us["take_attempts"] == us["take_fills"] == 2
    assert us["maker_orders"] == us["maker_fills"] == 0
    assert kalshi["take_attempts"] == kalshi["take_fills"] == 0
    assert kalshi["maker_orders"] == kalshi["maker_fills"] == 2
    assert us["take_fill_rate"] == kalshi["maker_fill_rate"] == 1
    assert us["avg_latency_ms"] == 250 and kalshi["avg_latency_ms"] == 500
    assert us["pnl_usd"] == pytest.approx(1)
    assert kalshi["locked_usd"] == pytest.approx(1.2)
    assert kalshi["directional_usd"] == pytest.approx(1.4)
    assert us["worst_usd"] == pytest.approx(1)
    assert kalshi["worst_usd"] == pytest.approx(2.6)
    for metric in ("windows", "settled_windows", "fills", "locked_usd", "directional_usd", "pnl_usd", "won", "lost"):
        assert us[metric] + kalshi[metric] == pytest.approx(total[metric])
    assert us["reporting_complete"] and kalshi["reporting_complete"]
    assert us["fill_rate_basis"] == "orders_placed_on_day"


def test_separate_reports_do_not_split_or_increase_combined_risk_caps():
    model = both_venues()
    model.config = replace(model.config, open_usd=6)
    assert model.place("btc15m", "up", "take", .4, 10, .6, 1010).event == "speeddesk_take"
    assert model.place("kalshi15m", "up", "take", .4, 10, .6, 1010).reason == "open_budget"
    assert model.daily_summary(1010, "polymarket_us")["take_attempts"] == 1
    assert model.daily_summary(1010, "kalshi")["take_attempts"] == 0
    assert model.daily_summary(1010)["take_attempts"] == 1


def test_venue_reports_survive_restart_without_reclassifying_window_metadata():
    model = trade_both_venues()
    model.add_window(replace(model.windows["kalshi15m"], venue="polymarket_us"))
    model.settle("kalshi15m", False, 1900)
    expected = {venue: model.daily_summary(1900, venue) for venue in ("polymarket_us", "kalshi")}
    restored = PracticeDesk.from_state(json.loads(json.dumps(model.to_state())))
    assert restored.window_venues["kalshi15m"] == "kalshi"
    for venue, summary in expected.items():
        assert restored.daily_summary(1900, venue) == summary
    assert expected["kalshi"]["settled_windows"] == 1
    assert expected["polymarket_us"]["settled_windows"] == 0


def test_midnight_fill_rates_follow_placement_cohort_while_fills_follow_execution_day():
    model = PracticeDesk(SpeedConfig(window_usd=100, open_usd=100))
    model.add_window(Window("cross-midnight", 86380, 87280, 100, maker_coefficient=0, venue="kalshi"))

    def fresh(now):
        model.tick_btc(100, now)
        for side in ("up", "down"):
            model.on_book(Book("cross-midnight", side, (Level(.3, 10),), (Level(.4, 100),), now, str(now)))

    fresh(86399)
    model.place("cross-midnight", "up", "rest", .3, 5, .5, 86399)
    before = model.daily_summary(86399, "kalshi")
    assert before["maker_orders"] == 1 and before["maker_fill_rate"] == 0
    fresh(86400.5)
    model.on_trade(Trade("cross-midnight", "up", .3, 12, 86400.5, "first", "sell"))
    fresh(86401)
    model.on_trade(Trade("cross-midnight", "up", .3, 3, 86401, "second", "sell"))
    yesterday = model.daily_summary(86399, "kalshi")
    today = model.daily_summary(86401, "kalshi")
    assert yesterday["maker_fills"] == yesterday["maker_orders"] == 1
    assert yesterday["maker_fill_rate"] == 1 and yesterday["fills"] == 0
    assert today["fills"] == 2 and today["windows"] == 1
    assert today["maker_orders"] == today["maker_fills"] == 0
    assert today["maker_fill_rate"] is None and today["avg_latency_ms"] == 1750
    assert model.daily_summary(86401)["maker_fills"] == 1  # existing aggregate semantics
    restored = PracticeDesk.from_state(json.loads(json.dumps(model.to_state())))
    assert restored.daily_summary(86399, "kalshi") == yesterday
    assert restored.daily_summary(86401, "kalshi") == today


def test_zero_activity_legacy_warmup_migrates_to_exact_zero_venue_reports():
    state = legacy_state(both_venues())
    state["days"] = {utc_day(1010): {"fills": 0, "pnl_usd": 0, "take_orders": 0, "rest_orders": 0}}
    restored = PracticeDesk.from_state(state)
    for venue in ("polymarket_us", "kalshi"):
        report = restored.daily_summary(1010, venue)
        assert report["reporting_complete"]
        assert report["fills"] == report["take_attempts"] == report["maker_orders"] == report["pnl_usd"] == 0
        assert report["worst_usd"] is None and report["avg_latency_ms"] is None
    assert not restored.venue_incomplete_days


def test_legacy_activity_never_becomes_invented_venue_attempts_or_latency():
    model = trade_both_venues()
    model.settle("btc15m", True, 1900)
    aggregate = model.daily_summary(1900)
    restored = PracticeDesk.from_state(legacy_state(model))
    assert restored.daily_summary(1900) == aggregate
    for venue in ("polymarket_us", "kalshi"):
        report = restored.daily_summary(1900, venue)
        assert report["day"] == utc_day(1900) and report["venue"] == venue
        assert not report["reporting_complete"]
        for key in aggregate:
            if key != "day":
                assert report[key] is None
    again = PracticeDesk.from_state(json.loads(json.dumps(restored.to_state())))
    assert again.daily_summary(1900, "kalshi") == restored.daily_summary(1900, "kalshi")
    assert again.daily_summary(86401, "kalshi")["reporting_complete"]
    assert again.daily_summary(86401, "kalshi")["fills"] == 0


def test_legacy_outstanding_attempt_is_unknown_even_before_any_fill():
    model = both_venues()
    model.place("kalshi15m", "up", "rest", .3, 5, .5, 1010)
    state = legacy_state(model)
    state["days"] = {}  # missing old counters cannot turn that surviving order into zero activity
    restored = PracticeDesk.from_state(state)
    assert not restored.daily_summary(1010, "kalshi")["reporting_complete"]
    assert not restored.orders  # normal restart cancellation still applies


def test_unknown_venue_activity_is_never_assigned_to_a_known_venue():
    model = desk()
    model.add_window(Window("unknown", 1000, 1900, 100, maker_coefficient=0, venue="unidentified"))
    for side in ("up", "down"):
        model.on_book(replace(model.books[("btc15m", side)], window="unknown"))
    model.place("unknown", "up", "rest", .3, 5, .5, 1010)
    assert model.daily_summary(1010)["maker_orders"] == 1
    assert set(model.venue_days) == {"polymarket_us", "kalshi"}
    for venue in model.venue_days:
        report = model.daily_summary(1010, venue)
        assert not report["reporting_complete"] and report["maker_orders"] is None
    with pytest.raises(ValueError):
        model.daily_summary(1010, "unidentified")


def test_incomplete_new_reporting_state_fails_closed_instead_of_returning_false_zero():
    state = both_venues().to_state()
    state.pop("venue_days")
    with pytest.raises(KeyError):
        PracticeDesk.from_state(state)
