"""Reference strategies on TRAIN and VALIDATION (never TEST).

    python research/lab/baseline.py            # all baselines, per-coin + portfolio, both splits
    python research/lab/baseline.py --json out.json

1. ``nightcrawler``  - the bot's own default dip-rebound: ``nightcrawler.strategy.entry_signal``
   on the closed 1m bars of the last ``dip_lookback_h`` (snapshot=None, like its backtester),
   its universe filter (age >= MIN_AGE_MIN, mcap in [MIN, MAX]) and its exits (stop 18 %,
   50 % take-profit at +40 %, then 15 % trail, 120 min time stop, 30 min cooldown).
   Differences vs src/nightcrawler/backtest.py: levels are measured from the entry MID (not
   the cost-inclusive price), costs come from costs.py (tiered pool fee, Ultra, MEV buffer,
   constant-product impact) instead of the flat model, wick fills are "half" by default, and
   entries need the coin to have graduated.
2. ``grad_hold60``   - buy at the first close after graduation, sell 60 minutes later.
3. ``random``        - one entry per coin at a seeded uniformly random time 0-6 h after
   graduation (independent of the data), nightcrawler's exits.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

from harness import (Buy, Exits, SimConfig, Strategy, load_coins, run_per_coin, run_portfolio)  # noqa: E402
from costs import CostModel  # noqa: E402

from nightcrawler.models import Candle, StrategyParams  # noqa: E402
from nightcrawler.strategy import entry_signal  # noqa: E402

P = StrategyParams()  # nightcrawler defaults


def nc_exits(p: StrategyParams = P) -> Exits:
    return Exits(stop_pct=p.stop_loss_pct, take_profit_pct=p.take_profit_pct, tp_fraction=p.partial_tp_fraction,
                 trail_pct=p.trail_pct, trail_after_tp=True, max_hold_s=p.max_hold_min * 60)


class NightcrawlerDefault(Strategy):
    """nightcrawler.strategy.entry_signal wrapped as a harness strategy (see module docstring)."""

    name = "nightcrawler_dip_rebound"
    horizon_s = P.max_age_h * 3600

    def __init__(self, params: StrategyParams = P) -> None:
        self.p = params

    def on_coin_start(self, meta):
        self.created = meta["created_ts"]
        self.supply = meta["supply"]
        self.candles: list[Candle] = []
        self.ts: list[int] = []

    def on_candle(self, i, view, position):
        b = view.bar()
        self.candles.append(Candle(b.ts, b.o, b.h, b.l, b.c, b.v))  # bars 0..i only, accumulated
        self.ts.append(b.ts)
        if position is not None:
            return None  # exits are managed by the harness
        p, now = self.p, view.now
        age_min = (now - self.created) / 60
        if not p.min_age_min <= age_min <= p.max_age_h * 60:
            return None
        if not p.min_mcap_usd <= b.c * self.supply <= p.max_mcap_usd:
            return None
        lo = bisect.bisect_left(self.ts, now - p.dip_lookback_h * 3600)
        # cheap necessary conditions first (identical outcome, much faster)
        if b.c > float(view.h[lo:].max()) * (1 - p.dip_pct / 2):
            return None
        if not all(c.c > c.o for c in self.candles[-p.confirm_green:]):
            return None
        sig = entry_signal(self.candles[lo:], None, p, now)
        if sig.kind != "enter":
            return None
        return Buy(exits=nc_exits(p), tag="dip_rebound")


class GradHold60(Strategy):
    name = "grad_hold60"
    horizon_s = 3600

    def on_coin_start(self, meta):
        self.done = False

    def on_candle(self, i, view, position):
        if self.done or position is not None or not view.graduated:
            return None
        self.done = True
        return Buy(exits=Exits(max_hold_s=3600), tag="grad")


class RandomEntry(Strategy):
    name = "random_entry"
    horizon_s = 6 * 3600 + 3 * 3600

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def on_coin_start(self, meta):
        h = int(hashlib.sha256(f"{self.seed}:{meta['mint']}".encode()).hexdigest()[:12], 16)
        self.delay = random.Random(h).uniform(0, 6 * 3600)
        self.done = False

    def on_candle(self, i, view, position):
        if self.done or position is not None or not view.graduated:
            return None
        if view.now - view.graduated_ts >= self.delay:
            self.done = True
            return Buy(exits=nc_exits(), tag="random")
        return None


BASELINES = {"nightcrawler": NightcrawlerDefault, "grad_hold60": GradHold60, "random": RandomEntry}


def run_all(splits=("train", "validation"), bootstrap: int = 2000, sensitivity: bool = True) -> dict:
    out: dict = {}
    for split in splits:
        coins = load_coins(split=split)
        print(f"\n=== {split.upper()}: {len(coins)} coins (default universe) ===")
        for key, cls in BASELINES.items():
            t0 = time.time()
            pc = run_per_coin(cls, coins)
            pf = run_portfolio(cls, coins)
            mpc, mpf = pc.metrics(bootstrap), pf.metrics(bootstrap)
            print(f"[{key}] ({time.time() - t0:.1f}s)")
            print("  per-coin  $20:", _line(mpc))
            print("  portfolio $100:", _line(mpf), f"rejected={pf.rejected}")
            print("  exits:", mpc["exit_reasons"])
            row = {"per_coin": _slim(mpc), "portfolio": _slim(mpf), "portfolio_rejected": pf.rejected}
            if sensitivity:
                sens = {}
                for label, cfg in {
                    "zero_costs": SimConfig(cost=CostModel(ultra_bps=0, mev_bps=0, fee_mult=0, impact_mult=1e-9,
                                                           priority_sol=0, base_fee_lamports=0)),
                    "costs_x2": SimConfig(cost=CostModel().stressed(2.0)),
                    "wick_touch": SimConfig(wick_fill="touch"),
                    "wick_worst": SimConfig(wick_fill="worst"),
                }.items():
                    m = run_per_coin(cls, coins, cfg).metrics(0)
                    sens[label] = {"avg_ret_pct": m["avg_ret_pct"], "net_pnl_usd": m["net_pnl_usd"]}
                print("  per-coin sensitivity (avg ret %):",
                      {k: None if v["avg_ret_pct"] is None else round(v["avg_ret_pct"], 2) for k, v in sens.items()})
                row["per_coin_sensitivity"] = sens
            out.setdefault(split, {})[key] = row
    return out


def _line(m: dict) -> str:
    keys = [("trades", "trades"), ("coins_traded", "coins"), ("win_rate_pct", "win%"), ("avg_ret_pct", "avg%"),
            ("median_ret_pct", "med%"), ("profit_factor", "PF"), ("exp_ci95_pct", "CI95%"),
            ("net_pnl_usd", "net$"), ("total_return_pct", "ret%"), ("max_drawdown_pct", "maxDD%"),
            ("best_coin_share_pct", "best%"), ("pnl_without_best_coin_usd", "net$-best")]
    parts = []
    for k, label in keys:
        v = m.get(k)
        if v is None:
            continue
        parts.append(f"{label}={round(v, 2) if isinstance(v, float) else v}")
    return " ".join(parts)


def _slim(m: dict) -> dict:
    return {k: v for k, v in m.items() if k != "by_hour_utc"} | {"by_hour_utc": m.get("by_hour_utc")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    ap.add_argument("--no-sensitivity", action="store_true")
    a = ap.parse_args()
    res = run_all(sensitivity=not a.no_sensitivity)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))
