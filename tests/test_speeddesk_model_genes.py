"""The practice speed desk's opt-in arena fields: every default keeps today's behaviour exactly."""

from __future__ import annotations

import json
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from speeddesk_golden import FIXTURE, coverage, run

from nightcrawler import speeddesk_live_model
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
