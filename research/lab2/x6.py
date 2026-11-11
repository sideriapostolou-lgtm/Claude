"""X6: buy the coins whose organic (non-AGENT) buyers take over when BOOST stops (B2 bars only).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X6/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; the AGENT
column only once knowable; NULL stays None). Labels (the gate's realized 30-minute mid-price change) are outcomes:
they are read through AsOf at a LATER time and never feed a decision.

Mechanism (PREREG 1): BOOST (the protocol's AGENT) buys 17.5845 SOL, price-blind, until g + 330-353 s, then stops.
That is a natural experiment: reflexive flow that followed the AGENT's lift stops with it, demand does not. At the end
of the K-th minute after BOOST's last slice (bar ``j_b``), compare the coin's non-AGENT flow with its own BOOST-time
flow (bars 3 .. j_b, after the w120 migration burst):

* TAKEOVER(CONSTANT): post-BOOST non-AGENT buy SOL per minute >= the BOOST-time non-AGENT rate (whole window and its
  last half), >= 1 SOL/min, net inflow >= 0, non-AGENT buyers per minute >= max(BOOST-time, 3), no minute > 50 % of the
  window's buying, alive;
* TAKEOVER(REPLACE): the same with the threshold = the BOOST-time TOTAL buy rate (AGENT included); reported only
  (PREREG amendment 1: BOOST is a small part of the BOOST-time bid, so REPLACE ~ CONSTANT);
* DIES: post rate < 0.5 x the BOOST-time non-AGENT rate (gate contrast only).

Universe: slow graduates (grad delay > 5 s), class OTHER (not OPERATOR / FACTORY), a detected AGENT whose BOOST reached
bar 4. One decision per coin and K. Grid: K in {5, 10} x exit in {hold30, fade60} (4 configs). Exits: -30 % stop, hold 30 min or fade (flow halved and net selling over the last 3
bars) capped at 60 min; worst fills, next-bar exits.

Gate (PREREG 7, TRAIN, before any P&L): per K, mean 30-min forward mid change of TAKEOVER minus DIES >= +5 points with
a 90 % CI above 0 and TAKEOVER mean > 0; KILL / UNDERPOWERED stop X6 before the grid runs.

CLI::

    python research/lab2/x6.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x6.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x6.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x6.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x6.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x6.py --stage final
    python research/lab2/x6.py --stage val --check             # prerequisites only

Each stage writes ``X6/<stage>.json`` and ``X6/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
stage after a gate KILL, no VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or
FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run).
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

VERSION = "x6-v1"
OUT_DIR = HERE / "X6"
HYP, HYP_SEP = "X6", "X6-sep"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-7)
BASE_FIRST_BAR = 3           # baseline = BOOST bars 3 .. j_b (entirely after the w120 migration burst)
MIN_BASE_BARS = 2            # j_b >= 4
AGENT_BUYER_SOL = 0.01       # the AGENT counts as one of a minute's buyers when it bought >= 0.01 SOL in it
K_GRID = (5, 10)             # post-BOOST window length (minutes) = the decision
LEVELS = ("CONSTANT", "REPLACE")
LEVEL = "CONSTANT"           # the traded level (PREREG amendment 1); REPLACE is computed and reported only
EXIT_GRID = ("hold30", "fade60")
HOLD_S = {"hold30": 1800.0, "fade60": 3600.0}
MIN_RATE_SOL = 1.0           # post-BOOST non-AGENT buy SOL per minute
MIN_BUYERS_PM = 3.0          # post-BOOST non-AGENT buyers per minute
MAX_TOP_SHARE = 0.5          # no single post-window minute carries more than half of its buying (not Z2's whale)
DIES_FRAC = 0.5              # DIES: post rate < 0.5 x BOOST-time non-AGENT rate
STOP_PCT = 0.30
FADE_BARS = 3
FADE_FRAC = 0.5
AGE_MAX_S = 1500.0           # no decision after g + 25 min
EXIT_BY_AGE_S = 178 * 60.0   # registered deadline (never binds: entries <= g + 25 min, holds <= 60 min)
SIZE_USD = 20.0
SLOW_MIN_DELAY_S = 5.0       # universe: grad delay > 5 s (instant graduates excluded by rule)
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MAX_DELAY_S = 5.0
FACTORY_MIN_TOP5 = 0.85
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; every exit fills on the NEXT bar at min(open, low)
# separation gate (stop rule, TRAIN)
SEP_HORIZON_BARS = 30
SEP_MIN_COINS = 30           # per group (TAKEOVER and DIES), per K
SEP_MIN_DIFF = 0.05
SEP_B = 2000
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 30, 30
MAX_CENSORED = C.MAX_CENSORED_SHARE
SHORTLIST_MAX = 2
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                     # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "base_first_bar": BASE_FIRST_BAR, "min_base_bars": MIN_BASE_BARS,
    "agent_buyer_sol": AGENT_BUYER_SOL, "agent_window_s": float(C.AGENT_WINDOW_S), "min_rate_sol": MIN_RATE_SOL,
    "min_buyers_pm": MIN_BUYERS_PM, "max_top_share": MAX_TOP_SHARE, "dies_frac": DIES_FRAC, "stop_pct": STOP_PCT,
    "fade_bars": FADE_BARS, "fade_frac": FADE_FRAC, "age_max_s": AGE_MAX_S, "exit_by_age_s": EXIT_BY_AGE_S,
    "size_usd": SIZE_USD, "slow_min_delay_s": SLOW_MIN_DELAY_S, "classes": ["OTHER"], "level": LEVEL,
    "placebo": "universe + BOOST over + alive; controls: momentum, unmatched",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(K: int, exit_set: str) -> dict:
    if int(K) not in K_GRID or exit_set not in EXIT_GRID:
        raise ValueError(f"(K={K!r}, exit={exit_set!r}) is not in the pre-registered grid")
    return {**FIXED, "K": int(K), "exit": exit_set, "max_hold_s": HOLD_S[exit_set]}


GRID = [make_params(k, e) for k in K_GRID for e in EXIT_GRID]
assert len(GRID) <= 12
SEP_PARAMS = {"version": VERSION, "test": "separation", "k_grid": list(K_GRID), "horizon_bars": SEP_HORIZON_BARS,
              "min_coins": SEP_MIN_COINS, "min_diff": SEP_MIN_DIFF, "level": "CONSTANT", "features": FIXED}
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "latency_60s": dataclasses.replace(FILL, latency_s=60.0)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class X6Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"K{int(p['K'])}|{p['exit']}"


def exit_spec(p: Mapping[str, Any]) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=HOLD_S[p["exit"]], exit_by_age_s=EXIT_BY_AGE_S)


# =========================================================================== features (AsOf only)


def _m0(snap: C.AsOf) -> int:
    return int(snap.g) // 60 * 60          # the graduation minute's start (CoinData.m0)


def window_end_bar(g: float) -> int:
    """j_w: the last bar that starts before g + 420 s (the end of the AGENT window)."""
    m0 = int(g) // 60 * 60
    return int(math.ceil((float(g) + C.AGENT_WINDOW_S - m0) / 60.0)) - 1


def flow_stats(bars: C.Bars, lo: int, hi: int) -> dict:
    """Non-AGENT flow over completed bars lo .. hi-1 (per-minute rates; the AGENT column is NaN = 0 before known)."""
    lo, hi = max(int(lo), 0), int(hi)
    n = hi - lo
    if n <= 0:
        return {"n": 0, "r_org": None, "r_tot": None, "net": None, "nb": None, "top": None}
    buy = np.asarray(bars.buy_sol[lo:hi], float)
    ag = np.nan_to_num(np.asarray(bars.agent_buy_sol[lo:hi], float), nan=0.0)
    sell = np.asarray(bars.sell_sol[lo:hi], float)
    nb = np.asarray(bars.n_buyers[lo:hi], float)
    org = np.clip(buy - ag, 0.0, None)
    org_nb = np.clip(nb - (ag >= AGENT_BUYER_SOL), 0.0, None)
    tot = float(org.sum())
    return {"n": n, "r_org": tot / n, "r_tot": float(buy.sum()) / n, "net": float((org - sell).sum()),
            "nb": float(org_nb.sum()) / n, "top": float(org.max()) / tot if tot > 0 else None}


def boost_state(snap: C.AsOf) -> dict:
    """BOOST as of ``snap``: ready once bar j_w completed (then tau >= g + 420 s and AGENT presence is decided).

    -> {ready, boost (None until ready), reason, j_w, j_b, n_base, r_org_B, r_tot_B, nb_B, agent_sol_B}."""
    j_w = window_end_bar(snap.g)
    out: dict[str, Any] = {"ready": False, "boost": None, "reason": None, "j_w": j_w, "j_b": None, "n_base": 0,
                           "r_org_B": None, "r_tot_B": None, "nb_B": None, "agent_sol_B": None}
    k = snap.k
    if k < j_w + 1:
        return out
    out["ready"] = True
    if not snap.agent_detected:
        out.update(boost=False, reason="no_agent")
        return out
    bars = snap.bars
    ag = np.nan_to_num(np.asarray(bars.agent_buy_sol[:j_w + 1], float), nan=0.0)
    idx = np.flatnonzero(ag > 0)
    if not len(idx):
        out.update(boost=False, reason="no_agent_bar")
        return out
    j_b = int(idx.max())
    n_base = j_b - BASE_FIRST_BAR + 1
    out.update(j_b=j_b, n_base=max(n_base, 0))
    if n_base < MIN_BASE_BARS:
        out.update(boost=False, reason="short_boost")
        return out
    fs = flow_stats(bars, BASE_FIRST_BAR, j_b + 1)
    out.update(boost=True, r_org_B=fs["r_org"], r_tot_B=fs["r_tot"], nb_B=fs["nb"],
               agent_sol_B=float(ag[BASE_FIRST_BAR:j_b + 1].sum()))
    return out


def x6_class(snap: C.AsOf) -> str | None:
    """PLAN 4.2 rules as in M1 (same thresholds, same order): OPERATOR, FACTORY, else OTHER. None when an input is NULL
    or not yet knowable (a NULL never passes and is never 0)."""
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


def is_slow(snap: C.AsOf) -> bool | None:
    """Graduated more than 5 s after creation (creation not scanned: the 1,800 s lower bound). None when unknown."""
    d = snap.get("grad_delay_s")
    if d is None:
        d = snap.get("grad_delay_lb_s")
    return None if d is None else bool(d > SLOW_MIN_DELAY_S)


def universe_reason(snap: C.AsOf, bs: Mapping[str, Any] | None = None) -> str | None:
    """None when the coin is in X6's universe at ``snap`` (PREREG 2.3), else why not. Needs a READY boost state."""
    bs = bs if bs is not None else boost_state(snap)
    if not bs["ready"]:
        return "not_ready"
    slow = is_slow(snap)
    if slow is None:
        return "delay_null"
    if not slow:
        return "instant"
    cls = x6_class(snap)
    if cls != "OTHER":
        return f"class_{cls}"
    if not bs["boost"]:
        return bs["reason"]
    return None


def decision_bar(bs: Mapping[str, Any], K: int) -> int | None:
    """Completed bars at the coin's one decision for K: j_b + 1 + K (never before BOOST is known to be over)."""
    if not bs.get("boost"):
        return None
    return max(int(bs["j_b"]) + 1 + int(K), int(bs["j_w"]) + 1)


def takeover_eval(snap: C.AsOf, K: int, bs: Mapping[str, Any] | None = None) -> dict:
    """PREREG 3 at ``snap`` for window K: the post-BOOST window = the K bars after j_b (needs them completed).

    -> {ok, K, k_dec, due, r_P, r_last, net_P, nb_P, top_P, ratio, alive, conds, TAKEOVER: {CONSTANT, REPLACE}, DIES,
    MIDDLE, momentum, **boost_state}."""
    bs = dict(bs) if bs is not None else boost_state(snap)
    out: dict[str, Any] = {**bs, "ok": False, "K": int(K), "k_dec": decision_bar(bs, K), "due": False, "r_P": None,
                           "r_last": None, "net_P": None, "nb_P": None, "top_P": None, "ratio": None, "alive": None,
                           "conds": {}, "TAKEOVER": {lv: False for lv in LEVELS}, "DIES": False, "MIDDLE": False,
                           "momentum": False}
    if out["k_dec"] is None:
        return out
    j_b, k = int(bs["j_b"]), snap.k
    lo, hi = j_b + 1, j_b + 1 + int(K)
    out["due"] = k == out["k_dec"]
    if k < hi:
        return out
    bars = snap.bars
    P = flow_stats(bars, lo, hi)
    L = flow_stats(bars, hi - int(math.ceil(K / 2.0)), hi)
    alive = bool(snap.alive())
    r_B, r_T, nb_B = float(bs["r_org_B"]), float(bs["r_tot_B"]), float(bs["nb_B"])
    common_ok = {"size": P["r_org"] >= MIN_RATE_SOL, "absorb": P["net"] >= 0,
                 "breadth": P["nb"] >= max(nb_B, MIN_BUYERS_PM),
                 "dispersed": P["top"] is not None and P["top"] <= MAX_TOP_SHARE, "alive": alive}
    conds = {"rate_CONSTANT": P["r_org"] >= r_B and L["r_org"] >= r_B,
             "rate_REPLACE": P["r_org"] >= r_T and L["r_org"] >= r_T, **common_ok}
    to = {lv: bool(conds[f"rate_{lv}"] and all(common_ok.values())) for lv in LEVELS}
    dies = bool(P["r_org"] < DIES_FRAC * r_B)
    out.update(ok=True, r_P=P["r_org"], r_last=L["r_org"], net_P=P["net"], nb_P=P["nb"], top_P=P["top"],
               ratio=(P["r_org"] / r_B) if r_B > 0 else None, alive=alive, conds={c: bool(v) for c, v in conds.items()},
               TAKEOVER=to, DIES=dies, MIDDLE=bool(not to["CONSTANT"] and not dies),
               momentum=bool(P["net"] >= 0 and not to["CONSTANT"]))
    return out


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The X6 strategy for common.backtest: one decision per coin at BOOST end + K minutes."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    bs = boost_state(snap)
    if not bs["ready"]:
        return None
    if universe_reason(snap, bs) is not None:
        return C.SKIP                 # static from the end of the AGENT window: never trade this coin
    k_dec = decision_bar(bs, p["K"])
    if snap.k < k_dec:
        return None
    if snap.k > k_dec:
        return C.SKIP
    ev = takeover_eval(snap, p["K"], bs)
    if not ev["TAKEOVER"][p["level"]]:
        return C.SKIP
    return C.Enter(exits=exit_spec(p), tag=p["level"], state={"r_P": ev["r_P"], "ratio": ev["ratio"]})


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    k = snap.k
    return int(min(max((tau - _m0(snap)) // 60, 0), k))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """``fade60`` only: >= 3 completed bars after the entry decision, non-AGENT buying over the last 3 < 0.5 x the
    entry r_P and net selling over them. Placebo positions carry no state: their r_P is the non-AGENT buy rate over
    the K bars before THEIR decision (the signal's formula), so they run the same rule. Stop, time and deadline are
    mechanical (ExitSpec)."""
    if p["exit"] != "fade60":
        return None
    k = snap.k
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    if k - k_dec < FADE_BARS:
        return None
    bars = snap.bars
    ref = (pos.state or {}).get("r_P")
    if ref is None:
        ref = flow_stats(bars, k_dec - int(p["K"]), k_dec)["r_org"]
        if ref is None:
            return None
    st = flow_stats(bars, k - FADE_BARS, k)
    if st["r_org"] < FADE_FRAC * float(ref) and st["net"] < 0:
        return C.Exit("fade")
    return None


# =========================================================================== controls


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched placebo (PLAN 3.4 'the same eligible coins'): the X6 universe, BOOST over, alive."""
    bs = boost_state(snap)
    return bool(bs["ready"] and universe_reason(snap, bs) is None and snap.alive())


def momentum_ok(K: int):
    """Momentum control: placebo_ok and net non-AGENT inflow >= 0 over the K bars before the drawn decision."""
    def ok(snap: C.AsOf) -> bool:
        if not placebo_ok(snap):
            return False
        st = flow_stats(snap.bars, snap.k - int(K), snap.k)
        return st["net"] is not None and st["net"] >= 0
    ok.__name__ = f"momentum_K{int(K)}"
    return ok


def placebo_controls(p: Mapping[str, Any]) -> dict:
    return {"momentum": {"eligible": momentum_ok(p["K"]), "strata": None},
            "unmatched": {"eligible": None, "strata": None}}


# =========================================================================== separation gate (labels: never features)


def sep_obs(ds: C.Dataset, mints: Iterable[str] | None = None, with_labels: bool = True) -> pd.DataFrame:
    """One observation per universe coin and K at its decision (alive, label inside the data), with the group flags
    and (``with_labels``) the LABEL: the realized 30-minute mid-price change, read through AsOf 30 minutes later."""
    rows = []
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        t0 = float(cd.bar_start(window_end_bar(cd.g) + 1) + C.GRID_OFFSET_S)
        snap0 = ds.asof(m, t0)
        bs = boost_state(snap0)
        if universe_reason(snap0, bs) is not None:
            continue
        for K in K_GRID:
            kd = decision_bar(bs, K)
            t = float(cd.bar_start(kd) + C.GRID_OFFSET_S)
            if t - cd.g > AGE_MAX_S:
                continue
            snap = ds.asof(m, t)
            ev = takeover_eval(snap, K)
            if not ev["ok"] or not ev["alive"]:
                continue
            later = ds.asof(m, t + 60.0 * SEP_HORIZON_BARS)
            if later.k - snap.k < SEP_HORIZON_BARS:
                continue                          # the label would leave the data window
            row = {"mint": m, "K": K, "t": t, "age_min": (t - cd.g) / 60.0, "j_b": ev["j_b"], "r_org_B": ev["r_org_B"],
                   "r_P": ev["r_P"], "ratio": ev["ratio"], "nb_P": ev["nb_P"], "net_P": ev["net_P"],
                   "TAKEOVER": ev["TAKEOVER"]["CONSTANT"], "REPLACE": ev["TAKEOVER"]["REPLACE"], "DIES": ev["DIES"],
                   "MIDDLE": ev["MIDDLE"], "momentum": ev["momentum"], "fwd30": None}
            if with_labels:
                row["fwd30"] = later.price / snap.price - 1.0
            rows.append(row)
    cols = ["mint", "K", "t", "age_min", "j_b", "r_org_B", "r_P", "ratio", "nb_P", "net_P", "TAKEOVER", "REPLACE",
            "DIES", "MIDDLE", "momentum", "fwd30"]
    return pd.DataFrame(rows, columns=cols)


def _boot_diff(a: np.ndarray, b: np.ndarray, B: int, seed: int = 0) -> tuple[float, float] | None:
    """90 % CI of mean(a) - mean(b), resampling each group's coins (one observation per coin) independently."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return None
    rng = np.random.default_rng(seed)
    d = rng.choice(a, (B, len(a))).mean(1) - rng.choice(b, (B, len(b))).mean(1)
    return float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95))


def _wins(x: np.ndarray) -> float | None:
    if not len(x):
        return None
    lo, hi = np.quantile(x, [0.05, 0.95])
    return float(np.clip(x, lo, hi).mean())


def sep_check(obs: pd.DataFrame, B: int = SEP_B, hide: bool = False) -> dict:
    """PREREG 7. PASS when any K passes; KILL when none passes and one was powered; else UNDERPOWERED. ``hide`` (debug
    split) returns counts only."""
    out: dict[str, Any] = {"n_obs": int(len(obs)), "n_coins": int(obs["mint"].nunique()) if len(obs) else 0,
                           "need": {"coins_per_group": SEP_MIN_COINS, "diff": SEP_MIN_DIFF,
                                    "horizon_bars": SEP_HORIZON_BARS}, "per_K": {}, "passed": []}
    any_powered = False
    for K in K_GRID:
        o = obs[obs["K"] == K] if len(obs) else obs
        grp = {g: o[o[g]] if len(o) else o for g in ("TAKEOVER", "REPLACE", "DIES", "MIDDLE", "momentum")}
        d: dict[str, Any] = {"n": int(len(o)), **{f"n_{g}": int(len(v)) for g, v in grp.items()}}
        out["per_K"][str(K)] = d
        if hide:
            continue
        a = grp["TAKEOVER"]["fwd30"].to_numpy(float)
        b = grp["DIES"]["fwd30"].to_numpy(float)
        powered = len(a) >= SEP_MIN_COINS and len(b) >= SEP_MIN_COINS
        any_powered |= powered
        ma = float(a.mean()) if len(a) else None
        mb = float(b.mean()) if len(b) else None
        diff = None if ma is None or mb is None else ma - mb
        ci = _boot_diff(a, b, B)
        ok = bool(powered and diff is not None and diff >= SEP_MIN_DIFF and ci is not None and ci[0] > 0 and ma > 0)
        d.update(powered=bool(powered), diff=diff, diff_ci90=ci, passes=ok,
                 means={g: (float(v["fwd30"].mean()) if len(v) else None) for g, v in grp.items()},
                 medians={g: (float(v["fwd30"].median()) if len(v) else None) for g, v in grp.items()},
                 winsorized={g: _wins(v["fwd30"].to_numpy(float)) for g, v in grp.items()})
        if ok:
            out["passed"].append(K)
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    out["decision"] = "PASS" if out["passed"] else ("KILL" if any_powered else "UNDERPOWERED")
    return out


# =========================================================================== evaluation


def _q(x: Iterable[float | None], qs=(0.1, 0.5, 0.9)) -> dict | None:
    a = np.asarray([v for v in x if v is not None and math.isfinite(v)], float)
    return {f"p{int(100 * q)}": float(np.quantile(a, q)) for q in qs} if len(a) else None


def _decision_feats(ds: C.Dataset, trades: pd.DataFrame, K: int) -> list[dict]:
    out = []
    for r in trades.itertuples(index=False):
        ev = takeover_eval(ds.asof(r.mint, float(r.t_dec)), K)
        out.append({"ratio": ev["ratio"], "nb_P": ev["nb_P"], "r_P": ev["r_P"]})
    return out


def evaluate(res: C.Result, ds: C.Dataset, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts and decision-time features only -- never returns, exit reasons,
    fill prices or placebo outcomes."""
    t = res.trades
    p = res.meta["params"]
    ages = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    feats = _decision_feats(ds, t, p["K"]) if len(t) else []
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "decision_age_min": _q(ages.tolist()) if len(t) else None,
            "decision_ratio": _q([f["ratio"] for f in feats]), "decision_nb_P": _q([f["nb_P"] for f in feats]),
            "decision_r_P": _q([f["r_P"] for f in feats]),
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
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    return base


def x6_extras(ev: Mapping[str, Any]) -> list[dict]:
    """X6.1 (PREREG 8): the candidate beats the momentum control (mean_diff > 0). Blocking."""
    md = ((ev.get("controls") or {}).get("momentum") or {}).get("mean_diff")
    return [{"id": "X6.1", "name": "beats the momentum control (mean_diff > 0)",
             "pass": None if md is None else bool(md > 0), "value": md}]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 + 3.6 (common.verdict_entry) + X6.1. Item 9 (FINAL mean > 0) is judged in the overall
    verdict once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(e["pass"] is None for e in extras):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def _rank(key: str) -> int:
    keys = [config_key(p) for p in GRID]
    return keys.index(key) if key in keys else len(keys)


def train_configs(passed_K: Iterable[int]) -> list[dict]:
    """PREREG 7: only the configs of the K that passed the gate run (unrun configs are no trials)."""
    ok = {int(k) for k in passed_K}
    return [p for p in GRID if int(p["K"]) in ok]


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 8: qualifiers (sample, mean, top-2, matched placebo, momentum control, censoring) ranked by the coin-
    bootstrap 90 % CI lower bound (ties: mean, then grid order); shortlist = the top 2."""
    rows = []
    for key, e in evals.items():
        pc = (e.get("placebo") or {}).get("mean_diff")
        mc = ((e.get("controls") or {}).get("momentum") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and mc is not None and mc > 0 and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": key, "powered": bool(powered), "qualifies": bool(good), "n": e["n"],
                     "coins": e["n_coins"], "mean": e.get("mean"), "mean_without_top2": e.get("mean_without_top2"),
                     "ci90_lo": ci[0] if ci else None, "placebo_diff": pc, "momentum_diff": mc, "censored_share": cs})
    q = [r for r in rows if r["qualifies"]]
    if q:
        q.sort(key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                              _rank(r["config"])))
        top = q[:SHORTLIST_MAX]
        by_key = {config_key(p): p for p in GRID}
        sl = [by_key[r["config"]] for r in top]
        return {"verdict": "SHORTLISTED", "rows": rows, "ranked": [r["config"] for r in top], "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / placebo / momentum / censoring bars"
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
    """PREREG 8 VAL: a filter, never a ranking. Candidate = the TRAIN rank-1 config if it proceeds, else rank 2."""
    per = {role: decide_val_one(evals[role]) for role in ranked_roles}
    for role in ranked_roles:
        if per[role]["proceed"]:
            return {"verdict": per[role]["verdict"], "candidate_role": role, "candidate_config": evals[role]["config"],
                    "candidate_hash": evals[role]["params_hash"], "per_config": per, "proceed": True}
    v = "FAIL_VAL" if any(d["verdict"] == "FAIL_VAL" for d in per.values()) else "UNDERPOWERED_VAL"
    return {"verdict": v, "candidate_role": None, "candidate_config": None, "candidate_hash": None, "per_config": per,
            "proceed": False}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 8: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: X6 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds X6 never looked at; the TRAIN third hosted the debug run."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                            "note": "census TRAIN third: hosted the debug run (PREREG 13), not judged"}}


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
    """Raise :class:`X6Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X6Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X6Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X6Refused("PREREG.md changed after the first official TRAIN run; record changes in X6/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise X6Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X6Refused("TRAIN already ran on complete data (X6/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X6Refused("no TRAIN result (X6/train.json): run --stage train first")
    if train.get("provisional"):
        raise X6Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_SEP":
        raise X6Refused("X6 is dead: the separation gate failed on TRAIN (PREREG 7)")
    if tv != "SHORTLISTED":
        raise X6Refused(f"TRAIN decision {tv}: X6 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise X6Refused("no VAL shortlist for X6 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise X6Refused("the X6 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X6Refused("VAL already ran (X6/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise X6Refused(f"no VAL result (X6/val.json): {stage.upper()} needs a VAL decision first")
    vd = val.get("decision") or {}
    if vd.get("verdict") not in PROCEED_VAL:
        raise X6Refused(f"VAL decision {vd.get('verdict')}: X6 stopped (PLAN 8 rule 7 input); {stage.upper()} is not "
                        "spent")
    if vd.get("candidate_hash") not in sl.get("hashes", []):
        raise X6Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X6Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise X6Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X6Refused(f"{stage.upper()} already ran (X6/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise X6Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X6Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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
    """Counts and as-of structure only (no prices after a decision, no returns): the universe funnel, where BOOST ends,
    and how often each takeover condition holds at the decision (alive decisions only for the groups)."""
    reasons: dict[str, int] = {}
    jb: dict[str, int] = {}
    nbase: dict[str, int] = {}
    per_K: dict[str, dict] = {}
    ratio_by_K: dict[str, list] = {str(K): [] for K in K_GRID}
    rate_B, nb_B = [], []
    for K in K_GRID:
        per_K[str(K)] = {"decisions": 0, "alive": 0, "TAKEOVER_CONSTANT": 0, "TAKEOVER_REPLACE": 0, "DIES": 0,
                         "MIDDLE": 0, "momentum": 0, "past_age_max": 0,
                         "conds": {c: 0 for c in ("rate_CONSTANT", "rate_REPLACE", "size", "absorb", "breadth",
                                                  "dispersed", "alive")}, "decision_age_min": []}
    for m in ds.mints:
        cd = ds.coin(m)
        t0 = float(cd.bar_start(window_end_bar(cd.g) + 1) + C.GRID_OFFSET_S)
        snap0 = ds.asof(m, t0)
        bs = boost_state(snap0)
        why = universe_reason(snap0, bs)
        reasons[str(why or "in_universe")] = reasons.get(str(why or "in_universe"), 0) + 1
        if bs.get("j_b") is not None:
            jb[str(bs["j_b"])] = jb.get(str(bs["j_b"]), 0) + 1
        if why is not None:
            continue
        nbase[str(bs["n_base"])] = nbase.get(str(bs["n_base"]), 0) + 1
        rate_B.append(bs["r_org_B"])
        nb_B.append(bs["nb_B"])
        for K in K_GRID:
            d = per_K[str(K)]
            kd = decision_bar(bs, K)
            t = float(cd.bar_start(kd) + C.GRID_OFFSET_S)
            if t - cd.g > AGE_MAX_S:
                d["past_age_max"] += 1
                continue
            ev = takeover_eval(ds.asof(m, t), K)
            if not ev["ok"]:
                continue
            d["decisions"] += 1
            d["decision_age_min"].append((t - cd.g) / 60.0)
            for c, v in ev["conds"].items():
                d["conds"][c] += int(bool(v))
            if not ev["alive"]:
                continue
            d["alive"] += 1
            ratio_by_K[str(K)].append(ev["ratio"])
            d["TAKEOVER_CONSTANT"] += int(ev["TAKEOVER"]["CONSTANT"])
            d["TAKEOVER_REPLACE"] += int(ev["TAKEOVER"]["REPLACE"])
            d["DIES"] += int(ev["DIES"])
            d["MIDDLE"] += int(ev["MIDDLE"])
            d["momentum"] += int(ev["momentum"])
    for K in K_GRID:
        d = per_K[str(K)]
        d["decision_age_min"] = _q(d["decision_age_min"])
        d["ratio_r_P_over_r_org_B"] = _q(ratio_by_K[str(K)], (0.1, 0.25, 0.5, 0.75, 0.9))
    return {"coins": len(ds), "universe_funnel": reasons, "j_b_bar": dict(sorted(jb.items())),
            "baseline_bars": dict(sorted(nbase.items())),
            "boost_nonagent_buy_sol_per_min": _q(rate_B, (0.1, 0.25, 0.5, 0.75, 0.9)),
            "boost_nonagent_buyers_per_min": _q(nb_B, (0.1, 0.25, 0.5, 0.75, 0.9)), "per_K": per_K}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X6/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x6_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X6Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise X6Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise X6Refused("no configs to run (shortlist or VAL candidate missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X6Refused(str(e)) from e
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
                                   "note": "PREREG 7: the separation gate precedes any P&L; the grid was not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
            else:
                run_cfgs = [(config_key(p), p) for p in train_configs(sep["passed"])]
        results: dict[str, C.Result] = {}
        for role, p in run_cfgs:
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok,
                                       placebo_controls=placebo_controls(p), stress=STRESS, declarations=DECL,
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
                                  note=f"{VERSION}: PREREG 8, rank order {dec['ranked']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals, [r for r, _ in configs])
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", (_read_json(out_dir / "val.json") or {}).get("decision", {})
                                 .get("candidate_role"))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = x6_extras(evals["candidate"])
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "x6_extras": extras}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x6 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise X6Refused(str(e)) from e


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
        return "KILLED (takeover does not separate from flow-dies: PREREG 7)"
    if tv == "UNDERPOWERED_SEP":
        return "UNDERPOWERED (too few TAKEOVER or DIES coins for the gate on TRAIN)"
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
    L = [f"# X6 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X6 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, gate labels, exit reasons and "
              "fill prices are hidden and no parameter was chosen here.**", ""]
    sp = doc.get("separation")
    if sp:
        L += ["## Separation gate (PREREG 7)", "",
              f"- Observations: {sp['n_obs']} from {sp['n_coins']} coins (need ≥ {SEP_MIN_COINS} TAKEOVER and ≥ "
              f"{SEP_MIN_COINS} DIES coins per K).",
              f"- Decision: **{sp['decision']}**" + (f"; passed K: {sp['passed']}." if sp.get("passed") else "."), ""]
        hidden = sp["decision"].startswith("HIDDEN")
        if hidden:
            L += ["| K | obs | TAKEOVER | REPLACE | DIES | MIDDLE | momentum |", "|---:|---:|---:|---:|---:|---:|---:|"]
            for K, d in sp["per_K"].items():
                L.append(f"| {K} | {d['n']} | {d['n_TAKEOVER']} | {d['n_REPLACE']} | {d['n_DIES']} | {d['n_MIDDLE']} | "
                         f"{d['n_momentum']} |")
        else:
            L += ["| K | TAKEOVER n | DIES n | mean TAKEOVER | mean DIES | diff | 90% CI | median TAKEOVER | "
                  "median DIES | passes |", "|---:|---:|---:|---:|---:|---:|---|---:|---:|---|"]
            for K, d in sp["per_K"].items():
                mn, md = d.get("means") or {}, d.get("medians") or {}
                L.append(f"| {K} | {d['n_TAKEOVER']} | {d['n_DIES']} | {_pct(mn.get('TAKEOVER'))} | "
                         f"{_pct(mn.get('DIES'))} | {_pct(d.get('diff'))} | {_ci(d.get('diff_ci90'))} | "
                         f"{_pct(md.get('TAKEOVER'))} | {_pct(md.get('DIES'))} | {d.get('passes')} |")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts and structure (no returns)", "",
              f"- Coins {ec['coins']}; universe funnel: {ec['universe_funnel']}.",
              f"- BOOST's last bar j_b (all coins with an AGENT bar): {ec['j_b_bar']}; baseline bars (universe): "
              f"{ec['baseline_bars']}.",
              f"- BOOST-time non-AGENT buy SOL/min: {ec['boost_nonagent_buy_sol_per_min']}; buyers/min: "
              f"{ec['boost_nonagent_buyers_per_min']}.", "",
              "| K | decisions | alive | TAKEOVER CONSTANT | TAKEOVER REPLACE | DIES | MIDDLE | momentum | past g+25 | "
              "decision age (min) | r_P / r_org_B |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for K, d in ec["per_K"].items():
            L.append(f"| {K} | {d['decisions']} | {d['alive']} | {d['TAKEOVER_CONSTANT']} | {d['TAKEOVER_REPLACE']} | "
                     f"{d['DIES']} | {d['MIDDLE']} | {d['momentum']} | {d['past_age_max']} | {d['decision_age_min']} | "
                     f"{d['ratio_r_P_over_r_org_B']} |")
        L += ["", "| K | " + " | ".join(next(iter(ec["per_K"].values()))["conds"]) + " |",
              "|---:|" + "---:|" * len(next(iter(ec["per_K"].values()))["conds"])]
        for K, d in ec["per_K"].items():
            L.append(f"| {K} | " + " | ".join(str(v) for v in d["conds"].values()) + " |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | decision age (min) | r_P / r_org_B | nb_P | placebo trades | controls | "
                  "horizon exits | entries/day |", "|---|---:|---:|---|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['decision_age_min']} | "
                         f"{e['decision_ratio']} | {e['decision_nb_P']} | {e['n_placebo']} | {e['n_controls']} | "
                         f"{e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "momentum diff | unmatched diff | costs ×1.5 | latency 60 s | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                stt = e.get("stress") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('momentum') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('unmatched') or {}).get('mean_diff'))} | {_pct(stt.get('costs_x1.5'))} | "
                         f"{_pct(stt.get('latency_60s'))} | {_pct(e.get('censored_share'), 0)} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, momentum diff "
                 f"{_pct(r['momentum_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (rank order {dec.get('ranked')}).")
    if dec.get("per_config"):
        for role, d in dec["per_config"].items():
            L.append(f"- VAL {role}: {d['verdict']} (n {d['n']}, mean {_pct(d['mean'])}).")
        L.append(f"- Candidate: {dec.get('candidate_config')} ({dec.get('candidate_role')}).")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("x6_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
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
    ap = argparse.ArgumentParser(description="X6 post-BOOST organic takeover: pre-registered stages; see "
                                             "research/lab2/X6/PREREG.md")
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
    except X6Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
