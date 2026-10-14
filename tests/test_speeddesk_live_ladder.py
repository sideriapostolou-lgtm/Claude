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
    speeddesk_live_model,
)
from nightcrawler.config import ConfigError, Secret, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_live import STATE_KEY, KalshiLiveDesk
from nightcrawler.speeddesk_live_ladder import (
    KEPT_RESULTS,
    Ladder,
    LadderState,
    limits_view,
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
    ladder.attach(book)
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
    """The rule written out independently: window, open, day stop, contract cap (the $10 total stop is fixed).
    The contract cap, so the first buy, is the configured one at every rung (owner, 2026-10-13: "Keep 5 at every
    rung")."""
    if rung == 0:
        return numbers(base)
    window = min(base.window_usd + 5 * rung, 20.0)  # today's code ceilings ($20 a window) apply first
    return (window, max(base.open_usd, 2 * window), max(base.day_loss_usd, round(.6 * window, 6)), base.clip)


def numbers(limits: LiveLimits) -> tuple[float, float, float, float]:
    return limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.clip


def saved_at(rung: int, *, prior: int | None = None, rung_from: float = T0, confirmed: bool = True,
             base: LiveLimits = BASE) -> dict[str, Any]:
    return {"version": 2, "rung": rung, "prior_rung": rung if prior is None else prior, "rung_from": rung_from,
            "confirmed": confirmed, "counted_from": rung_from, "started_at": T0 - 100, "start_pnl": 0, "peak_pnl": 0,
            "last_stop_at": None, "results": {}, "last_change": None, "floor": limits_view(base)}


def at_rung(rung: int, *, base: LiveLimits = BASE) -> tuple[LiveRiskBook, Ladder, Window]:
    book, ladder = setup(base=base)
    assert ladder.start(book, T0, saved_at(rung, base=base)) == "restored"
    window = slot(0)
    book.add_window(window)
    book.update_cash(10_000, window.start + 10)
    return book, ladder, window


# ---- the rule's numbers ----------------------------------------------------------------------------------------

def test_each_rung_adds_five_dollars_with_open_and_day_stop_scaled_and_the_clip_and_total_stop_fixed():
    assert rung_limits(BASE, 0) is BASE  # rung 0 is exactly the configured limits
    assert numbers(rung_limits(BASE, 1)) == (15, 30, 9, 5)
    assert numbers(rung_limits(BASE, 2)) == (20, 40, 12, 5)
    for rung in range(3):  # rungs 0 to 2: today's top from $10
        limits = rung_limits(BASE, rung)
        assert numbers(limits) == expected(rung)
        assert limits.clip == BASE.clip  # the first buy stays the configured 5 contracts
        assert limits.total_loss_usd == 10  # the lifetime stop never scales
        assert (limits.lock_s, limits.lock_max_price, limits.pair_cap, limits.max_imbalance, limits.fee_precision,
                limits.cutoff_s) == (BASE.lock_s, BASE.lock_max_price, BASE.pair_cap, BASE.max_imbalance,
                                     BASE.fee_precision, BASE.cutoff_s)
    # The configured values stay the owner's floor: a rung never goes below them.
    floor = LiveLimits(window_usd=10, open_usd=35, day_loss_usd=10, total_loss_usd=4, clip=8, fee_precision=.0001)
    assert numbers(rung_limits(floor, 1)) == (15, 35, 10, 8) and rung_limits(floor, 1).total_loss_usd == 4
    # The contract cap is the configured one at every rung, however small or large the window.
    tiny = LiveLimits(window_usd=.5, open_usd=1, day_loss_usd=1, total_loss_usd=1, clip=.5, fee_precision=.0001)
    assert rung_limits(tiny, 1).clip == .5 and rung_limits(replace(tiny, window_usd=.4, clip=.1), 1).clip == .1
    assert rung_limits(replace(tiny, window_usd=.1, clip=.1), 0).clip == .1  # rung 0 stays as configured
    assert rung_limits(replace(BASE, clip=3), 2).clip == 3 and rung_limits(replace(BASE, clip=25), 2).clip == 25


def test_the_climb_stops_at_the_code_ceilings_and_at_the_configured_maximum():
    # Today's code ceilings are $20 a window, $40 open and $12 a day: from $10 the ladder has two rungs.
    assert max_rung(BASE, 50_000) == 2 and Ladder(BASE).top == 2
    ladder = Ladder(BASE)
    assert numbers(ladder.limits_at_rung(3)) == numbers(ladder.limits_at_rung(2)) == (20, 40, 12, 5)
    assert Ladder(BASE, max_window_usd=15).top == 1 and Ladder(BASE, max_window_usd=14.99).top == 0
    assert Ladder(BASE, max_window_usd=12).top == 0 and Ladder(BASE, enabled=False).top == 0
    assert numbers(rung_limits(BASE, 2, max_window_usd=15)) == (15, 30, 9, 5)
    ladder = Ladder(BASE)
    assert ladder.max_window_usd == 20 and ladder.configured_max_window_usd == 50_000


def test_with_the_code_ceilings_raised_the_top_rung_is_exactly_fifty_thousand_dollars(monkeypatch):
    """The owner's maximum: $50,000 a window, $100,000 open, $30,000 day stop; never more. The contract cap stays
    the configured 5 at every rung, the top included (owner, 2026-10-13: "Keep 5 at every rung").
    (A test-only patch of the code ceilings, which stay at $20/$40/$12 in this release.)"""
    monkeypatch.setattr(speeddesk_live_model, "HARD_WINDOW_USD", 50_000.0)
    monkeypatch.setattr(speeddesk_live_model, "HARD_OPEN_USD", 100_000.0)
    monkeypatch.setattr(speeddesk_live_model, "HARD_DAY_LOSS_USD", 30_000.0)
    # The ladder asks the risk book's clamp for its top: the contract cap no longer grows, so its ceiling (25) never
    # binds and the money ceilings alone set the top. Raising the contract ceiling changes nothing.
    for hard_clip in (25.0, 25_000.0):
        monkeypatch.setattr(speeddesk_live_model, "HARD_CLIP", hard_clip)
        assert max_rung(BASE, 50_000) == 9998 and max_rung(BASE, 60_000) == 9998 and max_rung(BASE, 12) == 0
        top = rung_limits(BASE, 9998)
        assert numbers(top) == (50_000, 100_000, 30_000, 5) and top.total_loss_usd == 10
        assert numbers(rung_limits(BASE, 10**6)) == numbers(top)
        assert numbers(rung_limits(BASE, 5)) == (35, 70, 21, 5) and numbers(rung_limits(BASE, 8)) == (50, 100, 30, 5)
    previous = numbers(BASE)
    for rung in range(1, 9999):
        current = numbers(rung_limits(BASE, rung))
        assert all(now >= before for now, before in zip(current, previous, strict=True))
        assert current[0] == 10 + 5 * rung and current[1] == 2 * current[0] and current[3] == 5
        previous = current
    assert Ladder(BASE).top == 9998 and Ladder(BASE, max_window_usd=1_000).top == 198
    # The risk book's own clamp still holds above the owner's maximum, and the total stop stays $10.
    clamped = LiveLimits(window_usd=60_000, open_usd=200_000, day_loss_usd=90_000, total_loss_usd=99, clip=30_000)
    assert (clamped.window_usd, clamped.open_usd, clamped.day_loss_usd, clamped.total_loss_usd, clamped.clip) == (
        50_000, 100_000, 30_000, 10, 25_000)


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
    # Provisional until the first look at the boundary has checked everything again.
    assert numbers(book.limits_for(following.slug)) == expected(0) and ladder.state.waiting
    book.update_cash(10_000, current.start + 30)
    assert book.can_buy(current.slug, "up", "take", .4, 6, current.start + 30) == "clip"  # the 5-contract cap
    assert book.can_buy(current.slug, "up", "take", .4, 5, current.start + 30) == ""
    book.update_cash(10_000, following.start)
    assert ladder.due(following.start)
    confirmed = ladder.evaluate(book, following.start)
    assert confirmed["action"] == "confirm" and (confirmed["from_rung"], confirmed["to_rung"]) == (0, 1)
    assert confirmed["promotion"]["ready"] and confirmed["promotion"]["recheck"]
    assert not ladder.due(following.start) and not ladder.state.waiting
    assert numbers(book.limits_for(following.slug)) == expected(1)
    assert numbers(book.limits_now(following.start)) == expected(1)
    assert numbers(book.limits_for(current.slug)) == expected(0)  # the window under way never changed
    book.update_cash(10_000, following.start + 30)
    # Rung 1 keeps the configured 5-contract cap (owner, 2026-10-13: "Keep 5 at every rung").
    assert book.can_buy(following.slug, "up", "take", .4, 5, following.start + 30) == ""
    assert book.can_buy(following.slug, "up", "take", .4, 6, following.start + 30) == "clip"
    assert book.limits_for(following.slug).clip == 5 and book.limits_for(following.slug).window_usd == 15


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
    # A waiting promotion leaves the rung in force's counters running ...
    assert ladder.state.start_pnl == pytest.approx(0) and len(ladder.state.results) == 96
    # ... and they restart at the boundary: window 96 began before it and is not counted at rung 1. From window 97
    # it takes 96 more.
    end = settle_run(book, ladder, 96, "W")
    assert ladder.state.last_change["action"] == "confirm" and ladder.state.results == {}
    assert ladder.state.start_pnl == pytest.approx(97 * WIN)
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
    # Rung 1 windows at the configured 5-contract cap: four losses (-$8.40) give back less than $9 ...
    for index in (97, 98, 99, 100):
        trade(book, index, wins=False, size=5)
        assert ladder.evaluate(book, slot(index).end) is None
    assert ladder.state.peak_pnl == pytest.approx(peak)
    assert ladder.demotion(book)["giveback_usd"] == pytest.approx(8.4)
    # ... a fifth crosses the line: one rung down, from the next window.
    index = 101
    trade(book, index, wins=False, size=5)
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


def rung_one_promoting(*, losses: int = 12) -> tuple[LiveRiskBook, Ladder]:
    """Rung 1 in force with a promotion to rung 2 waiting: 84 wins then `losses` losses of one contract each."""
    book, ladder = setup()
    assert ladder.start(book, T0 - 100, saved_at(1, rung_from=T0 - 100)) == "restored"
    settle_run(book, ladder, 0, "W" * 84 + "L" * losses)
    assert (ladder.state.rung, ladder.state.prior_rung, ladder.state.waiting) == (2, 1, True)
    return book, ladder


def test_a_waiting_promotion_keeps_the_in_force_rungs_demotion_line():
    """At rung 1 the line is the rung's peak less $9 (60 % of its $15 window), not the waiting rung 2's $12. The
    promotion was decided with $5.04 already given back; the rung-1 window under way then loses $4.10."""
    book, ladder = rung_one_promoting()
    rung1_peak = 84 * WIN
    demotion = ladder.demotion(book)
    assert demotion["rung"] == 1 and demotion["peak_pnl_usd"] == pytest.approx(rung1_peak)
    assert demotion["line_usd"] == pytest.approx(rung1_peak - 9) and not demotion["due"]
    assert ladder.panel(book, slot(96).start)["demotion"]["giveback_limit_usd"] == pytest.approx(9)
    current = slot(96)
    assert ladder.rung_for(current.start) == 1
    book.add_window(current)
    book.update_cash(10_000, current.start + 30)
    fill(book, current, "up", .8, 5, current.start + 30)  # rung 1's 5-contract starter at $0.80, lost: -$4.10
    book.settle(current.slug, False, current.end, f"settle-{current.slug}")
    book.update_cash(10_000, current.end)
    record = ladder.evaluate(book, current.end)
    assert book.realized_pnl <= rung1_peak - 9
    assert record["action"] == "demote" and (record["from_rung"], record["to_rung"]) == (1, 0)
    assert record["rung_in_force"] == 1 and "dropping the waiting promotion to rung 2" in record["state"]
    assert record["limits_before"]["window_usd"] == 15 and record["effective_from"] == slot(97).end
    assert (ladder.state.rung, ladder.state.prior_rung, ladder.state.waiting) == (0, 1, False)
    for index in range(97, 100):  # never rung 2: window 97 began at the decision (rung 1), then rung 0
        book.add_window(slot(index))
        assert numbers(book.limits_for(slot(index).slug)) == expected(1 if index == 97 else 0)


def test_open_risk_that_could_cross_the_line_cancels_a_waiting_promotion_at_its_boundary():
    book, ladder = rung_one_promoting()
    current = slot(96)
    book.add_window(current)
    book.update_cash(10_000, current.start + 30)
    fill(book, current, "up", .8, 5, current.start + 30)  # $4.10 at risk, unsettled at the boundary
    book.update_cash(10_000, current.end)
    record = ladder.evaluate(book, current.end)
    assert record["action"] == "cancel" and "giveback" in record["promotion"]["blocked"]
    assert (ladder.state.rung, ladder.state.prior_rung) == (1, 1)
    book.add_window(slot(97))
    assert numbers(book.limits_for(slot(97).slug)) == expected(1)


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
    assert ladder.start(book, T0 + 100, saved_at(2)) == "restored"
    ladder.state.peak_pnl = 12  # $12 given back at rung 2
    record = ladder.evaluate(book, T0 + 100)
    assert (record["from_rung"], record["to_rung"], record["effective_from"]) == (2, 1, T0 + 900)
    ladder.state.peak_pnl = 20  # another full give-back before the boundary
    assert ladder.evaluate(book, T0 + 200) is None and ladder.state.rung == 1
    assert ladder.evaluate(book, T0 + 900)["to_rung"] == 0  # the next step waits for the next boundary


# ---- every limit check at a rung -----------------------------------------------------------------------------

def test_every_check_uses_the_windows_rung():
    # Contract cap: the configured 5 at every rung (owner, 2026-10-13: "Keep 5 at every rung").
    for rung in (0, 1, 2):
        book, _, window = at_rung(rung)
        assert book.can_buy(window.slug, "up", "take", .4, 6, window.start + 10) == "clip"
        assert book.can_buy(window.slug, "up", "take", .4, 5, window.start + 10) == ""
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
    # A lock completes a pair in pieces no larger than the rung's contract cap (the configured 5 at every rung).
    for rung in (0, 1, 2):
        book, _, window = at_rung(rung)
        clip = book.limits_for(window.slug).clip
        assert clip == BASE.clip == 5
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
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "total_loss"  # realized loss reached the entry floor
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
        # The room above the lifetime stop counts the open first buy as lost: $10 less its $2.10.
        assert promotion["gain_needed_usd"] == 0 and promotion["at_risk_usd"] == pytest.approx(2.1)
        assert promotion["room_usd"] == pytest.approx(10 - 2.1)
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
        # Rung 1: a $15 window, and the first buy stays the configured 5 contracts.
        assert [creation["size"] for creation in account.creates] == [5.0]
        assert desk.panel()["caps"] == {"window_usd": 15, "open_usd": 30, "day_stop_usd": 9, "total_stop_usd": 10,
                                        "clip": 5}
        config = desk.twin.config
        assert (config.window_usd, config.open_usd, config.day_stop_usd, config.clip) == (15, 30, 9, 5)
        force_rung(desk, 0, clock.now())
        clock.advance(.5)
        asyncio.run(desk.step())
        assert (desk.twin.config.window_usd, desk.twin.config.clip) == (10, 5)
    finally:
        desk.close()


def test_the_first_buy_stays_at_the_configured_cap_at_every_rung(tmp_path: Path):
    """Owner, 2026-10-13 ~20:15 UTC: "Keep 5 at every rung". The contract cap per order, so the first buy in a
    window, is the configured SPEEDDESK_KALSHI_CLIP (5) at every rung; only the window, open budget and day stop
    grow."""
    for rung in (0, 1, 2):
        limits = rung_limits(BASE, rung)
        assert limits.clip == BASE.clip == 5 and limits.window_usd == 10 + 5 * rung
        book, _, window = at_rung(rung)
        assert book.limits_for(window.slug).clip == 5
        assert book.can_buy(window.slug, "up", "take", .4, 5, window.start + 10) == ""
        assert book.can_buy(window.slug, "up", "take", .4, 6, window.start + 10) == "clip"
    ladder = Ladder(BASE)
    assert ladder.top == 2 and ladder.limits_at_rung(ladder.top).clip == 5  # the top rung too
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        force_rung(desk, 1, clock.now())
        asyncio.run(desk.step())
        assert [creation["size"] for creation in account.creates] == [5.0]  # a $15 window, a 5-contract first buy
        panel = desk.panel()
        assert (panel["caps"]["window_usd"], panel["caps"]["clip"], panel["ladder"]["limits"]["clip"]) == (15, 5, 5)
        assert panel["ladder"]["promotion"]["next_limits"]["clip"] == 5 and desk.twin.config.clip == 5
    finally:
        desk.close()
    # The cap is the configured one, not a fixed 5: a 3-contract setting gives a 3-contract first buy at rung 1.
    desk, account, clock = make_desk(tmp_path / "three", caps=LADDER_CAPS, extra={"speeddesk_kalshi_clip": 3.0})
    try:
        force_rung(desk, 1, clock.now())
        asyncio.run(desk.step())
        assert [creation["size"] for creation in account.creates] == [3.0]
        assert desk.panel()["caps"]["window_usd"] == 15 and desk.panel()["caps"]["clip"] == 3
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
    desk.ladder.state = LadderState(rung=1, prior_rung=0, rung_from=boundary, confirmed=False,
                                    started_at=clock.now(), start_pnl=0.0, peak_pnl=1.5, last_stop_at=clock.now() - 60,
                                    last_change={"action": "promote", "from_rung": 0, "to_rung": 1,
                                                 "effective_from": boundary, "at": clock.now()},
                                    floor=limits_view(desk.book.limits))
    desk.checkpoint(durable=True)
    saved = desk.ledger.get_kv(STATE_KEY)["ladder"]
    assert (saved["rung"], saved["prior_rung"], saved["rung_from"], saved["peak_pnl"]) == (1, 0, boundary, 1.5)
    assert saved["confirmed"] is False and saved["floor"]["window_usd"] == 10
    desk.close()
    restored = KalshiLiveDesk(settings, tmp_path / "live", snapshot, clock=clock.now,
                              client_factory=lambda: None, direct_member_verified=True)
    try:
        state = restored.ladder.state
        assert (state.rung, state.prior_rung, state.rung_from, state.waiting) == (1, 0, boundary, True)
        # The counters come from the saved books, never from the saved numbers: no window settled, so no peak.
        assert state.peak_pnl == 0 and state.start_pnl == 0
        assert state.last_stop_at == clock.now() - 60 and state.last_change["action"] == "promote"
        # The window under way is still rung 0; the waiting promotion starts at its close.
        assert numbers(restored.book.limits_for(TICKER)) == expected(0)
        panel = restored.panel()["ladder"]
        assert panel["change_pending"] and panel["recheck_pending"] and panel["rung"] == 0
        assert panel["pending_limits"]["window_usd"] == 15
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
    {**saved_at(1), "version": 1}, {**saved_at(1), "version": 3}, {**saved_at(1), "rung": -1},
    {**saved_at(1), "rung": True}, {**saved_at(1), "rung_from": float("nan")}, {**saved_at(1), "results": [1]},
    {**saved_at(1), "results": {"x": "y"}}, {**saved_at(1), "last_change": "promote"},
    {**saved_at(1), "confirmed": 1}, {**saved_at(1), "floor": [10]}, {**saved_at(1), "floor": {"window_usd": "x"}},
    {key: value for key, value in saved_at(1).items() if key != "floor"},
    saved_at(2, prior=0, rung_from=T0 + 900, confirmed=False),  # two rungs at one boundary
    saved_at(1, prior=0, rung_from=T0 + 1800, confirmed=False),  # a change beyond the next boundary
    saved_at(1, prior=0, rung_from=T0 + 900, confirmed=True),  # a promotion applied before its boundary
    saved_at(0, prior=1, rung_from=T0 + 900, confirmed=False),  # only a promotion waits for a re-check
    "not a ladder", [1],
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
    settle_run(book, ladder, -40, "W" * 30)  # $17.40 settled before the restart, all of it at the saved rung
    saved = {**saved_at(2, rung_from=0), "last_stop_at": T0 - 5000}
    assert ladder.start(book, T0, saved) == "clamped" and ladder.state.rung == 1
    book.add_window(slot(0))
    assert numbers(book.limits_for(slot(0).slug)) == expected(1)
    # Counters restart after any change (the stop time is kept): nothing the higher rung earned counts at rung 1.
    progress = ladder.promotion(book, T0)
    assert progress["windows"] == 0 and progress["gain_usd"] == 0 and ladder.state.last_stop_at == T0 - 5000
    assert ladder.state.counted_from == ladder.state.rung_from == T0 + 900


def test_saved_state_stays_readable_by_the_previous_release(tmp_path: Path):
    """The previous release reads the books, intents and twin it knows and ignores other top-level keys. The ladder
    adds one top-level key and nothing inside them. After a rollback the old release writes the state back without
    it, and the next upgrade starts again at rung 0 (the configured limits)."""
    desk, account, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    snapshot, settings = desk.snapshot, desk.settings
    try:
        force_rung(desk, 1, clock.now())
        asyncio.run(desk.step())
        assert account.creates and account.creates[0]["size"] == 5.0 and desk.panel()["caps"]["window_usd"] == 15
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
    raw["ladder"]["promotion"]["blocked"] = ["windows", "<script>", "giveback", "window_started"]
    raw["ladder"]["promotion"]["gain_usd"] = float("nan")
    raw["ladder"]["recheck_pending"] = True
    raw["ladder"]["last_change"] = {"action": "confirm", "from_rung": 0, "to_rung": 1, "effective_from": 5.0, "at": 4.0}
    report = {"as_of": clock.now(), "status": "Practice connected", "today": {"day": utc_day(clock.now())},
              "kalshi_live": raw}
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: report)
    settings = make_settings(SPEEDDESK_KALSHI_MODE="live", SPEEDDESK_KALSHI_LIVE_CONFIRM="yes",
                             KALSHI_KEY_ID="fake-panel-key-id", KALSHI_PRIVATE_KEY="fake-panel-key-material")
    ladder = pagestate.speed_desk(settings, clock.now())["kalshi_live"]["ladder"]
    assert ladder["rung"] == 0 and ladder["limits"]["clip"] == 5 and ladder["top_rung"] == 2
    assert ladder["promotion"]["blocked"] == ["windows", "giveback", "window_started"]
    assert ladder["promotion"]["gain_usd"] is None and ladder["recheck_pending"] is True
    assert ladder["promotion"]["at_risk_usd"] == 0 and ladder["promotion"]["gain_counted_usd"] == 0
    assert ladder["promotion"]["room_needed_usd"] == pytest.approx(24.75)
    assert ladder["promotion"]["windows_needed"] == 96 and ladder["promotion"]["cash_needed_usd"] == 30
    assert ladder["demotion"]["at_floor"] and ladder["last_change"]["action"] == "confirm"
    assert ladder["last_change"]["to_rung"] == 1
    assert ladder["configured_max_window_usd"] == 50_000 and ladder["max_window_usd"] == 20
    assert pagestate._kalshi_ladder(None) is None and pagestate._kalshi_ladder("junk") is None


# ---- review findings (2026-10-13 fix round): each test pins the rule a reviewer showed was broken -------------

def test_a_day_that_ran_into_its_daily_stop_blocks_a_promotion():
    """Rule 4. Realized daily loss reaching the entry floor blocks promotion even with 96 completed windows.
    The next attempted buy latches the day stop; an exposure-only refusal would not do so."""
    book, ladder = setup()
    settle_run(book, ladder, 0, "W" * 84)  # Oct 8-9: +$48.72
    settle_run(book, ladder, 128, "L" * 12)  # Oct 10: -$5.04; a thirteenth new buy would now be refused
    assert ladder.state.last_stop_at == slot(139).end and ladder.state.rung == 0  # $0.96 left
    window = slot(142)
    book.add_window(window)
    at = window.start + 10
    book.update_cash(10_000, at)
    assert not book.risk_status(at)["day_stopped"]  # the flag alone never saw it
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "day_stop"
    assert ladder.state.last_stop_at == at  # the book told the ladder at once
    assert ladder.evaluate(book, at) is None and ladder.state.rung == 0
    assert "stops" in ladder.promotion(book, at)["blocked"]


def test_after_a_daily_stop_the_same_utc_day_never_gets_a_bigger_day_stop():
    book, ladder = setup()
    settle_run(book, ladder, 0, "W" * 84)
    settle_run(book, ladder, 128, "L" * 12)  # 96 windows, but only $.96 daily room: no promotion
    stopped, later = slot(142), slot(143)
    book.add_window(stopped)
    book.update_cash(10_000, stopped.start + 10)
    assert book.can_buy(stopped.slug, "up", "take", .4, 1, stopped.start + 10) == "day_stop"
    ladder.evaluate(book, stopped.start + 10)
    book.add_window(later)
    book.update_cash(10_000, later.start + 10)
    assert utc_day(later.start) == utc_day(stopped.start)
    assert book.can_buy(later.slug, "up", "take", .4, 1, later.start + 10) == "day_stop"
    assert book.limits_for(later.slug).day_loss_usd == 6


def test_a_refused_one_contract_buy_is_a_stop_and_a_trimmed_size_is_not():
    book, ladder = setup()
    window = slot(0)
    book.add_window(window)
    at = window.start + 10
    book.update_cash(10_000, at)
    book.day_pnl[utc_day(at)] = -2.5  # $2.50 of today's $6 used
    assert book.can_buy(window.slug, "up", "take", .8, 5, at) == "day_stop"  # 5 x $0.81 does not fit ...
    assert book.can_buy(window.slug, "up", "take", .8, 3, at) == ""  # ... 3 do: the stop only trims the size
    assert book.stop_hit_at is None and ladder.state.last_stop_at is None
    book.day_pnl[utc_day(at)] = -5.7
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "day_stop"  # not even one contract fits
    assert book.stop_hit_at == at and ladder.state.last_stop_at == at
    book.day_pnl[utc_day(at)], book.realized_pnl = 0.0, -9.7  # the lifetime stop binds the same way
    assert book.can_buy(window.slug, "up", "take", .4, 1, at + 1) == "total_loss"
    assert ladder.state.last_stop_at == at + 1


def barely_ready() -> tuple[LiveRiskBook, Ladder, float]:
    """61 wins and 35 losses at rung 0: gain $20.68 against $20.58 needed."""
    book, ladder = setup()
    now = settle_run(book, ladder, 0, "W" * 61 + "L" * 35)
    return book, ladder, now


def test_a_promotion_is_cancelled_when_the_gain_is_gone_by_its_boundary():
    book, ladder, _ = barely_ready()
    assert ladder.state.last_change["action"] == "promote" and ladder.state.waiting
    current = slot(96)
    assert ladder.state.rung_from == current.end and ladder.rung_for(current.start) == 0
    needed = 2 * 1.05 * math.sqrt(96)
    assert 0 < book.realized_pnl - needed < .2  # condition 2 held, barely, at the decision
    book.add_window(current)
    book.update_cash(10_000, current.start + 30)
    fill(book, current, "up", .4, 5, current.start + 30)  # rung 0's 5-contract starter, lost: -$2.10
    for t in (current.start + 60, current.end - 1):
        book.update_cash(10_000, t)
        assert ladder.evaluate(book, t) is None
    book.update_cash(10_000, current.end + .5)
    record = ladder.evaluate(book, current.end + .5)  # unsettled: the $2.10 still open counts as lost
    assert record["action"] == "cancel" and record["promotion"]["blocked"] == ["gain"]
    assert record["promotion"]["gain_counted_usd"] == pytest.approx(book.realized_pnl - 2.1)
    assert ladder.rung_for(slot(97).start) == 0 and not ladder.state.waiting


def test_a_promotion_is_cancelled_when_the_room_above_the_stop_is_gone_by_its_boundary():
    book = LiveRiskBook(BASE)
    # The same -$5.46 lifetime history, spread over two UTC days so every synthetic buy obeys the daily entry
    # floor. Constructing thirteen consecutive losses in one day would itself stop before the last one now.
    for index in (*range(-96, -89), *range(6)):
        trade(book, index, wins=False)
    ladder = Ladder(BASE)
    ladder.start(book, slot(12).end - 1)
    ladder.attach(book)
    outcomes = "WW" + "LW" * 35 + "W" * 24  # 96 windows: 61 wins, 35 losses
    now = settle_run(book, ladder, 13, outcomes)
    record = ladder.state.last_change
    assert record["action"] == "promote" and ladder.state.waiting
    progress = ladder.promotion(book, now)
    assert progress["room_usd"] - progress["room_needed_usd"] == pytest.approx(25.22 - 24.75)
    current = slot(13 + len(outcomes))
    book.add_window(current)
    book.update_cash(10_000, current.start + 10)
    fill(book, current, "up", .4, 5, current.start + 10)
    book.settle(current.slug, False, current.end, f"settle-{current.slug}")
    book.update_cash(10_000, current.end)
    record = ladder.evaluate(book, current.end)
    assert record["action"] == "cancel" and {"gain", "house_money"} <= set(record["promotion"]["blocked"])
    book.add_window(slot(14 + len(outcomes)))
    assert numbers(book.limits_for(slot(14 + len(outcomes)).slug)) == expected(0)


def test_the_cash_for_the_next_open_budget_is_checked_again_at_the_boundary():
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["to_rung"] == 1
    book.update_cash(5, now + 60)  # an owner withdrawal: $5 left against the $30 the new rung's open budget needs
    assert ladder.evaluate(book, now + 61) is None  # before the boundary only a stop or a demotion acts
    book.update_cash(5, slot(96).end)
    record = ladder.evaluate(book, slot(96).end)
    assert record["action"] == "cancel" and record["promotion"]["blocked"] == ["cash"]
    assert ladder.rung_for(slot(97).start) == 0


def test_a_stop_just_before_the_boundary_cancels_the_promotion_at_its_recheck():
    """The desk looks about once a second, so a stop can land between the last look and the boundary."""
    book, ladder, now = ready_ladder()
    boundary = ladder.evaluate(book, now)["effective_from"]
    book.integrity_error = "fill_changed"  # trips half a second before the boundary
    book.update_cash(10_000, boundary + .5)
    record = ladder.evaluate(book, boundary + .5)
    assert record["action"] == "cancel" and "stops" in record["promotion"]["blocked"]
    assert ladder.rung_for(boundary) == 0 and ladder.state.last_stop_at == boundary + .5


def test_a_window_that_traded_before_the_recheck_keeps_its_limits():
    book, ladder, now = ready_ladder()
    assert ladder.evaluate(book, now)["effective_from"] == slot(97).start
    following = slot(97)
    book.add_window(following)
    book.update_cash(10_000, following.start + 1)
    fill(book, following, "up", .4, 5, following.start + 1)  # an order in the new window before the re-check
    record = ladder.evaluate(book, following.start + 2)
    assert record["action"] == "cancel" and record["promotion"]["blocked"] == ["window_started"]
    assert numbers(book.limits_for(following.slug)) == expected(0)  # never changed mid-window
    again = ladder.evaluate(book, following.start + 3)  # the next look decides again, for the window after it
    assert again["action"] == "promote" and again["effective_from"] == following.end


def test_a_cancelled_promotion_leaves_the_rungs_counters_and_line_as_they_were():
    book, ladder = rung_one_promoting()
    state = ladder.state
    before = (state.counted_from, state.started_at, state.start_pnl, state.peak_pnl, dict(state.results),
              ladder.demotion(book)["line_usd"])
    book.integrity_error = "fill_changed"
    record = ladder.evaluate(book, slot(96).start + 60)
    assert record["action"] == "cancel" and (record["from_rung"], record["to_rung"]) == (2, 1)
    state = ladder.state
    assert (state.counted_from, state.started_at, state.start_pnl, state.peak_pnl, dict(state.results),
            ladder.demotion(book)["line_usd"]) == before
    assert len(state.results) == 96 and state.rung == state.prior_rung == 1


@pytest.mark.parametrize("wins", [False, True])
def test_an_earlier_rungs_window_that_settles_after_the_change_is_not_counted_at_the_new_rung(wins):
    book, ladder = setup()
    for index in range(96):
        trade(book, index)
    window = slot(96)
    book.add_window(window)
    book.update_cash(10_000, window.start + 10)
    fill(book, window, "up", .4, 5, window.start + 10)  # rung 0's window under way
    book.update_cash(10_000, window.start + 60)
    assert ladder.evaluate(book, window.start + 60)["action"] == "promote"
    book.update_cash(10_000, window.end)
    assert ladder.evaluate(book, window.end)["action"] == "confirm"
    book.settle(window.slug, wins, window.end + 30, "settle-late")  # settles after the boundary: +$2.90 or -$2.10
    book.update_cash(10_000, window.end + 31)
    assert ladder.evaluate(book, window.end + 31) is None
    progress, demotion = ladder.promotion(book, window.end + 31), ladder.demotion(book)
    assert progress["windows"] == 0 and progress["gain_usd"] == pytest.approx(0)
    assert demotion["giveback_usd"] == pytest.approx(0)
    assert demotion["peak_pnl_usd"] == pytest.approx(book.realized_pnl) == ladder.state.start_pnl
    # A restart rebuilds the same numbers from the books.
    restored = Ladder(BASE)
    assert restored.start(book, window.end + 32, json.loads(json.dumps(ladder.to_state()))) == "restored"
    assert (restored.state.start_pnl, restored.state.peak_pnl) == pytest.approx(
        (ladder.state.start_pnl, ladder.state.peak_pnl))


@pytest.mark.parametrize(("floor", "saved_rung"), [(15, 1), (5, 2)])
def test_changing_the_configured_floor_starts_the_ladder_again_at_rung_zero(floor, saved_rung):
    """Rungs earned at a $10 floor mean nothing at another: raising it to $15 would stack rung 1 to $20; lowering it
    to $5 to cut risk would still trade $15 windows with $30 open."""
    base = LiveLimits(window_usd=floor, open_usd=2 * floor, day_loss_usd=min(6.0, .6 * floor) if floor < 10 else 9,
                      total_loss_usd=10, clip=5, fee_precision=.0001)
    book = LiveRiskBook(base)
    ladder = Ladder(base)
    saved = {**saved_at(saved_rung, rung_from=T0 - 900), "last_stop_at": T0 - 60}
    assert ladder.start(book, T0, saved) == "rebased"
    ladder.attach(book)
    assert numbers(book.limits_now(T0 + 10)) == numbers(base) and ladder.state.rung == 0
    assert ladder.state.last_stop_at == T0 - 60 and ladder.to_state()["floor"]["window_usd"] == floor


def test_the_contract_cap_has_its_own_ceiling_in_the_risk_book():
    limits = LiveLimits(window_usd=50_000, open_usd=100_000, day_loss_usd=30_000, clip=25_000)
    assert (limits.window_usd, limits.clip) == (20, 25)
    assert LiveLimits(clip=5).clip == 5 and LiveLimits(clip=25).clip == 25


def test_the_room_counts_money_at_risk_and_a_resume_anchor_above_zero():
    book, ladder, now = ready_ladder()
    book.stop_anchor = 45.0  # a resume token taken at +$45: the lifetime stop now trips at +$35
    progress = ladder.promotion(book, now)
    assert progress["room_usd"] == pytest.approx(96 * WIN + 10 - 45) and "house_money" in progress["blocked"]
    book.stop_anchor = -3.0  # an anchor below zero never adds room
    assert ladder.promotion(book, now)["room_usd"] == pytest.approx(96 * WIN + 10)


def test_the_desk_rechecks_a_waiting_promotion_at_once_at_its_boundary(tmp_path: Path):
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        boundary = clock.now() + .5
        desk.ladder.state = LadderState(rung=1, prior_rung=0, rung_from=boundary, confirmed=False,
                                        started_at=clock.now(), floor=limits_view(desk.book.limits))
        desk._ladder_step()  # a look half a second before the boundary
        assert desk.ladder.state.waiting
        clock.advance(.6)  # within the one-second spacing, but the boundary has passed
        desk._ladder_step()
        changes = [item for item in desk.latest_events if item["event"] == "speeddesk_live_ladder"
                   and item.get("action") == "cancel"]
        assert changes and "windows" in changes[-1]["promotion"]["blocked"]
        assert not desk.ladder.state.waiting and desk.ladder.rung_for(clock.now()) == 0
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["total", "day"])
def test_a_restart_notes_a_saved_stop_before_a_token_clears_it(tmp_path: Path, stop: str):
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        if stop == "total":
            desk.book.halted, desk.book.halt_reason = True, "total_loss"
        else:  # today's loss counted from a +$6 mark: the $6 day stop is used up
            desk.book.day_anchor = {utc_day(clock.now()): 6.0}
        desk.ladder.state.last_stop_at = None
        desk.checkpoint(durable=True)
    finally:
        desk.close()
    token = ({"speeddesk_kalshi_resume_token": Secret("owner-resume-1")} if stop == "total"
             else {"speeddesk_kalshi_day_reset_token": Secret("owner-day-reset-1")})
    again, _, clock = make_desk(tmp_path, caps=LADDER_CAPS, extra=token)
    try:
        assert not again.book.halted and again.book.day_loss(clock.now()) == 0  # the token cleared the stop ...
        assert again.ladder.state.last_stop_at == clock.now()  # ... after the ladder noted it
        assert "stops" in again.ladder.promotion(again.book, clock.now())["blocked"]
    finally:
        again.close()


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
        ladder.attach(book)
        for spec in book.windows.values():
            if spec.start <= now < spec.end:
                assert ladder.rung_for(spec.start) == self.ladder.rung_for(spec.start)
        assert (ladder.state.start_pnl, ladder.state.peak_pnl) == pytest.approx(
            (self.ladder.state.start_pnl, self.ladder.state.peak_pnl))
        assert ladder.promotion(book, now)["windows"] == self.ladder.promotion(self.book, now)["windows"]
        self.book, self.ladder = book, ladder
        self.counts["restart"] += 1

    def observe(self, window: Window, now: float) -> None:
        """A window's rung is fixed from its first order to its close (a waiting promotion applies only to windows
        that have not traded), and a window is at most one rung from the window before it."""
        assert 0 <= self.ladder.state.rung <= self.ladder.top == 3
        rung = self.ladder.rung_for(window.start)
        if window.slug in self.pinned:
            assert self.pinned[window.slug] == rung
        else:
            assert self.last_pinned is None or abs(rung - self.last_pinned) <= 1
        assert (numbers(self.book.limits_for(window.slug)) == expected(rung, RUN_BASE)
                == numbers(self.book.limits_now(now)))

    def pin(self, window: Window) -> None:
        if window.slug not in self.pinned:
            rung = self.ladder.rung_for(window.start)
            assert self.last_pinned is None or abs(rung - self.last_pinned) <= 1
            self.pinned[window.slug], self.last_pinned = rung, rung

    def look(self, now: float) -> None:
        before = self.ladder.state.rung
        record = self.ladder.evaluate(self.book, now)
        if record is None:
            assert self.ladder.state.rung == before
            return
        self.counts[record["action"]] += 1
        if record["action"] in ("promote", "confirm"):
            assert record["promotion"]["ready"] and record["promotion"]["blocked"] == []
            assert record["to_rung"] == record["from_rung"] + 1 and record["promotion"]["windows"] >= 3
        else:
            assert record["action"] == "cancel" or record["demotion"]["due"]
            assert record["to_rung"] == record["from_rung"] - 1 >= 0
        if record["action"] in ("promote", "demote"):
            assert record["effective_from"] > now
        else:  # the re-check of a waiting promotion, at or after its boundary (or a stop before it)
            assert record["action"] == "cancel" or record["effective_from"] <= now
            assert not self.ladder.state.waiting

    def buy(self, window: Window, now: float, *, lock: bool) -> None:
        self.pin(window)
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
        light_side, unpaired = book.lock_side(window.slug)
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
            # The stops count the buy's new risk: a strictly balancing contract (light side, within the unpaired
            # count, under $1 with fees) completes a $1 pair and is exempt like a lock (2026-10-14); the rest counts.
            balancing = min(size, unpaired) if side == light_side and intent.unit_reserve < 1 else 0
            risk = cost - balancing * intent.unit_reserve
            assert day_loss + at_risk + risk < day_usd
            assert total_loss + at_risk + risk < 10
            if risk < cost:
                self.counts["balancing"] += 1
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
    assert totals["confirm"] >= 5 and totals["demote"] >= 2 and totals["lock"] > 0, totals
    assert all(totals["refused_" + reason] for reason in ("clip", "window_budget", "day_stop", "total_budget",
                                                          "cash_budget")), totals
