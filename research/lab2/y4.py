"""Y4: do coins react at round USD market caps? Break / retest of round levels vs a shifted-level twin. Expected: no
edge.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Y4/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; the SOL/USD
of the last minute that ended before tau). Outcomes (forward mid-price moves of the event study, trade returns) are
read through AsOf at a LATER time and never feed a decision.

Mechanism (PREREG 1): take-profit orders typed as round USD market caps and milestone alerts ("X hit $100k") could
make round levels special: a clean break above one (close >= L x 1.03 after 10 closes below L) continues, a touch that
closes below L is rejected. Y4 measures the folklore gross (event study, PREREG 7) and trades it net of costs (break or
first retest, exit when the USD market cap closes back below L, a 25 % catastrophe stop, a 15 or 60 min hold). Each
config has a SHIFTED-LEVEL TWIN (levels x 1.28, non-round): round - shifted is the roundness effect.

CLI::

    python research/lab2/y4.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/y4.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/y4.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/y4.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/y4.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/y4.py --stage final
    python research/lab2/y4.py --stage val --check             # prerequisites only

Each stage writes ``Y4/<stage>.json`` and ``Y4/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8 data
gates V1-V4, PREREG frozen after the first official TRAIN run).
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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C

VERSION = "y4-v1"
OUT_DIR = HERE / "Y4"
HYP, HYP_ES = "Y4", "Y4-eventstudy"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-7)
ROUND_USD = (10e3, 25e3, 50e3, 100e3, 250e3, 500e3, 1e6, 2.5e6, 5e6, 10e6)   # the 1-2.5-5 sequence
SHIFT = 1.28                     # PREREG 3.1: maximizes the distance of the twin's break zones from salient numbers
SHIFTED_USD = tuple(round(L * SHIFT, 6) for L in ROUND_USD)
LEVEL_SETS = {"round": np.asarray(ROUND_USD, float), "shifted": np.asarray(SHIFTED_USD, float)}
N_BELOW = 10                     # approach window: the N bars before the event bar closed below L (touch: highs)
MARGIN = 0.03                    # clean break: close >= L x (1 + m)
RETEST_W = 15                    # a retest must come within W bars of the break
RETEST_BAND = 0.03               # retest: low <= L x (1 + rho) and close >= L
MIN_BAR = 1                      # bar 0 (partial graduation minute, rebuilt open / low) is never used
AGE_MIN_S, AGE_MAX_S = 600.0, 6900.0   # decision ages [10, 115] min: after BOOST / AGENT; >= 60 min of hold data
STOP_PCT = 0.25                  # catastrophe stop
EXIT_BY_AGE_S = 178 * 60.0       # registered deadline: sell no later than g + 178 min (never censored)
SIZE_USD = 20.0
ENTRY_GRID = ("break", "retest")
HOLD_GRID_MIN = (15, 60)
LEVELS_GRID = ("round", "shifted")
SELECTABLE = "round"             # shifted configs are controls, never the candidate
ES_H = (15, 60)                  # event-study label horizons (bars)
CLASSES = ("BREAK", "HOLD", "REJECT")
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 60, 40
MAX_CENSORED = C.MAX_CENSORED_SHARE
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03             # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "levels_round_usd": list(ROUND_USD), "levels_shifted_usd": list(SHIFTED_USD),
    "shift": SHIFT, "n_below": N_BELOW, "margin": MARGIN, "retest_w": RETEST_W, "retest_band": RETEST_BAND,
    "min_bar": MIN_BAR, "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S, "stop_pct": STOP_PCT,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD, "usd": "levels / AsOf.sol_usd at the decision",
    "thesis_exit": "AsOf.mcap_usd < level (bar completed after the decision), next-bar worst fill",
    "placebo": "mcap-band matched (round bands), mcap_usd >= $10k; unmatched control",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(entry: str, hold_min: int, levels: str) -> dict:
    if entry not in ENTRY_GRID or levels not in LEVELS_GRID or int(hold_min) not in HOLD_GRID_MIN \
            or int(hold_min) != hold_min:
        raise ValueError(f"(entry={entry!r}, hold={hold_min}, levels={levels!r}) is not in the pre-registered grid")
    return {**FIXED, "entry": entry, "hold_min": int(hold_min), "max_hold_s": 60.0 * int(hold_min), "levels": levels}


GRID = [make_params(e, h, lv) for lv in LEVELS_GRID for e in ENTRY_GRID for h in HOLD_GRID_MIN]
assert len(GRID) == 8   # the task cap is 12
ES_PARAMS = {"version": VERSION, "test": "event_study", "levels_round_usd": list(ROUND_USD),
             "levels_shifted_usd": list(SHIFTED_USD), "n_below": N_BELOW, "margin": MARGIN, "horizons": list(ES_H),
             "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S, "touch": "first contact from below (prior N highs < L)"}
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "open_fills": dataclasses.replace(FILL, entry_fill="open", exit_fill="open")}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class Y4Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['entry']}|h{int(p['hold_min'])}|{p['levels']}"


def twin_of(p: Mapping[str, Any]) -> dict:
    """The same rule on the other level set (round <-> shifted)."""
    return make_params(p["entry"], int(p["hold_min"]), "shifted" if p["levels"] == "round" else "round")


def level_name(usd: float) -> str:
    return f"{usd / 1e6:g}M" if usd >= 1e6 else f"{usd / 1e3:g}k"


# =========================================================================== events on dense bar arrays (PREREG 3.2)


def break_at(c: np.ndarray, traded: np.ndarray, b: int, lv: np.ndarray) -> int | None:
    """Index into ``lv`` (level prices, ascending) of the level that bar ``b`` breaks cleanly, or None.

    L* = the highest level with L* (1 + m) <= close(b); b traded; every close of the N bars before b < L*."""
    if b - N_BELOW < MIN_BAR or b >= len(c) or not traded[b] > 0:
        return None
    hit = np.flatnonzero(lv * (1.0 + MARGIN) <= float(c[b]))
    if not len(hit):
        return None
    i = int(hit[-1])
    return i if float(np.max(c[b - N_BELOW:b])) < float(lv[i]) else None


def retest_at(c: np.ndarray, l: np.ndarray, traded: np.ndarray, r: int, lv: np.ndarray) -> tuple[int, int] | None:
    """(level index, break bar) when bar ``r`` is the FIRST retest of the most recent BREAK in [r - W, r - 1]: every
    close since the break >= L*, every low between the break and r > L* (1 + rho), low(r) <= L* (1 + rho), r traded."""
    if r < 1 or r >= len(c) or not traded[r] > 0:
        return None
    for b in range(r - 1, max(r - RETEST_W, MIN_BAR + N_BELOW) - 1, -1):
        i = break_at(c, traded, b, lv)
        if i is None:
            continue
        L = float(lv[i])
        band = L * (1.0 + RETEST_BAND)
        ok = (float(np.min(c[b + 1:r + 1])) >= L and (r == b + 1 or float(np.min(l[b + 1:r])) > band)
              and float(l[r]) <= band)
        return (i, b) if ok else None          # only the most recent break counts
    return None


def touch_at(c: np.ndarray, h: np.ndarray, traded: np.ndarray, b: int, lv: np.ndarray) -> tuple[int, str] | None:
    """(level index, class) of the first contact from below at bar ``b`` (event study): the highest level with
    high(b) >= L while every high of the N bars before b < L. BREAK: close >= L (1 + m); HOLD: L <= close < L (1 + m);
    REJECT: close < L."""
    if b - N_BELOW < MIN_BAR or b >= len(c) or not traded[b] > 0:
        return None
    prior = float(np.max(h[b - N_BELOW:b]))
    hit = np.flatnonzero((lv <= float(h[b])) & (lv > prior))
    if not len(hit):
        return None
    i = int(hit[-1])
    L, cb = float(lv[i]), float(c[b])
    return i, ("BREAK" if cb >= L * (1.0 + MARGIN) else "HOLD" if cb >= L else "REJECT")


# =========================================================================== features (AsOf only)


def level_prices(levels: str, sol_usd: float) -> np.ndarray:
    """USD levels -> pool prices (SOL per whole token) at one SOL/USD price."""
    return LEVEL_SETS[levels] / (float(sol_usd) * C.TOKEN_SUPPLY)


def _arrays(snap: C.AsOf) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bars = snap.bars
    return (np.asarray(bars.c, float), np.asarray(bars.h, float), np.asarray(bars.l, float),
            np.asarray(bars.traded, float))


def entry_decision(snap: C.AsOf, p: Mapping[str, Any]) -> tuple[bool, dict]:
    """PREREG 4: the config's event (BREAK or RETEST) on the last completed bar, levels converted at the decision's
    SOL/USD. -> (fires, info)."""
    c, _, l, tr = _arrays(snap)
    k = len(c)
    info: dict[str, Any] = {"k": k, "level_usd": None, "level": None, "event_bar": None}
    if k < 2:
        return False, info
    lv = level_prices(p["levels"], snap.sol_usd)
    r = k - 1
    if p["entry"] == "break":
        i, b = break_at(c, tr, r, lv), r
    elif p["entry"] == "retest":
        res = retest_at(c, l, tr, r, lv)
        i, b = res if res is not None else (None, None)
    else:
        raise ValueError(f"unknown entry mode {p['entry']!r}")
    if i is None:
        return False, info
    usd = float(LEVEL_SETS[p["levels"]][i])
    info.update(level_usd=usd, level=level_name(usd), event_bar=int(b), mcap_usd=snap.mcap_usd)
    return True, info


def ref_level_usd(close_usd: float, p: Mapping[str, Any]) -> float | None:
    """The reference level of a position decided at a bar that closed at ``close_usd`` (PREREG 5): break configs the
    highest level with L (1 + m) <= close, retest configs the highest level <= close. For a signal it equals L*."""
    lv = LEVEL_SETS[p["levels"]]
    ok = lv * (1.0 + MARGIN) <= close_usd if p["entry"] == "break" else lv <= close_usd
    hit = np.flatnonzero(ok)
    return float(lv[hit[-1]]) if len(hit) else None


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return 0
    return int(min(max((tau - int(bars.minute_ts[0])) // 60, 0), k))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """Level lost: the last completed bar, completed AFTER the entry decision, has a USD market cap below the
    reference level. Signals carry L* in their state; stateless placebo positions recompute it from the bar completed
    at THEIR decision (PREREG 5), converted at the current SOL price."""
    bars = snap.bars
    k = len(bars)
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    if k <= k_dec or k_dec < 1:
        return None
    L = (pos.state or {}).get("level_usd")
    if L is None:
        L = ref_level_usd(float(bars.c[k_dec - 1]) * C.TOKEN_SUPPLY * snap.sol_usd, p)
    if L is None:
        return None
    return C.Exit("level_lost") if snap.mcap_usd < L else None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The Y4 strategy for common.backtest (one entry per coin)."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    ok, info = entry_decision(snap, p)
    if not ok:
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=float(p["max_hold_s"]), exit_by_age_s=EXIT_BY_AGE_S),
                   tag=info["level"], state={"level_usd": info["level_usd"]})


# =========================================================================== controls


def band(snap: C.AsOf) -> int:
    """Market-cap band: the number of ROUND levels at or below the current USD market cap (PREREG 2)."""
    return int(np.searchsorted(LEVEL_SETS["round"], snap.mcap_usd, side="right"))


def placebo_ok(snap: C.AsOf) -> bool:
    return bool(snap.mcap_usd >= ROUND_USD[0])


PLACEBO_CONTROLS = {"unmatched": {"eligible": placebo_ok, "strata": None}}


# =========================================================================== scan: event counts + event-study obs


def _quantiles(x: Sequence[float]) -> dict | None:
    if not len(x):
        return None
    a = np.asarray(x, float)
    return {"n": len(a), "p25": float(np.quantile(a, 0.25)), "median": float(np.median(a)),
            "p75": float(np.quantile(a, 0.75)), "max": float(a.max())}


def round_trip_frac(snap: C.AsOf, cost: C.CostModel | None = None) -> float | None:
    """costs.py round trip of a $20 ticket at the pool state after the last completed bar (fee tier by date and
    market cap, impact on the pool's own k = X * y, network fees), as a fraction of the stake. A cost, not an outcome."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return None
    X, y = float(bars.X[k - 1]), float(bars.y[k - 1])
    if not (X > 0 and y > 0):
        return None
    return C.round_trip_pct(SIZE_USD / snap.sol_usd, snap.price, X * y, snap.t, cost or C.CostModel()) / 100.0


ES_COLS = ["mint", "set", "level", "level_usd", "cls", "age_min", "t", "mcap_usd", "round_trip"] + \
    [f"fwd{h}" for h in ES_H]


def scan(ds: C.Dataset, labels: bool, mints: Sequence[str] | None = None) -> tuple[pd.DataFrame, dict]:
    """One pass over the decision grid (ages 10-115 min) of every coin: event-study TOUCH observations (with their
    forward labels, read through AsOf H minutes later, only when ``labels``) and counts of BREAK / RETEST events per
    level set. Counts and decision-time states only when ``labels`` is False."""
    rows: list[dict] = []
    cnt = {s: {"touch_bars": {k: 0 for k in CLASSES}, "touch_coins": set(), "break_bars": 0, "break_coins": set(),
               "retest_bars": 0, "retest_coins": set(), "break_by_level": {}, "retest_by_level": {},
               "touch_by_level": {}} for s in LEVEL_SETS}
    first_break: dict[str, list] = {"mcap_usd": [], "round_trip": [], "age_min": []}
    fee = {}
    n_dec = 0
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        seen = False
        for j in range(1, C.N_BARS + 1):
            t = float(cd.bar_start(j) + C.GRID_OFFSET_S)
            age = t - cd.g
            if age < AGE_MIN_S:
                continue
            if age > AGE_MAX_S:
                break
            snap = ds.asof(m, t)
            n_dec += 1
            c, h, l, tr = _arrays(snap)
            b = len(c) - 1
            for s in LEVEL_SETS:
                lv = level_prices(s, snap.sol_usd)
                usd = LEVEL_SETS[s]
                x = cnt[s]
                tch = touch_at(c, h, tr, b, lv)
                if tch is not None:
                    i, cls = tch
                    x["touch_bars"][cls] += 1
                    x["touch_coins"].add(m)
                    key = level_name(usd[i])
                    x["touch_by_level"].setdefault(key, {k: 0 for k in CLASSES})[cls] += 1
                    row = {"mint": m, "set": s, "level": key, "level_usd": float(usd[i]), "cls": cls,
                           "age_min": age / 60.0, "t": t, "mcap_usd": snap.mcap_usd, "round_trip": round_trip_frac(snap)}
                    for H in ES_H:
                        row[f"fwd{H}"] = None
                        if labels:            # OUTCOME: read H minutes later, never a feature
                            later = ds.asof(m, t + 60.0 * H)
                            if later.k - snap.k >= H:
                                row[f"fwd{H}"] = later.price / snap.price - 1.0
                    rows.append(row)
                bi = break_at(c, tr, b, lv)
                if bi is not None:
                    x["break_bars"] += 1
                    x["break_coins"].add(m)
                    key = level_name(usd[bi])
                    x["break_by_level"][key] = x["break_by_level"].get(key, 0) + 1
                    if s == "round" and not seen:
                        seen = True
                        first_break["mcap_usd"].append(snap.mcap_usd)
                        first_break["age_min"].append(age / 60.0)
                        rt = round_trip_frac(snap)
                        if rt is not None:
                            first_break["round_trip"].append(rt)
                        fb = str(int(C.fee_bps_at(snap.t, snap.mcap_sol)))
                        fee[fb] = fee.get(fb, 0) + 1
                rt_ev = retest_at(c, l, tr, b, lv)
                if rt_ev is not None:
                    x["retest_bars"] += 1
                    x["retest_coins"].add(m)
                    key = level_name(usd[rt_ev[0]])
                    x["retest_by_level"][key] = x["retest_by_level"].get(key, 0) + 1
    obs = pd.DataFrame(rows, columns=ES_COLS)
    counts = {"decision_minutes": n_dec, "coins": len(mints) if mints is not None else len(ds),
              "by_set": {s: {"touch_bars": x["touch_bars"], "touch_coins": len(x["touch_coins"]),
                             "break_bars": x["break_bars"], "break_coins": len(x["break_coins"]),
                             "retest_bars": x["retest_bars"], "retest_coins": len(x["retest_coins"]),
                             "touch_by_level": x["touch_by_level"], "break_by_level": x["break_by_level"],
                             "retest_by_level": x["retest_by_level"]} for s, x in cnt.items()},
              "first_round_break_decision_state": {"mcap_usd": _quantiles(first_break["mcap_usd"]),
                                                   "age_min": _quantiles(first_break["age_min"]),
                                                   "round_trip": _quantiles(first_break["round_trip"]),
                                                   "fee_bps_tier": fee}}
    return obs, counts


# =========================================================================== event-study statistics (PREREG 7)


def _joint_boot(obs: pd.DataFrame, terms: Sequence[tuple[np.ndarray, float]], col: str, B: int,
                seed: int = 0) -> tuple[float | None, tuple[float, float] | None]:
    """Statistic sum_g w_g * mean(col | mask_g) with COINS resampled jointly across the terms (a coin's observations
    in every term travel together). -> (point, 95 % CI) or (None, None) when a term is empty."""
    ok = obs[col].notna().to_numpy(bool)
    vals = pd.to_numeric(obs[col], errors="coerce").to_numpy(float)
    codes, uniq = pd.factorize(obs["mint"])
    n = len(uniq)
    point, S, N = 0.0, [], []
    for mask, w in terms:
        mk = np.asarray(mask, bool) & ok
        if not mk.any():
            return None, None
        s = np.bincount(codes[mk], weights=vals[mk], minlength=n)
        cn = np.bincount(codes[mk], minlength=n).astype(float)
        point += w * float(s.sum() / cn.sum())
        S.append(s)
        N.append(cn)
    if n < 2:
        return point, None
    rng = np.random.default_rng(seed)
    out = []
    step = max(1, 2_000_000 // n)
    for a in range(0, B, step):
        e = min(B, a + step)
        idx = rng.integers(0, n, size=(e - a, n))
        stat = np.zeros(e - a)
        for (_, w), s, cn in zip(terms, S, N):
            with np.errstate(divide="ignore", invalid="ignore"):
                stat = stat + w * (s[idx].sum(1) / cn[idx].sum(1))
        out.append(stat)
    d = np.concatenate(out)
    d = d[np.isfinite(d)]
    if len(d) < 10:
        return point, None
    return point, (float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975)))


def event_study_stats(obs: pd.DataFrame, B: int = 2000) -> dict:
    """PREREG 7.2: per-cell means with coin-bootstrap CIs, the roundness effect (round - shifted) per class and
    horizon, the reaction spread (BREAK - REJECT) per set and its round - shifted difference, per-level cells."""
    out: dict[str, Any] = {"n_obs": len(obs), "n_coins": int(obs["mint"].nunique()) if len(obs) else 0,
                           "cells": {}, "roundness": {}, "spread": {}, "spread_round_minus_shifted": {},
                           "by_level": {}, "cost": {}}
    if not len(obs):
        return out
    st, cl = obs["set"].to_numpy(object), obs["cls"].to_numpy(object)
    for s in LEVEL_SETS:
        for k in CLASSES:
            for H in ES_H:
                sub = obs[(st == s) & (cl == k)]
                v = pd.to_numeric(sub[f"fwd{H}"], errors="coerce")
                keep = v.notna().to_numpy(bool)
                vv, coins = v.to_numpy(float)[keep], sub["mint"].to_numpy(object)[keep]
                out["cells"][f"{s}|{k}|h{H}"] = {
                    "n": len(vv), "coins": len(set(coins)), "mean": float(vv.mean()) if len(vv) else None,
                    "median": float(np.median(vv)) if len(vv) else None,
                    "ci95": C.coin_bootstrap_ci(vv, coins, 0.95, B) if len(vv) else None}
    for k in CLASSES:
        for H in ES_H:
            pt, ci = _joint_boot(obs, [((st == "round") & (cl == k), 1.0), ((st == "shifted") & (cl == k), -1.0)],
                                 f"fwd{H}", B)
            out["roundness"][f"{k}|h{H}"] = {"diff": pt, "ci95": ci}
    for H in ES_H:
        for s in LEVEL_SETS:
            pt, ci = _joint_boot(obs, [((st == s) & (cl == "BREAK"), 1.0), ((st == s) & (cl == "REJECT"), -1.0)],
                                 f"fwd{H}", B)
            out["spread"][f"{s}|h{H}"] = {"diff": pt, "ci95": ci}
        pt, ci = _joint_boot(obs, [((st == "round") & (cl == "BREAK"), 1.0), ((st == "round") & (cl == "REJECT"), -1.0),
                                   ((st == "shifted") & (cl == "BREAK"), -1.0),
                                   ((st == "shifted") & (cl == "REJECT"), 1.0)], f"fwd{H}", B)
        out["spread_round_minus_shifted"][f"h{H}"] = {"diff": pt, "ci95": ci}
    for (s, lvl), g in obs.groupby(["set", "level"], sort=False):
        out["by_level"][f"{s}|{lvl}"] = {k: {"n": int((g["cls"] == k).sum()),
                                             "mean_fwd15": (float(pd.to_numeric(g.loc[g["cls"] == k, "fwd15"],
                                                                                errors="coerce").mean())
                                                            if (g["cls"] == k).any() else None)}
                                         for k in CLASSES}
    rb = obs[(st == "round") & (cl == "BREAK")]["round_trip"].dropna()
    out["cost"] = {"round_break_round_trip": _quantiles(rb.to_numpy(float))}
    return out


def score_predictions(es: Mapping[str, Any], train_verdict: str | None) -> dict:
    """PREREG 7.3: is the folklore supported? Reports, never decisive."""
    rb = (es.get("roundness") or {}).get("BREAK|h15") or {}
    rr = (es.get("roundness") or {}).get("REJECT|h15") or {}
    cell = (es.get("cells") or {}).get("round|BREAK|h15") or {}
    cost = ((es.get("cost") or {}).get("round_break_round_trip") or {}).get("median")
    p1 = None if not rb.get("ci95") else bool(rb["ci95"][0] > 0)
    p2 = None if not rr.get("ci95") else bool(rr["ci95"][1] < 0)
    p3 = None if cell.get("mean") is None or cost is None else bool(cell["mean"] > cost)
    p4 = None if train_verdict is None else bool(train_verdict == "SHORTLISTED")
    return {
        "P1_round_break_continues_more": {"folklore_supported": p1, "value": rb},
        "P2_round_reject_falls_more": {"folklore_supported": p2, "value": rr},
        "P3_round_break_pays_for_costs": {"folklore_supported": p3, "mean_fwd15": cell.get("mean"),
                                          "median_round_trip": cost},
        "P4_a_round_config_qualifies": {"folklore_supported": p4, "train_verdict": train_verdict},
        "y4_expected": "no roundness effect, breaks do not pay for costs, nothing qualifies (all False)",
        "note": "predictions are reports (PREREG 7.3); the TRAIN decision is decide_train's",
    }


# =========================================================================== evaluation


def _age_bins(t: pd.DataFrame) -> dict:
    a = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    return {"10-30": int((a < 30).sum()), "30-60": int(((a >= 30) & (a < 60)).sum()),
            "60-90": int(((a >= 60) & (a < 90)).sum()), "90-116": int((a >= 90).sum())}


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, level tags, ages, placebo / control counts) --
    never returns, exit reasons, fill prices or placebo outcomes."""
    t = res.trades
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "levels": res.meta["params"]["levels"], "hypothesis": res.meta["hypothesis"], "n": len(t),
            "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_level_n": t["tag"].value_counts().to_dict() if len(t) else {}, "entry_age_min": _age_bins(t),
            "n_placebo": len(res.placebo), "n_controls": {k: len(v) for k, v in res.controls.items()},
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
    if len(t):
        mid, net = t["ret_mid"].to_numpy(float), t["ret_net"].to_numpy(float)
        base["cost_decomposition"] = {"mean_gross_move_worst_fills": float(mid.mean()),
                                      "mean_cost": float((mid - net).mean())}
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_level"] = {s: {"n": len(g), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} \
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


def round_minus_shifted(ev_round: Mapping[str, Any] | None, ev_twin: Mapping[str, Any] | None) -> float | None:
    a, b = (ev_round or {}).get("mean"), (ev_twin or {}).get("mean")
    return None if a is None or b is None else float(a - b)


# =========================================================================== pre-registered decisions


def _rank_key(r: Mapping[str, Any]) -> tuple:
    return (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"], ENTRY_GRID.index(r["entry"]),
            int(r["hold_min"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 8: a ROUND config qualifies (sample, mean, top-2, band-matched placebo, beats its shifted twin,
    censoring); rank by the coin-bootstrap 90 % CI lower bound; shortlist = (rank-1 round config, its twin)."""
    rows = []
    for p in GRID:
        if p["levels"] != SELECTABLE:
            continue
        e, tw = evals[config_key(p)], evals.get(config_key(twin_of(p))) or {}
        pc = (e.get("placebo") or {}).get("mean_diff")
        cs = e.get("censored_share")
        rms = round_minus_shifted(e, tw)
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and rms is not None and rms > 0
                and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "entry": p["entry"], "hold_min": int(p["hold_min"]),
                     "powered": bool(powered), "qualifies": bool(good), "n": e["n"], "coins": e["n_coins"],
                     "mean": e.get("mean"), "mean_without_top2": e.get("mean_without_top2"),
                     "ci90_lo": ci[0] if ci else None, "placebo_diff": pc, "twin_mean": tw.get("mean"),
                     "twin_n": tw.get("n"), "round_minus_shifted": rms, "censored_share": cs})
    q = sorted((r for r in rows if r["qualifies"]), key=_rank_key)
    if q:
        best = q[0]
        cand = make_params(best["entry"], best["hold_min"], SELECTABLE)
        sl = [cand, twin_of(cand)]
        return {"verdict": "SHORTLISTED", "rows": rows, "candidate": config_key(cand), "twin": config_key(sl[1]),
                "shortlist": sl, "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered round config failed the mean / top-2 / placebo / twin / censoring bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no round config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max(r['n'] for r in rows)} trades, {max(r['coins'] for r in rows)} coins)")
    return {"verdict": v, "reason": why, "rows": rows, "candidate": None, "twin": None, "shortlist": [],
            "shortlist_hashes": []}


def decide_val(ev_cand: Mapping[str, Any]) -> dict:
    n = ev_cand["n"]
    mean, mw2 = ev_cand.get("mean"), ev_cand.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "proceed": v in PROCEED_VAL}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Y4 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Y4 never looked at (the TRAIN third hosted the debug run: reported apart)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": len(g), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": len(judged),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": len(dbg), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                            "note": "census TRAIN third: hosted the debug run (PREREG 14), not judged"}}


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
    """[(role, params)] the stage runs: the grid (debug / train), else the shortlisted pair (candidate = the round
    config, twin = its shifted copy)."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    by = {c.get("levels"): c for c in sl.get("configs", [])}
    return [("candidate", by.get(SELECTABLE)), ("twin", by.get("shifted"))]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Y4Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Y4Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Y4Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Y4Refused("PREREG.md changed after the first official TRAIN run; record changes in Y4/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Y4Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Y4Refused("TRAIN already ran on complete data (Y4/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Y4Refused("no TRAIN result (Y4/train.json): run --stage train first")
    if train.get("provisional"):
        raise Y4Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Y4Refused(f"TRAIN decision {tv}: Y4 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Y4Refused("no VAL shortlist for Y4 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise Y4Refused("the Y4 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Y4Refused("VAL already ran (Y4/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Y4Refused(f"no VAL result (Y4/val.json): {stage.upper()} needs a VAL decision first")
    vv = (val.get("decision") or {}).get("verdict")
    if vv not in PROCEED_VAL:
        raise Y4Refused(f"VAL decision {vv}: Y4 stopped (PLAN 8 rule 7 input); {stage.upper()} is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Y4Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Y4Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Y4Refused(f"{stage.upper()} already ran (Y4/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise Y4Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Y4Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Y4/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "y4_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Y4Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Y4Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Y4Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Y4Refused(str(e)) from e
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
        # ---- event study (TRAIN: the folklore test, before the grid; debug: counts only)
        if stage in ("train", "debug"):
            obs, counts = scan(ds, labels=not debug)
            doc["event_counts"] = counts
            es_run = C.record_run(HYP_ES, ES_PARAMS, split, {"n": len(obs), "mean": None}, ledger_path,
                                  debug=debug)
            if debug:
                doc["event_study"] = {"n_obs": len(obs), "n_coins": int(obs["mint"].nunique()) if len(obs) else 0,
                                      "touch_counts": {f"{s}|{k}": int(((obs["set"] == s) & (obs["cls"] == k)).sum())
                                                       for s in LEVEL_SETS for k in CLASSES},
                                      "stats": "hidden on the debug split (forward moves are outcomes)"}
            else:
                doc["event_study"] = event_study_stats(obs, B=min(B, 2000))
            doc["event_study"]["trial"] = es_run
        results: dict[str, C.Result] = {}
        for role, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok, placebo_strata=band,
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        doc["n_trials_total"] = n_tr
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
            if "candidate" in evals:
                doc["round_minus_shifted"] = round_minus_shifted(evals["candidate"], evals.get("twin"))
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if math.isfinite(days) and days > 0 else None)
                                      for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 8 pair, candidate {dec['candidate']}, twin {dec['twin']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
            doc["predictions"] = score_predictions(doc["event_study"], dec["verdict"])
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"])
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"y4 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate + twin inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Y4Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"])) for role, r in results.items()]
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


def _q(q: Any, scale: float = 1.0, fmt: str = "{:.2f}") -> str:
    if not q:
        return "n/a"
    return (f"median {fmt.format(scale * q['median'])} (IQR {fmt.format(scale * q['p25'])}-"
            f"{fmt.format(scale * q['p75'])}, n {q['n']})")


def _render_counts(ec: Mapping[str, Any]) -> list[str]:
    L = ["## Event counts (no outcomes)", "",
         f"- Coins {ec['coins']}; decision minutes at ages 10-115 min: {ec['decision_minutes']}.", "",
         "| set | touches BREAK / HOLD / REJECT | touch coins | BREAK events (bars, coins) | RETEST events (bars, coins) |",
         "|---|---|---:|---|---|"]
    for s, x in ec["by_set"].items():
        tb = x["touch_bars"]
        L.append(f"| {s} | {tb['BREAK']} / {tb['HOLD']} / {tb['REJECT']} | {x['touch_coins']} | "
                 f"{x['break_bars']}, {x['break_coins']} | {x['retest_bars']}, {x['retest_coins']} |")
    L.append("")
    for s, x in ec["by_set"].items():
        L.append(f"- {s}: BREAK events by level {x['break_by_level']}; RETEST events by level {x['retest_by_level']}.")
    fs = ec["first_round_break_decision_state"]
    L += [f"- At each coin's first round BREAK (decision-time state, no later price): market cap "
          f"{_q(fs['mcap_usd'], 1, '${:,.0f}')}; age {_q(fs['age_min'], 1, '{:.0f} min')}; $20 round trip "
          f"{_q(fs['round_trip'], 100, '{:.2f}%')}; fee tier (bps, one side) {fs['fee_bps_tier']}.", ""]
    return L


def _render_es(es: Mapping[str, Any]) -> list[str]:
    L = ["## Event study (PREREG 7: the folklore, gross mid-price moves)", "",
         f"- Observations {es.get('n_obs')} from {es.get('n_coins')} coins.", ""]
    if isinstance(es.get("stats"), str):
        L += [f"- Touch counts {es.get('touch_counts')}; statistics {es['stats']}.", ""]
        return L
    L += ["| set | class | H | n | coins | mean | median | 95% CI |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for key, c in (es.get("cells") or {}).items():
        s, k, h = key.split("|")
        L.append(f"| {s} | {k} | {h[1:]} | {c['n']} | {c['coins']} | {_pct(c['mean'], 2)} | {_pct(c['median'], 2)} | "
                 f"{_ci(c['ci95'])} |")
    L += ["", "| roundness effect (round − shifted) | diff | 95% CI |", "|---|---:|---|"]
    for key, v in (es.get("roundness") or {}).items():
        L.append(f"| {key} | {_pct(v['diff'], 2)} | {_ci(v['ci95'])} |")
    for key, v in (es.get("spread") or {}).items():
        L.append(f"| spread BREAK − REJECT {key} | {_pct(v['diff'], 2)} | {_ci(v['ci95'])} |")
    for key, v in (es.get("spread_round_minus_shifted") or {}).items():
        L.append(f"| spread round − shifted {key} | {_pct(v['diff'], 2)} | {_ci(v['ci95'])} |")
    cost = (es.get("cost") or {}).get("round_break_round_trip")
    L += ["", f"- $20 round trip at round BREAK touches: {_q(cost, 100, '{:.2f}%')}.", ""]
    return L


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# Y4 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Y4 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns and forward moves are hidden "
              "and no parameter was chosen here.**", ""]
    if doc.get("event_counts"):
        L += _render_counts(doc["event_counts"])
    if doc.get("event_study"):
        L += _render_es(doc["event_study"])
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | levels | entry age (min) | placebo trades | controls | horizon exits | "
                  "entries/day |", "|---|---:|---:|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_level_n']} | {e['entry_age_min']} | "
                         f"{e['n_placebo']} | {e['n_controls']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | band-matched diff | "
                  "unmatched diff | costs ×1.5 | open fills | gross move | cost | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                cd = e.get("cost_decomposition") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('unmatched') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                         f"{_pct((e.get('stress') or {}).get('open_fills'))} | "
                         f"{_pct(cd.get('mean_gross_move_worst_fills'))} | {_pct(cd.get('mean_cost'))} | "
                         f"{_pct(e.get('censored_share'), 0)} |")
        L.append("")
    if doc.get("round_minus_shifted") is not None:
        L += [f"- Candidate − shifted twin (reported, never judged): {_pct(doc['round_minus_shifted'])}.", ""]
    pr = doc.get("predictions")
    if pr:
        L += ["## Pre-registered predictions (PREREG 7.3; reports, never decisive)", ""]
        for key in ("P1_round_break_continues_more", "P2_round_reject_falls_more", "P3_round_break_pays_for_costs",
                    "P4_a_round_config_qualifies"):
            L.append(f"- {key}: folklore supported = {pr[key]['folklore_supported']}.")
        L += [f"- Y4 expected: {pr['y4_expected']}.", ""]
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, band-matched diff {_pct(r['placebo_diff'])}, round − shifted "
                 f"{_pct(r['round_minus_shifted'])} (twin n {r['twin_n']}), qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (candidate {dec.get('candidate')}, twin "
                 f"{dec.get('twin')}).")
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
    ap = argparse.ArgumentParser(description="Y4 round USD market-cap levels: pre-registered stages; see "
                                             "research/lab2/Y4/PREREG.md")
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
    except Y4Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
