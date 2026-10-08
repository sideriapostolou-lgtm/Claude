"""Pure strategy functions shared by the live engine and the backtester (owner: O3).

NO IO, NO clock reads, NO randomness: every function is a deterministic
function of its arguments, so a backtest replays exactly what live would do.

THE SETUP: "dip-rebound"
------------------------
A fresh memecoin pumps, dumps hard, and buyers come back. We only buy AFTER
the rebound is confirmed on CLOSED candles - never "the exact bottom".

``entry_signal`` returns ``Signal(kind="enter")`` iff ALL hold (else
``kind="none"`` with the first failing reason):

1. Use only closed 1m candles: ``c.ts + 60 <= now``. Need at least
   ``confirm_green + 2`` of them (reason ``"insufficient data"``).
2. Window = closed candles with ``ts >= now - dip_lookback_h*3600`` (if the
   token is younger, that is simply all candles since the first one).
3. ``H`` = max high in the window (first occurrence wins ties), at index ``iH``;
   ``L`` = min low of the candles AFTER ``iH``. ``dip = 1 - L/H`` (fraction).
   Require ``dip >= dip_pct`` (reason ``"dip x% < required y%"``).
4. Not chasing: last close ``<= H * (1 - dip_pct / 2)`` (still at least half
   the required dip below the high).
5. Buyers return: the last ``confirm_green`` closed candles are all green
   (``c > o``) AND (last close > previous candle's high OR last volume >
   previous volume).
6. If ``snapshot`` is given: ``snapshot.buy_sell_ratio_m5`` must be not None
   and ``>= min_buy_sell_ratio``. (Backtests pass ``snapshot=None``; that
   check is then skipped - documented optimism.)

``metrics`` on every result (when computable): ``high, high_ts, low, low_ts,
dip, last_close, last_ts, green_run, ratio_m5, candles_used``.
``confidence``: heuristic in [0, 1], 0 for ``none``.

EXITS (``exit_signal``) - first match wins:

1. ``radar`` flagged -> exit all, reason ``"radar: <first reason>"``.
2. Stop loss: ``price_now <= entry * (1 - stop_loss_pct)`` -> exit all ``"stop_loss"``.
3. Time stop: ``now - opened_at >= max_hold_min*60`` -> exit all ``"time_stop"``.
4. Partial take-profit (once): not ``partial_taken`` and
   ``price_now >= entry * (1 + take_profit_pct)`` -> ``fraction=partial_tp_fraction``,
   ``"take_profit_partial"``.
5. Trailing stop (only after the partial): ``price_now <= peak * (1 - trail_pct)``
   -> exit all ``"trailing_stop"``.
6. Otherwise ``kind="none"``, reason ``"hold"``.

``peak`` = max(position.peak_price_usd, price_now, highs of closed candles
with ``ts >= opened_at``); returned as ``metrics["peak_price_usd"]`` so the
caller can persist it. ``entry`` = ``position.entry_price_usd``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nightcrawler.models import Candle, MarketSnapshot, Position, RadarSignal, Signal, StrategyParams

__all__ = [
    "CANDLE_INTERVAL_S",
    "ExitLevels",
    "closed_candles",
    "rolling_high",
    "entry_signal",
    "exit_signal",
    "exit_levels",
]

CANDLE_INTERVAL_S = 60


@dataclass(frozen=True, slots=True)
class ExitLevels:
    """Absolute USD price levels for a position (used by the backtester intrabar).

    ``take_profit`` is None once the partial was taken; ``trail`` is None
    before it. All prices are USD per whole token.
    """

    stop: float
    take_profit: float | None
    trail: float | None
    time_stop_ts: float


def closed_candles(candles: Sequence[Candle], now: float, interval_s: int = CANDLE_INTERVAL_S) -> list[Candle]:
    """Candles with ``ts + interval_s <= now`` (input must be ascending; order preserved)."""
    raise NotImplementedError


def rolling_high(candles: Sequence[Candle], now: float, lookback_h: float) -> tuple[float, int] | None:
    """``(high, index)`` of the max high among candles with ``ts >= now - lookback_h*3600``.

    ``index`` refers to the input sequence. None if no candle qualifies.
    First occurrence wins ties.
    """
    raise NotImplementedError


def entry_signal(candles: Sequence[Candle], snapshot: MarketSnapshot | None, params: StrategyParams,
                 now: float) -> Signal:
    """Dip-rebound entry check (see module docstring). ``candles`` ascending 1m, may include an open candle."""
    raise NotImplementedError


def exit_signal(position: Position, candles: Sequence[Candle], price_now: float, params: StrategyParams,
                now: float, radar: RadarSignal | None = None) -> Signal:
    """Exit check for an OPEN position (see module docstring for order and reasons).

    ``price_now``: latest USD price per whole token (Jupiter price v3 live;
    the simulated intrabar price in backtests). ``kind="exit"`` with
    ``fraction`` in (0, 1]; ``metrics`` always includes ``peak_price_usd``,
    ``pnl_pct`` (percent vs entry) and ``held_min``.
    """
    raise NotImplementedError


def exit_levels(position: Position, params: StrategyParams) -> ExitLevels:
    """Price levels implied by ``position`` and ``params`` (stop, TP or trail, time stop)."""
    raise NotImplementedError
