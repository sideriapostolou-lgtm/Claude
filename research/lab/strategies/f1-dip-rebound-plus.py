"""F1 "dip-rebound-plus": buy capitulation dips only when real buyers return, with an anti-chase cap.

This is the viral "buy the dip after buyers return" idea, done carefully, as a parameterised
harness strategy (one instance per coin, decisions on CLOSED bars 0..i only, fills at the next
open via the harness).

ENTRY (all must hold at the close of bar i; checks ordered cheap -> expensive):

1. Graduated, and ``min_age_min <= minutes since graduation <= max_age_min``.
2. Entries taken on this coin < ``max_entries``.
3. Activity: USD volume of the last ``vol_win`` bars >= ``min_vol_usd`` (dead coins excluded).
4. Market cap at the close in [``min_mcap``, ``max_mcap``] (close x supply).
5. Dip: H = max high of the last ``lookback_min`` bars (graduation bar onwards), L = min low of
   the bars AFTER the high bar. Drawdown ``1 - L/H`` in [``dd_min``, ``dd_max``]; the high is at
   least ``min_since_high`` bars old (avoids buying the first leg of a rug).
6. Rebound / ANTI-CHASE: ``min_reb <= close / L <= max_reb`` (bounced, but not chased).
7. Confirmation (``confirm``, "+"-joined variants must all hold):
   * ``green``   - bar i is green (c > o);  ``green2`` - bars i-1 and i are green;
   * ``break``   - close > previous bar's high;
   * ``vol``     - volume_i >= ``vol_mult`` x mean volume of the previous ``vol_base`` bars;
   * ``hl``      - higher low: the dip-low bar is >= ``hl_bars`` bars old and every low of the
                   last ``hl_bars`` bars is > L.

EXITS (``exit``):

* ``fixed``   - stop ``stop_pct``, take-profit ``tp_pct`` (fraction ``tp_frac``; optional
                ``trail_pct`` armed after the partial when ``trail_after_tp``), time stop.
* ``atr``     - stop = clip(``atr_k`` x ATR%(``atr_n``), ``atr_min``, ``atr_max``),
                take-profit = ``r_mult`` x stop; time stop.
* ``lowstop`` - structural stop just under the dip low: L x (1 - ``low_buf``); take-profit =
                ``r_mult`` x (distance to the stop measured from the decision close); time stop.
All relative levels resolve against the fill mid (harness). ``max_hold_min`` = time stop.

No state is shared across instances; all state lives on ``self`` and is rebuilt from bars 0..i.
Never reads cost/coverage/census outcome fields.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from harness import Buy, Exits, Strategy  # noqa: E402

DEFAULTS: dict[str, Any] = dict(
    # regime
    min_age_min=30.0, max_age_min=720.0, min_mcap=15_000.0, max_mcap=5_000_000.0,
    vol_win=10, min_vol_usd=2_000.0,
    # dip
    lookback_min=360, dd_min=0.4, dd_max=0.8, min_since_high=5,
    # anti-chase
    min_reb=1.05, max_reb=1.6,
    # confirmation
    confirm="break", vol_mult=2.0, vol_base=30, hl_bars=3,
    # exits
    exit="fixed", stop_pct=0.20, tp_pct=0.40, tp_frac=1.0, trail_pct=None, trail_after_tp=True,
    max_hold_min=60.0, atr_n=14, atr_k=2.0, atr_min=0.08, atr_max=0.40, r_mult=2.0, low_buf=0.03,
    max_entries=1,
)

CONFIRMS = ("green", "green2", "break", "vol", "hl")


class DipReboundPlus(Strategy):
    name = "f1_dip_rebound_plus"

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(DEFAULTS)
        if unknown:
            raise TypeError(f"unknown params {sorted(unknown)}")
        p = {**DEFAULTS, **params}
        for c in str(p["confirm"]).split("+"):
            if c and c not in CONFIRMS:
                raise ValueError(f"unknown confirmation {c!r}")
        if p["exit"] not in ("fixed", "atr", "lowstop"):
            raise ValueError(f"unknown exit {p['exit']!r}")
        self.p = p
        self.confirms = tuple(c for c in str(p["confirm"]).split("+") if c)
        # horizon: the harness stops calling when flat this long after graduation (speed only)
        self.horizon_s = float(p["max_age_min"]) * 60.0 + 60.0

    # ------------------------------------------------------------------ factory helper
    @classmethod
    def factory(cls, **params: Any):
        def make() -> "DipReboundPlus":
            return cls(**params)
        make.__name__ = f"{cls.__name__}_factory"
        return make

    def on_coin_start(self, meta: Mapping[str, Any]) -> None:
        self.entries = 0  # positions observed at a bar close (a rejected portfolio buy is not counted)
        self.in_pos = False
        self.grad_idx: int | None = None

    # ------------------------------------------------------------------ helpers
    def _atr_pct(self, view) -> float:
        n = int(self.p["atr_n"])
        h, l, c = view.h[-(n + 1):], view.l[-(n + 1):], view.c[-(n + 1):]
        if len(c) < 2:
            return float("nan")
        prev_c = c[:-1]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)))
        return float(tr.mean() / c[-1]) if c[-1] > 0 else float("nan")

    def _exits(self, view, low: float) -> Exits | None:
        p = self.p
        hold = float(p["max_hold_min"]) * 60.0
        if p["exit"] == "fixed":
            return Exits(stop_pct=p["stop_pct"], take_profit_pct=p["tp_pct"], tp_fraction=p["tp_frac"],
                         trail_pct=p["trail_pct"], trail_after_tp=p["trail_after_tp"], max_hold_s=hold)
        if p["exit"] == "atr":
            a = self._atr_pct(view)
            if not math.isfinite(a) or a <= 0:
                return None
            stop = min(max(p["atr_k"] * a, p["atr_min"]), p["atr_max"])
            return Exits(stop_pct=stop, take_profit_pct=p["r_mult"] * stop, tp_fraction=p["tp_frac"],
                         trail_pct=p["trail_pct"], trail_after_tp=p["trail_after_tp"], max_hold_s=hold)
        # lowstop
        close = float(view.c[-1])
        stop_price = low * (1.0 - p["low_buf"])
        dist = 1.0 - stop_price / close
        if dist <= 0:
            return None
        return Exits(stop_price=stop_price, take_profit_pct=p["r_mult"] * dist, tp_fraction=p["tp_frac"],
                     trail_pct=p["trail_pct"], trail_after_tp=p["trail_after_tp"], max_hold_s=hold)

    # ------------------------------------------------------------------ main
    def on_candle(self, i, view, position):
        p = self.p
        if position is not None:
            if not self.in_pos:
                self.in_pos = True
                self.entries += 1
            return None
        self.in_pos = False
        if not view.graduated:
            return None
        if self.grad_idx is None:
            # the bar that contains the graduation time (known once graduation has happened)
            k = int(np.searchsorted(view.ts, view.graduated_ts, side="right")) - 1
            self.grad_idx = max(0, min(k, i))
        if self.entries >= p["max_entries"]:
            return None
        age_min = (view.now - view.graduated_ts) / 60.0
        if age_min < p["min_age_min"] or age_min > p["max_age_min"]:
            return None
        v = view.v
        vw = int(p["vol_win"])
        if float(v[-vw:].sum()) < p["min_vol_usd"]:
            return None
        c = view.c
        close = float(c[-1])
        mcap = close * view.supply
        if not p["min_mcap"] <= mcap <= p["max_mcap"]:
            return None
        start = max(self.grad_idx, i + 1 - int(p["lookback_min"]))
        hw = view.h[start:]
        k_hi = int(np.argmax(hw))
        since_high = len(hw) - 1 - k_hi
        if since_high < max(1, int(p["min_since_high"])):
            return None
        high = float(hw[k_hi])
        lows_after = view.l[start + k_hi + 1:]
        k_lo = int(np.argmin(lows_after))
        low = float(lows_after[k_lo])
        if high <= 0 or low <= 0:
            return None
        dd = 1.0 - low / high
        if not p["dd_min"] <= dd <= p["dd_max"]:
            return None
        reb = close / low
        if not p["min_reb"] <= reb <= p["max_reb"]:
            return None
        o = view.o
        for cf in self.confirms:
            if cf == "green":
                if not c[-1] > o[-1]:
                    return None
            elif cf == "green2":
                if i < 1 or not (c[-1] > o[-1] and c[-2] > o[-2]):
                    return None
            elif cf == "break":
                if i < 1 or not c[-1] > view.h[-2]:
                    return None
            elif cf == "vol":
                vb = int(p["vol_base"])
                prev = v[-(vb + 1):-1]
                if len(prev) == 0 or not v[-1] >= p["vol_mult"] * float(prev.mean()):
                    return None
            elif cf == "hl":
                hb = int(p["hl_bars"])
                bars_since_low = len(lows_after) - 1 - k_lo
                if bars_since_low < hb or not float(view.l[-hb:].min()) > low:
                    return None
        ex = self._exits(view, low)
        if ex is None:
            return None
        return Buy(exits=ex, tag=f"dd={dd:.2f} reb={reb:.2f} age={age_min:.0f}")


def make(**params: Any):
    """Zero-arg factory for the harness: ``run_portfolio(make(dd_min=0.5), coins)``."""
    return DipReboundPlus.factory(**params)
