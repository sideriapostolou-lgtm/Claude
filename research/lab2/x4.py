"""X4: the floor lottery, bought only when a dispersed revival starts at the floor (B2 bars only).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X4/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; the AGENT
column only once knowable; NULL stays None). Labels (the separation gate's 60-minute revival, the floor bound of a
filled trade) are outcomes: they are read through AsOf at a LATER time and never feed a decision.

Mechanism (PREREG 1): a PumpSwap migration pool prices on X = x + v (v ~ 17.58 SOL virtual). When every outside token
is sold back, x -> 0 and the price hits the floor p_f = v^2 / k (~17.6 SOL market cap). The as-of distance to it is

    fm = p / p_f = (X / v)^2,   v = X - x_real   (last completed bar)

Entered at fm, the loss before costs is bounded by 1 - 1/fm; a net inflow dX multiplies the price by ((X + dX) / X)^2.
The unconditional floor lottery was killed in wave 1 (H12). X4 buys only when a revival has started while the price
is still near the floor: AT_FLOOR (median fm over the 20 bars before the last 10 <= 1.25, fm now <= 1.5), DISPERSED
(no minute carries > 50 % of the window's buy SOL) and

* BREADTH: >= 12 buyer-minutes in the last 10 bars, a minute with >= 2 buyers, at least double the previous 10 bars,
  net inflow > 0;
* FLOW: net inflow >= 1.0 SOL over the last 10 bars from >= 3 buyer-minutes;
* BOTH: both.

Exits (all mechanical, filled on the NEXT bar at min(open, low)): TP2X = +100 % take-profit or 60 min; RUN = 90 min;
both with a -60 % "floor broke" stop and the g + 178 min deadline. The floor is the stop.

Separation gate (PREREG 9, TRAIN, before any P&L): among AT_FLOOR decisions at ages 30, 35, ..., 115 min, does a
signal raise P(max close over the next 60 min >= 2 x price) to >= 2x the no-signal rate, >= +5 points, with the
coin-bootstrap 90 % CI of the difference above 0? KILL / UNDERPOWERED stop X4 before the grid runs.

CLI::

    python research/lab2/x4.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x4.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x4.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x4.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x4.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x4.py --stage final
    python research/lab2/x4.py --stage val --check             # prerequisites only

Each stage writes ``X4/<stage>.json`` and ``X4/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
stage after a separation-gate KILL, no VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never
CONFIRM or FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "x4-v1"
OUT_DIR = HERE / "X4"
HYP, HYP_SEP = "X4", "X4-sep"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 4-9)
W_BARS = 10                  # the revival window: the last 10 completed bars
PRE_BARS = 20                # the pre-window before it (dead_before)
FM_FLOOR = 1.25              # dead_before: median fm over the pre-window <= 1.25 (holders can extract <= 2.1 SOL)
FM_MAX = 1.5                 # cheap_now: fm of the last completed bar <= 1.5 (loss to the floor <= 33 % pre-cost)
DISPERSED_MAX_SHARE = 0.5    # no single window minute carries more than half of the window's buy SOL (not Z2)
BREADTH_MIN_BM = 12          # buyer-minutes (wallets >= 0.01 SOL per minute) over the window
BREADTH_MIN_PEAK = 2         # at least one window minute with >= 2 distinct buyers
BREADTH_SURGE = 2.0          # window buyer-minutes >= 2 x the previous 10 bars' (a revival, not steady churn)
FLOW_MIN_NI = 1.0            # SOL of net inflow over the window (~ +11 % at the floor, twice the round trip)
FLOW_MIN_BM = 3              # ... from at least 3 buyer-minutes
SIGNALS = ("BREADTH", "FLOW", "BOTH")
EXIT_GRID = ("TP2X", "RUN")
TP_PCT = {"TP2X": 1.0, "RUN": None}
HOLD_S = {"TP2X": 3600.0, "RUN": 5400.0}
STOP_PCT = 0.60              # "the floor broke" (LP withdrawal / virtual-reserve change); the floor is the stop
AGE_MIN_S, AGE_MAX_S = 1800.0, 9000.0   # entry decisions at ages 30-150 min
EXIT_BY_AGE_S = 178 * 60.0   # registered deadline: sell no later than g + 178 min (never censored)
SIZE_USD = 20.0
INSTANT_MAX_DELAY_S = 5.0    # stratum (reports only)
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; every exit (incl. the take-profit) fills on the NEXT bar
# separation gate (stop rule, TRAIN)
SEP_AGES_MIN = tuple(range(30, 116, 5))
SEP_HORIZON_BARS = 60
SEP_REVIVE_MULT = 2.0
SEP_REPORT_MULT = 1.5        # reported, never decisive
SEP_MIN_OBS, SEP_MIN_COINS = 30, 15
SEP_MIN_RATIO, SEP_MIN_DIFF = 2.0, 0.05
SEP_B = 2000
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 40, 40
MAX_CENSORED = C.MAX_CENSORED_SHARE
SHORTLIST_MAX = 2
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                     # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "w_bars": W_BARS, "pre_bars": PRE_BARS, "fm_floor": FM_FLOOR, "fm_max": FM_MAX,
    "dispersed_max_share": DISPERSED_MAX_SHARE, "breadth_min_bm": BREADTH_MIN_BM,
    "breadth_min_peak": BREADTH_MIN_PEAK, "breadth_surge": BREADTH_SURGE, "flow_min_ni": FLOW_MIN_NI,
    "flow_min_bm": FLOW_MIN_BM, "stop_pct": STOP_PCT, "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD, "placebo": "at_floor (floor-matched), unstratified",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(signal: str, exit_set: str) -> dict:
    if signal not in SIGNALS or exit_set not in EXIT_GRID:
        raise ValueError(f"(signal={signal!r}, exit={exit_set!r}) is not in the pre-registered grid")
    return {**FIXED, "signal": signal, "exit": exit_set, "take_profit_pct": TP_PCT[exit_set],
            "max_hold_s": HOLD_S[exit_set]}


GRID = [make_params(s, e) for s in SIGNALS for e in EXIT_GRID]
assert len(GRID) <= 12
SEP_PARAMS = {"version": VERSION, "test": "separation", "ages_min": list(SEP_AGES_MIN),
              "horizon_bars": SEP_HORIZON_BARS, "revive_mult": SEP_REVIVE_MULT, "min_obs": SEP_MIN_OBS,
              "min_coins": SEP_MIN_COINS, "min_ratio": SEP_MIN_RATIO, "min_diff": SEP_MIN_DIFF, "features": FIXED}
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "size_10usd": dataclasses.replace(FILL, size_usd=10.0)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class X4Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['signal']}|{p['exit']}"


def exit_spec(p: Mapping[str, Any]) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=STOP_PCT, take_profit_pct=TP_PCT[p["exit"]], max_hold_s=HOLD_S[p["exit"]],
                      exit_by_age_s=EXIT_BY_AGE_S)


# =========================================================================== features (AsOf only)


def _k_end(snap: C.AsOf, k_end: int | None) -> int:
    k = snap.k
    return k if k_end is None else max(0, min(int(k_end), k))


def fm_series(bars: C.Bars, lo: int, hi: int) -> np.ndarray:
    """fm = (X / v)^2 for completed bars lo..hi-1, v = X - x_real (NaN where v <= 0 or a value is missing or the
    real reserve is negative: no virtual reserve, no floor)."""
    X = np.asarray(bars.X[lo:hi], float)
    xr = np.asarray(bars.x_real[lo:hi], float)
    v = X - xr
    ok = np.isfinite(X) & np.isfinite(xr) & (X > 0) & (v > 0) & (xr >= -1e-9)
    out = np.full(len(X), np.nan)
    out[ok] = (X[ok] / v[ok]) ** 2
    return out


def floor_state(snap: C.AsOf, k_end: int | None = None, full: bool = True) -> dict:
    """PREREG 4-5 at ``snap`` (or as of an earlier cutoff: the first ``k_end`` completed bars).

    -> {ok, k, fm_now, fm_pre_med, dead_before, cheap_now, at_floor, BM, BM_prev, peak, buy_w, NI, top_min_share,
    dispersed, X, x_real, v, signals: {BREADTH, FLOW, BOTH}}. ``full=False`` (the strategy and the placebo) returns
    early when the last bar is above FM_MAX: ``at_floor`` and every signal are then False either way."""
    k = _k_end(snap, k_end)
    out: dict[str, Any] = {"ok": False, "k": k, "fm_now": None, "fm_pre_med": None, "dead_before": False,
                           "cheap_now": False, "at_floor": False, "BM": None, "BM_prev": None, "peak": None,
                           "buy_w": None, "NI": None, "top_min_share": None, "dispersed": False, "X": None,
                           "x_real": None, "v": None, "signals": {s: False for s in SIGNALS}}
    if k < PRE_BARS + W_BARS:
        return out
    bars = snap.bars
    if not full:
        last = fm_series(bars, k - 1, k)[0]
        if not (math.isfinite(last) and last <= FM_MAX):
            out["fm_now"] = float(last) if math.isfinite(last) else None
            return out
    fm = fm_series(bars, k - PRE_BARS - W_BARS, k)
    fm_pre, fm_now = fm[:PRE_BARS], float(fm[-1])
    fm_pre_med = float(np.median(fm_pre)) if np.isfinite(fm_pre).all() else None
    fm_now_v = fm_now if math.isfinite(fm_now) else None
    dead_before = fm_pre_med is not None and fm_pre_med <= FM_FLOOR
    cheap_now = fm_now_v is not None and fm_now_v <= FM_MAX
    w, pv = slice(k - W_BARS, k), slice(k - 2 * W_BARS, k - W_BARS)
    nb = np.asarray(bars.n_buyers[:k], float)
    buy = np.clip(np.asarray(bars.buy_sol[:k], float)
                  - np.nan_to_num(np.asarray(bars.agent_buy_sol[:k], float), nan=0.0), 0.0, None)
    sell = np.asarray(bars.sell_sol[:k], float)
    BM, BM_prev, peak = float(nb[w].sum()), float(nb[pv].sum()), float(nb[w].max())
    buy_w = float(buy[w].sum())
    NI = buy_w - float(sell[w].sum())
    top = float(buy[w].max()) / buy_w if buy_w > 0 else None
    dispersed = top is not None and top <= DISPERSED_MAX_SHARE
    at_floor = bool(dead_before and cheap_now)
    base = at_floor and dispersed
    breadth = bool(base and BM >= BREADTH_MIN_BM and peak >= BREADTH_MIN_PEAK and BM >= BREADTH_SURGE * BM_prev
                   and NI > 0)
    flow = bool(base and NI >= FLOW_MIN_NI and BM >= FLOW_MIN_BM)
    X, xr = float(bars.X[k - 1]), float(bars.x_real[k - 1])
    out.update(ok=True, fm_now=fm_now_v, fm_pre_med=fm_pre_med, dead_before=bool(dead_before),
               cheap_now=bool(cheap_now), at_floor=at_floor, BM=BM, BM_prev=BM_prev, peak=peak, buy_w=buy_w, NI=NI,
               top_min_share=top, dispersed=bool(dispersed), X=X, x_real=xr if math.isfinite(xr) else None,
               v=(X - xr) if math.isfinite(xr) else None,
               signals={"BREADTH": breadth, "FLOW": flow, "BOTH": bool(breadth and flow)})
    return out


def stratum(snap: C.AsOf) -> str:
    """instant (graduated <= 5 s after creation; known at g) or slow (incl. creation not scanned: > 30 min)."""
    d = snap.get("grad_delay_s")
    return "instant" if d is not None and d <= INSTANT_MAX_DELAY_S else "slow"


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The X4 strategy for common.backtest (one entry per coin; every exit is mechanical)."""
    if pos is not None:
        return None
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    fs = floor_state(snap, full=False)
    if not fs["signals"][p["signal"]]:
        return None
    return C.Enter(exits=exit_spec(p), tag=stratum(snap),
                   state={"fm_now": fs["fm_now"], "BM": fs["BM"], "NI": fs["NI"]})


# =========================================================================== controls


def placebo_ok(snap: C.AsOf) -> bool:
    """Floor-matched control (PLAN 3.4 'the same eligible coins'): AT_FLOOR at the drawn decision."""
    return bool(floor_state(snap, full=False)["at_floor"])


PLACEBO_CONTROLS = {"unmatched": {"eligible": None, "strata": None}}


# =========================================================================== separation gate (labels: never features)


def _grid_time(cd: C.CoinData, target: float) -> float:
    """The last decision-grid time (minute boundary + 20 s) at or before ``target``."""
    j = int(math.floor((target - C.GRID_OFFSET_S - cd.m0) / 60.0))
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def sep_obs(ds: C.Dataset, mints: Iterable[str] | None = None, with_labels: bool = True) -> pd.DataFrame:
    """AT_FLOOR decisions at ages 30, 35, ..., 115 min with their signal flags and (``with_labels``) the LABEL:
    the max close over the next 60 completed bars / the decision price, read through AsOf 60 minutes later."""
    rows = []
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        for a in SEP_AGES_MIN:
            t = _grid_time(cd, cd.g + 60.0 * a)
            snap = ds.asof(m, t)
            fs = floor_state(snap)
            if not fs["at_floor"]:
                continue
            later = ds.asof(m, t + 60.0 * SEP_HORIZON_BARS)
            if later.k - snap.k < SEP_HORIZON_BARS:
                continue                          # the label would leave the data window
            sig = fs["signals"]
            row = {"mint": m, "age_min": a, "t": t, "fm_now": fs["fm_now"], **{s: bool(sig[s]) for s in SIGNALS},
                   "none": not any(sig.values()), "max_ratio60": None, "revive60": None, "revive15": None}
            if with_labels:
                c = np.asarray(later.bars.c[snap.k:snap.k + SEP_HORIZON_BARS], float)
                ratio = float(c.max()) / snap.price
                row.update(max_ratio60=ratio, revive60=bool(ratio >= SEP_REVIVE_MULT),
                           revive15=bool(ratio >= SEP_REPORT_MULT))
            rows.append(row)
    cols = ["mint", "age_min", "t", "fm_now", *SIGNALS, "none", "max_ratio60", "revive60", "revive15"]
    return pd.DataFrame(rows, columns=cols)


def _boot_diff(obs: pd.DataFrame, s: str, B: int, seed: int = 0) -> tuple[float, float] | None:
    """90 % coin-bootstrap CI of rate(revive60 | s) - rate(revive60 | no signal): coins resampled with all their
    observations (both groups)."""
    codes, uniq = pd.factorize(obs["mint"])
    n = len(uniq)
    if n < 2:
        return None
    y = obs["revive60"].astype(float).to_numpy()
    ins, ino = obs[s].to_numpy(bool), obs["none"].to_numpy(bool)
    a_s, n_s = np.bincount(codes, weights=y * ins, minlength=n), np.bincount(codes, weights=ins, minlength=n)
    a_0, n_0 = np.bincount(codes, weights=y * ino, minlength=n), np.bincount(codes, weights=ino, minlength=n)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        idx = rng.integers(0, n, n)
        ds_, d0 = n_s[idx].sum(), n_0[idx].sum()
        if ds_ > 0 and d0 > 0:
            out.append(a_s[idx].sum() / ds_ - a_0[idx].sum() / d0)
    if len(out) < 10:
        return None
    return float(np.quantile(out, 0.05)), float(np.quantile(out, 0.95))


def sep_check(obs: pd.DataFrame, B: int = SEP_B, hide: bool = False) -> dict:
    """PREREG 9. PASS when any signal passes; KILL when none passes and one was powered; else UNDERPOWERED.
    ``hide`` (debug split) returns counts only."""
    n_obs = int(len(obs))
    out: dict[str, Any] = {"n_obs": n_obs, "n_coins": int(obs["mint"].nunique()) if n_obs else 0,
                           "n_none": int(obs["none"].sum()) if n_obs else 0,
                           "need": {"obs": SEP_MIN_OBS, "coins": SEP_MIN_COINS, "ratio": SEP_MIN_RATIO,
                                    "diff": SEP_MIN_DIFF, "revive_mult": SEP_REVIVE_MULT}, "per_signal": {},
                           "passed": []}
    for s in SIGNALS:
        sub = obs[obs[s]] if n_obs else obs
        out["per_signal"][s] = {"n": int(len(sub)), "coins": int(sub["mint"].nunique()) if len(sub) else 0}
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    none = obs[obs["none"]] if n_obs else obs
    rate_0 = float(none["revive60"].astype(float).mean()) if len(none) else None
    out["rate_none"] = rate_0
    out["rate15_none"] = float(none["revive15"].astype(float).mean()) if len(none) else None
    out["mean_ratio_none"] = float(none["max_ratio60"].mean()) if len(none) else None
    any_powered = False
    for s in SIGNALS:
        d = out["per_signal"][s]
        sub = obs[obs[s]] if n_obs else obs
        powered = d["n"] >= SEP_MIN_OBS and d["coins"] >= SEP_MIN_COINS
        any_powered |= powered
        rate_s = float(sub["revive60"].astype(float).mean()) if len(sub) else None
        diff = None if rate_s is None or rate_0 is None else rate_s - rate_0
        ci = _boot_diff(obs, s, B) if (len(sub) and len(none)) else None
        ok = bool(powered and diff is not None and rate_s >= SEP_MIN_RATIO * rate_0 and diff >= SEP_MIN_DIFF
                  and ci is not None and ci[0] > 0)
        d.update(powered=bool(powered), rate=rate_s, diff=diff, diff_ci90=ci, passes=ok,
                 rate15=float(sub["revive15"].astype(float).mean()) if len(sub) else None,
                 mean_ratio=float(sub["max_ratio60"].mean()) if len(sub) else None)
        if ok:
            out["passed"].append(s)
    out["decision"] = "PASS" if out["passed"] else ("KILL" if any_powered else "UNDERPOWERED")
    return out


# =========================================================================== evaluation


def floor_bounds(ds: C.Dataset, trades: pd.DataFrame) -> np.ndarray:
    """REPORT per trade: 1 - p_f / fill price, the loss to the floor before costs (p_f = v^2 / k at the start of the
    fill bar, read through AsOf once that bar's predecessor completed). NaN when v <= 0."""
    out = np.full(len(trades), np.nan)
    for i, r in enumerate(trades.itertuples(index=False)):
        cd = ds.coin(r.mint)
        j = cd.bar_of(r.t_in)
        if j < 1:
            continue
        b = ds.asof(r.mint, cd.bar_start(j) + C.DECISION_LAG_S).bars
        X, xr, y = float(b.X[j - 1]), float(b.x_real[j - 1]), float(b.y[j - 1])
        v = X - xr
        if not (math.isfinite(v) and v > 0 and X > 0 and y > 0):
            continue
        out[i] = 1.0 - (v * v / (X * y)) / float(r.entry_price)
    return out


def _decision_fm(ds: C.Dataset, trades: pd.DataFrame) -> list[float]:
    return [floor_state(ds.asof(r.mint, float(r.t_dec)))["fm_now"] for r in trades.itertuples(index=False)]


def _q(x: Iterable[float | None], qs=(0.1, 0.5, 0.9)) -> dict | None:
    a = np.asarray([v for v in x if v is not None and math.isfinite(v)], float)
    return {f"p{int(100 * q)}": float(np.quantile(a, q)) for q in qs} if len(a) else None


def evaluate(res: C.Result, ds: C.Dataset, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, strata, ages, decision fm, placebo counts) --
    never returns, exit reasons, fill prices, floor bounds or placebo outcomes."""
    t = res.trades
    ages = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_stratum_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "entry_age_min": {"30-60": int(((ages >= 0) & (ages < 60)).sum()), "60-90": int(((ages >= 60) & (ages < 90)).sum()),
                              "90-120": int(((ages >= 90) & (ages < 120)).sum()), "120-151": int((ages >= 120).sum())},
            "decision_fm": _q(_decision_fm(ds, t)) if len(t) else None,
            "n_placebo": int(len(res.placebo)), "n_controls": {k: int(len(v)) for k, v in res.controls.items()},
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    fb = floor_bounds(ds, t) if len(t) else np.zeros(0)
    base["floor_bound"] = _q(fb.tolist()) if len(t) else None
    base["tp_hit_rate"] = float((t["reason"] == "take_profit").mean()) if len(t) else None
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_stratum"] = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} \
        if len(t) else {}
    return base


def combine_verdict(base: Mapping[str, Any]) -> str:
    """PLAN 3.5 items 1-8 and 10 + 3.6 (common.verdict_entry). Item 9 (FINAL mean > 0) is judged in the overall
    verdict once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True:
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def _rank(sig: str, ex: str) -> tuple[int, int]:
    return (SIGNALS.index(sig) if sig in SIGNALS else len(SIGNALS), EXIT_GRID.index(ex) if ex in EXIT_GRID else 9)


def train_configs(passed_signals: Iterable[str]) -> list[dict]:
    """PREREG 9: only the configs of the signals that passed the separation gate run (unrun configs are no trials)."""
    ok = set(passed_signals)
    return [p for p in GRID if p["signal"] in ok]


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 10: qualifiers (sample, mean, top-2, floor-matched control, censoring) ranked by the coin-bootstrap
    90 % CI lower bound (ties: mean, then signal and exit order); shortlist = the top 2."""
    rows = []
    for key, e in evals.items():
        sig, ex = key.split("|")
        pc = (e.get("placebo") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": key, "signal": sig, "exit": ex, "powered": bool(powered), "qualifies": bool(good),
                     "n": e["n"], "coins": e["n_coins"], "mean": e.get("mean"),
                     "mean_without_top2": e.get("mean_without_top2"), "ci90_lo": ci[0] if ci else None,
                     "placebo_diff": pc, "censored_share": cs})
    q = [r for r in rows if r["qualifies"]]
    if q:
        q.sort(key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                              *_rank(r["signal"], r["exit"])))
        top = q[:SHORTLIST_MAX]
        sl = [make_params(r["signal"], r["exit"]) for r in top]
        return {"verdict": "SHORTLISTED", "rows": rows, "ranked": [r["config"] for r in top], "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / floor-matched control / censoring bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max((r['n'] for r in rows), default=0)} trades, {max((r['coins'] for r in rows), default=0)} coins)")
    return {"verdict": v, "reason": why, "rows": rows, "ranked": [], "shortlist": [], "shortlist_hashes": []}


def decide_val_one(ev: Mapping[str, Any]) -> dict:
    n = ev["n"]
    mean, mw2 = ev.get("mean"), ev.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "proceed": v in PROCEED_VAL}


def decide_val(evals: Mapping[str, Mapping[str, Any]], ranked_roles: list[str]) -> dict:
    """PREREG 10 VAL: a filter, never a ranking. Candidate = the TRAIN rank-1 config if it proceeds, else rank 2."""
    per = {role: decide_val_one(evals[role]) for role in ranked_roles}
    for role in ranked_roles:
        if per[role]["proceed"]:
            return {"verdict": per[role]["verdict"], "candidate_role": role, "candidate_config": evals[role]["config"],
                    "candidate_hash": evals[role]["params_hash"], "per_config": per, "proceed": True}
    v = "FAIL_VAL" if any(d["verdict"] == "FAIL_VAL" for d in per.values()) else "UNDERPOWERED_VAL"
    return {"verdict": v, "candidate_role": None, "candidate_config": None, "candidate_hash": None, "per_config": per,
            "proceed": False}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 10: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: X4 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds X4 never looked at. The TRAIN third hosted the debug run and, before it,
    wave 1's unconditional floor-lottery measurement (PREREG 1): reported apart, never judged."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                            "note": "census TRAIN third: debug run + wave-1 H12 (PREREG 1), not judged"}}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and <= 5 % of tradeable coins missing B2 data."""
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    notes = []
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                         f"B2 {d['b2_hours']}/{d['hours_in_split']} h")
    notes += C.coverage_problems(cov)
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{HYP}.json")


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, dict]]:
    """[(role, params)] the stage runs: the grid (debug; TRAIN filters it by the gate at run time), the shortlist in
    rank order (val), the VAL candidate (test / confirm / final)."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    if stage == "val":
        return [(f"rank{i + 1}", c) for i, c in enumerate(sl["configs"])]
    val = _read_json(Path(out_dir) / "val.json") or {}
    h = (val.get("decision") or {}).get("candidate_hash")
    cand = [c for c in sl["configs"] if C.params_hash(c) == h]
    return [("candidate", cand[0])] if cand else []


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`X4Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X4Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X4Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X4Refused("PREREG.md changed after the first official TRAIN run; record changes in X4/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise X4Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X4Refused("TRAIN already ran on complete data (X4/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X4Refused("no TRAIN result (X4/train.json): run --stage train first")
    if train.get("provisional"):
        raise X4Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_SEP":
        raise X4Refused("X4 is dead: the separation gate failed on TRAIN (PREREG 9)")
    if tv != "SHORTLISTED":
        raise X4Refused(f"TRAIN decision {tv}: X4 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise X4Refused("no VAL shortlist for X4 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise X4Refused("the X4 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X4Refused("VAL already ran (X4/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise X4Refused(f"no VAL result (X4/val.json): {stage.upper()} needs a VAL decision first")
    vd = val.get("decision") or {}
    if vd.get("verdict") not in PROCEED_VAL:
        raise X4Refused(f"VAL decision {vd.get('verdict')}: X4 stopped (PLAN 8 rule 7 input); {stage.upper()} is not "
                        "spent")
    if vd.get("candidate_hash") not in sl.get("hashes", []):
        raise X4Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X4Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise X4Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X4Refused(f"{stage.upper()} already ran (X4/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise X4Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X4Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    return info


# =========================================================================== stage runner


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        x = float(o)
        return None if math.isnan(x) or math.isinf(x) else x
    if o is pd.NA:
        return None
    return o


def _coverage_counts(split: str, flow: Path | None, census: C.Census | None) -> dict:
    if split == "final":
        return {s: C.coverage_dataset(s, flow, census).coverage for s in C.FINAL_SPLITS}
    return C.coverage_dataset(split, flow, census).coverage


def _span_days(ds: C.Dataset) -> float:
    c = ds.coins["created_for_split"] if len(ds) else pd.Series(dtype=float)
    if ds.split in C.SPLIT_BOUNDS and ds.coverage.get("complete"):
        lo, hi = C.SPLIT_BOUNDS[ds.split]
        return (hi - lo) / 86400.0
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9) if len(c) else float("nan")


def event_counts(ds: C.Dataset) -> dict:
    """Counts and as-of structure only (no prices after a decision, no returns): how often each AT_FLOOR / signal
    condition holds on the decision grid at ages 30-150 min, where the floor sits (min fm per coin) and the virtual
    reserve v (a mechanics check: ~17.58 SOL)."""
    conds = ("dead_before", "cheap_now", "at_floor", "dispersed_at_floor", "bm12_at_floor", "ni1_at_floor",
             *SIGNALS)
    coins = {c: set() for c in conds}
    minutes = {c: 0 for c in conds}
    snap_ages = (30, 60, 90, 120, 150)
    at_age = {a: 0 for a in snap_ages}
    strata: dict[str, int] = {}
    fm_floor_minutes, fm_min_coin, v_at60 = [], [], []
    n_dec = 0
    for m in ds.mints:
        cd = ds.coin(m)
        first = True
        fmin = math.inf
        for j in range(1, C.N_BARS + 1):          # the engine's decision grid: t = bar_start(j) + 20 s
            t = float(cd.bar_start(j) + C.GRID_OFFSET_S)
            age = t - cd.g
            if age < AGE_MIN_S or age > AGE_MAX_S:
                continue
            snap = ds.asof(m, t)
            if first:
                s = stratum(snap)
                strata[s] = strata.get(s, 0) + 1
                first = False
            n_dec += 1
            fs = floor_state(snap)
            if fs["fm_now"] is not None:
                fmin = min(fmin, fs["fm_now"])
            if fs["v"] is not None and abs(age - 3600) < 30:
                v_at60.append(fs["v"])
            for a in snap_ages:
                if abs(age - 60 * a) < 30 and fs["at_floor"]:
                    at_age[a] += 1
            flags = {"dead_before": fs["dead_before"], "cheap_now": fs["cheap_now"], "at_floor": fs["at_floor"],
                     "dispersed_at_floor": fs["at_floor"] and fs["dispersed"],
                     "bm12_at_floor": fs["at_floor"] and (fs["BM"] or 0) >= BREADTH_MIN_BM,
                     "ni1_at_floor": fs["at_floor"] and (fs["NI"] or 0) >= FLOW_MIN_NI,
                     **{s: fs["signals"][s] for s in SIGNALS}}
            if fs["at_floor"]:
                fm_floor_minutes.append(fs["fm_now"])
            for c, v in flags.items():
                if v:
                    coins[c].add(m)
                    minutes[c] += 1
        if math.isfinite(fmin):
            fm_min_coin.append(fmin)
    return {"coins": len(ds), "strata": strata, "decision_minutes": n_dec,
            "coins_with_condition": {c: len(v) for c, v in coins.items()},
            "coin_minutes_with_condition": dict(minutes),
            "coins_at_floor_at_age_min": {str(a): n for a, n in at_age.items()},
            "fm_now_at_floor_minutes": _q(fm_floor_minutes, (0.1, 0.25, 0.5, 0.75, 0.9)),
            "fm_min_per_coin_30_150": _q(fm_min_coin, (0.05, 0.1, 0.25, 0.5, 0.75)),
            "coins_min_fm_le_1.25": int(sum(1 for v in fm_min_coin if v <= FM_FLOOR)),
            "v_sol_at_60min": _q(v_at60, (0.01, 0.1, 0.5, 0.9, 0.99))}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X4/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x4_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X4Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise X4Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise X4Refused("no configs to run (shortlist or VAL candidate missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X4Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():      # archive, never overwrite, an official run
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        if ds is None:
            ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds)}
        run_cfgs = configs
        # ---- separation gate (TRAIN: before any P&L; debug: counts only)
        if stage in ("train", "debug"):
            obs = sep_obs(ds, with_labels=not debug)
            sep = sep_check(obs, B=min(B, SEP_B), hide=debug)
            sep["trial"] = C.record_run(HYP_SEP, SEP_PARAMS, split, {"n": sep["n_obs"], "mean": None}, ledger_path,
                                        debug=debug)
            doc["separation"] = sep
            if debug:
                doc["event_counts"] = event_counts(ds)
            elif sep["decision"] != "PASS":
                v = "KILLED_SEP" if sep["decision"] == "KILL" else "UNDERPOWERED_SEP"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "PREREG 9: the separation gate precedes any P&L; the grid was not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
            else:
                run_cfgs = [(config_key(p), p) for p in train_configs(sep["passed"])]
        results: dict[str, C.Result] = {}
        for role, p in run_cfgs:
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok,
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, ds, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        doc["n_trials_total"] = n_tr
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 10, rank order {dec['ranked']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals, [r for r, _ in configs])
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", (_read_json(out_dir / "val.json") or {}).get("decision", {})
                                 .get("candidate_role"))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x4 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise X4Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"])) for role, r in results.items()]
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str | None) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if role is None or not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["role"] == role].reset_index(drop=True)


def _finish(doc: dict, out_dir: Path, stage: str, provisional: bool, t0: float, ledger_path: Path | None) -> dict:
    doc["runtime_s"] = round(time.time() - t0, 1)
    doc["n_trials_total"] = C.n_trials(ledger_path)
    doc["overall"] = overall_verdict(out_dir, pending=doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = stage + ("_prelim" if provisional else "")
    doc = _jsonable(doc)
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=False))
    (out_dir / f"{name}.md").write_text(render_md(doc))
    return doc


def overall_verdict(out_dir: Path, pending: Mapping[str, Any] | None = None) -> str:
    """The hypothesis-level status from every stage written so far (``pending`` = the stage being written)."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return _read_json(Path(out_dir) / f"{s}.json")

    tr = doc("train")
    if not tr or tr.get("provisional"):
        return "PENDING (no official TRAIN run)"
    tv = (tr.get("decision") or {}).get("verdict")
    if tv == "KILLED_SEP":
        return "KILLED (no signal separates floor revivals: PREREG 9)"
    if tv == "UNDERPOWERED_SEP":
        return "UNDERPOWERED (too few floor signals for the separation gate on TRAIN)"
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN)"
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vv = (va.get("decision") or {}).get("verdict")
    if vv == "FAIL_VAL":
        return "NO EDGE (failed VAL; PLAN 8 rule 7 input)"
    if vv == "UNDERPOWERED_VAL":
        return "UNDERPOWERED (VAL)"
    te = doc("test")
    if not te:
        return "PENDING TEST"
    ok, why = confirm_allowed(te)
    if not ok:
        return f"NO EDGE ({why})"
    co = doc("confirm")
    if not co:
        return "PENDING CONFIRM"
    cv = (co.get("verdict") or {}).get("verdict")
    if cv == "UNDERPOWERED":
        return "UNDERPOWERED (CONFIRM)"
    if cv != "PASS":
        return f"NO EDGE (CONFIRM {cv})"
    fi = doc("final")
    if not fi:
        return "PENDING FINAL"
    return "EDGE" if (fi.get("decision") or {}).get("mean_positive") else "NO EDGE (FINAL mean <= 0)"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# X4 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X4 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, labels and fill prices are "
              "hidden and no parameter was chosen here.**", ""]
    sp = doc.get("separation")
    if sp:
        L += ["## Separation gate (PREREG 9)", "",
              f"- AT_FLOOR observations: {sp['n_obs']} from {sp['n_coins']} coins; with no signal: {sp['n_none']} "
              f"(need ≥ {SEP_MIN_OBS} signal observations from ≥ {SEP_MIN_COINS} coins).",
              f"- Decision: **{sp['decision']}**" + (f"; passed: {sp['passed']}." if sp.get("passed") else "."), ""]
        if "rate_none" in sp:
            L += [f"- No-signal revival rate (2× within 60 min): {_pct(sp['rate_none'])}; 1.5×: "
                  f"{_pct(sp.get('rate15_none'))}.", "",
                  "| signal | obs | coins | revive 2× | diff vs none | 90% CI (coin) | revive 1.5× | passes |",
                  "|---|---:|---:|---:|---:|---|---:|---|"]
            for s, d in sp["per_signal"].items():
                L.append(f"| {s} | {d['n']} | {d['coins']} | {_pct(d.get('rate'))} | {_pct(d.get('diff'))} | "
                         f"{_ci(d.get('diff_ci90'))} | {_pct(d.get('rate15'))} | {d.get('passes')} |")
        else:
            L += ["| signal | obs | coins |", "|---|---:|---:|"]
            for s, d in sp["per_signal"].items():
                L.append(f"| {s} | {d['n']} | {d['coins']} |")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts and structure (no returns)", "",
              f"- Coins {ec['coins']} (strata {ec['strata']}); decision minutes at ages 30-150: {ec['decision_minutes']}.",
              f"- Coins AT_FLOOR at age 30 / 60 / 90 / 120 / 150 min: {ec['coins_at_floor_at_age_min']}.",
              f"- fm at AT_FLOOR decision minutes: {ec['fm_now_at_floor_minutes']}.",
              f"- Min fm per coin over ages 30-150 min: {ec['fm_min_per_coin_30_150']}; coins whose min fm ≤ "
              f"{FM_FLOOR}: {ec['coins_min_fm_le_1.25']}.",
              f"- Virtual reserve v (SOL) at age 60 min (mechanics check): {ec['v_sol_at_60min']}.", "",
              "| condition | coins | coin-minutes |", "|---|---:|---:|"]
        for c, n in ec["coins_with_condition"].items():
            L.append(f"| {c} | {n} | {ec['coin_minutes_with_condition'][c]} |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | strata | entry age (min) | decision fm | placebo trades | controls | "
                  "horizon exits | entries/day |", "|---|---:|---:|---|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_stratum_n']} | {e['entry_age_min']} | "
                         f"{e['decision_fm']} | {e['n_placebo']} | {e['n_controls']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | floor-matched diff | "
                  "unmatched diff | TP hits | costs ×1.5 | $10 ticket | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                stt = e.get("stress") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('unmatched') or {}).get('mean_diff'))} | {_pct(e.get('tp_hit_rate'), 0)} | "
                         f"{_pct(stt.get('costs_x1.5'))} | {_pct(stt.get('size_10usd'))} | "
                         f"{_pct(e.get('censored_share'), 0)} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, floor-matched diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (rank order {dec.get('ranked')}).")
    if dec.get("per_config"):
        for role, d in dec["per_config"].items():
            L.append(f"- VAL {role}: {d['verdict']} (n {d['n']}, mean {_pct(d['mean'])}).")
        L.append(f"- Candidate: {dec.get('candidate_config')} ({dec.get('candidate_role')}).")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    if dec.get("reason"):
        L.append(f"- Reason: {dec['reason']}.")
    if dec.get("note"):
        L.append(f"- {dec['note']}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="X4 floor lottery with a revival signal: pre-registered stages; see "
                                             "research/lab2/X4/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=10_000, help="bootstrap draws")
    ap.add_argument("--n-placebo", type=int, default=20)
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            print(json.dumps(check_prereqs(stage, rerun_reason=a.rerun_reason), indent=1))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B,
                        n_placebo=a.n_placebo)
    except X4Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
