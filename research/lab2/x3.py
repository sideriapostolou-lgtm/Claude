"""X3: buy the exhaustion of a selling climax, only in deep pools, later in the coin's life.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X3/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; static fields
only once knowable; NULL stays None). Labels (the reversion gate's mid-price changes) are outcomes read through AsOf
at a LATER time and never feed a decision.

Mechanism (PREREG 1): a constant-product pool has no market maker, so an impatient seller who dumps in one minute pays
the full curve impact; whoever buys after the dump supplies the liquidity and collects the rebound. X3 trades that
only where it is most likely a liquidity event (g + 60 -> g + 145 min, market cap >= 1,470 SOL, non-factory and
non-operator coins) and where our own round trip is cheapest, and it asks the rebound to beat THAT pool's exact round
trip. The climax outflow and the rebound target come from the pricing reserve X = x + v (price = X^2 / k):
target P* = close_c * ((X_c + 0.5 dX) / X_c)^2, the price once half of the climax outflow dX has returned.

CLI::

    python research/lab2/x3.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x3.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x3.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x3.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x3.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x3.py --stage final
    python research/lab2/x3.py --stage val --check             # prerequisites only

Each stage writes ``X3/<stage>.json`` and ``X3/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlist, nothing after a reversion-gate KILL, TEST / CONFIRM / FINAL once each, never
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

VERSION = "x3-v1"
OUT_DIR = HERE / "X3"
HYP, HYP_GATE = "X3", "X3-gate"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-8)
AGE_MIN_S = 60 * 60.0        # decisions from g + 60 min (after BOOST, the airdrop dumps and the rug window)
AGE_MAX_S = 145 * 60.0       # ... to g + 145 min: a 30-min hold ends before the registered deadline
EXIT_BY_AGE_S = 178 * 60.0   # registered deadline inside the B2 window (fills by g + 179 min); never binds here
DEEP_MCAP_SOL = 1470.0       # pump.fun fee-tier boundary (1.20 % -> 1.15 % per side); never searched
SHALLOW_MCAP_SOL = 100.0     # gate diagnostic only: "shallow" = [100, 1,470) SOL (above the ~17.6 SOL floor)
W_BASE = 30                  # baseline window: the 30 completed bars before the climax bar
VOL_FLOOR_SOL = 0.05         # baseline floor (avoids dividing by a dead coin's zero median)
VOL_MULT = 3.0               # climax: sell SOL >= 3 x the median minute volume (buy + sell)
MAX_DROP = 0.50              # a > 50 % one-minute drop is a rug (M1's label), not a climax
LP_FRAC_Y = 0.005            # liquidity event: tokens leave / enter the pool outside trades by > 0.5 % of y
RHO = 0.5                    # target: half of the climax outflow returns to the pricing reserve
EXHAUST_SELL_FRAC = 1.0 / 3  # confirm timing: the next minute sells <= 1/3 of the climax minute ...
STOP_PCT = 0.15              # ... and closes at or above the climax close. Stop: PLAN D1 / X1 grid level
SIZE_USD = 20.0
BUCKETS = (1470.0, 3440.0, 9820.0)   # depth buckets for reporting: fee-tier boundaries (1.15 / 1.05 / 0.95 %)
M_GRID = (2.0, 4.0)
TIMINGS = ("now", "confirm")
HOLDS_MIN = (10, 30)
# classes (PLAN 4.2 rules M1 uses): OPERATOR -> M1 only, FACTORY -> airdrop dumps; X3 trades OTHER only
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MAX_DELAY_S = 5.0
FACTORY_MIN_TOP5 = 0.85
ALLOWED_CLASSES = ("OTHER",)
# reversion gate (PREREG 8)
GATE_M, GATE_TIMING = 2.0, "now"
GATE_DRAWS, GATE_MAX_TRIES = 20, 200
GATE_SKIP_S = 1800.0         # after an event, the coin's next 30 min are skipped (labels never overlap)
GATE_MIN_EVENTS, GATE_MIN_COINS = 50, 30
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 30, 20
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                         # PLAN 3.5 default bar
PASS_CONTROL_MARGIN = 0.06                   # PLAN 3.5 item 5
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

MAIN_CFG = C.FillConfig(exit_delay_bars=1)   # worst fills; every exit triggered in bar j fills at bar j + 1's low
STRESS = {"costs_x1.5": MAIN_CFG.stressed(1.5), "rent_0.22": dataclasses.replace(MAIN_CFG, rent_usd=0.22),
          "latency_60s": dataclasses.replace(MAIN_CFG, latency_s=60.0), "same_bar_exits": C.FillConfig()}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}

FIXED = {
    "version": VERSION, "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S, "exit_by_age_s": EXIT_BY_AGE_S,
    "deep_mcap_sol": DEEP_MCAP_SOL, "w_base": W_BASE, "vol_floor_sol": VOL_FLOOR_SOL, "vol_mult": VOL_MULT,
    "max_drop": MAX_DROP, "lp_frac_y": LP_FRAC_Y, "rho": RHO, "exhaust_sell_frac": EXHAUST_SELL_FRAC,
    "stop_pct": STOP_PCT, "size_usd": SIZE_USD, "classes": list(ALLOWED_CLASSES), "alive": "AsOf.alive()",
    "placebo": "age window & OTHER & alive & deep, +-120 s",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exits",
}


def make_params(m: float, timing: str, hold_min: int) -> dict:
    if m not in M_GRID or timing not in TIMINGS or hold_min not in HOLDS_MIN:
        raise ValueError(f"({m}, {timing!r}, {hold_min}) is not in the X3 grid")
    return {**FIXED, "m": float(m), "timing": timing, "hold_min": int(hold_min)}


GRID = [make_params(m, tm, h) for m in M_GRID for tm in TIMINGS for h in HOLDS_MIN]
GATE_PARAMS = {"version": VERSION, "test": "reversion_gate", "m": GATE_M, "timing": GATE_TIMING,
               "holds_min": list(HOLDS_MIN), "draws": GATE_DRAWS, "skip_s": GATE_SKIP_S,
               "min_events": GATE_MIN_EVENTS, "min_coins": GATE_MIN_COINS, "fixed": FIXED}


class X3Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"m{p['m']:g}|{p['timing']}|h{p['hold_min']}"


# =========================================================================== features (AsOf only)


def x3_class(snap: C.AsOf) -> str | None:
    """PLAN 4.2 rules in PLAN order (as m1.m1_class): OPERATOR, FACTORY, else OTHER. None when an input that decides
    the class is NULL or not yet knowable (fail closed; NULL is never 0)."""
    buy, nby = snap.get("w120_buy_sol"), snap.get("w120_n_buyers")
    if buy is None or nby is None or not snap.agent_resolved:
        return None
    ag_sol, ag_n = 0.0, 0
    if snap.agent_detected:
        aw = snap.get("agent_wallet")
        ag_sol = sum(float(w[1]) for w in (snap.get("w120_top10") or ()) if w[0] == aw)
        ag_n = 1
    if buy - ag_sol >= OPERATOR_MIN_BUY_SOL and nby - ag_n <= OPERATOR_MAX_BUYERS:
        return "OPERATOR"
    d = snap.get("grad_delay_s")
    if d is None:
        lb = snap.get("grad_delay_lb_s")
        if lb is None:
            return None
        return "OTHER" if lb > FACTORY_MAX_DELAY_S else None
    if d <= FACTORY_MAX_DELAY_S:
        sh = snap.top_share("w120", 5, exclude_agent=True)
        if sh is None:
            return None
        if sh >= FACTORY_MIN_TOP5:
            return "FACTORY"
    return "OTHER"


def depth_bucket(mcap_sol: float) -> str:
    """Reporting bucket at the fee-tier boundaries ('d1470' = [1,470, 3,440), ...; 'shallow' below 1,470 SOL)."""
    lab = "shallow"
    for b in BUCKETS:
        if mcap_sol >= b:
            lab = f"d{b:g}"
    return lab


def in_band(mcap_sol: float, band: str) -> bool:
    if band == "deep":
        return mcap_sol >= DEEP_MCAP_SOL
    if band == "shallow":
        return SHALLOW_MCAP_SOL <= mcap_sol < DEEP_MCAP_SOL
    raise ValueError(band)


def climax_info(bars: C.Bars, c: int) -> dict | None:
    """The climax test on completed bar ``c`` (PREREG 4); None when bars c - 31 .. c are not all completed.

    ``bars`` is an AsOf view (completed bars only), so nothing after the cutoff can enter."""
    if c < W_BASE + 1 or c >= len(bars):
        return None
    buy, sell = bars.buy_sol, bars.sell_sol
    vol = np.asarray(buy[c - W_BASE:c], float) + np.asarray(sell[c - W_BASE:c], float)
    base = max(float(np.median(vol)), VOL_FLOOR_SOL)
    s_c, b_c = float(sell[c]), float(buy[c])
    prev_max = float(np.max(sell[c - W_BASE:c]))
    p0, p1 = float(bars.c[c - 1]), float(bars.c[c])
    X0, X1 = float(bars.X[c - 1]), float(bars.X[c])
    y0, y1 = float(bars.y[c - 1]), float(bars.y[c])
    resid = y1 - (y0 - float(bars.buy_tok[c]) + float(bars.sell_tok[c]))
    lp_event = bool(y0 > 0 and abs(resid) > LP_FRAC_Y * y0)
    drop = 1.0 - p1 / p0 if p0 > 0 else 0.0
    dX = X0 - X1
    fires = bool(bars.traded[c] and s_c >= VOL_MULT * base and s_c >= prev_max and s_c > b_c and p1 < p0
                 and X1 < X0 and not lp_event and drop <= MAX_DROP)
    target = p1 * ((X1 + RHO * dX) / X1) ** 2 if X1 > 0 else None
    return {"c": int(c), "fires": fires, "sell": s_c, "buy": b_c, "base_vol": base, "sell_mult": s_c / base,
            "prev_max_sell": prev_max, "drop": drop, "X_before": X0, "X_after": X1, "outflow": dX,
            "outflow_frac": dX / X0 if X0 > 0 else None, "lp_event": lp_event, "close": p1, "target": target}


def round_trip_frac(snap: C.AsOf, cost: C.CostModel | None = None) -> float | None:
    """Exact $20 round trip at the decision state (fee tier by date and market cap, impact on the pool's own
    k = X * y of the last completed bar, Ultra + buffer, 2 network fees), as a fraction of the stake."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return None
    X, y = float(bars.X[k - 1]), float(bars.y[k - 1])
    if not (X > 0 and y > 0):
        return None
    return C.round_trip_pct(SIZE_USD / snap.sol_usd, snap.price, X * y, snap.t, cost or C.CostModel()) / 100.0


def entry_decision(snap: C.AsOf, p: Mapping[str, Any], band: str = "deep") -> tuple[bool, dict]:
    """PREREG 5 at ``snap`` except the age window and the class (checked by :func:`strategy`): depth band, climax at
    bar c (``now``: the last completed bar; ``confirm``: the one before, plus exhaustion), alive, tp >= m x rt."""
    k = snap.k
    timing = p["timing"]
    c = k - 1 if timing == "now" else k - 2
    mcap = snap.mcap_sol
    info: dict[str, Any] = {"k": k, "c": c, "mcap_sol": mcap, "bucket": depth_bucket(mcap), "climax": None,
                            "exhausted": None, "alive": None, "rt": None, "tp": None, "tp_over_rt": None}
    if not in_band(mcap, band):
        return False, info
    bars = snap.bars
    ci = climax_info(bars, c)
    info["climax"] = ci
    if ci is None or not ci["fires"]:
        return False, info
    if timing == "confirm":
        j = k - 1
        info["exhausted"] = bool(float(bars.sell_sol[j]) <= EXHAUST_SELL_FRAC * ci["sell"]
                                 and float(bars.c[j]) >= ci["close"])
        if not info["exhausted"]:
            return False, info
    info["alive"] = bool(snap.alive())
    if not info["alive"]:
        return False, info
    rt = round_trip_frac(snap)
    info["rt"] = rt
    if rt is None or rt <= 0 or ci["target"] is None:
        return False, info
    tp = ci["target"] / snap.price - 1.0
    info["tp"] = tp
    info["tp_over_rt"] = tp / rt
    return bool(tp >= float(p["m"]) * rt), info


def exit_spec(p: Mapping[str, Any], tp: float) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=STOP_PCT, take_profit_pct=float(tp), max_hold_s=60.0 * float(p["hold_min"]),
                      exit_by_age_s=EXIT_BY_AGE_S)


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The X3 strategy for common.backtest (one entry per coin; every exit is mechanical)."""
    if pos is not None:
        return None
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    if not in_band(snap.mcap_sol, "deep"):
        return None                                 # cheap test first: depth changes over time, never SKIP on it
    cls = x3_class(snap)
    if cls not in ALLOWED_CLASSES:
        return C.SKIP                               # OPERATOR / FACTORY / unresolvable: static by g + 420 s
    ok, info = entry_decision(snap, p, "deep")
    if not ok:
        return None
    ci = info["climax"]
    return C.Enter(exits=exit_spec(p, info["tp"]), tag=info["bucket"],
                   state={"rt": info["rt"], "tp": info["tp"], "drop": ci["drop"], "outflow_frac": ci["outflow_frac"],
                          "sell_mult": ci["sell_mult"]})


def _eligible(snap: C.AsOf, band: str) -> bool:
    if not (AGE_MIN_S <= snap.age_s <= AGE_MAX_S):
        return False
    if not in_band(snap.mcap_sol, band):
        return False
    return x3_class(snap) in ALLOWED_CLASSES and bool(snap.alive())


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe (judged): age window, class OTHER, alive and deep at the draw's decision."""
    return _eligible(snap, "deep")


def placebo_any_depth(snap: C.AsOf) -> bool:
    """Diagnostic control: the same without the depth condition."""
    return AGE_MIN_S <= snap.age_s <= AGE_MAX_S and x3_class(snap) in ALLOWED_CLASSES and bool(snap.alive())


PLACEBO_CONTROLS = {"any_depth": {"eligible": placebo_any_depth, "strata": None}}


# =========================================================================== reversion gate (PREREG 8)


def decision_times(cd: C.CoinData) -> list[float]:
    """The engine's decision grid (minute boundary + 20 s) inside the age window."""
    out = []
    for j in range(C.N_BARS):
        t = float(cd.bar_start(j + 1) + C.GRID_OFFSET_S)
        a = t - cd.g
        if a < AGE_MIN_S:
            continue
        if a > AGE_MAX_S:
            break
        out.append(t)
    return out


def _labels(ds: C.Dataset, m: str, snap: C.AsOf) -> dict[int, float | None]:
    """OUTCOME: mid-price change over H minutes from the decision close, read through AsOf H minutes later."""
    out = {}
    for h in HOLDS_MIN:
        later = ds.asof(m, snap.t + 60.0 * h)
        out[h] = (later.price / snap.price - 1.0) if later.k - snap.k >= h and snap.price > 0 else None
    return out


def gate_events(ds: C.Dataset, band: str = "deep", timing: str = GATE_TIMING, with_labels: bool = True,
                mints: Iterable[str] | None = None) -> pd.DataFrame:
    """Gate events: every decision where the (m = 2, ``timing``) entry rule holds in ``band``; after an event the
    coin's next 30 min are skipped. Labels are added only when ``with_labels``."""
    p = {"m": GATE_M, "timing": timing}
    rows = []
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        nxt = -math.inf
        for t in decision_times(cd):
            if t < nxt:
                continue
            snap = ds.asof(m, t)
            if not in_band(snap.mcap_sol, band):
                continue
            cls = x3_class(snap)
            if cls not in ALLOWED_CLASSES:
                break
            ok, info = entry_decision(snap, p, band)
            if not ok:
                continue
            ci = info["climax"]
            row = {"mint": m, "band": band, "timing": timing, "t": t, "age_min": (t - cd.g) / 60.0,
                   "mcap_sol": info["mcap_sol"], "bucket": info["bucket"], "rt": info["rt"], "tp": info["tp"],
                   "drop": ci["drop"], "outflow_frac": ci["outflow_frac"], "sell_mult": ci["sell_mult"]}
            if with_labels:
                for h, v in _labels(ds, m, snap).items():
                    row[f"label{h}"] = v
            rows.append(row)
            nxt = t + GATE_SKIP_S
    cols = ["mint", "band", "timing", "t", "age_min", "mcap_sol", "bucket", "rt", "tp", "drop", "outflow_frac",
            "sell_mult"] + ([f"label{h}" for h in HOLDS_MIN] if with_labels else [])
    return pd.DataFrame(rows, columns=cols)


def gate_draws(ds: C.Dataset, events: pd.DataFrame, band: str = "deep", seed: int = 0,
               n_draws: int = GATE_DRAWS, max_tries: int = GATE_MAX_TRIES) -> pd.DataFrame:
    """Matched random decisions for each event: random coins of the split, decision age within +-120 s, eligible as
    the placebo in ``band``; OUTCOME labels over the same horizons. One row per event: n_draws and mean labels."""
    mints = ds.mints
    rows = []
    band_id = {"deep": 0, "shallow": 1}[band]
    for i, ev in enumerate(events.itertuples(index=False)):
        rng = np.random.default_rng([seed, band_id, i])
        a = float(ev.age_min) * 60.0
        got = tries = 0
        acc: dict[int, list[float]] = {h: [] for h in HOLDS_MIN}
        while got < n_draws and tries < max_tries:
            tries += 1
            m = mints[int(rng.integers(len(mints)))]
            cd = ds.coin(m)
            ks = np.arange(1, C.N_BARS)
            ages = cd.m0 + 60 * ks + C.GRID_OFFSET_S - cd.g
            cand = ks[np.abs(ages - a) <= C.PLACEBO_AGE_TOL_S]
            if not len(cand):
                continue
            k = int(cand[int(rng.integers(len(cand)))])
            snap = ds.asof(m, float(cd.bar_start(k) + C.GRID_OFFSET_S))
            if not _eligible(snap, band):
                continue
            lab = _labels(ds, m, snap)
            if any(v is None for v in lab.values()):
                continue
            for h in HOLDS_MIN:
                acc[h].append(float(lab[h]))
            got += 1
        rows.append({"event": i, "n_draws": got, **{f"draw{h}": (float(np.mean(acc[h])) if acc[h] else None)
                                                    for h in HOLDS_MIN}})
    return pd.DataFrame(rows, columns=["event", "n_draws"] + [f"draw{h}" for h in HOLDS_MIN])


def gate_obs(ds: C.Dataset, with_labels: bool = True, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Every event table the gate reads: 'deep' (decisive), 'deep_confirm' and 'shallow' (diagnostics). Without
    labels (debug) the matched draws are not drawn either: counts only."""
    out = {}
    for name, band, timing in (("deep", "deep", "now"), ("deep_confirm", "deep", "confirm"),
                               ("shallow", "shallow", "now")):
        ev = gate_events(ds, band, timing, with_labels=with_labels)
        if with_labels:
            dr = gate_draws(ds, ev, band, seed=seed)
            ev = pd.concat([ev.reset_index(drop=True), dr.drop(columns=["event"])], axis=1)
        out[name] = ev
    return out


def _excess(ev: pd.DataFrame, h: int, B: int) -> dict | None:
    d = ev[(ev["n_draws"] > 0) & ev[f"label{h}"].notna() & ev[f"draw{h}"].notna()]
    if not len(d):
        return None
    diff = d[f"label{h}"].to_numpy(float) - d[f"draw{h}"].to_numpy(float)
    return {"n": int(len(d)), "n_coins": int(d["mint"].nunique()), "excess": float(diff.mean()),
            "mean_rt": float(d["rt"].mean()), "mean_label": float(d[f"label{h}"].mean()),
            "mean_draw": float(d[f"draw{h}"].mean()),
            "excess_ci95_coin": C.coin_bootstrap_ci(diff, d["mint"].to_numpy(object), 0.95, B)}


def gate_check(obs: Mapping[str, pd.DataFrame], B: int = 2000, hide: bool = False) -> dict:
    """PREREG 8: PASS / KILL / UNDERPOWERED on the deep `now` events; diagnostics never decide. ``hide`` (debug):
    counts only."""
    deep = obs["deep"]
    usable = deep[deep["n_draws"] > 0] if "n_draws" in deep else deep
    out: dict[str, Any] = {
        "n_events": int(len(deep)), "n_coins": int(deep["mint"].nunique()) if len(deep) else 0,
        "n_events_with_draws": int(len(usable)) if "n_draws" in deep else None,
        "by_bucket": deep["bucket"].value_counts().to_dict() if len(deep) else {},
        "n_events_deep_confirm": int(len(obs.get("deep_confirm", pd.DataFrame()))),
        "n_events_shallow": int(len(obs.get("shallow", pd.DataFrame()))),
        "need": {"events": GATE_MIN_EVENTS, "coins": GATE_MIN_COINS, "rule": "excess_H >= mean rt for some H"}}
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        out["passing_horizons"] = list(HOLDS_MIN)
        return out
    n, nc = len(usable), int(usable["mint"].nunique()) if len(usable) else 0
    per = {}
    for h in HOLDS_MIN:
        e = _excess(deep, h, B) if len(deep) else None
        if e is not None:
            e["pass"] = bool(e["excess"] >= e["mean_rt"])
        per[str(h)] = e
    out["per_horizon"] = per
    passing = [h for h in HOLDS_MIN if per[str(h)] and per[str(h)]["pass"]]
    if n < GATE_MIN_EVENTS or nc < GATE_MIN_COINS:
        out["decision"], passing = "UNDERPOWERED", []
    elif passing:
        out["decision"] = "PASS"
    else:
        out["decision"] = "KILL"
    out["passing_horizons"] = passing
    diag: dict[str, Any] = {}
    for b in sorted(deep["bucket"].unique()) if len(deep) else []:
        sub = deep[deep["bucket"] == b]
        diag[f"bucket_{b}"] = {str(h): _excess(sub, h, min(B, 1000)) for h in HOLDS_MIN}
    for name in ("deep_confirm", "shallow"):
        ev = obs.get(name)
        if ev is not None and len(ev) and "n_draws" in ev:
            diag[name] = {str(h): _excess(ev, h, min(B, 1000)) for h in HOLDS_MIN}
    out["diagnostics"] = diag
    return out


# =========================================================================== evaluation


def evaluate(res: C.Result, ds: C.Dataset, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, depth buckets, placebo n, horizon exits)."""
    t = res.trades
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_bucket_n": t["tag"].value_counts().to_dict() if len(t) else {}, "n_placebo": int(len(res.placebo)),
            "n_placebo_any_depth": int(len((res.controls or {}).get("any_depth", ()))),
            "horizon_exits": int(cens.sum()),
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if len(t):          # decision-time features (never outcomes): the exact round trip and the target paid for
        rts = [round_trip_frac(ds.asof(r.mint, float(r.t_dec))) for r in t.itertuples(index=False)]
        base["mean_rt"] = float(np.mean([x for x in rts if x is not None])) if any(x is not None for x in rts) else None
        base["mean_tp"] = float(t["take_profit_pct"].mean())
    if hide:     # exit reasons (target vs stop vs time) and fill prices are outcomes: hidden like returns
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["mean_mcap_in_sol"] = float(t["mcap_in_sol"].mean()) if len(t) else None
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    pa = (res.controls or {}).get("any_depth")
    base["placebo_any_depth"] = C.placebo_compare(t, pa, B=B) if pa is not None and len(pa) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_bucket"] = {b: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for b, g in t.groupby("tag")} \
        if len(t) else {}
    return base


def combine_verdict(base: Mapping[str, Any]) -> str:
    """PLAN 3.5 items 1-8 + 10 (common.verdict_entry). Item 9 (FINAL) is judged in the overall verdict."""
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


def decide_train(evals: Mapping[str, Mapping[str, Any]], passing_horizons: Iterable[int]) -> dict:
    """PREREG 9: the qualifier (>= 30 trades from >= 20 coins, mean > 0, mean w/o top 2 > 0, matched-control diff > 0)
    with the highest coin-bootstrap 90 % CI lower bound (ties: higher mean, then grid order) is the ONE shortlisted
    config. Only configs whose H passed the reversion gate are considered."""
    ok_h = {int(h) for h in passing_horizons}
    rows = []
    for i, p in enumerate(GRID):
        key = config_key(p)
        if int(p["hold_min"]) not in ok_h or key not in evals:
            continue
        e = evals[key]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0)
        ci = e.get("ci90")
        rows.append({"config": key, "order": i, "powered": powered, "qualifies": bool(good), "n": e["n"],
                     "n_coins": e["n_coins"], "mean": e.get("mean"), "ci90_lo": ci[0] if ci else None,
                     "placebo_diff": pc})
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                                        r["order"]))[0]
        sl = [GRID[best["order"]]]
        return {"verdict": "SHORTLISTED", "candidate": best["config"], "rows": rows, "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / matched-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max([r['n'] for r in rows] or [0])} trades)")
    return {"verdict": v, "reason": why, "rows": rows, "shortlist": [], "shortlist_hashes": []}


def decide_val(ev: Mapping[str, Any]) -> dict:
    n = ev["n"]
    mean, mw2 = ev.get("mean"), ev.get("mean_without_top2")
    pc = (ev.get("placebo") or {}).get("mean_diff")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and mw2 is not None and mw2 > 0 and pc is not None and pc > 0):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "placebo_diff": pc,
            "proceed": v in PROCEED_VAL}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: X3 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds X3 never looked at; the TRAIN third (debugged on) is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "design_third": {"n": int(len(design)),
                             "mean": float(design["ret_net"].mean()) if len(design) else None,
                             "note": "census TRAIN third: used to debug the code, not judged"}}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def data_gates(flow: Path | None = None, split: str = "train") -> tuple[bool, list[str]]:
    """PLAN 8 rule 1 for ``split`` (common.validation_gates)."""
    return C.validation_gates(split, flow)


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


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def stage_configs(stage: str, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)] the stage runs (TRAIN / debug: the grid; later: the one shortlisted candidate)."""
    if stage in ("debug", "train"):
        return [(config_key(p), HYP, p) for p in GRID]
    sl = _shortlist(HYP, shortlist_path)
    if not sl or not sl.get("configs"):
        return []
    return [("candidate", HYP, sl["configs"][0])]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`X3Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X3Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X3Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X3Refused("PREREG.md changed after the first official TRAIN run; record changes in X3/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = data_gates(flow, STAGE_SPLIT[stage])
    if not ok and stage != "debug":
        raise X3Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X3Refused("TRAIN already ran on complete data (X3/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X3Refused("no TRAIN result (X3/train.json): run --stage train first")
    if train.get("provisional"):
        raise X3Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_GATE":
        raise X3Refused("X3 is dead: the reversion gate failed on TRAIN (PREREG 8 stop rule)")
    if tv != "SHORTLISTED":
        raise X3Refused(f"TRAIN decision {tv}: X3 stopped before VAL")
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        raise X3Refused("no VAL shortlist for X3 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise X3Refused("the X3 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X3Refused("VAL already ran (X3/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise X3Refused("no VAL result (X3/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise X3Refused(f"VAL decision {vv}: X3 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X3Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok, why = confirm_allowed(test)
        if not ok:
            raise X3Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X3Refused(f"{stage.upper()} already ran (X3/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise X3Refused(f"X3 already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X3Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def _q(x: Iterable[float]) -> dict | None:
    x = np.asarray([v for v in x if v is not None], float)
    if not len(x):
        return None
    return {k: float(np.quantile(x, q)) for k, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9), ("max", 1.0))}


def event_counts(ds: C.Dataset, gobs: Mapping[str, pd.DataFrame] | None = None) -> dict:
    """Counts and decision-time feature quantiles only (never outcomes): classes, how many coins are ever deep and
    alive in the window, deep coin-decisions, climaxes by timing, and the depth / cost / target of the gate events."""
    cls_n: dict[str, int] = {}
    deep_coins, deep_alive_coins, climax_coins = set(), set(), {tm: set() for tm in TIMINGS}
    deep_decisions = climax_decisions = 0
    for m in ds.mints:
        cd = ds.coin(m)
        times = decision_times(cd)
        if not times:
            continue
        cls = x3_class(ds.asof(m, times[0]))
        cls_n[str(cls)] = cls_n.get(str(cls), 0) + 1
        if cls not in ALLOWED_CLASSES:
            continue
        for t in times:
            snap = ds.asof(m, t)
            if not in_band(snap.mcap_sol, "deep"):
                continue
            deep_decisions += 1
            deep_coins.add(m)
            if snap.alive():
                deep_alive_coins.add(m)
            bars = snap.bars
            for tm, c in (("now", snap.k - 1), ("confirm", snap.k - 2)):
                ci = climax_info(bars, c)
                if ci is not None and ci["fires"]:
                    climax_coins[tm].add(m)
                    climax_decisions += tm == "now"
    out: dict[str, Any] = {"coins": len(ds), "class_counts": cls_n, "coins_ever_deep": len(deep_coins),
                           "coins_ever_deep_and_alive": len(deep_alive_coins), "deep_coin_decisions": deep_decisions,
                           "climax_bars_in_deep_decisions": climax_decisions,
                           "coins_with_a_deep_climax": {tm: len(v) for tm, v in climax_coins.items()}}
    if gobs is not None:
        for name, ev in gobs.items():
            out[f"gate_events_{name}"] = {"n": int(len(ev)), "coins": int(ev["mint"].nunique()) if len(ev) else 0,
                                          "by_bucket": ev["bucket"].value_counts().to_dict() if len(ev) else {},
                                          "mcap_sol": _q(ev["mcap_sol"]) if len(ev) else None,
                                          "rt": _q(ev["rt"]) if len(ev) else None,
                                          "tp": _q(ev["tp"]) if len(ev) else None,
                                          "drop": _q(ev["drop"]) if len(ev) else None,
                                          "age_min": _q(ev["age_min"]) if len(ev) else None}
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X3/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x3_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X3Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise X3Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise X3Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X3Refused(str(e)) from e
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
        # ---- reversion gate (TRAIN: before any strategy P&L; debug: counts only)
        if stage in ("train", "debug"):
            gobs = gate_obs(ds, with_labels=not debug)
            gc = gate_check(gobs, B=min(B, 2000), hide=debug)
            doc["gate"] = gc
            gr = C.record_run(HYP_GATE, GATE_PARAMS, split, {"n": gc["n_events"], "mean": None}, ledger_path,
                              debug=debug, cfg=MAIN_CFG)
            doc["gate"]["trial"] = gr
            if debug:
                doc["event_counts"] = event_counts(ds, gobs)
            elif gc["decision"] != "PASS":
                v = "KILLED_GATE" if gc["decision"] == "KILL" else "UNDERPOWERED_GATE"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "PREREG 8: the reversion gate precedes any strategy P&L; the grid was "
                                           "not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
            else:
                keep = set(gc["passing_horizons"])
                run_cfgs = [x for x in configs if int(x[2]["hold_min"]) in keep]
        # ---- the configs
        results: dict[str, C.Result] = {}
        for role, h, p in run_cfgs:
            results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, cfg=MAIN_CFG, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok,
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, ds, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals, doc["gate"]["passing_horizons"])
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 9, candidate {dec['candidate']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"])
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN,
                                   control_margin=PASS_CONTROL_MARGIN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x3 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise X3Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"]), hypothesis=r.meta["hypothesis"])
              for role, r in results.items()]
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
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
    if tv == "KILLED_GATE":
        return "KILLED (reversion gate failed on TRAIN)"
    if tv == "UNDERPOWERED_GATE":
        return "UNDERPOWERED (too few deep-pool climaxes for the reversion gate on TRAIN)"
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


def _qs(q: Any, scale: float = 1.0, nd: int = 1) -> str:
    if not q:
        return "n/a"
    return "/".join(f"{scale * q[k]:.{nd}f}" for k in ("p10", "p50", "p90"))


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# X3 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X3 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and gate labels "
              "are hidden, and no parameter was chosen here.**", ""]
    g = doc.get("gate")
    if g:
        L += ["## Reversion gate (PREREG 8)", "",
              f"- Deep `now` events (m = 2): {g['n_events']} from {g['n_coins']} coins (with matched draws: "
              f"{g.get('n_events_with_draws', 'n/a')}); need ≥ {GATE_MIN_EVENTS} and ≥ {GATE_MIN_COINS} coins; by depth "
              f"bucket {g.get('by_bucket')}.",
              f"- Diagnostics: deep `confirm` events {g.get('n_events_deep_confirm')}, shallow (100-1,470 SOL) events "
              f"{g.get('n_events_shallow')}.",
              f"- Decision: **{g['decision']}**; passing horizons: {g.get('passing_horizons')}."]
        for h, e in (g.get("per_horizon") or {}).items():
            if e:
                L.append(f"- H = {h} min: excess {_pct(e['excess'], 2)} (95% CI by coin {_ci(e['excess_ci95_coin'])}) "
                         f"vs mean rt {_pct(e['mean_rt'], 2)}; events {_pct(e['mean_label'], 2)}, draws "
                         f"{_pct(e['mean_draw'], 2)}; pass {e['pass']}.")
        for name, per in (g.get("diagnostics") or {}).items():
            parts = [f"H{h}: {_pct(e['excess'], 2)} vs rt {_pct(e['mean_rt'], 2)} (n {e['n']})"
                     for h, e in per.items() if e]
            L.append(f"- Diagnostic {name}: {'; '.join(parts) or 'n/a'}.")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (features only, no returns)", "",
              f"- Classes at g + 60 min: {ec['class_counts']}.",
              f"- OTHER coins ever deep (≥ 1,470 SOL) in g + 60 → 145 min: {ec['coins_ever_deep']} (and alive: "
              f"{ec['coins_ever_deep_and_alive']}); deep coin-decisions: {ec['deep_coin_decisions']}; climax bars seen "
              f"at deep decisions: {ec['climax_bars_in_deep_decisions']}; coins with a deep climax: "
              f"{ec['coins_with_a_deep_climax']}.", "",
              "| gate events | n | coins | by bucket | mcap SOL p10/p50/p90 | rt % p10/p50/p90 | tp % p10/p50/p90 | "
              "climax drop % p10/p50/p90 | age min p10/p50/p90 |",
              "|---|---:|---:|---|---|---|---|---|---|"]
        for name in ("deep", "deep_confirm", "shallow"):
            e = ec.get(f"gate_events_{name}")
            if e is None:
                continue
            L.append(f"| {name} | {e['n']} | {e['coins']} | {e['by_bucket']} | {_qs(e['mcap_sol'], 1, 0)} | "
                     f"{_qs(e['rt'], 100, 2)} | {_qs(e['tp'], 100, 1)} | {_qs(e['drop'], 100, 1)} | "
                     f"{_qs(e['age_min'], 1, 0)} |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | depth buckets | mean rt | mean tp | placebo trades (matched / any depth) | "
                  "horizon exits | entries/day |",
                  "|---|---:|---:|---|---:|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                rt = "n/a" if e.get("mean_rt") is None else f"{100 * e['mean_rt']:.2f}%"
                tp = "n/a" if e.get("mean_tp") is None else f"{100 * e['mean_tp']:.1f}%"
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_bucket_n']} | {rt} | {tp} | "
                         f"{e['n_placebo']} / {e['n_placebo_any_depth']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (deep) | "
                  "placebo diff (any depth) | costs ×1.5 | same-bar exits | mean rt | reasons |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|"]
            for k, e in cf.items():
                st_ = e.get("stress") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('placebo_any_depth') or {}).get('mean_diff'))} | "
                         f"{_pct(st_.get('costs_x1.5'))} | {_pct(st_.get('same_bar_exits'))} | "
                         f"{_pct(e.get('mean_rt'), 2)} | {e.get('reasons')} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']} ({r['n_coins']} coins), mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']}"
                 + (f" (candidate {dec['candidate']})" if dec.get("candidate") else "") + ".")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    for k in ("reason", "note"):
        if dec.get(k):
            L.append(f"- {dec[k]}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="X3 deep-pool climax-exhaustion reversion: pre-registered stages; "
                                             "see research/lab2/X3/PREREG.md")
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
    except X3Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
