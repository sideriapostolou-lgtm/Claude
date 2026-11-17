"""F2 - momentum / breakout-continuation strategies for freshly graduated pump.fun coins.

All strategies here are harness ``Strategy`` subclasses (one instance per coin, decisions at the
CLOSE of bar i from bars 0..i only, fills at the next open through costs.py). They are fully
parameterised by :class:`F2Params`; build a zero-arg factory with :func:`factory`.

Entry families (``F2Params.entry``):

* ``"breakout"``  - close makes a new ``lookback``-bar high (close > max high of the previous
  ``lookback`` bars), the bar's USD volume is >= ``vol_mult`` x the mean volume of the previous
  ``vol_base`` bars, and the last ``vol_win`` bars traded >= ``min_vol_usd``. Optional
  ``higher_lows`` (the low of the last half-window is above the low of the first half) and an
  anti-chase cap ``max_ext`` (close <= (1 + max_ext) x the lowest low of the lookback window).
* ``"early"``     - early post-graduation strength, one shot at ``check_min`` minutes after
  graduation: close >= ``min_rel_grad`` x the graduation-bar close, close within ``max_dd`` of the
  post-graduation peak, and >= ``min_vol_usd`` traded over the last ``vol_win`` bars.
* ``"squeeze"``   - volatility contraction then expansion: the previous ``squeeze_win`` bars spanned
  a high/low range <= ``squeeze_range`` of their close while at least ``squeeze_active`` of them
  traded, then the current bar closes above that range with a ``vol_mult`` volume surge.
* ``"trend"``     - long-horizon higher-highs on established coins: close >= (1 + ``trend_ret``) x the
  close ``trend_bars`` bars ago, close above the previous 10 bars' highs, optional ``higher_lows``
  over the ``trend_bars`` window, >= ``min_vol_usd`` over ``vol_win`` bars (meant for old, large coins).

Common filters: minutes since graduation in [``min_age_min``, ``max_age_min``], market cap
(close x supply) in [``mc_lo``, ``mc_hi``], graduation kind (``grad_kind``: "any" | "organic" |
"instant", from graduation delay - both timestamps are public once graduated), and
``skip_floored``: skip coins whose low since graduation already touched ``floor_mc`` (the coin was
rugged back to the ~$1.9k floor).

Exits: ``stop_pct`` (fail-fast hard stop), ``trail_pct`` fixed or ``trail_atr_mult`` x ATR%
(volatility-scaled, clamped to [``trail_lo``, ``trail_hi``], computed from closed bars at the
decision), optional partial take-profit, ``max_hold_min`` time stop, and a fail-fast rule
(``fail_bars``/``fail_ret``: if after ``fail_bars`` bars the position is not up ``fail_ret``,
sell at the next open).

No lookahead: every quantity is computed from ``view`` (bars 0..i) and launch metadata; per-coin
state lives on the instance only (no class attributes are mutated).
"""

from __future__ import annotations

import dataclasses
import functools
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

_LAB = Path(__file__).resolve().parents[1]
if str(_LAB) not in sys.path:
    sys.path.insert(0, str(_LAB))

from harness import Buy, Exits, Sell, Strategy  # noqa: E402

INSTANT_GRAD_S = 10.0  # graduation within 10 s of creation = creator bought out the curve at launch


@dataclass(frozen=True)
class F2Params:
    entry: str = "breakout"  # breakout | early | squeeze
    # ---- universe filters (all causal)
    min_age_min: float = 0.0  # minutes since graduation (at the decision close)
    max_age_min: float = 360.0
    mc_lo: float = 20_000.0
    mc_hi: float = 1e13
    min_vol_usd: float = 5_000.0  # USD volume over the last ``vol_win`` closed bars
    vol_win: int = 5
    grad_kind: str = "any"  # any | organic | instant
    skip_floored: bool = True
    floor_mc: float = 3_000.0
    # ---- breakout
    lookback: int = 30
    vol_mult: float = 3.0
    vol_base: int = 30
    max_ext: float | None = None  # close <= (1+max_ext) * lowest low of the lookback window
    higher_lows: bool = False
    # ---- early strength
    check_min: float = 30.0
    min_rel_grad: float = 1.0
    max_dd: float = 0.3
    # ---- squeeze
    squeeze_win: int = 20
    squeeze_range: float = 0.25
    squeeze_active: int = 10
    # ---- trend (long-horizon higher-highs on established coins)
    trend_bars: int = 60
    trend_ret: float = 0.05
    # ---- exits
    stop_pct: float | None = 0.15
    trail_pct: float | None = 0.15
    trail_atr_mult: float | None = None
    atr_win: int = 15
    trail_lo: float = 0.08
    trail_hi: float = 0.40
    tp_pct: float | None = None
    tp_fraction: float = 1.0
    trail_after_tp: bool = False
    max_hold_min: float = 60.0
    fail_bars: int | None = None
    fail_ret: float = 0.0
    max_entries: int = 1

    def key(self) -> str:
        d = dataclasses.asdict(self)
        base = dataclasses.asdict(F2Params())
        diff = {k: v for k, v in d.items() if v != base[k]}
        return ",".join(f"{k}={v}" for k, v in sorted(diff.items())) or "default"


class F2Momentum(Strategy):
    """Parameterised momentum strategy (see module docstring)."""

    name = "f2_momentum"

    def __init__(self, params: F2Params | None = None, name: str | None = None, **kw: Any) -> None:
        self.p = params if params is not None else F2Params(**kw)
        self.name = name or f"f2_{self.p.entry}"
        self.horizon_s = (self.p.max_age_min + 1.0) * 60.0

    # ------------------------------------------------------------------ per-coin state
    def on_coin_start(self, meta: Mapping[str, Any]) -> None:
        self.created_ts = float(meta["created_ts"])
        self.supply = float(meta["supply"])
        self.gi: int | None = None  # index of the bar in which graduation happened
        self.grad_close = None
        self.min_low_since_grad = np.inf
        self.peak_since_grad = 0.0
        self.last_i = -1
        self.entries = 0
        self.checked = False
        self.kind_ok: bool | None = None

    def _update(self, i: int, view) -> None:
        """Incremental post-graduation stats from closed bars; recomputed from the view on any gap."""
        if self.gi is None:
            if not view.graduated:
                self.last_i = i
                return
            gts = view.graduated_ts
            close_ts = view.ts + view.dur
            self.gi = int(np.searchsorted(close_ts, gts, side="left"))
            self.grad_close = float(view.c[self.gi])
            delay = gts - self.created_ts
            kind = "instant" if delay <= INSTANT_GRAD_S else "organic"
            self.kind_ok = self.p.grad_kind in ("any", kind)
            self.min_low_since_grad = float(view.l[self.gi:].min())
            self.peak_since_grad = float(view.h[self.gi:].max())
        elif i == self.last_i + 1:
            self.min_low_since_grad = min(self.min_low_since_grad, float(view.l[-1]))
            self.peak_since_grad = max(self.peak_since_grad, float(view.h[-1]))
        else:
            self.min_low_since_grad = float(view.l[self.gi:].min())
            self.peak_since_grad = float(view.h[self.gi:].max())
        self.last_i = i

    # ------------------------------------------------------------------ decisions
    def on_candle(self, i, view, position):
        self._update(i, view)
        p = self.p
        if position is not None:
            if p.fail_bars is not None and position.bars_held >= p.fail_bars \
                    and position.unrealized_pct < p.fail_ret and not position.partial_taken:
                return Sell(1.0, reason="fail_fast")
            return None
        if self.gi is None or not self.kind_ok or self.entries >= p.max_entries:
            return None
        age_min = (view.now - view.graduated_ts) / 60.0
        if p.entry == "early":
            if self.checked or age_min < p.check_min:
                return None
            self.checked = True  # one shot: only the first close at/after check_min is evaluated
        if age_min < p.min_age_min or age_min > p.max_age_min:
            return None
        c = float(view.c[-1])
        mc = c * self.supply
        if mc < p.mc_lo or mc > p.mc_hi:
            return None
        if p.skip_floored and self.min_low_since_grad * self.supply <= p.floor_mc:
            return None
        if p.entry == "early":
            sig = self._early(i, view, age_min, c)
        elif p.entry == "breakout":
            sig = self._breakout(i, view, c)
        elif p.entry == "squeeze":
            sig = self._squeeze(i, view, c)
        elif p.entry == "trend":
            sig = self._trend(i, view, c)
        else:
            raise ValueError(p.entry)
        if not sig:
            return None
        self.entries += 1
        return Buy(exits=self._exits(view), tag=p.entry)

    def _recent_vol_ok(self, view) -> bool:
        p = self.p
        return float(view.v[-p.vol_win:].sum()) >= p.min_vol_usd

    def _early(self, i, view, age_min, c) -> bool:
        p = self.p
        if c < p.min_rel_grad * self.grad_close:
            return False
        if c < (1.0 - p.max_dd) * self.peak_since_grad:
            return False
        return self._recent_vol_ok(view)

    def _breakout(self, i, view, c) -> bool:
        p = self.p
        n = i + 1
        if n < max(p.lookback, p.vol_base) + 1:
            return False
        v = view.v
        vi = float(v[-1])
        if vi <= 0.0:
            return False
        if c <= float(view.h[-p.lookback - 1:-1].max()):
            return False
        base = float(v[-p.vol_base - 1:-1].mean())
        if vi < p.vol_mult * max(base, 1.0):
            return False
        if not self._recent_vol_ok(view):
            return False
        lows = view.l[-p.lookback - 1:-1]
        if p.max_ext is not None and c > (1.0 + p.max_ext) * float(lows.min()):
            return False
        if p.higher_lows:
            half = len(lows) // 2
            if float(lows[half:].min()) <= float(lows[:half].min()):
                return False
        return True

    def _squeeze(self, i, view, c) -> bool:
        p = self.p
        n = i + 1
        w = p.squeeze_win
        if n < max(w, p.vol_base) + 1:
            return False
        v = view.v
        vi = float(v[-1])
        if vi <= 0.0:
            return False
        hi = float(view.h[-w - 1:-1].max())
        lo = float(view.l[-w - 1:-1].min())
        ref = float(view.c[-2])
        if ref <= 0 or (hi - lo) / ref > p.squeeze_range:
            return False
        if int((v[-w - 1:-1] > 0).sum()) < p.squeeze_active:
            return False
        if c <= hi:
            return False
        base = float(v[-p.vol_base - 1:-1].mean())
        if vi < p.vol_mult * max(base, 1.0):
            return False
        return self._recent_vol_ok(view)

    def _trend(self, i, view, c) -> bool:
        p = self.p
        n = i + 1
        tb = p.trend_bars
        if n < tb + 1 or float(view.v[-1]) <= 0.0:
            return False
        if c < (1.0 + p.trend_ret) * float(view.c[-tb - 1]):
            return False
        if c <= float(view.h[-11:-1].max()):  # at a fresh 10-bar high
            return False
        if p.higher_lows:
            lows = view.l[-tb - 1:-1]
            half = len(lows) // 2
            if float(lows[half:].min()) <= float(lows[:half].min()):
                return False
        return self._recent_vol_ok(view)

    def _exits(self, view) -> Exits:
        p = self.p
        trail = p.trail_pct
        if p.trail_atr_mult is not None:
            w = p.atr_win
            h, lo, cl = view.h[-w:], view.l[-w:], view.c[-w:]
            atr_pct = float(np.mean((h - lo) / np.maximum(cl, 1e-18)))
            trail = min(max(p.trail_atr_mult * atr_pct, p.trail_lo), p.trail_hi)
        return Exits(stop_pct=p.stop_pct, trail_pct=trail, take_profit_pct=p.tp_pct, tp_fraction=p.tp_fraction,
                     trail_after_tp=p.trail_after_tp, max_hold_s=p.max_hold_min * 60.0)


def factory(params: F2Params | None = None, name: str | None = None, **kw: Any):
    """Zero-arg factory for the harness runners: ``run_portfolio(factory(F2Params(...)), coins)``."""
    prm = params if params is not None else F2Params(**kw)
    return functools.partial(F2Momentum, prm, name)


def params_from_dict(d: Mapping[str, Any]) -> F2Params:
    return F2Params(**dict(d))
