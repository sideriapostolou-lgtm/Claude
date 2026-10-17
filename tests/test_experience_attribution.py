"""Attribution: the parts always add up to the trade (docs/EXPERIENCE.md §6.2, §11 ``test_attribution_identity``).

``r = market + cell choice + selection + timing + exit + delay + costs`` holds exactly (to 1e-9) over 1,000 synthetic
paths; constructed cases give the expected signs; a0 and a use only other coins' outcomes (AO-8), so the graded
coin's own later prices cannot move them; missing steps never break the identity.
"""

from __future__ import annotations

import math
import random

import pytest

from nightcrawler.experience import attribution as att
from nightcrawler.experience.constants import ATTR_ENTRY_DRAWS, ATTR_WINDOW_S, PARTS, PLACEBO_HOLDS_MIN
from nightcrawler.models import Candle


def path(prices: list[float], start: int = 0) -> list[Candle]:
    return [Candle(start + 60 * i, p, p, p, p, 1.0) for i, p in enumerate(prices)]


def random_path(rng: random.Random, minutes: int = 600) -> list[Candle]:
    price, out = rng.uniform(1e-4, 1e-3), []
    for _ in range(minutes):
        price *= math.exp(rng.gauss(-0.001, 0.03))
        out.append(price)
    return path(out)


def test_the_seven_parts_always_sum_to_the_trade() -> None:
    rng = random.Random(1)
    for _ in range(1000):
        steps = att.Steps(*(rng.uniform(-1, 1) for _ in range(7)))
        parts = att.parts(steps, cost_floor=rng.uniform(0, 0.1))
        assert tuple(parts) == PARTS
        assert abs(math.fsum(parts.values()) - steps.r) < 1e-9


def test_the_identity_holds_on_real_paths_with_missing_steps() -> None:
    rng = random.Random(2)
    for i in range(1000):
        bars = random_path(rng)
        t_dec = 60.0 * rng.randint(0, 590)
        t_in = t_dec + rng.uniform(0, 300)
        t_out = t_in + rng.uniform(0, 4 * 3600)
        r = rng.uniform(-1, 1)
        holds = [rng.uniform(60, 7200) for _ in range(rng.choice((0, 5, 30)))]
        d = None if i % 7 == 0 else rng.uniform(-1, 1)
        out = att.attribute(bars=bars, mint=f"M{i}", t_dec=t_dec, t_in=t_in, t_out=t_out, a0=rng.uniform(-0.2, 0),
                            a=rng.uniform(-0.3, 0.1), d=d, r=r, holds=holds, cost_floor=0.02)
        assert abs(math.fsum(out["parts"].values()) - r) < 1e-9
        assert set(out["missing"]) <= {"b", "c", "d", "e"}
        if d is None:
            assert "d" in out["missing"]


def test_constructed_cases_have_the_expected_signs() -> None:
    # flat at 1.0 for 2 hours, then a steady rise: entering exactly at the turn is the best timing
    t_dec = 7200.0
    prices = [1.0] * 120 + [1.0 + 0.002 * k for k in range(1, 361)]
    bars = path(prices)
    hold = 1800.0
    d = att.mid_return(bars, t_dec, t_dec + 3600)  # the rule's exits held longer than the placebo: better
    t_in, t_out = t_dec + 240.0, t_dec + 3600.0  # landed 4 minutes late on a rising price
    e = att.mid_return(bars, t_in, t_out)
    assert d is not None and e is not None
    r = e - 0.03  # costs
    out = att.attribute(bars=bars, mint="M", t_dec=t_dec, t_in=t_in, t_out=t_out, a0=-0.06, a=-0.04, d=d, r=r,
                        holds=[hold] * PLACEBO_HOLDS_MIN)
    p = out["parts"]
    assert out["missing"] == []
    assert p["market"] == pytest.approx(-0.06) and p["cell_choice"] == pytest.approx(0.02)
    assert p["timing"] > 0  # entering at the turn beat random times around it
    assert p["exit"] > 0  # the rule's exit beat placebo exits
    assert p["delay"] < 0  # landing later on a rising price cost
    assert p["costs"] == pytest.approx(-0.03)
    assert math.fsum(p.values()) == pytest.approx(r, abs=1e-9)


def test_a_cost_floor_stays_with_the_market_part() -> None:
    steps = att.Steps(a0=-0.05, a=-0.05, b=0.0, c=0.0, d=0.0, e=0.0, r=-0.03)
    plain = att.parts(steps)
    floored = att.parts(steps, cost_floor=0.03)
    assert plain["selection"] == pytest.approx(0.05) and plain["costs"] == pytest.approx(-0.03)
    # with the as-of cost floor, a coin exactly as good as its cell selects nothing and executes at the floor
    assert floored["selection"] == pytest.approx(0.02) and floored["costs"] == pytest.approx(0.0)


def test_market_and_cell_parts_never_read_the_graded_coins_future() -> None:
    rng = random.Random(3)
    bars = random_path(rng)
    t_dec = 60.0 * 200
    kwargs = dict(mint="M", t_dec=t_dec, t_in=t_dec + 30, t_out=t_dec + 3600, a0=-0.05, a=-0.02, d=0.01, r=-0.1,
                  holds=[1200.0] * 25)
    first = att.attribute(bars=bars, **kwargs)
    later = [b if b.ts + 60 <= t_dec else Candle(b.ts, b.o * 7, b.h * 7, b.l * 7, b.c * 7, b.v) for b in bars]
    second = att.attribute(bars=later, **kwargs)
    assert first["parts"]["market"] == second["parts"]["market"]
    assert first["parts"]["cell_choice"] == second["parts"]["cell_choice"]
    assert first["parts"]["selection"] != second["parts"]["selection"]  # the coin's own path is used from b on


def test_entry_draws_and_placebo_holds_are_hash_seeded() -> None:
    times = att.entry_times("MintA", 10_000.0)
    assert len(times) == ATTR_ENTRY_DRAWS and times == att.entry_times("MintA", 10_000.0)
    assert all(abs(t - 10_000.0) <= ATTR_WINDOW_S for t in times) and times != att.entry_times("MintB", 10_000.0)
    holds = [float(h) for h in range(60, 60 * 41, 60)]
    picks = att.placebo_holds("MintA", holds, 20, salt="c")
    assert picks == att.placebo_holds("MintA", list(reversed(holds)), 20, salt="c")  # order of the input is irrelevant
    assert set(picks) <= set(holds)


def test_frozen_holds_use_only_trades_closed_before_the_week_and_need_twenty() -> None:
    trades = [{"t_in": 100.0 * i, "t_out": 100.0 * i + 600 + i} for i in range(30)]
    week_start = 100.0 * 25 + 600
    holds = att.frozen_holds(trades, week_start)
    assert holds is not None and len(holds) == 25 and holds == sorted(holds)
    assert att.frozen_holds(trades[:PLACEBO_HOLDS_MIN - 1], 1e9) is None
