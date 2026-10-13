"""The Kalshi earned-growth ladder (owner, 2026-10-13 ~18:40 UTC: "Max $50,000 a window build the ladder").

Synthetic windows and fills only; no account or network. Every trade goes through the risk book's own checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, make_desk

from nightcrawler import (
    pagestate,
    speeddesk,
    speeddesk_live_ladder,
    speeddesk_live_model,
)
from nightcrawler.config import ConfigError, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_live import STATE_KEY, KalshiLiveDesk
from nightcrawler.speeddesk_live_ladder import (
    KEPT_RESULTS,
    Ladder,
    LadderState,
    max_rung,
    rung_limits,
)
from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
    LiveSettlement,
    OrderSnapshot,
)
from nightcrawler.speeddesk_model import Window, utc_day

T0 = 1_791_475_200.0  # 2026-10-08 16:00 UTC, a quarter-hour boundary
# The owner's floor as Railway sets it: $10 a window, $20 open, $6 day stop, $10 total stop, 5-contract first buy.
BASE = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
# One contract at $0.40 reserves $0.42 with the 7 % taker fee at $0.0001 precision: +$0.58 a win, -$0.42 a loss.
WIN, LOSS = .58, -.42


def slot(index: int) -> Window:
    start = T0 + 900 * index
    return Window(f"KXBTC15M-L{index + 1000:05d}", start, start + 900, 100, taker_coefficient=.07,
                  maker_coefficient=0, venue="kalshi")


def setup(*, base: LiveLimits = BASE, start: float = T0 - 100, book: LiveRiskBook | None = None,
          **kwargs: Any) -> tuple[LiveRiskBook, Ladder]:
    book = book or LiveRiskBook(base)
    ladder = Ladder(base, **kwargs)
    ladder.start(book, start)
    book.window_limits = ladder.limits_for_start
    return book, ladder


def fill(book: LiveRiskBook, window: Window, side: Any, price: float, size: float, at: float) -> LiveIntent:
    """A buy through the book's own checks, filled in full at the reserved fee."""
    client = f"nc-speed-{window.slug}-{side}-{len(book.intents)}"
    intent = book.reserve_intent(window.slug, side, "take", price, size, at, client)
    book.mark_submitted(client, f"order-{client}")
    book.record_fill(ActualFill(f"fill-{client}", f"order-{client}", client, window.slug, side, price, size,
                                round(size * (intent.unit_reserve - price), 6), at))
    return intent


def trade(book: LiveRiskBook, index: int, *, wins: bool = True, size: float = 1, price: float = .4) -> LiveSettlement:
    """One window: buy Up 10 s after the open, fill it, settle at the close."""
    window = slot(index)
    book.add_window(window)
    book.update_cash(10_000, window.start + 10)
    fill(book, window, "up", price, size, window.start + 10)
    result = book.settle(window.slug, wins, window.end, f"settle-{window.slug}")
    assert result is not None
    return result


def settle_run(book: LiveRiskBook, ladder: Ladder, first: int, outcomes: str) -> float:
    """Trade one window per letter (W wins, L loses) and look at the ladder after each close."""
    now = 0.0
    for offset, letter in enumerate(outcomes):
        trade(book, first + offset, wins=letter == "W")
        now = slot(first + offset).end
        book.update_cash(10_000, now)
        ladder.evaluate(book, now)
    return now


def ready_ladder(**kwargs: Any) -> tuple[LiveRiskBook, Ladder, float]:
    """96 winning windows at rung 0, not yet looked at: every promotion condition holds."""
    book, ladder = setup(**kwargs)
    for index in range(96):
        trade(book, index)
    now = slot(95).end
    book.add_window(slot(96))  # the next window is known, as it is to the live desk
    book.update_cash(10_000, now)
    return book, ladder, now


def expected(rung: int, base: LiveLimits = BASE) -> tuple[float, float, float, float]:
    """The rule written out independently: window, open, day stop, contract cap (the $10 total stop is fixed)."""
    if rung == 0:
        return numbers(base)
    window = min(base.window_usd + 5 * rung, 20.0)  # today's code ceilings ($20 a window) apply first
    return (window, max(base.open_usd, 2 * window), max(base.day_loss_usd, round(.6 * window, 6)),
            max(base.clip, math.floor(window / 2)))


def numbers(limits: LiveLimits) -> tuple[float, float, float, float]:
    return limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.clip


def saved_at(rung: int, *, prior: int | None = None, rung_from: float = T0, peak: float = 0.0) -> dict[str, Any]:
    return {"version": 1, "rung": rung, "prior_rung": rung if prior is None else prior, "rung_from": rung_from,
            "started_at": T0 - 100, "start_pnl": 0, "peak_pnl": peak, "last_stop_at": None, "results": {},
            "last_change": None}


def at_rung(rung: int, *, base: LiveLimits = BASE) -> tuple[LiveRiskBook, Ladder, Window]:
    book, ladder = setup(base=base)
    assert ladder.start(book, T0, saved_at(rung)) == "restored"
    window = slot(0)
    book.add_window(window)
    book.update_cash(10_000, window.start + 10)
    return book, ladder, window


# ---- the rule's numbers ----------------------------------------------------------------------------------------

def test_each_rung_adds_five_dollars_with_open_clip_and_day_stop_scaled_and_the_total_stop_fixed():
    assert rung_limits(BASE, 0) is BASE  # rung 0 is exactly the configured limits
    assert numbers(rung_limits(BASE, 1)) == (15, 30, 9, 7)
    assert numbers(rung_limits(BASE, 2)) == (20, 40, 12, 10)
    for rung in range(5):
        limits = rung_limits(BASE, rung)
        assert numbers(limits) == expected(rung)
        assert limits.total_loss_usd == 10  # the lifetime stop never scales
        assert (limits.lock_s, limits.lock_max_price, limits.pair_cap, limits.max_imbalance, limits.fee_precision,
                limits.cutoff_s) == (BASE.lock_s, BASE.lock_max_price, BASE.pair_cap, BASE.max_imbalance,
                                     BASE.fee_precision, BASE.cutoff_s)
    # The configured values stay the owner's floor: a rung never goes below them.
    floor = LiveLimits(window_usd=10, open_usd=35, day_loss_usd=10, total_loss_usd=4, clip=8, fee_precision=.0001)
    assert numbers(rung_limits(floor, 1)) == (15, 35, 10, 8) and rung_limits(floor, 1).total_loss_usd == 4
    # The contract cap is never below one contract.
    tiny = LiveLimits(window_usd=.5, open_usd=1, day_loss_usd=1, total_loss_usd=1, clip=.5, fee_precision=.0001)
    assert rung_limits(tiny, 1).clip == 2 and rung_limits(replace(tiny, window_usd=.4, clip=.1), 1).clip == 2
    assert rung_limits(replace(tiny, window_usd=.1, clip=.1), 0).clip == .1  # rung 0 stays as configured


def test_the_climb_stops_at_the_code_ceilings_and_at_the_configured_maximum():
    # Today's code ceilings are $20 a window, $40 open and $12 a day: from $10 the ladder has two rungs.
    assert max_rung(10, 50_000) == 2 and Ladder(BASE).top == 2
    assert numbers(rung_limits(BASE, 3)) == numbers(rung_limits(BASE, 2)) == (20, 40, 12, 10)
    assert Ladder(BASE, max_window_usd=15).top == 1 and Ladder(BASE, max_window_usd=14.99).top == 0
    assert Ladder(BASE, max_window_usd=12).top == 0 and Ladder(BASE, enabled=False).top == 0
    assert numbers(rung_limits(BASE, 2, max_window_usd=15)) == (15, 30, 9, 7)
    ladder = Ladder(BASE)
    assert ladder.max_window_usd == 20 and ladder.configured_max_window_usd == 50_000


def test_with_the_code_ceilings_raised_the_top_rung_is_exactly_fifty_thousand_dollars(monkeypatch):
    """The owner's maximum: $50,000 a window, $100,000 open, $30,000 day stop, 25,000 contracts; never more.
    (A test-only patch of the code ceilings, which stay at $20/$40/$12 in this release.)"""
    for module in (speeddesk_live_model, speeddesk_live_ladder):
        monkeypatch.setattr(module, "HARD_WINDOW_USD", 50_000.0)
    monkeypatch.setattr(speeddesk_live_model, "HARD_OPEN_USD", 100_000.0)
    monkeypatch.setattr(speeddesk_live_model, "HARD_DAY_LOSS_USD", 30_000.0)
    assert max_rung(10, 50_000) == 9998 and max_rung(10, 60_000) == 9998 and max_rung(10, 12) == 0
    top = rung_limits(BASE, 9998)
    assert numbers(top) == (50_000, 100_000, 30_000, 25_000) and top.total_loss_usd == 10
    assert numbers(rung_limits(BASE, 10**6)) == numbers(top)
    assert numbers(rung_limits(BASE, 5)) == (35, 70, 21, 17)
    previous = numbers(BASE)
    for rung in range(1, 9999):
        current = numbers(rung_limits(BASE, rung))
        assert all(now >= before for now, before in zip(current, previous, strict=True))
        assert current[0] == 10 + 5 * rung and current[1] == 2 * current[0]
        previous = current
    assert Ladder(BASE).top == 9998 and Ladder(BASE, max_window_usd=1_000).top == 198
    # The risk book's own clamp still holds above the owner's maximum, and the total stop stays $10.
    clamped = LiveLimits(window_usd=60_000, open_usd=200_000, day_loss_usd=90_000, total_loss_usd=99)
    assert (clamped.window_usd, clamped.open_usd, clamped.day_loss_usd, clamped.total_loss_usd) == (
        50_000, 100_000, 30_000, 10)


def test_ladder_settings_default_on_and_never_above_the_owners_maximum():
    settings = Settings()
    assert settings.speeddesk_kalshi_ladder is True and settings.speeddesk_kalshi_ladder_max_window_usd == 50_000
    # The existing ceilings are unchanged by this release: $20 a window, $40 open, $12 a day, $10 total.
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_WINDOW_USD"):
        Settings(speeddesk_kalshi_window_usd=20.01)
    assert Settings.from_env({"SPEEDDESK_KALSHI_LADDER": "false"}).speeddesk_kalshi_ladder is False
    limited = Settings.from_env({"SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD": "15"})
    assert limited.speeddesk_kalshi_ladder_max_window_usd == 15
    for value in (0, -1, 50_000.01, float("nan"), float("inf"), True, "100"):
        with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD"):
            Settings(speeddesk_kalshi_ladder_max_window_usd=value)


# ---- promotion ----------------------------------------------------------------------------------------------

def test_promotion_after_all_five_conditions_and_only_from_the_next_window():
    book, ladder, now = ready_ladder()
    record = ladder.evaluate(book, now)
    assert record is not None and record["action"] == "promote" and (record["from_rung"], record["to_rung"]) == (0, 1)
    progress = record["promotion"]
    assert progress["ready"] and progress["blocked"] == [] and progress["windows"] == 96
    assert progress["gain_usd"] == pytest.approx(96 * WIN)
    assert progress["gain_needed_usd"] == pytest.approx(2 * 1.05 * math.sqrt(96))  # sigma floor: 10.5 % of $10
    assert progress["room_usd"] == pytest.approx(96 * WIN + 10) and progress["room_needed_usd"] == pytest.approx(24.75)
    assert progress["cash_needed_usd"] == 30 and record["limits_after"]["window_usd"] == 15
    # The window under way when the rung changed keeps its limits; the change starts at its close.
    current, following = slot(96), slot(97)
    assert record["effective_from"] == current.end == following.start
    assert numbers(book.limits_for(current.slug)) == expected(0)
    assert numbers(book.limits_now(current.start + 600)) == expected(0)
    book.add_window(following)
    assert numbers(book.limits_for(following.slug)) == expected(1)
    assert numbers(book.limits_now(following.start)) == expected(1)
    book.update_cash(10_000, current.start + 30)
    assert book.can_buy(current.slug, "up", "take", .4, 6, current.start + 30) == "clip"  # still the 5-contract cap
    book.update_cash(10_000, following.start + 30)
    assert book.can_buy(following.slug, "up", "take", .4, 7, following.start + 30) == ""
    assert book.can_buy(following.slug, "up", "take", .4, 8, following.start + 30) == "clip"


def test_not_promoted_short_of_ninety_six_windows():
    book, ladder = setup()
    now = settle_run(book, ladder, 0, "W" * 95)
    assert ladder.state.rung == 0 and ladder.promotion(book, now)["blocked"] == ["windows"]
    trade(book, 95)
    book.update_cash(10_000, slot(95).end)
    assert ladder.evaluate(book, slot(95).end)["to_rung"] == 1


def test_not_promoted_without_the_gain():
    book, ladder = setup(start=0)
    settle_run(book, ladder, -60, "W" * 40)  # $23.20 earned before this rung began
    book, ladder = setup(book=book, start=T0 - 100)
    now = settle_run(book, ladder, 0, "WL" * 48)
    progress = ladder.promotion(book, now)
    assert progress["windows"] == 96 and progress["gain_usd"] == pytest.approx(48 * WIN + 48 * LOSS)
    assert progress["gain_usd"] < progress["gain_needed_usd"] and progress["blocked"] == ["gain"]
    assert ladder.state.rung == 0


def test_not_promoted_without_house_money():
    """A rung that began in the red can gain enough and still lack the room above the lifetime stop."""
    book, ladder = setup(start=0)
    settle_run(book, ladder, -80, "L" * 11)  # 2026-10-07: -$4.62
    settle_run(book, ladder, -20, "L" * 10)  # 2026-10-08, before the ladder: -$4.20
    assert book.realized_pnl == pytest.approx(-8.82)
    book, ladder = setup(book=book, start=T0 - 100)
    now = settle_run(book, ladder, 0, "WWL" * 30 + "WLWLLL")  # 62 wins, 34 losses
    progress = ladder.promotion(book, now)
    assert progress["windows"] == 96 and progress["gain_usd"] >= progress["gain_needed_usd"]
    assert progress["room_usd"] < progress["room_needed_usd"] == pytest.approx(24.75)
    assert progress["blocked"] == ["house_money"] and ladder.state.rung == 0


@pytest.mark.parametrize("stop", ["integrity", "total", "day", "recent"])
def test_not_promoted_after_a_stop_until_a_quiet_day_has_passed(stop):
    book, ladder, now = ready_ladder()
    day = utc_day(now)
    if stop == "integrity":
        book.integrity_error = "fill_changed"
    elif stop == "total":
        book.halted, book.halt_reason = True, "total_loss"
    elif stop == "day":
        book.day_pnl[day] = book.day_pnl.get(day, 0.0) - 60  # today's loss is past the day stop
    else:
        ladder.state.last_stop_at = now - 23 * 3600  # a stop 23 hours ago
    assert ladder.evaluate(book, now) is None and ladder.state.rung == 0
    assert ladder.promotion(book, now)["blocked"] == ["stops"]
    if stop == "recent":
        later = now + 3600 + 1
    else:
        assert ladder.state.last_stop_at == now
        book.integrity_error, book.halted, book.halt_reason = None, False, None
        if stop == "day":
            book.day_pnl[day] += 60
        book.update_cash(10_000, now + 3600)
        assert ladder.evaluate(book, now + 3600) is None  # cleared, but not yet a quiet day
        assert ladder.promotion(book, now + 3600)["blocked"] == ["stops"]
        later = now + 86_400
    book.update_cash(10_000, later)
    assert ladder.evaluate(book, later)["to_rung"] == 1


@pytest.mark.parametrize("cash", ["short", "stale", "unknown"])
def test_not_promoted_without_the_cash_for_the_next_open_budget(cash):
    book, ladder, now = ready_ladder()
    if cash == "short":
        book.update_cash(29.99, now)  # the next rung's open budget is $30
    elif cash == "unknown":
        book.cash_usd = book.cash_at = None
    look = now + 61 if cash == "stale" else now  # a balance more than a minute old proves nothing
    assert ladder.evaluate(book, look) is None
    assert ladder.promotion(book, look)["blocked"] == ["cash"]
    book.update_cash(30, look + 1)
    assert ladder.evaluate(book, look + 1)["to_rung"] == 1


def test_pending_reservations_count_against_the_cash_for_promotion():
    book, ladder, now = ready_ladder()
    window, at = slot(96), now + 5
    book.update_cash(32, at)
    book.reserve_intent(window.slug, "up", "take", .4, 5, at, "nc-speed-pending")  # holds $2.10
    assert ladder.evaluate(book, at) is None
    progress = ladder.promotion(book, at)
    assert progress["blocked"] == ["cash"] and progress["available_cash_usd"] == pytest.approx(32 - 2.1)


def test_one_rung_at_a_time_and_the_counters_restart():
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["to_rung"] == 1
    for later in (now + 1, now + 5):  # waiting for the boundary: nothing more, however good it looks
        book.update_cash(10_000, later)
        assert ladder.evaluate(book, later) is None and ladder.state.rung == 1
        assert "change_pending" in ladder.promotion(book, later)["blocked"]
    assert ladder.state.start_pnl == pytest.approx(96 * WIN) and ladder.state.results == {}
    # Window 96 began before the boundary: it is not counted at rung 1. From window 97 it takes 96 more.
    end = settle_run(book, ladder, 96, "W")
    blocked = ladder.promotion(book, end)["blocked"]
    assert ladder.promotion(book, end)["windows"] == 0 and "windows" in blocked and "change_pending" not in blocked
    end = settle_run(book, ladder, 97, "W" * 95)
    assert ladder.state.rung == 1 and ladder.promotion(book, end)["windows"] == 95
    trade(book, 192)
    book.update_cash(10_000, slot(192).end)
    record = ladder.evaluate(book, slot(192).end)
    assert (record["from_rung"], record["to_rung"]) == (1, 2) and record["limits_after"]["window_usd"] == 20
    assert record["promotion"]["gain_needed_usd"] == pytest.approx(2 * 1.575 * math.sqrt(96))  # 10.5 % of $15
    # Rung 2 is the top today ($20 a window): no promotion past it, however well it goes.
    end = settle_run(book, ladder, 193, "W" * 120)
    assert ladder.state.rung == 2 and "at_ceiling" in ladder.promotion(book, end)["blocked"]


def test_the_configured_maximum_stops_the_climb():
    book, ladder, now = ready_ladder(max_window_usd=15)
    assert ladder.evaluate(book, now)["to_rung"] == 1
    end = settle_run(book, ladder, 96, "W" * 200)
    assert ladder.state.rung == 1 and ladder.promotion(book, end)["blocked"][:1] == ["at_ceiling"]


# ---- demotion ------------------------------------------------------------------------------------------------

def test_demotion_after_giving_back_sixty_percent_of_a_window_and_never_below_rung_zero():
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["to_rung"] == 1
    settle_run(book, ladder, 96, "W")  # window 96 is still rung 0
    peak = book.realized_pnl
    # Rung 1 windows with seven contracts each: three losses (-$8.82) give back less than $9 ...
    for index in (97, 98, 99):
        trade(book, index, wins=False, size=7)
        assert ladder.evaluate(book, slot(index).end) is None
    assert ladder.state.peak_pnl == pytest.approx(peak)
    assert ladder.demotion(book)["giveback_usd"] == pytest.approx(8.82)
    # ... a fourth crosses the line: one rung down, from the next window.
    index = 100
    trade(book, index, wins=False, size=7)
    record = ladder.evaluate(book, slot(index).end)
    assert record["action"] == "demote" and (record["from_rung"], record["to_rung"]) == (1, 0)
    assert record["demotion"]["due"] and record["demotion"]["giveback_limit_usd"] == pytest.approx(9)
    assert record["effective_from"] == slot(index + 1).end  # the window starting at the decision counts as begun
    assert numbers(book.limits_now(slot(index + 1).start + 1)) == expected(1)
    book.add_window(slot(index + 2))
    assert numbers(book.limits_for(slot(index + 2).slug)) == expected(0)
    # At rung 0 a give-back changes nothing and does not restart the counters.
    started = ladder.state.started_at
    end = settle_run(book, ladder, index + 2, "LLLLL")
    assert ladder.state.rung == 0 and ladder.state.started_at == started and ladder.evaluate(book, end) is None
    assert ladder.demotion(book)["at_floor"] and ladder.demotion(book)["line_usd"] is None


def test_a_demotion_cancels_a_promotion_that_has_not_started_yet():
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["to_rung"] == 1
    ladder.state.peak_pnl = book.realized_pnl + 9  # $9 given back before the boundary
    record = ladder.evaluate(book, now + 60)
    assert record["action"] == "demote" and (record["from_rung"], record["to_rung"]) == (1, 0)
    assert ladder.state.rung == ladder.state.prior_rung == 0
    book.add_window(slot(97))
    assert numbers(book.limits_for(slot(97).slug)) == expected(0)


@pytest.mark.parametrize("stop", ["integrity", "day"])
def test_a_stop_before_the_boundary_cancels_a_waiting_promotion(stop):
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["to_rung"] == 1
    if stop == "integrity":
        book.integrity_error = "fill_changed"
    else:
        book.day_pnl[utc_day(now)] -= 60
    record = ladder.evaluate(book, now + 60)
    assert record["action"] == "cancel" and (record["from_rung"], record["to_rung"]) == (1, 0)
    assert ladder.state.rung == ladder.state.prior_rung == 0 and ladder.state.last_stop_at == now + 60
    book.add_window(slot(97))
    assert numbers(book.limits_for(slot(97).slug)) == expected(0)


def test_a_waiting_demotion_is_never_doubled_before_its_boundary():
    book, ladder = setup()
    assert ladder.start(book, T0 + 100, saved_at(2, peak=12)) == "restored"
    record = ladder.evaluate(book, T0 + 100)
    assert (record["from_rung"], record["to_rung"], record["effective_from"]) == (2, 1, T0 + 900)
    ladder.state.peak_pnl = 20  # another full give-back before the boundary
    assert ladder.evaluate(book, T0 + 200) is None and ladder.state.rung == 1
    assert ladder.evaluate(book, T0 + 900)["to_rung"] == 0  # the next step waits for the next boundary


# ---- every limit check at a rung -----------------------------------------------------------------------------

def test_every_check_uses_the_windows_rung():
    book, _, window = at_rung(2)
    assert book.can_buy(window.slug, "up", "take", .4, 11, window.start + 10) == "clip"
    assert book.can_buy(window.slug, "up", "take", .4, 10, window.start + 10) == ""
    book, _, window = at_rung(0)
    assert book.can_buy(window.slug, "up", "take", .4, 6, window.start + 10) == "clip"
    # Window budget: a $3 floor window refuses the second half of a $4.70 pair at rung 0, not at rung 1 ($8).
    small = LiveLimits(window_usd=3, open_usd=6, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
    for rung, verdict in ((0, "window_budget"), (1, "")):
        book, _, window = at_rung(rung, base=small)
        fill(book, window, "up", .4, 5, window.start + 10)
        assert book.can_buy(window.slug, "down", "take", .5, 5, window.start + 11) == verdict
    # Day stop: $4 lost today stops a $2.10 buy at rung 0 ($6), not at rung 2 ($12).
    for rung, verdict in ((0, "day_stop"), (2, "")):
        book, _, window = at_rung(rung)
        book.day_pnl[utc_day(window.start)] = -4
        assert book.can_buy(window.slug, "up", "take", .4, 5, window.start + 10) == verdict
        assert book.risk_status(window.start + 10)["limits"]["day_loss_usd"] == expected(rung)[2]
    # Open budget: a floor of $3 open refuses $3.60 at rung 0; rung 1 allows twice its window.
    tight = LiveLimits(window_usd=10, open_usd=3, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
    for rung, verdict in ((0, "open_budget"), (1, "")):
        book, _, window = at_rung(rung, base=tight)
        assert book.can_buy(window.slug, "up", "take", .7, 5, window.start + 10) == verdict
    # A lock completes a pair in pieces no larger than the rung's contract cap.
    for rung, clip in ((0, 5), (2, 10)):
        book, _, window = at_rung(rung)
        fill(book, window, "up", .4, clip, window.start + 10)
        lock_at = window.end - 200
        book.update_cash(10_000, lock_at)
        assert book.can_lock(window.slug, "down", .5, clip + 1, lock_at) == "clip"
        assert book.can_lock(window.slug, "down", .5, clip, lock_at) == ""


def test_the_lifetime_stop_never_scales_and_still_stops_real_money():
    book, _, window = at_rung(2)
    at = window.start + 10
    assert book.limits_for(window.slug).total_loss_usd == 10
    book.realized_pnl = -9.6  # $9.60 lost since launch
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "total_budget"  # $9.60 + $0.42 >= $10
    book.realized_pnl = -10.0
    assert book.risk_status(at)["halted"] and book.halt_reason == "total_loss"
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "total_loss"


# ---- the live desk ---------------------------------------------------------------------------------------------

LADDER_CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
               "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}


def force_rung(desk: KalshiLiveDesk, rung: int, now: float) -> None:
    """Put the desk's ladder at a rung for every window (as if restored there)."""
    desk.ladder.state = LadderState(rung=rung, prior_rung=rung, rung_from=0.0, started_at=now,
                                    start_pnl=desk.book.realized_pnl, peak_pnl=desk.book.realized_pnl)


def test_the_desk_starts_at_rung_zero_with_the_configured_limits(tmp_path: Path):
    desk, account, _ = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        asyncio.run(desk.step())
        assert [creation["size"] for creation in account.creates] == [5.0]
        panel = desk.panel()["ladder"]
        assert panel["enabled"] and panel["rung"] == 0 and panel["top_rung"] == 2
        assert panel["limits"] == {"window_usd": 10, "open_usd": 20, "day_stop_usd": 6, "clip": 5, "total_stop_usd": 10}
        promotion = panel["promotion"]
        assert (promotion["windows"], promotion["windows_needed"], promotion["next_rung"]) == (0, 96, 1)
        assert promotion["gain_needed_usd"] == 0 and promotion["room_usd"] == 10
        assert promotion["room_needed_usd"] == pytest.approx(24.75) and promotion["cash_needed_usd"] == 30
        assert {"windows", "gain", "house_money", "cash"} <= set(promotion["blocked"])
        assert panel["demotion"]["at_floor"] and panel["demotion"]["line_usd"] is None
        started = [event for event in desk.latest_events if event["event"] == "speeddesk_live_ladder"]
        assert started and started[0]["action"] == "start" and started[0]["state"] == "new"
    finally:
        desk.close()


def test_the_desk_with_the_ladder_off_always_uses_the_configured_limits(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS, extra={"speeddesk_kalshi_ladder": False,
                                                                         "speeddesk_kalshi_ladder_max_window_usd": 15.0})
    try:
        force_rung(desk, 2, clock.now())  # even a saved rung is ignored while the ladder is off
        asyncio.run(desk.step())
        assert [creation["size"] for creation in account.creates] == [5.0]
        panel = desk.panel()["ladder"]
        assert not panel["enabled"] and panel["rung"] == 0 and panel["top_rung"] == 0
        assert "ladder_off" in panel["promotion"]["blocked"] and desk.panel()["caps"]["window_usd"] == 10
    finally:
        desk.close()


def test_the_desk_and_its_practice_twin_use_the_rungs_limits(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        force_rung(desk, 1, clock.now())
        asyncio.run(desk.step())
        # Rung 1: the first buy is 7 contracts (half the $15 window).
        assert [creation["size"] for creation in account.creates] == [7.0]
        assert desk.panel()["caps"] == {"window_usd": 15, "open_usd": 30, "day_stop_usd": 9, "total_stop_usd": 10,
                                        "clip": 7}
        config = desk.twin.config
        assert (config.window_usd, config.open_usd, config.day_stop_usd, config.clip) == (15, 30, 9, 7)
        force_rung(desk, 0, clock.now())
        clock.advance(.5)
        asyncio.run(desk.step())
        assert (desk.twin.config.window_usd, desk.twin.config.clip) == (10, 5)
    finally:
        desk.close()


def test_the_lifetime_stop_switches_the_desk_to_practice_at_any_rung(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        force_rung(desk, 2, clock.now())
        desk.book.realized_pnl = -10.0
        asyncio.run(desk.step())
        assert not account.creates and desk.panel()["mode"] == "paper"
        assert desk._risk_stop_reason().startswith("Total loss stop")
        assert "stops" in desk.panel()["ladder"]["promotion"]["blocked"]
    finally:
        desk.close()


def test_the_ladder_survives_a_restart(tmp_path: Path):
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    snapshot, settings = desk.snapshot, desk.settings
    boundary = clock.now() + 890
    desk.ladder.state = LadderState(rung=1, prior_rung=0, rung_from=boundary, started_at=clock.now(),
                                    start_pnl=0.0, peak_pnl=1.5, last_stop_at=clock.now() - 60,
                                    last_change={"action": "promote", "from_rung": 0, "to_rung": 1,
                                                 "effective_from": boundary, "at": clock.now()})
    desk.checkpoint(durable=True)
    saved = desk.ledger.get_kv(STATE_KEY)["ladder"]
    assert (saved["rung"], saved["prior_rung"], saved["rung_from"], saved["peak_pnl"]) == (1, 0, boundary, 1.5)
    desk.close()
    restored = KalshiLiveDesk(settings, tmp_path / "live", snapshot, clock=clock.now,
                              client_factory=lambda: None, direct_member_verified=True)
    try:
        state = restored.ladder.state
        assert (state.rung, state.prior_rung, state.rung_from, state.peak_pnl) == (1, 0, boundary, 1.5)
        assert state.last_stop_at == clock.now() - 60 and state.last_change["action"] == "promote"
        # The window under way is still rung 0; the waiting promotion starts at its close.
        assert numbers(restored.book.limits_for(TICKER)) == expected(0)
        panel = restored.panel()["ladder"]
        assert panel["change_pending"] and panel["rung"] == 0 and panel["pending_limits"]["window_usd"] == 15
        started = [event for event in restored.latest_events if event["event"] == "speeddesk_live_ladder"]
        assert started[-1]["state"] == "restored"
    finally:
        restored.close()


def test_a_restart_rebuilds_the_count_from_the_books():
    book, ladder = setup()
    settle_run(book, ladder, 0, "W" * 10)
    saved = json.loads(json.dumps(ladder.to_state()))
    assert saved["windows"] == 10 and len(saved["results"]) == 10
    saved["results"] = {f"KXBTC15M-FAKE-{n}": 5.0 for n in range(500)}  # a saved list can never inflate the count
    restored_book = LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())), BASE)
    restored = Ladder(BASE)
    assert restored.start(restored_book, slot(9).end, saved) == "restored"
    assert restored.promotion(restored_book, slot(9).end)["windows"] == 10
    assert set(restored.state.results) == {slot(index).slug for index in range(10)}


def test_the_saved_list_is_bounded_but_the_count_is_not():
    book, ladder = setup(windows_needed=10_000)
    settle_run(book, ladder, 0, "W" * (KEPT_RESULTS + 8))
    saved = ladder.to_state()
    assert saved["windows"] == KEPT_RESULTS + 8 and len(saved["results"]) == KEPT_RESULTS
    assert next(iter(saved["results"])) == slot(8).slug  # the latest are kept


@pytest.mark.parametrize("saved", [
    {"version": 2, "rung": 1}, {"version": 1, "rung": -1, "prior_rung": 0}, {"version": 1, "rung": True},
    {"version": 1, "rung": 1, "prior_rung": 1, "rung_from": float("nan"), "started_at": 0, "start_pnl": 0,
     "peak_pnl": 0}, {**saved_at(1), "results": [1]}, {**saved_at(1), "results": {"x": "y"}},
    {**saved_at(1), "last_change": "promote"}, "not a ladder", [1],
])
def test_an_unreadable_ladder_starts_again_at_rung_zero(saved):
    book, ladder = setup()
    assert ladder.start(book, T0, saved) == "unreadable"
    assert ladder.state.rung == ladder.state.prior_rung == 0 and ladder.state.rung_from == T0 + 900


def test_switching_the_ladder_off_or_lowering_its_maximum_lowers_the_limits():
    book, ladder = setup(enabled=False)
    assert ladder.start(book, T0, saved_at(2, rung_from=0)) == "reset_off" and ladder.state.rung == 0
    book.add_window(slot(0))
    assert numbers(book.limits_for(slot(0).slug)) == expected(0)
    assert ladder.evaluate(book, T0) is None
    assert ladder.promotion(book, T0)["blocked"][:2] == ["ladder_off", "at_ceiling"]
    book, ladder = setup(max_window_usd=15)
    assert ladder.start(book, T0, saved_at(2, rung_from=0)) == "clamped" and ladder.state.rung == 1
    book.add_window(slot(0))
    assert numbers(book.limits_for(slot(0).slug)) == expected(1)


def test_saved_state_stays_readable_by_the_previous_release(tmp_path: Path):
    """The previous release reads the books, intents and twin it knows and ignores other top-level keys. The ladder
    adds one top-level key and nothing inside them. After a rollback the old release writes the state back without
    it, and the next upgrade starts again at rung 0 (the configured limits)."""
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    snapshot, settings = desk.snapshot, desk.settings
    try:
        force_rung(desk, 1, clock.now())
        asyncio.run(desk.step())
        assert account.creates and account.creates[0]["size"] == 7.0
        desk.checkpoint(durable=True)
        state = desk.ledger.get_kv(STATE_KEY)
    finally:
        desk.close()
    plain = LiveRiskBook(BASE).to_state()
    assert set(state["book"]) == set(plain) and set(state["book"]["limits"]) == set(plain["limits"])
    assert state["book"]["limits"]["window_usd"] == 10  # the saved limits stay the configured ones
    intent = next(iter(state["intents"].values()))
    assert set(intent) == {"client_order_id", "window", "side", "kind", "price", "size", "fair", "at", "order_id",
                           "terminal", "uncertain", "cancel_requested", "twin_order_id"}
    assert set(next(iter(state["book"]["intents"].values()))) == set(next(iter(plain_intents())))
    old_book = LiveRiskBook.from_state(json.loads(json.dumps(state["book"])), BASE)  # what the old release does
    assert old_book.limits_for(next(iter(old_book.windows))).window_usd == 10
    rolled_back = {key: value for key, value in state.items() if key != "ladder"}
    ledger = Ledger(tmp_path / "live" / "receipts.db", _Clock(clock.now))
    ledger.set_kv(STATE_KEY, rolled_back)
    ledger.close()
    again = KalshiLiveDesk(settings, tmp_path / "live", snapshot, clock=clock.now, client_factory=lambda: account,
                           direct_member_verified=True)
    try:
        assert again.ladder.state.rung == 0 and numbers(again.book.limits_now(clock.now())) == expected(0)
        starts = [event for event in again.latest_events if event["event"] == "speeddesk_live_ladder"]
        assert starts[-1]["state"] == "new"
    finally:
        again.close()


def plain_intents() -> list[dict[str, Any]]:
    """A saved intent from a book without a ladder (the fields the previous release reads)."""
    book = LiveRiskBook(BASE)
    window = slot(0)
    book.add_window(window)
    book.update_cash(100, window.start + 10)
    book.reserve_intent(window.slug, "up", "take", .4, 1, window.start + 10, "nc-speed-plain")
    return list(book.to_state()["intents"].values())


class _Clock:
    def __init__(self, now: Any) -> None:
        self.now = now


def test_one_log_line_per_change_with_every_number(tmp_path: Path, caplog):
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        desk.ladder.state = LadderState(rung=1, prior_rung=1, rung_from=0.0, started_at=clock.now() - 3600,
                                        start_pnl=0.0, peak_pnl=9.0)
        with caplog.at_level(logging.INFO, logger="nightcrawler.speeddesk"):
            caplog.clear()
            for _ in range(3):
                desk._ladder_step()
                desk.checkpoint()
        lines = [record.getMessage() for record in caplog.records
                 if record.getMessage().startswith("speeddesk_live_ladder ")]
        assert len(lines) == 1
        payload = json.loads(lines[0].split(" ", 1)[1])
        assert payload["action"] == "demote" and (payload["from_rung"], payload["to_rung"]) == (1, 0)
        assert payload["effective_from"] > clock.now() and payload["effective_from_utc"]
        assert payload["limits_before"]["window_usd"] == 15 and payload["limits_after"]["window_usd"] == 10
        for key in ("windows", "windows_needed", "gain_usd", "gain_needed_usd", "sigma_usd", "room_usd",
                    "room_needed_usd", "available_cash_usd", "cash_needed_usd", "last_stop_at"):
            assert key in payload["promotion"]
        assert payload["demotion"]["peak_pnl_usd"] == 9 and payload["demotion"]["giveback_limit_usd"] == 9
    finally:
        desk.close()


def test_the_status_line_and_the_page_carry_the_ladder(tmp_path: Path, caplog, make_settings, monkeypatch):
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        with caplog.at_level(logging.INFO, logger="nightcrawler.speeddesk"):
            caplog.clear()
            desk.last_status = -math.inf
            desk._heartbeat()
        status = next(json.loads(record.getMessage().split(" ", 1)[1]) for record in caplog.records
                      if record.getMessage().startswith("speeddesk_live_status "))
        assert status["ladder"]["rung"] == 0 and status["ladder"]["promotion"]["windows_needed"] == 96
        assert status["ladder"]["demotion"]["at_floor"] and status["caps"]["clip"] == 5
        raw = desk.panel()
    finally:
        desk.close()
    raw["ladder"]["promotion"]["blocked"] = ["windows", "<script>"]
    raw["ladder"]["promotion"]["gain_usd"] = float("nan")
    raw["ladder"]["last_change"] = {"action": "promote", "from_rung": 0, "to_rung": 1, "effective_from": 5.0, "at": 4.0}
    report = {"as_of": clock.now(), "status": "Practice connected", "today": {"day": utc_day(clock.now())},
              "kalshi_live": raw}
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: report)
    settings = make_settings(SPEEDDESK_KALSHI_MODE="live", SPEEDDESK_KALSHI_LIVE_CONFIRM="yes",
                             KALSHI_KEY_ID="fake-panel-key-id", KALSHI_PRIVATE_KEY="fake-panel-key-material")
    ladder = pagestate.speed_desk(settings, clock.now())["kalshi_live"]["ladder"]
    assert ladder["rung"] == 0 and ladder["limits"]["clip"] == 5 and ladder["top_rung"] == 2
    assert ladder["promotion"]["blocked"] == ["windows"] and ladder["promotion"]["gain_usd"] is None
    assert ladder["promotion"]["room_needed_usd"] == pytest.approx(24.75)
    assert ladder["promotion"]["windows_needed"] == 96 and ladder["promotion"]["cash_needed_usd"] == 30
    assert ladder["demotion"]["at_floor"] and ladder["last_change"]["to_rung"] == 1
    assert ladder["configured_max_window_usd"] == 50_000 and ladder["max_window_usd"] == 20
    assert pagestate._kalshi_ladder(None) is None and pagestate._kalshi_ladder("junk") is None


# ---- randomized: no event sequence breaks the rung's limits ---------------------------------------------------

# A $5 floor window (rungs $5, $10, $15, $20): its window budget binds before the day stop does.
RUN_BASE = LiveLimits(window_usd=5, open_usd=10, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)


class Run:
    """A random sequence of buys, fills, cancels, locks, settlements, restarts and ladder looks."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.book, self.ladder = setup(base=RUN_BASE, windows_needed=3)
        self.pinned: dict[str, int] = {}
        self.last_pinned: int | None = None
        self.orders = 0
        self.counts: Counter[str] = Counter()

    def restart(self, now: float) -> None:
        book = LiveRiskBook.from_state(json.loads(json.dumps(self.book.to_state())), RUN_BASE)
        ladder = Ladder(RUN_BASE, windows_needed=3)
        assert ladder.start(book, now, json.loads(json.dumps(self.ladder.to_state()))) == "restored"
        book.window_limits = ladder.limits_for_start
        for spec in book.windows.values():
            if spec.start <= now < spec.end:
                assert ladder.rung_for(spec.start) == self.ladder.rung_for(spec.start)
        assert ladder.promotion(book, now)["windows"] == self.ladder.promotion(self.book, now)["windows"]
        self.book, self.ladder = book, ladder
        self.counts["restart"] += 1

    def observe(self, window: Window, now: float) -> None:
        """A window's rung is fixed from its start to its close; the next one is at most one rung away."""
        assert 0 <= self.ladder.state.rung <= self.ladder.top == 3
        rung = self.ladder.rung_for(window.start)
        if window.slug not in self.pinned:
            assert self.last_pinned is None or abs(rung - self.last_pinned) <= 1
            self.pinned[window.slug], self.last_pinned = rung, rung
        assert self.pinned[window.slug] == rung
        assert (numbers(self.book.limits_for(window.slug)) == expected(rung, RUN_BASE)
                == numbers(self.book.limits_now(now)))

    def look(self, now: float) -> None:
        before = self.ladder.state.rung
        record = self.ladder.evaluate(self.book, now)
        if record is None:
            assert self.ladder.state.rung == before
            return
        self.counts[record["action"]] += 1
        if record["action"] == "promote":
            assert record["promotion"]["ready"] and record["promotion"]["blocked"] == []
            assert record["to_rung"] == record["from_rung"] + 1 and record["promotion"]["windows"] >= 3
        else:
            assert record["action"] == "cancel" or record["demotion"]["due"]
            assert record["to_rung"] == record["from_rung"] - 1 >= 0
        assert record["effective_from"] > now

    def buy(self, window: Window, now: float, *, lock: bool) -> None:
        window_usd, open_usd, day_usd, clip = expected(self.pinned[window.slug], RUN_BASE)
        book = self.book
        if self.rng.random() < .85:
            book.update_cash(self.rng.choice([3.0, 12.0, 60.0, 1_000.0, 1_000.0]), now)
        if lock:
            side, unpaired = book.lock_side(window.slug)
            if side is None or unpaired < 1:
                return
            size = float(self.rng.randint(1, math.floor(unpaired) + 2))
            price = self.rng.choice([.5, .7, .9, .97, .98])
        else:
            light, _ = book.lock_side(window.slug)  # mostly balance, so whole pairs build up toward the window budget
            side = light if light is not None and self.rng.random() < .7 else self.rng.choice(["up", "down"])
            size = float(self.rng.randint(1, int(clip) + 3))
            price = self.rng.choice([.05, .2, .35, .45, .5, .6, .75, .9])
        current = book.inventory[window.slug].spent + sum(item.reserved for item in book.intents.values()
                                                           if item.window == window.slug)
        at_risk, reserved, debits = book.at_risk_usd, book.reserved_usd, book.cash_debits
        day_loss, total_loss = book.day_loss(now), max(0.0, book.stop_anchor - book.realized_pnl)
        self.orders += 1
        try:
            intent = book.reserve_intent(window.slug, side, "take", price, size, now, f"nc-speed-r{self.orders}",
                                         lock=lock)
        except LiveRejected as exc:
            self.counts["refused_" + exc.reason] += 1
            return
        cost = intent.size * intent.unit_reserve
        assert intent.size <= clip + 1e-9
        assert book.cash_usd is not None and cost + reserved + debits <= book.cash_usd + 1e-9
        if not lock:
            assert current + cost <= window_usd + 1e-9
            assert at_risk + cost <= open_usd + 1e-9
            assert day_loss + at_risk + cost < day_usd
            assert total_loss + at_risk + cost < 10
        self.counts["lock" if lock else "buy"] += 1

    def fill_or_cancel(self, now: float) -> None:
        active = [item for item in self.book.intents.values() if item.reservation_active]
        if not active:
            return
        intent = self.rng.choice(active)
        order_id = intent.order_id or f"venue-{intent.client_order_id}"
        self.book.mark_submitted(intent.client_order_id, order_id)
        if self.rng.random() < .65 and intent.remaining >= 1:
            size = float(self.rng.randint(1, math.floor(intent.remaining)))
            fee = round(size * (intent.unit_reserve - intent.price) * self.rng.random(), 6)
            self.book.record_fill(ActualFill(f"f-{self.orders}-{len(self.book.fills)}", order_id,
                                             intent.client_order_id, intent.window, intent.side, intent.price, size,
                                             fee, now))
            self.counts["fill"] += 1
        else:
            self.close(intent, now)

    def close(self, intent: LiveIntent, now: float) -> None:
        order_id = intent.order_id or f"venue-{intent.client_order_id}"
        self.book.mark_submitted(intent.client_order_id, order_id)
        assert self.book.reconcile_order(OrderSnapshot(intent.client_order_id, order_id, "canceled",
                                                       intent.filled_size, 0, now), fills_complete=True)

    def window(self, index: int, good: bool) -> None:
        window = slot(index)
        self.book.add_window(window)
        for now in sorted(self.rng.uniform(window.start, window.end - 21) for _ in range(self.rng.randint(6, 24))):
            self.observe(window, now)
            action = self.rng.random()
            if action < .4:
                self.buy(window, now, lock=now >= window.end - BASE.lock_s)
            elif action < .75:
                self.fill_or_cancel(now)
            elif action < .99:
                self.look(now)
            else:
                self.restart(now)
                self.observe(window, now)
            assert self.book.integrity_error is None
        end = window.end
        for intent in [item for item in self.book.intents.values() if item.reservation_active]:
            self.close(intent, end)
        inventory = self.book.inventory[window.slug]
        heavy = inventory.up.shares >= inventory.down.shares
        self.book.settle(window.slug, heavy if self.rng.random() < (.85 if good else .25) else not heavy, end,
                         f"s-{window.slug}")
        self.book.update_cash(1_000.0, end)
        self.look(end)


def test_randomized_sequences_never_break_the_rungs_limits():
    totals: Counter[str] = Counter()
    for seed in range(20):
        run = Run(seed)
        good = True
        for index in range(150):
            if index % 15 == 0:
                good = run.rng.random() < .7
            run.window(index, good)
        assert run.counts["buy"] and run.counts["fill"] and run.counts["restart"], (seed, run.counts)
        totals.update(run.counts)
    # The sequences really climbed and fell, and every refusal kind the rungs set was reached.
    assert totals["promote"] >= 5 and totals["demote"] >= 2 and totals["lock"] > 0, totals
    assert all(totals["refused_" + reason] for reason in ("clip", "window_budget", "day_stop", "total_budget",
                                                          "cash_budget")), totals
