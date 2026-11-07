"""Attribution: the parts always add up to the trade (docs/EXPERIENCE.md §6.2, G50, DP-05). Pure.

Each step changes ONE thing, so the chain telescopes::

    a0  universe mean of R-host x as of t_dec (snapshot receipted before)  market      = a0      nobody
    a   as-of mean R-host x of the trade's cell                            cell_choice = a - a0  Crawler
    b   this coin: K = 20 hash-chosen entries within +-30 min, placebo     selection   = b - a   Cocoon, Strategy
    c   this coin, the actual t_dec, placebo exits                         timing      = c - b   Strategy
    d   this coin, t_dec, the rule's exits (radar too), mid, no delay      exit        = d - c   exits, Radar
    e   the actual entry and exit landing times, at mid, no costs          delay       = e - d   Broker, cadence
    r   the actual net return                                              costs       = r - e   Broker

so ``r = market + cell_choice + selection + timing + exit + delay + costs`` exactly. a0 and a are NET means of other
coins' outcomes (AO-8); b to e are GROSS returns at mid on the graded coin's own path. ``cost_floor`` (the as-of
universe mean cost of a random trade, ``mean(g - x)`` of the same snapshot) is taken off b to e so the cost floor
stays in ``market`` ("market drift and the cost floor", charged to nobody) and ``costs`` holds only the excess over
it; with ``cost_floor = 0`` the steps are exactly the table's. Luck sits inside every part: single post-mortems are
never acted on.

Placebo exits use holding times drawn (hash-seeded) from the version's own holding-time distribution, frozen from
trades that closed before the week began (:func:`frozen_holds`, >= 20 of them); without one, the trade's own hold.
Step d needs one zero-delay, zero-cost replay of the coin, done by the caller. A step that cannot be computed
(censored draws, no replay) takes the previous step's value - its part is 0 - and is listed in ``missing``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nightcrawler.experience.constants import ATTR_ENTRY_DRAWS, ATTR_WINDOW_S, PARTS, PLACEBO_HOLDS_MIN
from nightcrawler.experience.stats import hash_key
from nightcrawler.learn.labels import Bar, BarSeries

__all__ = ["Steps", "parts", "entry_times", "placebo_holds", "frozen_holds", "mid_return", "selection_step",
           "timing_step", "attribute"]


@dataclass(frozen=True)
class Steps:
    a0: float
    a: float
    b: float
    c: float
    d: float
    e: float
    r: float


def parts(steps: Steps, cost_floor: float = 0.0) -> dict[str, float]:
    """The seven parts (in :data:`~nightcrawler.experience.constants.PARTS` order) of a full chain of steps."""
    b, c, d, e = (v - cost_floor for v in (steps.b, steps.c, steps.d, steps.e))
    values = (steps.a0, steps.a - steps.a0, b - steps.a, c - b, d - c, e - d, steps.r - e)
    return dict(zip(PARTS, values, strict=True))


def entry_times(mint: str, t_dec: float, *, k: int = ATTR_ENTRY_DRAWS, window_s: float = ATTR_WINDOW_S) -> list[float]:
    """Step b's ``k`` entry times, hash-chosen within ``t_dec +- window_s`` (whole seconds)."""
    span = 2 * int(window_s) + 1
    return [t_dec + int(hash_key(f"attr:entry:{mint}:{i}"), 16) % span - int(window_s) for i in range(k)]


def placebo_holds(mint: str, holds: Sequence[float], k: int, *, salt: str) -> list[float]:
    """``k`` holding times drawn, hash-seeded, from ``holds`` (the input order does not matter)."""
    ordered = sorted(float(h) for h in holds)
    return [ordered[int(hash_key(f"attr:hold:{salt}:{mint}:{i}"), 16) % len(ordered)] for i in range(k)]


def frozen_holds(trades: Iterable[Mapping[str, Any]], week_start: float) -> list[float] | None:
    """The version's holding times (``t_out - t_in``) of trades closed before ``week_start``; None below 20."""
    holds = sorted(float(t["t_out"]) - float(t["t_in"]) for t in trades
                   if isinstance(t.get("t_out"), (int, float)) and isinstance(t.get("t_in"), (int, float))
                   and t["t_out"] < week_start)
    return holds if len(holds) >= PLACEBO_HOLDS_MIN else None


def _mid(series: BarSeries, t_in: float, t_out: float) -> float | None:
    if t_out > series.end or t_out < t_in:
        return None
    p_in, p_out = series.close_at(t_in), series.close_at(t_out)
    return None if p_in is None or p_out is None or p_in <= 0 else p_out / p_in - 1.0


def mid_return(bars: Sequence[Bar], t_in: float, t_out: float, *, end_ts: float | None = None) -> float | None:
    """Gross return at mid from the close at ``t_in`` to the close at ``t_out`` (None past the data)."""
    return _mid(BarSeries(bars, end_ts), float(t_in), float(t_out))


def _mean(values: Iterable[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return math.fsum(known) / len(known) if known else None


def selection_step(bars: Sequence[Bar], mint: str, t_dec: float, holds: Sequence[float], *,
                   end_ts: float | None = None) -> float | None:
    """Step b: mean gross return over the coin's hash-chosen entry times around ``t_dec`` with placebo exits."""
    series = BarSeries(bars, end_ts)
    times = entry_times(mint, t_dec)
    holds_b = placebo_holds(mint, holds, len(times), salt="b")
    return _mean(_mid(series, t, t + h) for t, h in zip(times, holds_b, strict=True))


def timing_step(bars: Sequence[Bar], mint: str, t_dec: float, holds: Sequence[float], *,
                end_ts: float | None = None) -> float | None:
    """Step c: mean gross return entering at ``t_dec`` with placebo exits."""
    series = BarSeries(bars, end_ts)
    return _mean(_mid(series, t_dec, t_dec + h) for h in placebo_holds(mint, holds, ATTR_ENTRY_DRAWS, salt="c"))


def attribute(*, bars: Sequence[Bar], mint: str, t_dec: float, t_in: float, t_out: float, a0: float, a: float,
              d: float | None, r: float, holds: Sequence[float] | None = None, cost_floor: float = 0.0,
              end_ts: float | None = None) -> dict[str, Any]:
    """The post-mortem attribution of one trade: ``{"parts", "steps", "missing"}`` (see the module docstring).
    ``d`` is the caller's zero-delay, zero-cost replay of the rule's exits from ``t_dec`` (None if not run)."""
    holds = list(holds) if holds else [max(0.0, t_out - t_in)]
    b = selection_step(bars, mint, t_dec, holds, end_ts=end_ts)
    c = timing_step(bars, mint, t_dec, holds, end_ts=end_ts)
    e = mid_return(bars, t_in, t_out, end_ts=end_ts)
    missing = [name for name, v in (("b", b), ("c", c), ("d", d), ("e", e)) if v is None]
    b_adj = a if b is None else b - cost_floor
    c_adj = b_adj if c is None else c - cost_floor
    if d is not None:
        d_adj = d - cost_floor
    else:
        d_adj = c_adj if e is None else e - cost_floor  # no replay: the exit's effect is not split from the delay
    e_adj = d_adj if e is None else e - cost_floor
    return {"parts": parts(Steps(a0, a, b_adj, c_adj, d_adj, e_adj, r)),
            "steps": {"a0": a0, "a": a, "b": b, "c": c, "d": d, "e": e, "r": r, "cost_floor": cost_floor},
            "missing": missing}
