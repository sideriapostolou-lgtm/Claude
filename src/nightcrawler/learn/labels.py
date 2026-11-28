"""Outcome labels of a coin or a trade (docs/EXPERIENCE.md §4.5). Pure, standard library only.

Shared by experience (O8) and Coach phase 3 (O7 reviews); learn never imports experience. Every label of every coin
comes from the same source: CLOSED 1-minute bars (tape candles forward, B2 bars on history), passed in as any objects
with ``ts`` (the minute's OPEN, epoch seconds), ``h``, ``l`` and ``c`` (:class:`~nightcrawler.models.Candle` fits).
Horizons are parameters, so Coach phase 3's horizons (5 m, 30 m, 2 h, 6 h) call the same code.

* ``x`` - net return of a $20 trade, ``proceeds / stake - 1`` after every cost, clipped to [-1, 1]; ``x_raw`` kept
  (:func:`net_return`).
* ``crash50(t, H)`` - some minute ``m`` that opened at or after ``t`` and closed by ``t + H`` has
  ``low_m <= 0.5 x close_{m-1}`` AND the close 5 minutes later (of minute ``m + 5``) is ``<= 0.6 x close_{m-1}``:
  the second condition keeps sandwich and MEV wicks out. ``t_crash`` is that ``m`` (:func:`crash50`).
* ``dead(t, H)`` - the last close at or before ``t + H`` is ``<= 0.2 x`` the price at ``t`` (:func:`dead`).
* ``bad = crash50 or dead``; ``good`` = the coin's random-entry (R host) ``x > 0``.
* ``mfe`` / ``mae`` - best and worst points of a trade from closes; ``mae_wick`` from lows (:func:`excursions`).

"The close at or before ts" is the close of the last bar that CLOSED by ``ts`` (``bar.ts + 60 <= ts``); a minute
without a trade keeps the previous close. A label that the bars cannot decide (the data ends inside the horizon or
before a crash could be confirmed) is ``None``, never a guess: censoring is the caller's rule.

Labels are OUTCOMES (AO-8): readable only from ``label_ready_ts = t + H + 10 min`` (:func:`require_ready`).
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "MINUTE",
    "HORIZON_S",
    "LABEL_DELAY_S",
    "COACH_HORIZONS_S",
    "CRASH_DROP",
    "CRASH_CONFIRM_S",
    "CRASH_CONFIRM_LEVEL",
    "DEAD_LEVEL",
    "LabelNotReady",
    "Bar",
    "Crash",
    "Excursion",
    "BarSeries",
    "net_return",
    "label_ready_ts",
    "require_ready",
    "close_at",
    "crash50",
    "dead",
    "is_bad",
    "is_good",
    "excursions",
    "coin_labels",
]

MINUTE = 60
#: H: the forward horizon of the coin labels (on history it runs to the window end, a caller's choice).
HORIZON_S = 6 * 3600
#: label_ready_ts = t + H + LABEL_DELAY_S.
LABEL_DELAY_S = 600.0
COACH_HORIZONS_S = (300, 1800, 7200, 21600)
CRASH_DROP = 0.5
#: The confirmation close is that of minute m + 5, which closes 6 minutes after m opens.
CRASH_CONFIRM_S = 5 * MINUTE
CRASH_CONFIRM_LEVEL = 0.6
DEAD_LEVEL = 0.2


class LabelNotReady(RuntimeError):
    """An outcome label read before its ``label_ready_ts``."""


class Bar(Protocol):
    @property
    def ts(self) -> int | float: ...
    @property
    def h(self) -> float: ...
    @property
    def l(self) -> float: ...  # noqa: E743 - conventional OHLC name
    @property
    def c(self) -> float: ...


@dataclass(frozen=True)
class Crash:
    """``crashed``: True / False / None (undecidable); ``t_crash``: the crash minute's open, or None."""

    crashed: bool | None
    t_crash: int | None = None


@dataclass(frozen=True)
class Excursion:
    mfe: float
    mae: float
    mae_wick: float


def net_return(proceeds: float, stake: float) -> tuple[float, float]:
    """``(x, x_raw)``: ``x_raw = proceeds / stake - 1`` and ``x`` its clip to [-1, 1]."""
    x_raw = float(proceeds) / float(stake) - 1.0
    return max(-1.0, min(1.0, x_raw)), x_raw


def label_ready_ts(t: float, horizon_s: float = HORIZON_S) -> float:
    return float(t) + float(horizon_s) + LABEL_DELAY_S


def require_ready(ready_ts: float, now: float) -> None:
    """Raise :class:`LabelNotReady` while ``now < ready_ts``."""
    if now < ready_ts:
        raise LabelNotReady(f"label readable from {ready_ts:.0f}, now {now:.0f}")


class BarSeries:
    """Bars sorted by open time, with their close times for :meth:`close_at` lookups; ``end`` is where the data's
    coverage ends (default: the last bar's close)."""

    def __init__(self, bars: Sequence[Bar], end_ts: float | None = None) -> None:
        self.bars = sorted(bars, key=lambda b: b.ts)
        self.closes_at = [float(b.ts) + MINUTE for b in self.bars]
        self.end = float(end_ts) if end_ts is not None else (self.closes_at[-1] if self.bars else float("-inf"))

    def close_at(self, ts: float) -> float | None:
        i = bisect.bisect_right(self.closes_at, ts)
        return float(self.bars[i - 1].c) if i else None


def close_at(bars: Sequence[Bar], ts: float) -> float | None:
    """The close of the last bar that closed at or before ``ts`` (None before the first one)."""
    return BarSeries(bars, None).close_at(ts)


def _crash(series: BarSeries, t: float, horizon_s: float) -> Crash:
    unconfirmable = False
    for bar in series.bars:
        m = float(bar.ts)
        if m < t:
            continue
        if m + MINUTE > t + horizon_s:
            break
        prev = series.close_at(m)
        if prev is None or float(bar.l) > CRASH_DROP * prev:
            continue
        confirm_ts = m + CRASH_CONFIRM_S + MINUTE
        if confirm_ts > series.end:
            unconfirmable = True
            continue
        later = series.close_at(confirm_ts)
        if later is not None and later <= CRASH_CONFIRM_LEVEL * prev:
            return Crash(True, int(bar.ts))
    if unconfirmable or series.end < t + horizon_s:
        return Crash(None)
    return Crash(False)


def crash50(bars: Sequence[Bar], t: float, horizon_s: float = HORIZON_S, *, end_ts: float | None = None) -> Crash:
    """See the module docstring. ``end_ts``: where the data's coverage ends (default: the last bar's close)."""
    return _crash(BarSeries(bars, end_ts), float(t), float(horizon_s))


def _dead(series: BarSeries, t: float, horizon_s: float) -> bool | None:
    start = series.close_at(t)
    if start is None or series.end < t + horizon_s:
        return None
    last = series.close_at(t + horizon_s)
    return last is not None and last <= DEAD_LEVEL * start


def dead(bars: Sequence[Bar], t: float, horizon_s: float = HORIZON_S, *, end_ts: float | None = None) -> bool | None:
    """See the module docstring (None when the bars do not reach ``t + H`` or nothing closed by ``t``)."""
    return _dead(BarSeries(bars, end_ts), float(t), float(horizon_s))


def is_bad(crashed: bool | None, is_dead: bool | None) -> bool | None:
    """``crash50 or dead``; None when neither is True and one of them is unknown."""
    if crashed is True or is_dead is True:
        return True
    if crashed is None or is_dead is None:
        return None
    return False


def is_good(x_random: float | None) -> bool | None:
    """The coin's R-host trade made money after costs."""
    return None if x_random is None else x_random > 0


def excursions(bars: Sequence[Bar], t_in: float, t_out: float, entry_price: float | None = None) -> Excursion | None:
    """``mfe`` / ``mae`` from the closes of bars that closed during the hold (``t_in < close <= t_out``), ``mae_wick``
    also from the lows of bars that lay wholly inside it; relative to ``entry_price`` (default: the close at
    ``t_in``). MFE is never below 0 and MAE never above 0 (the entry itself is a point of the trade)."""
    series = BarSeries(bars, None)
    price = float(entry_price) if entry_price is not None else series.close_at(t_in)
    if price is None or price <= 0:
        return None
    pairs = list(zip(series.bars, series.closes_at, strict=True))
    closes = [float(b.c) for b, closed in pairs if t_in < closed <= t_out]
    lows = [float(b.l) for b, closed in pairs if b.ts >= t_in and closed <= t_out]
    mfe = max(0.0, max(closes, default=price) / price - 1.0)
    mae = min(0.0, min(closes, default=price) / price - 1.0)
    return Excursion(mfe, mae, min(mae, min(lows, default=price) / price - 1.0))


def coin_labels(bars: Sequence[Bar], t: float, horizon_s: float = HORIZON_S, *,
                end_ts: float | None = None) -> dict[str, Any]:
    """The coin labels at ``t``: ``{crash50, t_crash, dead, bad, label_ready_ts}`` (booleans or None)."""
    series = BarSeries(bars, end_ts)
    crash = _crash(series, float(t), float(horizon_s))
    is_dead = _dead(series, float(t), float(horizon_s))
    return {"crash50": crash.crashed, "t_crash": crash.t_crash, "dead": is_dead, "bad": is_bad(crash.crashed, is_dead),
            "label_ready_ts": label_ready_ts(t, horizon_s)}
