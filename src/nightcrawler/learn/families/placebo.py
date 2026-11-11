"""Family ``placebo``: the control that MUST lose (docs/LEARNING.md §4.4).

Entry at the first decision at or after a hash-chosen offset in ``[g + min_age, g + min_age + 6 h)``
(``g`` = the coin's creation time) where the benchmark's universe check passes; the benchmark's exits,
costs and fills. It knows nothing about prices, so its mean must sit near the cost of trading (the lab
measured -6.4 % per trade). A placebo that looks profitable means the simulator is optimistic:
phase 2 freezes promotions when its last 300 trades average above -1 %. Never promotable, spends no
alpha.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from nightcrawler.models import Candle, MarketSnapshot, Signal, StrategyParams

NAME = "placebo"
PROMOTABLE = False
CONTROL = True
#: Width of the entry window after maturity (hours).
WINDOW_H = 6


def offset_s(mint: str) -> int:
    """Seconds after maturity at which the placebo enters ``mint`` (a hash, never randomness)."""
    digest = hashlib.sha256(f"placebo:{mint}".encode()).hexdigest()
    return int(digest, 16) % (WINDOW_H * 3600)


def entry_fn(mint: str, created_ts: float) -> Callable[[Sequence[Candle], MarketSnapshot | None, StrategyParams, float],
                                                       Signal]:
    def placebo_entry(candles: Sequence[Candle], snapshot: MarketSnapshot | None, params: StrategyParams,
                      now: float) -> Signal:
        due = created_ts + params.min_age_min * 60 + offset_s(mint)
        last = candles[-1] if candles else None
        metrics = {"due_ts": due, "last_ts": last.ts if last else None, "last_close": last.c if last else None}
        if now < due or last is None:
            return Signal(kind="none", reason="placebo: not yet", confidence=0.0, metrics=metrics)
        return Signal(kind="enter", reason="placebo", confidence=0.0, metrics=metrics)

    return placebo_entry
