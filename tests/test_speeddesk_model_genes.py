"""The practice speed desk's opt-in arena fields: every default keeps today's behaviour exactly."""

from __future__ import annotations

import json
import math
import random
import threading
import time
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from speeddesk_golden import FIXTURE, coverage, run

from nightcrawler import speeddesk_live_model, speeddesk_model
from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_model import (
    LOCK_MARGIN_S,
    OPT_IN_FIELDS,
    Book,
    Holding,
    Inventory,
    Level,
    PracticeDesk,
    SpeedConfig,
    Trade,
    Window,
    config_state,
    utc_day,
)

# What the pinned run must exercise, so the golden comparison means something.
COVERED = ("speeddesk_take:take", "speeddesk_fill:take", "speeddesk_rest:rest", "speeddesk_fill:rest",
           "speeddesk_cancel:reprice", "speeddesk_cancel:take_available", "speeddesk_cancel:ask_moved",
           "speeddesk_cancel:venue_feed_gap", "speeddesk_skip:maker_would_cross", "reason:balancing_only",
           "reason:starter_pending", "reason:window_budget", "reason:cutoff", "reason:day_stop", "settlement:")
DEFAULTS = {item.name: item.default for item in fields(SpeedConfig)}
SLUG = "KXBTC15M-genes"
START = 1_791_475_200.0
END = START + 900


def _first_difference(actual: dict[str, Any], expected: dict[str, Any]) -> str:
    for index, (got, want) in enumerate(zip(actual["events"], expected["events"], strict=False)):
        if got != want:
            return f"event {index}: {got} != {want}"
    if len(actual["events"]) != len(expected["events"]):
        return f"{len(actual['events'])} events, pinned {len(expected['events'])}"
    keys = [key for key in expected["state"] if actual["state"].get(key) != expected["state"][key]]
    return f"state differs in {keys}"


def kdesk(**changes: Any) -> PracticeDesk:
    """A Kalshi-like practice desk on the live limits, with a fed volatility (no hour of warm-up)."""
    config = SpeedConfig(**{"take_edge": 1.0, "make_edge": 0.03, "clip": 5, "window_usd": 10, "open_usd": 20,
                            "day_stop_usd": 6, "cutoff_s": 240, "whole_contracts": True, **changes})
    desk = PracticeDesk(config)
    desk.tape.sigma = lambda *_args: 0.0003  # type: ignore[method-assign]
    desk.add_window(Window(SLUG, START, END, None, taker_coefficient=0.07, maker_coefficient=0.0,
                           venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi"))
    return desk


def quote(desk: PracticeDesk, now: float, *, up: float = 0.6, down: float = 0.6, size: float = 50) -> None:
    desk.tick_btc(80_000, now)
    for side, ask in (("up", up), ("down", down)):
        desk.on_book(Book(SLUG, side, (Level(round(ask - 0.2, 2), 10),), (Level(ask, size),),  # type: ignore[arg-type]
                          now, f"{side}-{now}", now))


def hold(desk: PracticeDesk, up: float, down: float, price: float = 0.45) -> None:
    desk.inventory[SLUG] = Inventory(Holding(up, up * price), Holding(down, down * price))


def sell(desk: PracticeDesk, side: str, price: float, size: float, now: float) -> list[Any]:
    return desk.on_trade(Trade(SLUG, side, price, size, now, f"print-{side}-{now}", "sell", now), now)  # type: ignore[arg-type]


def orders(desk: PracticeDesk) -> list[tuple[str, str, float, bool]]:
    return sorted((order.side, order.kind, order.size, order.lock) for order in desk.orders.values())


# ---------------------------------------------------------------------- defaults are today's desk
def test_default_config_reproduces_the_pinned_run() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = run(SpeedConfig())
    counts = coverage(actual)
    assert all(counts.get(key) for key in COVERED), sorted(counts)
    assert actual == expected, _first_difference(actual, expected)


def test_explicit_default_values_reproduce_the_pinned_run_too() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    explicit = SpeedConfig(**{name: DEFAULTS[name] for name in OPT_IN_FIELDS})
    assert run(explicit) == expected


def test_saved_state_leaves_out_default_opt_in_fields_and_old_states_load() -> None:
    desk = PracticeDesk()
    state = desk.to_state()
    assert not set(OPT_IN_FIELDS) & set(state["config"])
    old = json.loads(FIXTURE.read_text(encoding="utf-8"))["state"]  # written before these fields existed
    assert not set(OPT_IN_FIELDS) & set(old["config"])
    restored = PracticeDesk.from_state(old)
    assert restored.config == SpeedConfig(**old["config"]) == SpeedConfig()
    changed = SpeedConfig(starter_clip=3, rounds=True, lock_s=240, stop_s=600, stop_pair_cost=1.1)
    saved = config_state(changed)
    assert saved["starter_clip"] == 3 and saved["rounds"] is True and "starter_delay_s" not in saved
    assert SpeedConfig(**saved) == changed
    assert PracticeDesk.from_state(json.loads(json.dumps(PracticeDesk(changed).to_state()))).config == changed


@pytest.mark.parametrize("changes", [{"lock_max_price": 0}, {"lock_max_price": 1.0}, {"lock_s": 900},
                                     {"stop_s": 900}, {"stop_pair_cost": 1.0}, {"stop_pair_cost": 2.5},
                                     {"starter_clip": -1}])
def test_opt_in_fields_are_validated(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SpeedConfig(**changes)


def test_the_live_twin_and_the_practice_desk_run_on_the_defaults(tmp_path: Path) -> None:
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=FakeClock())
    try:
        assert runner.live is not None
        for config in (runner.desk.config, runner.live.twin.config):
            assert all(getattr(config, name) == DEFAULTS[name] for name in OPT_IN_FIELDS)
        assert runner.desk.starter_gate is None and runner.live.twin.starter_gate is None
    finally:
        runner.close()


def test_lock_margin_is_the_live_companions() -> None:
    assert LOCK_MARGIN_S == speeddesk_live_model.LOCK_MARGIN_S


def test_the_worst_case_over_pending_legs_is_the_live_risk_books() -> None:
    """With the live rules on, the practice desk's money at risk is LiveRiskBook._worst, leg for leg (loss plan
    bug 1: a balancing bid or a lock adds nothing, a first buy adds all of its cost); same legs cap."""
    assert speeddesk_model.MAX_LEGS == speeddesk_live_model.MAX_LEGS
    rng = random.Random(20261014)
    for _ in range(2000):
        inventory = Inventory(Holding(rng.choice((0, 2, 5, 8)), round(rng.uniform(0, 4), 2)),
                              Holding(rng.choice((0, 2, 5, 8)), round(rng.uniform(0, 4), 2)))
        legs = [(rng.choice(("up", "down")), rng.choice((1, 3, 5)), round(rng.uniform(0.3, 3.0), 4))
                for _ in range(rng.randint(0, 3))]
        assert (PracticeDesk._worst(inventory, legs)  # type: ignore[arg-type]
                == speeddesk_live_model.LiveRiskBook._worst(inventory, legs))  # type: ignore[arg-type]
    legs = [("up", 1.0, 0.5)] * (speeddesk_model.MAX_LEGS + 1)
    inventory = Inventory(Holding(5, 2.0), Holding(0, 0.0))
    assert (PracticeDesk._worst(inventory, legs)  # type: ignore[arg-type]
            == speeddesk_live_model.LiveRiskBook._worst(inventory, legs) == 2.0 + 5.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- the starter
def test_starter_clip_sizes_the_first_buy_and_balancing_uses_the_clip() -> None:
    desk = kdesk(starter_clip=8)
    quote(desk, START + 10)
    desk.evaluate(START + 10)
    assert orders(desk) == [("up", "rest", 8.0, False)]  # the starter, above the 5-contract clip
    sell(desk, "up", 0.47, 20, START + 11)
    assert desk.inventory[SLUG].up.shares == 8
    quote(desk, START + 12)
    desk.evaluate(START + 12)
    assert orders(desk) == [("down", "rest", 5.0, False)]  # balancing: the clip


def test_starter_timing_blocks_starters_only() -> None:
    desk = kdesk(starter_delay_s=30)
    quote(desk, START + 10)
    desk.evaluate(START + 10)
    assert not desk.orders and desk.last_reason[SLUG] == "starter_wait"
    quote(desk, START + 31)
    desk.evaluate(START + 31)
    assert orders(desk) == [("up", "rest", 5.0, False)]

    late = kdesk(starter_stop_s=600)
    quote(late, END - 610)
    late.evaluate(END - 610)
    assert orders(late) == [("up", "rest", 5.0, False)]  # before the stop: a starter
    late.cancel(END - 601)
    quote(late, END - 590)
    late.evaluate(END - 590)
    assert not late.orders and late.last_reason[SLUG] == "starter_late"
    hold(late, 3, 0)
    late.evaluate(END - 590)
    assert orders(late) == [("down", "rest", 3.0, False)]  # balancing is never held


def test_rounds_allow_a_fresh_starter_after_a_complete_pair() -> None:
    plain = kdesk()
    hold(plain, 5, 5)
    quote(plain, START + 100)
    plain.evaluate(START + 100)
    assert orders(plain) == [("down", "rest", 3.0, False), ("up", "rest", 3.0, False)]  # imbalance-limited growth

    desk = kdesk(rounds=True)
    hold(desk, 5, 5)
    quote(desk, START + 100)
    desk.evaluate(START + 100)
    assert orders(desk) == [("up", "rest", 5.0, False)]  # one starter-size buy, nothing else
    sell(desk, "up", 0.47, 20, START + 101)
    assert desk.inventory[SLUG].up.shares == 10
    quote(desk, START + 102)
    desk.evaluate(START + 102)
    assert orders(desk) == [("down", "rest", 5.0, False)]  # then balancing only
    assert desk.can_buy(SLUG, "up", 0.47, 1, 0.0) == "balancing_only"


def test_whole_contracts_size_every_order_in_whole_contracts() -> None:
    fractional = kdesk(whole_contracts=False, window_usd=2.2)
    whole = kdesk(window_usd=2.2)
    for desk in (fractional, whole):
        quote(desk, START + 10)
        desk.evaluate(START + 10)
    assert orders(fractional) == [("up", "rest", 4.68, False)]
    assert orders(whole) == [("up", "rest", 4.0, False)]


def test_starter_gate_blocks_starters_only_and_none_is_todays_desk() -> None:
    desk = kdesk()
    desk.starter_gate = lambda window, now: "filter_says_no" if window.slug == SLUG else ""
    quote(desk, START + 10)
    desk.evaluate(START + 10)
    assert not desk.orders and desk.last_reason[SLUG] == "filter_says_no"
    hold(desk, 3, 0)
    desk.evaluate(START + 10)
    assert orders(desk) == [("down", "rest", 3.0, False)]
    desk.starter_gate = None
    open_desk = kdesk()
    quote(open_desk, START + 10)
    open_desk.evaluate(START + 10)
    assert orders(open_desk) == [("up", "rest", 5.0, False)]


# ---------------------------------------------------------------------- the lock and the stop
def test_lock_completes_the_unpaired_side_at_the_ask_past_every_buying_limit() -> None:
    desk = kdesk(lock_s=240, day_stop_usd=1)
    hold(desk, 5, 0)
    desk.days[utc_day(END - 200)] = {"pnl_usd": -50.0}  # far past the day stop
    quote(desk, END - 200, down=0.62)
    assert desk.blocked(desk.windows[SLUG], END - 200) == "cutoff"
    events = desk.evaluate(END - 200)
    assert [(event.event, event.reason) for event in events if event.event == "speeddesk_lock"] == [
        ("speeddesk_lock", "lock")]
    assert orders(desk) == [("down", "take", 5.0, True)]  # pair cost 0.45 + 0.62 > 0.99: a buy could not
    desk.advance(END - 199.9)
    assert orders(desk) == [("down", "take", 5.0, True)]  # it survives the cutoff's cancel
    quote(desk, END - 199.7, down=0.62)
    desk.advance(END - 199.7)
    assert desk.inventory[SLUG].down.shares == 5 and not desk.orders
    day = desk.days[utc_day(END - 200)]
    assert day["lock_filled_orders"] == 1 and day["lock_orders"] == 1 and "take_filled_orders" not in day


def test_lock_respects_its_price_cap_margin_depth_clip_and_fresh_books() -> None:
    def locked(**kwargs: Any) -> list[tuple[str, str, float, bool]]:
        desk = kdesk(lock_s=240)
        hold(desk, kwargs.pop("up", 5), 0)
        at = kwargs.pop("at", END - 200)
        quote(desk, kwargs.pop("quoted", at), down=kwargs.pop("ask", 0.62), size=kwargs.pop("size", 50))
        desk.evaluate(at)
        return [order for order in orders(desk) if order[3]]

    assert locked() == [("down", "take", 5.0, True)]
    assert locked(ask=0.98) == []  # above lock_max_price: the window is decided, left as it is
    assert locked(at=END - LOCK_MARGIN_S + 1) == []  # never this close to the close
    assert locked(at=END - 300) == []  # not lock time yet
    assert locked(size=3) == [("down", "take", 3.0, True)]  # only the depth shown
    assert locked(up=8) == [("down", "take", 5.0, True)]  # at most the clip at a time
    assert locked(up=0.6) == []  # no whole contract unpaired
    assert locked(quoted=END - 205) == []  # stale books: no lock


def test_lock_waits_for_a_pending_take_and_fills_immediate_or_cancel() -> None:
    desk = kdesk(lock_s=240)
    hold(desk, 5, 0)
    quote(desk, END - 200, down=0.62, size=3)
    desk.evaluate(END - 200)
    assert orders(desk) == [("down", "take", 3.0, True)]
    desk.evaluate(END - 199.9)
    assert orders(desk) == [("down", "take", 3.0, True)]  # one lock at a time
    quote(desk, END - 199.7, down=0.62, size=2)
    desk.advance(END - 199.7)
    assert desk.inventory[SLUG].down.shares == 2 and not desk.orders  # the rest is dropped (IOC)
    quote(desk, END - 199, down=0.62, size=50)
    desk.evaluate(END - 199)
    assert orders(desk) == [("down", "take", 3.0, True)]  # the next lock takes what is still unpaired


def test_stop_completes_early_only_once_completing_costs_its_trigger() -> None:
    desk = kdesk(stop_s=600, stop_pair_cost=1.10)
    hold(desk, 5, 0)
    quote(desk, END - 500, down=0.60)  # 0.45 + 0.60 + fee 0.0168 = 1.067: below the trigger
    desk.evaluate(END - 500)
    assert all(not order.lock for order in desk.orders.values())
    assert orders(desk) == [("down", "rest", 5.0, False)]  # an ordinary balancing bid
    quote(desk, END - 499, down=0.66)  # 0.45 + 0.66 + 0.0157 = 1.126: the stop fires
    events = desk.evaluate(END - 499)
    assert ("speeddesk_cancel", "stop") in [(event.event, event.reason) for event in events]
    assert orders(desk) == [("down", "take", 5.0, True)]
    early = kdesk(stop_s=600, stop_pair_cost=1.10)
    hold(early, 5, 0)
    quote(early, END - 700, down=0.70)
    early.evaluate(END - 700)
    assert all(not order.lock for order in early.orders.values())  # not stop time yet
    off = kdesk()
    hold(off, 5, 0)
    quote(off, END - 200, down=0.70)
    off.evaluate(END - 200)
    assert not off.orders  # off by default: no lock and no stop


# ---------------------------------------------------------------------- forgetting settled windows
def test_forget_drops_only_settled_or_void_windows_without_orders() -> None:
    desk = kdesk()
    quote(desk, START + 10)
    desk.evaluate(START + 10)
    with pytest.raises(ValueError):
        desk.forget(SLUG)  # open
    with pytest.raises(ValueError):
        desk.forget(SLUG, void=True)  # orders still pending
    desk.cancel(END, SLUG, "settled")
    desk.settle(SLUG, True, END)
    desk.forget(SLUG)
    assert SLUG not in desk.windows and SLUG not in desk.inventory and not desk.closed
    assert not any(key[0] == SLUG for key in desk.books) and SLUG not in desk.last_reason
    assert SLUG not in desk.bootstrap_order and SLUG not in desk.window_venues
    void = kdesk()
    void.forget(SLUG, void=True)
    assert not void.windows


# ---------------------------------------------------------------------- the live risk book's rules (review 2026-10-13)
def _twins(seed: int) -> tuple[PracticeDesk, speeddesk_live_model.LiveRiskBook, float]:
    """The same random state in a practice desk with the live rules switched on and in the live risk book: an older
    unsettled window and the current one, random holdings, a pending bid or not, a random day so far."""
    rng = random.Random(seed)
    now = START + 120
    practice = kdesk(day_stop_counts_risk=True, hedged_open_budget=True, open_usd=10)
    book = speeddesk_live_model.LiveRiskBook(speeddesk_live_model.LiveLimits(
        window_usd=10, open_usd=10, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=0.0001))
    older = "KXBTC15M-older"
    for slug, start in ((older, START - 900), (SLUG, START)):
        window = Window(slug, start, start + 900, None, taker_coefficient=0.07, maker_coefficient=0.0,
                        venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
        if slug != SLUG:
            practice.add_window(window)
        book.add_window(Window(**window.__dict__))
    book.update_cash(50.0, now)
    for slug in (older, SLUG):
        up, down = rng.choice((0, 2, 4, 5, 8)), rng.choice((0, 2, 4, 5, 8))
        price_up, price_down = rng.choice((0.3, 0.45, 0.6)), rng.choice((0.3, 0.45, 0.6))
        for inventory in (practice.inventory, book.inventory):
            inventory[slug] = Inventory(Holding(up, up * price_up), Holding(down, down * price_down))
    if rng.random() < 0.5:
        slug, side, size, price = rng.choice((older, SLUG)), rng.choice(("up", "down")), rng.choice((1, 3, 5)), 0.4
        practice.orders[99] = speeddesk_model.PracticeOrder(99, slug, side, "rest", price, size, size, now - 5,  # type: ignore[arg-type]
                                                            now - 4.75, 0.45, 0.0, 0.0, "", "kalshi", 0.01)
        book.intents["nc-speed-x"] = speeddesk_live_model.LiveIntent(
            "nc-speed-x", slug, side, "rest", price, size, now - 5, book.unit_reserve(slug, price, "rest"))  # type: ignore[arg-type]
    day = rng.choice((0.0, -1.0, -3.0, -4.0, -5.5, 2.0))
    practice.days[utc_day(now)] = {"pnl_usd": day}
    book.day_pnl[utc_day(now)] = day
    return practice, book, now


def test_the_live_stops_and_open_budget_match_the_live_risk_book() -> None:
    """The review's probe and a sweep: with the two fields on, every budget answer (window, open, day stop) of the
    practice desk is the live risk book's, for every size of a resting bid."""
    budgets = {"window_budget", "open_budget", "day_stop"}
    # place() checks these in practice; live's lifetime total stop is deliberately not copied (kalshi_arena).
    before_budgets = {"order_pending", "clip", "cutoff", "invalid_order", "cash_stale", "total_loss", "halted"}
    compared = seen = 0
    for seed in range(400):
        practice, book, now = _twins(seed)
        for side in ("up", "down"):
            for size in range(1, 6):
                live = book.can_buy(SLUG, side, "rest", 0.45, size, now)  # type: ignore[arg-type]
                ours = practice.can_buy(SLUG, side, 0.45, size, 0.0, now)  # type: ignore[arg-type]
                if live in before_budgets:
                    continue
                compared += 1
                if live in budgets or ours in budgets:
                    assert ours == live, (seed, side, size, ours, live)
                    seen += 1
    assert compared > 3000 and seen > 400  # the sweep reaches each budget often
    # The probe itself: after a $4 morning a 5-lot at 0.45 is refused live; the old practice rule rested it.
    old = kdesk()
    old.days[utc_day(START + 30)] = {"pnl_usd": -4.0}
    assert old.can_buy(SLUG, "up", 0.45, 5, 0.0, START + 30) == ""
    new = kdesk(day_stop_counts_risk=True)
    new.days[utc_day(START + 30)] = {"pnl_usd": -4.0}
    assert new.can_buy(SLUG, "up", 0.45, 5, 0.0, START + 30) == "day_stop"
    assert new.can_buy(SLUG, "up", 0.45, 4, 0.0, START + 30) == ""  # 4 + 1.80 < 6, as live allows 4
    quote(new, START + 30)
    new.evaluate(START + 30)
    assert orders(new) == [("up", "rest", 4.0, False)]


def test_a_complete_pair_risks_nothing_against_the_open_budget() -> None:
    older = "KXBTC15M-older"

    def desk(**changes: Any) -> PracticeDesk:
        made = kdesk(open_usd=10, **changes)
        made.add_window(Window(older, START - 900, START, None, taker_coefficient=0.07, maker_coefficient=0.0,
                               venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi"))
        made.inventory[older] = Inventory(Holding(10, 4.75), Holding(10, 4.75))  # a $9.50 pair, unsettled
        return made

    assert desk().can_buy(SLUG, "up", 0.45, 5, 0.0) == "open_budget"  # gross spend: 9.50 + 2.25 > 10
    assert desk(hedged_open_budget=True).can_buy(SLUG, "up", 0.45, 5, 0.0) == ""  # at risk: 0 + 2.25


def test_resting_bids_expire_after_thirty_seconds_and_queue_again() -> None:
    def books(desk: PracticeDesk, at: float, queue: float) -> None:
        desk.tick_btc(80_000, at)
        for side in ("up", "down"):  # a bid queue at the desk's resting price (fair 0.50 - edge 0.03)
            desk.on_book(Book(SLUG, side, (Level(0.47, queue),), (Level(0.6, 50),), at, f"{side}-{at}", at))  # type: ignore[arg-type]

    desk = kdesk(rest_ttl_s=30)
    placed = START + 10.6
    books(desk, placed, 10)
    desk.evaluate(placed)
    (order,) = desk.orders.values()
    assert order.queue_ahead == 10  # the bid shown at its price, from the book of the moment
    expires = math.floor(placed) + 30  # live: expiration_ts = int(now) + 30
    books(desk, expires + 0.05, 10)  # fresh feeds: nothing else cancels it
    events = sell(desk, "up", order.price, 3, expires + 0.1)
    assert not [event for event in events if event.event == "speeddesk_fill"] and order.queue_ahead == 10
    books(desk, expires + 0.2, 4)
    events = desk.evaluate(expires + 0.2)
    assert ("speeddesk_cancel", "expired") in [(event.event, event.reason) for event in events]
    (fresh,) = desk.orders.values()
    assert fresh.order_id != order.order_id and fresh.queue_ahead == 4  # behind the book again
    before = kdesk()
    books(before, placed, 10)
    before.evaluate(placed)
    books(before, expires + 0.2, 4)
    before.evaluate(expires + 0.2)
    assert [item.order_id for item in before.orders.values()] == [1]  # default: rests until cancelled


def test_the_fee_reserve_check_is_lives() -> None:
    for price in (0.01, 0.07, 0.33, 0.45, 0.5, 0.62, 0.97, 0.99):
        for coefficient in (0.0, 0.0175, 0.07):
            for precision in (0.01, 0.0001):
                assert speeddesk_model.unit_reserve(price, coefficient, precision) == (
                    speeddesk_live_model.reserve_unit_cost(price, coefficient, precision))
    def maker_fee(desk: PracticeDesk) -> PracticeDesk:
        desk.windows[SLUG].maker_coefficient = 0.0175  # a series with maker fees
        return desk

    fair = 0.5 + 0.0  # quote() puts Bitcoin on the strike: fair 0.5, a bid at 0.47
    assert fair == 0.5
    plain = maker_fee(kdesk())
    quote(plain, START + 10)
    plain.evaluate(START + 10)
    assert orders(plain) == [("up", "rest", 5.0, False)]  # today's rule ignores the fee on the edge
    checked = maker_fee(kdesk(edge_fee_precision=0.0001))
    quote(checked, START + 10)
    checked.evaluate(START + 10)
    assert not checked.orders and checked.last_reason[SLUG] == "edge_after_fee"  # 0.50 - 0.4744 < 0.03, as live
    zero = kdesk(edge_fee_precision=0.0001)  # no maker fee (production): the same bid as today
    quote(zero, START + 10)
    zero.evaluate(START + 10)
    assert orders(zero) == [("up", "rest", 5.0, False)]
    unverified = kdesk(edge_fee_precision=0.01)  # an account not attested direct: live sends nothing
    quote(unverified, START + 10)
    unverified.evaluate(START + 10)
    assert not unverified.orders and unverified.last_reason[SLUG] == "edge_after_fee"


def test_a_resting_starter_stops_when_its_no_first_buy_period_begins() -> None:
    desk = kdesk(starter_stop_s=600)
    quote(desk, END - 610)
    desk.evaluate(END - 610)
    assert orders(desk) == [("up", "rest", 5.0, False)]
    price = next(iter(desk.orders.values())).price
    quote(desk, END - 590)  # the same fair value: no reprice would cancel it
    events = desk.evaluate(END - 590)
    assert ("speeddesk_cancel", "starter_hold") in [(event.event, event.reason) for event in events]
    assert not desk.orders and desk.last_reason[SLUG] == "starter_late"
    sell(desk, "up", price, 20, END - 589)
    assert desk.inventory[SLUG].up.shares == 0  # no first buy inside the period (the review's probe filled 5)


def test_the_protective_stop_has_its_own_price_cap() -> None:
    desk = kdesk(stop_s=600, stop_pair_cost=1.10, lock_max_price=0.90)
    hold(desk, 5, 0, price=0.20)  # a cheap heavy side: completing costs 0.20 + 0.93 + fee
    quote(desk, END - 500, down=0.93)
    desk.evaluate(END - 500)
    assert orders(desk) == [("down", "take", 5.0, True)]  # the stop fires above the lock's own 0.90 cap
    lock = kdesk(lock_s=240, lock_max_price=0.90)
    hold(lock, 5, 0, price=0.20)
    quote(lock, END - 200, down=0.93)
    lock.evaluate(END - 200)
    assert not [order for order in orders(lock) if order[3]]  # the lock keeps its cap


def test_forget_keeps_only_today_and_yesterday_in_the_day_tables() -> None:
    desk = kdesk()
    for offset in range(5):
        day = utc_day(START - offset * 86_400)
        desk.days[day] = {"pnl_usd": -1.0}
        desk.traded_days[day] = {"x"}
        desk.filled_orders[day] = {1, 2}
        desk.venue_days["kalshi"][day] = {"fills": 1.0}
    desk.venue_filled_orders = {1, 2, 3}
    desk.forget(SLUG, void=True)
    kept = {utc_day(START), utc_day(START - 86_400)}
    assert set(desk.days) == set(desk.traded_days) == set(desk.filled_orders) == set(desk.venue_days["kalshi"]) == kept
    assert desk.venue_filled_orders == set() and all(not value for value in desk.filled_orders.values())
    assert desk.days[utc_day(START)] == {"pnl_usd": -1.0}  # today's P&L (the day stop) stays


def test_the_dedupe_memory_is_a_desk_attribute_with_todays_default() -> None:
    desk = kdesk()
    assert desk.trade_memory == 10_000
    desk.trade_memory = 3
    for n in range(10):
        desk.on_trade(Trade(SLUG, "up", 0.3, 1, START + n, f"p{n}", "sell", START + n), START + n)  # type: ignore[arg-type]
    assert len(desk.trade_order) == len(desk.seen_trades) == 3


def test_config_state_costs_no_more_than_asdict() -> None:
    """It runs in the live companion's durable checkpoint (the twin's to_state), before a real order's first byte."""
    from dataclasses import asdict

    config = SpeedConfig(clip=5, window_usd=10)
    assert config_state(config) == {key: value for key, value in asdict(config).items() if key not in OPT_IN_FIELDS}
    best: dict[str, float] = {}
    for _ in range(5):  # interleaved best-of, so a busy machine slows both alike
        for name, call in (("asdict", asdict), ("config_state", config_state)):
            started = time.perf_counter()
            for _ in range(2000):
                call(config)
            best[name] = min(best.get(name, math.inf), time.perf_counter() - started)
    assert best["config_state"] <= best["asdict"] * 1.2, best
