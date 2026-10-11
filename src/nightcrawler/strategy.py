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
   token is younger, that is simply all candles since the first one). The
   window must also hold ``confirm_green + 2`` candles (same reason) - a
   data gap must not let a stale high or a single candle decide.
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
``confidence``: heuristic in [0, 1], 0 for ``none`` (see :func:`_entry_confidence`).

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
caller can persist it. ``entry`` = ``position.entry_price_usd`` (must be > 0,
else ``ValueError``). A radar result with ``error`` set but not ``flagged``
is ignored here (an outage is not an exit trigger).

NO LOOKAHEAD: both signals look only at candles with ``ts + 60 <= now``, so
appending any candle that was still open (or not yet started) at ``now``
can never change a decision made at ``now``. ``tests/test_strategy.py``
proves this by appending arbitrary future candles.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Sequence

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
    return [c for c in candles if c.ts + interval_s <= now]


def rolling_high(candles: Sequence[Candle], now: float, lookback_h: float) -> tuple[float, int] | None:
    """``(high, index)`` of the max high among candles with ``ts >= now - lookback_h*3600``.

    ``index`` refers to the input sequence. None if no candle qualifies.
    First occurrence wins ties.
    """
    since = now - lookback_h * 3600
    best: tuple[float, int] | None = None
    for i, c in enumerate(candles):
        if c.ts >= since and (best is None or c.h > best[0]):
            best = (c.h, i)
    return best


# --------------------------------------------------------------------------- entry


def entry_signal(candles: Sequence[Candle], snapshot: MarketSnapshot | None, params: StrategyParams,
                 now: float) -> Signal:
    """Dip-rebound entry check (see module docstring). ``candles`` ascending 1m, may include an open candle."""
    need = params.confirm_green + 2
    since = now - params.dip_lookback_h * 3600
    window = [c for c in closed_candles(candles, now) if c.ts >= since]
    if len(window) < need:  # the window is a subset of the closed candles, so this covers rule 1 too
        return _none(f"insufficient data: {len(window)} closed candles in window < {need}",
                     {"candles_used": len(window)})

    found = rolling_high(window, now, params.dip_lookback_h)
    assert found is not None  # the window is non-empty and inside the lookback by construction
    high, i_high = found
    after_high = window[i_high + 1:]
    low_candle = min(after_high, key=lambda c: c.l) if after_high else window[i_high]
    last, prev = window[-1], window[-2]
    ratio = snapshot.buy_sell_ratio_m5 if snapshot is not None else None
    metrics: dict[str, Any] = {
        "high": high,
        "high_ts": window[i_high].ts,
        "low": low_candle.l,
        "low_ts": low_candle.ts,
        "dip": 1.0 - low_candle.l / high if after_high and high > 0 else 0.0,
        "last_close": last.c,
        "last_ts": last.ts,
        "green_run": _green_run(window),
        "ratio_m5": ratio,
        "candles_used": len(window),
    }

    dip = metrics["dip"]
    if dip < params.dip_pct:
        return _none(f"dip {dip:.1%} < required {params.dip_pct:.1%}", metrics)
    chase_ceiling = high * (1.0 - params.dip_pct / 2)
    if last.c > chase_ceiling:
        below = 1.0 - last.c / high
        return _none(f"chasing: last close {below:.1%} below high < {params.dip_pct / 2:.1%}", metrics)
    if metrics["green_run"] < params.confirm_green:
        return _none(f"buyers not back: {metrics['green_run']} green closes < {params.confirm_green}", metrics)
    breakout = last.c > prev.h
    volume_up = last.v > prev.v
    if not (breakout or volume_up):
        return _none("buyers not back: no close above prior high and no rising volume", metrics)
    if snapshot is not None and (ratio is None or ratio < params.min_buy_sell_ratio):
        shown = "n/a" if ratio is None else f"{ratio:.2f}"
        return _none(f"buy/sell ratio {shown} < {params.min_buy_sell_ratio:.2f}", metrics)

    confidence = _entry_confidence(dip, params, breakout, volume_up, ratio)
    reason = f"dip-rebound: dip {dip:.1%} from high, {metrics['green_run']} green closes"
    return Signal(kind="enter", reason=reason, confidence=confidence, metrics=metrics)


def _none(reason: str, metrics: dict) -> Signal:
    return Signal(kind="none", reason=reason, confidence=0.0, metrics=metrics)


def _green_run(candles: Sequence[Candle]) -> int:
    """Number of consecutive green candles at the end of ``candles``."""
    run = 0
    for c in reversed(candles):
        if not c.green:
            break
        run += 1
    return run


def _entry_confidence(dip: float, params: StrategyParams, breakout: bool, volume_up: bool,
                      ratio: float | None) -> float:
    """Heuristic in [0, 1]: 0.5 base, + up to 0.2 for dip beyond the requirement,
    + 0.1 each for a breakout close and rising volume, + 0.1 for strong 5m buying
    (ratio >= 1.5x the required ratio, at least 1.5)."""
    score = 0.5 + min(0.2, max(0.0, dip - params.dip_pct))
    score += 0.1 if breakout else 0.0
    score += 0.1 if volume_up else 0.0
    if ratio is not None and ratio >= 1.5 * max(params.min_buy_sell_ratio, 1.0):
        score += 0.1
    return round(min(1.0, score), 4)


# --------------------------------------------------------------------------- exit


def exit_levels(position: Position, params: StrategyParams) -> ExitLevels:
    """Price levels implied by ``position`` and ``params`` (stop, TP or trail, time stop).

    ``trail`` uses ``max(position.peak_price_usd, entry)`` as the peak.
    """
    entry = _entry_price(position)
    peak = max(position.peak_price_usd, entry)
    return ExitLevels(
        stop=entry * (1.0 - params.stop_loss_pct),
        take_profit=None if position.partial_taken else entry * (1.0 + params.take_profit_pct),
        trail=peak * (1.0 - params.trail_pct) if position.partial_taken else None,
        time_stop_ts=position.opened_at + params.max_hold_min * 60,
    )


def exit_signal(position: Position, candles: Sequence[Candle], price_now: float, params: StrategyParams,
                now: float, radar: RadarSignal | None = None) -> Signal:
    """Exit check for an OPEN position (see module docstring for order and reasons).

    ``price_now``: latest USD price per whole token (Jupiter price v3 live;
    the simulated intrabar price in backtests). ``kind="exit"`` with
    ``fraction`` in (0, 1]; ``metrics`` always includes ``peak_price_usd``,
    ``pnl_pct`` (percent vs entry) and ``held_min``.
    """
    entry = _entry_price(position)
    since_open = [c.h for c in closed_candles(candles, now) if c.ts >= position.opened_at]
    peak = max([position.peak_price_usd, price_now, *since_open])
    levels = exit_levels(_with_peak(position, peak), params)
    metrics = {
        "peak_price_usd": peak,
        "pnl_pct": (price_now / entry - 1.0) * 100.0,
        "held_min": (now - position.opened_at) / 60.0,
        "stop_price": levels.stop,
        "take_profit_price": levels.take_profit,
        "trail_price": levels.trail,
    }

    if radar is not None and radar.flagged:
        first = radar.reasons[0] if radar.reasons else "flagged"
        return _exit(f"radar: {first}", metrics)
    if price_now <= levels.stop:
        return _exit("stop_loss", metrics)
    if now >= levels.time_stop_ts:
        return _exit("time_stop", metrics)
    if levels.take_profit is not None and price_now >= levels.take_profit:
        return _exit("take_profit_partial", metrics, fraction=params.partial_tp_fraction)
    if levels.trail is not None and price_now <= levels.trail:
        return _exit("trailing_stop", metrics)
    return Signal(kind="none", reason="hold", confidence=0.0, metrics=metrics)


def _exit(reason: str, metrics: dict, fraction: float = 1.0) -> Signal:
    return Signal(kind="exit", reason=reason, confidence=1.0, metrics=metrics, fraction=fraction)


def _entry_price(position: Position) -> float:
    if position.entry_price_usd <= 0:
        raise ValueError(f"position {position.id} has no entry price")
    return position.entry_price_usd


def _with_peak(position: Position, peak: float) -> Position:
    """Copy of ``position`` with ``peak_price_usd`` replaced (the input stays untouched)."""
    return dataclasses.replace(position, peak_price_usd=peak)
