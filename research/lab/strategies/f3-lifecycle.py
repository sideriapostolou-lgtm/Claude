"""F3 lifecycle / time-structure strategies for the strategy lab (research only).

Every decision is taken at the CLOSE of bar i from bars 0..i (``view``) plus launch-time metadata.
Per-coin state lives on the INSTANCE (one instance per coin), never on the class.

Lifecycle state tracked incrementally (all causal):

* ``g``           first bar whose close is at/after graduation (``view.graduated`` turns True)
* ``instant``     graduated within ``inst_s`` seconds of creation (creator bought out the curve in
                  the launch transaction). Known at graduation: ``view.graduated_ts - meta.created_ts``.
* ``grad_mcap``   close of the graduation bar x supply (known at bar g)
* ``peak``        running max high since g;  ``max_dd`` = deepest (1 - low / running peak) seen so far
* ``first15``     USD volume of the first 15 bars after g (volume-decay reference, known at g+15)

Entry families (``F3Params.entry``):

* ``runner``      survivor of the first-hour die-off: class filter (organic/instant/any), age since
                  graduation in [t_lo, t_hi] min, still alive (15-bar USD volume, market cap), price
                  relative to the post-graduation peak in [rp_lo, rp_hi]. One entry per coin.
* ``second_leg``  after a first dump >= ``dump`` from the post-graduation peak, a base of ``W`` bars
                  whose high/low range <= ``rng`` with >= ``vmin`` USD volume, then a close above
                  the base high on volume >= ``vk`` x the base mean.
* ``base_bounce`` same base, but buy a green bar closing in the bottom ``q`` of the base range
                  (range trading inside the consolidation); optional take-profit at the base top.
* ``drifter``     late steady phase: instant graduates at grad market cap >= ``gm_lo``, age >= t_lo,
                  base range <= ``rng`` over ``W`` bars with >= ``vmin`` volume. One entry per coin.
* ``gated_dip``   the bot's own dip-rebound (nightcrawler.strategy.entry_signal) allowed only inside
                  a lifecycle window: class filter, age in [t_lo, t_hi], volume not decayed below
                  ``decay_min`` x the first 15 minutes after graduation.

Exits: harness ``Exits`` (stop_pct | structure stop at the base low, take_profit_pct | base top,
tp_fraction, trail_pct, trail_after_tp, max_hold_min) plus a lifecycle exit: sell when the USD
volume of the last ``dead_n`` bars falls below ``dead_v`` (the coin is dying).
"""

from __future__ import annotations

import bisect
import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent.parent / "src"))

from harness import Buy, Exits, Sell, Strategy  # noqa: E402


@dataclass(frozen=True)
class F3Params:
    entry: str = "runner"  # runner | second_leg | base_bounce | drifter | gated_dip
    # lifecycle / class filters
    cls: str = "any"  # org | inst | any
    inst_s: float = 5.0
    gm_lo: float = 0.0  # graduation-bar market cap bounds (USD)
    gm_hi: float = 1e18
    t_lo: float = 30.0  # minutes since graduation
    t_hi: float = 1e9
    mc_lo: float = 6000.0  # current market cap bounds (USD)
    mc_hi: float = 1e18
    v15_min: float = 1500.0  # USD volume of the last 15 bars
    rp_lo: float = 0.0  # close / post-graduation peak
    rp_hi: float = 1.0
    max_entries: int = 1
    # base / consolidation
    dump: float = 0.0  # required max drawdown from the post-graduation peak before the base
    W: int = 30
    rng: float = 1.6  # base high / base low
    vmin: float = 3000.0  # USD volume in the base
    vk: float = 2.0  # breakout volume multiple (second_leg)
    q: float = 0.25  # base_bounce: close in the bottom q of the range
    # gated dip
    decay_min: float = 0.0  # v15 / first15 >= decay_min
    # exits
    stop_pct: float | None = 0.25
    struct_stop: bool = False  # stop just below the base low instead of stop_pct
    struct_buf: float = 0.03
    tp_pct: float | None = None
    tp_base_top: bool = False
    tp_fraction: float = 1.0
    trail_pct: float | None = None
    trail_after_tp: bool = False
    max_hold_min: float = 60.0
    dead_n: int = 0  # 0 = off
    dead_v: float = 0.0

    def key(self) -> str:
        d = {k: v for k, v in dataclasses.asdict(self).items() if v != getattr(F3Params(), k) or k == "entry"}
        return json.dumps(d, sort_keys=True)

    def cid(self) -> str:
        return hashlib.sha1(self.key().encode()).hexdigest()[:10]


class F3Lifecycle(Strategy):
    name = "f3_lifecycle"

    def __init__(self, p: F3Params) -> None:
        self.p = p
        self.name = f"f3_{p.entry}_{p.cid()}"
        # stop calling when flat this long after graduation (speed only; never changes a decision)
        self.horizon_s = None if p.t_hi >= 1e8 else (p.t_hi + 1) * 60
        self._nc = None
        if p.entry == "gated_dip":
            from nightcrawler.models import StrategyParams  # read-only import
            self._nc = StrategyParams()

    # ----------------------------------------------------------------- per-coin state
    def on_coin_start(self, meta) -> None:
        self.created = float(meta["created_ts"])
        self.supply = float(meta["supply"])
        self.g: int | None = None
        self.instant = False
        self.grad_mcap = 0.0
        self.peak = 0.0
        self.max_dd = 0.0
        self.first15: float | None = None
        self.entries = 0  # filled entries (a Buy the portfolio rejects may be retried later)
        self._in_pos = False
        self._pending: Exits | None = None  # exits of the Buy returned at the previous call
        self.candles: list = []  # gated_dip only
        self.cts: list[int] = []

    def _update(self, i: int, view) -> None:
        if self.g is None:
            if not view.graduated:
                return
            self.g = i
            self.instant = (view.graduated_ts - self.created) < self.p.inst_s
            self.grad_mcap = float(view.c[i]) * self.supply
            self.peak = float(view.h[i])
            return
        h, low = float(view.h[i]), float(view.l[i])
        self.peak = max(self.peak, h)
        if self.peak > 0:
            self.max_dd = max(self.max_dd, 1.0 - low / self.peak)
        if self.first15 is None and i - self.g >= 15:
            self.first15 = float(view.v[self.g + 1:self.g + 16].sum())

    def _class_ok(self) -> bool:
        p = self.p
        if p.cls == "org" and self.instant:
            return False
        if p.cls == "inst" and not self.instant:
            return False
        return p.gm_lo <= self.grad_mcap < p.gm_hi

    # ----------------------------------------------------------------- main
    def on_candle(self, i, view, position):
        p = self.p
        if p.entry == "gated_dip":
            b = view.bar()
            from nightcrawler.models import Candle
            self.candles.append(Candle(b.ts, b.o, b.h, b.l, b.c, b.v))
            self.cts.append(b.ts)
        self._update(i, view)
        if position is not None and not self._in_pos:
            self.entries += 1
        elif position is None and self._pending is not None:
            # filled at this bar's open and already closed inside it (e.g. a one-bar rug)? count it
            ex = self._pending.resolve(float(view.o[-1]), float(view.ts[-1]))
            if (ex.stop_price is not None and float(view.l[-1]) <= ex.stop_price) or \
                    (ex.take_profit_price is not None and float(view.h[-1]) >= ex.take_profit_price):
                self.entries += 1
        self._pending = None
        self._in_pos = position is not None
        if position is not None:
            if p.dead_n and i - self.g >= p.dead_n and float(view.v[-p.dead_n:].sum()) < p.dead_v:
                return Sell(1.0, reason="volume_dead")
            return None
        if self.g is None or i == self.g or self.entries >= p.max_entries:
            return None
        age_min = (view.now - view.graduated_ts) / 60.0
        if not (p.t_lo <= age_min <= p.t_hi) or not self._class_ok():
            return None
        c = float(view.c[-1])
        mcap = c * self.supply
        if not (p.mc_lo <= mcap <= p.mc_hi):
            return None
        act = getattr(self, "_e_" + p.entry)(i, view, c)
        if isinstance(act, Buy):
            self._pending = act.exits
        return act

    # ----------------------------------------------------------------- entries
    def _exits(self, base_lo: float | None = None, base_hi: float | None = None) -> Exits:
        p = self.p
        stop_pct, stop_price = p.stop_pct, None
        if p.struct_stop and base_lo is not None:
            stop_pct, stop_price = None, base_lo * (1 - p.struct_buf)
        tp_pct, tp_price = p.tp_pct, None
        if p.tp_base_top and base_hi is not None:
            tp_pct, tp_price = None, base_hi
        return Exits(stop_pct=stop_pct, stop_price=stop_price, take_profit_pct=tp_pct, take_profit_price=tp_price,
                     tp_fraction=p.tp_fraction, trail_pct=p.trail_pct, trail_after_tp=p.trail_after_tp,
                     max_hold_s=p.max_hold_min * 60)

    def _alive(self, view) -> bool:
        return float(view.v[-15:].sum()) >= self.p.v15_min

    def _e_runner(self, i, view, c):
        p = self.p
        if not self._alive(view) or self.peak <= 0:
            return None
        rp = c / self.peak
        if not (p.rp_lo <= rp <= p.rp_hi):
            return None
        return Buy(exits=self._exits(), tag="runner")

    def _base(self, i, view):
        """(base_hi, base_lo, base_vol_mean) over bars i-W..i-1 (excludes bar i), or None."""
        p = self.p
        w0 = i - p.W
        if w0 <= self.g:
            return None
        hh = float(view.h[w0:i].max())
        ll = float(view.l[w0:i].min())
        if ll <= 0 or hh / ll > p.rng:
            return None
        vw = view.v[w0:i]
        vs = float(vw.sum())
        if vs < p.vmin:
            return None
        return hh, ll, vs / p.W

    def _e_second_leg(self, i, view, c):
        p = self.p
        if self.max_dd < p.dump:
            return None
        b = self._base(i, view)
        if b is None:
            return None
        hh, ll, vm = b
        if c > hh and float(view.v[-1]) >= p.vk * vm:
            return Buy(exits=self._exits(base_lo=ll, base_hi=None), tag="second_leg")
        return None

    def _e_base_bounce(self, i, view, c):
        p = self.p
        if self.max_dd < p.dump:
            return None
        b = self._base(i, view)
        if b is None:
            return None
        hh, ll, _ = b
        o = float(view.o[-1])
        if c > o and c <= ll + p.q * (hh - ll):
            return Buy(exits=self._exits(base_lo=ll, base_hi=hh), tag="base_bounce")
        return None

    def _e_drifter(self, i, view, c):
        b = self._base(i, view)
        if b is None:
            return None
        return Buy(exits=self._exits(base_lo=b[1]), tag="drifter")

    def _e_gated_dip(self, i, view, c):
        p, nc = self.p, self._nc
        if p.decay_min > 0:
            if self.first15 is None or self.first15 <= 0:
                return None
            if float(view.v[-15:].sum()) / self.first15 < p.decay_min:
                return None
        from nightcrawler.strategy import entry_signal
        now = view.now
        lo = bisect.bisect_left(self.cts, now - nc.dip_lookback_h * 3600)
        if c > float(view.h[lo:].max()) * (1 - nc.dip_pct / 2):
            return None
        if not all(x.c > x.o for x in self.candles[-nc.confirm_green:]):
            return None
        sig = entry_signal(self.candles[lo:], None, nc, now)
        if sig.kind != "enter":
            return None
        return Buy(exits=self._exits(), tag="gated_dip")


def factory(p: F3Params):
    """Zero-argument factory for the harness (one fresh instance per coin)."""

    def make() -> F3Lifecycle:
        return F3Lifecycle(p)

    make.__name__ = f"f3_{p.entry}_{p.cid()}"
    return make
