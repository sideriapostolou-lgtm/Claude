"""M1 (PLAN 4.5): ride mechanical bids, and exit when their rhythm breaks.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/M1/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; AGENT
fields only once knowable; NULL stays None, never 0). Labels (the realized 60-minute price change of the model
check, rug hits during a hold) are outcomes: they are read through AsOf at a LATER time and never feed a decision.

Two detectors
-------------
* **MECH-bar** (the pre-registered instrument; every strategy variant uses it). Minute bars carry no wallet ids, and
  backfill P4 (B1 trades) skips instant graduates -- the operator / ticker-clone coins that M1 exists for. So the
  PLAN's wallet test is mapped onto minute bars over the last 30 completed minutes (PLAN window (tau - 30 min, tau]):

  - ``floor``: the 3rd-lowest per-minute non-AGENT buy SOL (a price-ignoring buyer present in >= 28 of 30 minutes
    puts a floor under every minute's buying; organic flow only adds to it);
  - single actor: in the 6 quietest minutes the median number of buyers (>= 0.01 SOL) is <= 2;
  - steady: the CV of the 30 minute sums is < 0.5 (PLAN's buy-size regularity);
  - price-insensitive: |Spearman(minute buy SOL, previous minute's return)| < 0.3 (PLAN's threshold), over the
    minutes that carry the bid (the PLAN computes it over the MECH wallet's own buys);
  - fires when floor >= 0.01 SOL/min and the three tests pass. ``mech_bid_h`` = 60 x floor (SOL per hour).

* **MECH-wallet** (PLAN 4.5 verbatim, on B1 trades through ``snap.trades``): >= 6 buys, sells <= 10 % of buys in SOL,
  CV of buy gaps < 0.25, CV of buy sizes < 0.5, |Spearman(size, 1-minute return before the buy)| < 0.3, not AGENT,
  not CREATOR, not a pooled account. DIAGNOSTIC ONLY (agreement with MECH-bar on coins that have B1 trades); it is
  not a strategy variant, so M1 stays at the PLAN 3.4 limit of 4 variants.

Model check (stop rule 5, before any P&L): on TRAIN, OLS of the realized 60-minute mid-price change on
``drift_pred60 = ((X + mech_bid_h) / X)^2 - 1`` (X = pricing reserve x + v) over detector-firing decisions at ages
35, 45, ..., 115 min; KILL when slope < 0.5 or R^2 < 0.05.

CLI::

    python research/lab2/m1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/m1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/m1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/m1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/m1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/m1.py --stage final
    python research/lab2/m1.py --stage val --check             # prerequisites only

Each stage writes ``M1/<stage>.json`` and ``M1/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlist, no stage after a model-check KILL, TEST / CONFIRM / FINAL once each, never
CONFIRM or FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "m1-v1"
OUT_DIR = HERE / "M1"
HYP, HYP_TWIN, HYP_MC = "M1", "M1-twin", "M1-modelcheck"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-6)
# MECH-bar detector
W_BARS = 30                 # completed minutes in the MECH window (PLAN: (tau - 30 min, tau])
FLOOR_RANK = 3              # floor = 3rd-lowest minute -> the bid is present in >= 28 of 30 minutes
FLOOR_MIN_SOL = 0.01        # SOL per minute: at least one non-dust buy's worth
QUIET_N = 6                 # the quietest minutes examined by the single-actor test
QUIET_MAX_BUYERS = 2        # median buyers (>= 0.01 SOL) in those minutes
STEADY_MAX_CV = 0.5         # PLAN 4.5 size regularity (CV of buy sizes < 0.5) applied to the window's minute sums
SPEARMAN_MAX = 0.3          # PLAN 4.5: |Spearman(size, return before)| < 0.3
CARRY_FRAC = 0.5            # a minute "carries the bid" when its non-AGENT buy SOL >= 0.5 x floor
ALIVE_BARS = 2              # bid_alive: one of the last 2 completed minutes carries the bid (PLAN: within 120 s)
RHYTHM_BARS = 2             # rhythm break: the last 2 completed minutes after the entry decision both miss it
MECH_AGE_MIN = 10           # PLAN: mech_age >= 10 min
MECH_AGE_MISSES = 2         # misses tolerated inside the run that defines mech_age
# precursors (bar proxies of PLAN 4.5 "precursor")
DUMP_FRAC_X = 0.04          # one wallet sold >= 4 % of the pricing reserve in a minute (PLAN D1-E2 size, ~8 % price)
LP_FRAC_Y = 0.005           # tokens left the pool beyond trades by > 0.5 % of y: liquidity withdrawal
# classes (PLAN 4.2 rules that M1 needs: FACTORY excluded, OPERATOR allowed)
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MAX_DELAY_S = 5.0
FACTORY_MIN_TOP5 = 0.85
ALLOWED_CLASSES = ("OPERATOR", "OTHER")
# entry / exits
AGE_MIN_S = 1800.0          # PLAN: age >= 30 min
AGE_MAX_S = 7200.0          # data: B2 bars end at g + 180 min; entries stop at g + 120 min (>= 60 min of hold data)
STOP_PCT = 0.10
MAX_HOLD_S = 6 * 3600.0     # PLAN 6 h; the B2 horizon (g + 179 min) truncates it ("horizon" exits are reported)
SIZE_USD = 20.0
M_GRID = (1.0, 2.0)
EXIT_GRID = ("rhythm", "rhythm+prec")
CANDIDATE_EXIT, TWIN_EXIT = "rhythm+prec", "rhythm"
# model check (stop rule 5)
MC_AGES_MIN = tuple(range(35, 116, 10))   # the detector needs 32 completed bars; label ends <= g + 176 min
MC_HORIZON_S = 3600.0
MC_MIN_SLOPE, MC_MIN_R2 = 0.5, 0.05
MC_MIN_COINS, MC_MIN_OBS = 30, 100
# operator clusters (a bootstrap grouping, never a feature): shared creator / symbol / top-5 early pool buyer
CLUSTER_TOP_K = 5
# rug label: a one-minute drop of more than 50 % (PLAN: one-trade drop > 50 %; minute bars bound it from above)
RUG_DROP = 0.5
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_CLUSTERS = 30, 3
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.02                       # PLAN 4.5: mean >= +2 % net
PASS_MIN_TRADES, PASS_MIN_CLUSTERS = 60, 3  # PLAN 4.5 pass item 1 (evaluated on the powered one-shot split)
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "detector": "MECH-bar", "w_bars": W_BARS, "floor_rank": FLOOR_RANK,
    "floor_min_sol": FLOOR_MIN_SOL, "quiet_n": QUIET_N, "quiet_max_buyers": QUIET_MAX_BUYERS,
    "steady_max_cv": STEADY_MAX_CV, "spearman_max": SPEARMAN_MAX, "carry_frac": CARRY_FRAC,
    "alive_bars": ALIVE_BARS, "rhythm_bars": RHYTHM_BARS, "mech_age_min": MECH_AGE_MIN, "dump_frac_x": DUMP_FRAC_X, "lp_frac_y": LP_FRAC_Y,
    "classes": list(ALLOWED_CLASSES), "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S, "stop_pct": STOP_PCT,
    "max_hold_s": MAX_HOLD_S, "size_usd": SIZE_USD,
    "fill": "common.FillConfig() default: worst, latency 30 s, entry-bar exits",
}


def make_params(m: float, exit_set: str) -> dict:
    if exit_set not in EXIT_GRID:
        raise ValueError(f"exit set {exit_set!r} not in {EXIT_GRID}")
    return {**FIXED, "m": float(m), "exit": exit_set}


GRID = [make_params(m, e) for m in M_GRID for e in EXIT_GRID]
MC_PARAMS = {"version": VERSION, "test": "model_check", "ages_min": list(MC_AGES_MIN), "horizon_s": MC_HORIZON_S,
             "min_slope": MC_MIN_SLOPE, "min_r2": MC_MIN_R2, "detector": FIXED}
STRESS = {"costs_x1.5": C.FillConfig().stressed(1.5), "rent_0.22": C.FillConfig(rent_usd=0.22),
          "alt_fill": C.FillConfig(entry_bar_exits=False, exit_delay_bars=1)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class M1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"m{p['m']:g}|{p['exit']}"


# =========================================================================== small numerics


def _rank_avg(x: np.ndarray) -> np.ndarray:
    """Ranks 1..n with ties averaged."""
    order = np.argsort(x, kind="mergesort")
    sx = x[order]
    r = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation; 0.0 when undefined (fewer than 3 pairs or a constant series): a constant buy
    size is the most price-ignoring series there is."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return 0.0
    ra, rb = _rank_avg(a), _rank_avg(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return 0.0
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


def _cv(x: np.ndarray) -> float:
    m = float(np.mean(x)) if len(x) else 0.0
    return float(np.std(x) / m) if m > 0 else math.inf


# =========================================================================== MECH-bar features (AsOf only)


def bid_series(bars: C.Bars, k: int) -> np.ndarray:
    """Per-minute non-AGENT buy SOL of the first ``k`` completed bars (MECH excludes AGENT; the AGENT column is NaN
    before its identity is knowable, so nothing is subtracted then)."""
    buy = np.asarray(bars.buy_sol[:k], float)
    ag = np.asarray(bars.agent_buy_sol[:k], float)
    return np.clip(buy - np.nan_to_num(ag, nan=0.0), 0.0, None)


def _run_minutes(carry: np.ndarray, k: int) -> int:
    """Minutes from the start of the current bid run to tau: walk back from the last completed bar while the bar
    carries the bid, tolerating MECH_AGE_MISSES misses."""
    misses, start = 0, None
    for j in range(k - 1, -1, -1):
        if carry[j]:
            start = j
        elif misses < MECH_AGE_MISSES:
            misses += 1
        else:
            break
    return 0 if start is None else int(k - start)


def mech_bar(snap: C.AsOf, k_end: int | None = None) -> dict:
    """MECH-bar detector at ``snap`` (or as of an earlier cutoff: the first ``k_end`` completed bars).

    -> {ok, fires, k, floor, quiet_buyers, cv, spearman, bid_alive, mech_age_min, mech_bid_h, X, drift_pred60}."""
    bars = snap.bars
    k = len(bars) if k_end is None else max(0, min(int(k_end), len(bars)))
    out = {"ok": False, "fires": False, "k": k, "floor": None, "quiet_buyers": None, "cv": None, "spearman": None,
           "bid_alive": False, "mech_age_min": 0, "mech_bid_h": None, "X": None, "drift_pred60": None}
    if k < W_BARS + 2:
        return out
    b = bid_series(bars, k)
    bw = b[k - W_BARS:k]
    nb = np.asarray(bars.n_buyers[k - W_BARS:k], float)
    c = np.asarray(bars.c[:k], float)
    r_prev = c[k - W_BARS - 1:k - 1] / c[k - W_BARS - 2:k - 2] - 1.0     # return of minute i-1, for minute i
    order = np.argsort(bw, kind="stable")
    floor = float(bw[order[FLOOR_RANK - 1]])
    quiet = float(np.median(nb[order[:QUIET_N]]))
    # PLAN: Spearman over the MECH wallet's buys only -> over the window minutes that carry the bid. Minutes the
    # bid skipped would otherwise couple b_i to r_{i-1} through the bid's own impact (a spurious "reaction").
    on = bw >= CARRY_FRAC * floor
    rho = spearman(bw[on], r_prev[on])
    cv = _cv(bw)
    X = float(bars.X[k - 1])
    carry = b >= CARRY_FRAC * floor if floor > 0 else np.zeros(k, bool)
    mech_h = 60.0 * floor
    out.update(ok=True, floor=floor, quiet_buyers=quiet, cv=cv, spearman=rho, X=X, mech_bid_h=mech_h,
               bid_alive=bool(floor > 0 and carry[k - ALIVE_BARS:k].any()),
               mech_age_min=_run_minutes(carry, k),
               drift_pred60=((X + mech_h) / X) ** 2 - 1.0 if X > 0 else None,
               fires=bool(floor >= FLOOR_MIN_SOL and quiet <= QUIET_MAX_BUYERS and cv < STEADY_MAX_CV
                          and abs(rho) < SPEARMAN_MAX))
    return out


def precursors(snap: C.AsOf, j_from: int, k_end: int | None = None) -> dict:
    """Bar-level precursor flags in completed bars j_from .. k-1 -> {"dump": [bar idx], "lp": [bar idx]}.

    * dump: sell SOL >= DUMP_FRAC_X x X(before) x max(n_sellers, 1): by pigeonhole at least ONE wallet sold >= 4 % of
      the pricing reserve in that minute (the bar analog of an insider / operator dump);
    * lp: token conservation breaks downward, y < y(before) - buy_tok + sell_tok by > 0.5 % of y: tokens left the
      pool outside trades = a liquidity withdrawal (conservation holds to 1e-6 on all census bars)."""
    bars = snap.bars
    k = len(bars) if k_end is None else max(0, min(int(k_end), len(bars)))
    lo = max(int(j_from), 1)
    if lo >= k:
        return {"dump": [], "lp": []}
    j = np.arange(lo, k)
    sell = np.asarray(bars.sell_sol[:k], float)
    ns = np.maximum(np.asarray(bars.n_sellers[:k], float), 1.0)
    X = np.asarray(bars.X[:k], float)
    y = np.asarray(bars.y[:k], float)
    bt, st = np.asarray(bars.buy_tok[:k], float), np.asarray(bars.sell_tok[:k], float)
    dump = j[(sell[j] > 0) & (sell[j] >= DUMP_FRAC_X * X[j - 1] * ns[j])]
    resid = y[j] - (y[j - 1] - bt[j] + st[j])
    lp = j[resid < -LP_FRAC_Y * y[j - 1]]
    return {"dump": [int(v) for v in dump], "lp": [int(v) for v in lp]}


def m1_class(snap: C.AsOf) -> str | None:
    """PLAN 4.2 rules M1 needs, in PLAN order: OPERATOR, FACTORY, else OTHER (= ORGANIC / NEWS / COMPLETED, all
    allowed). None when an input is NULL or not yet knowable (a NULL never passes and is never 0)."""
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


def round_trip_frac(snap: C.AsOf, cost: C.CostModel | None = None) -> float | None:
    """costs.py round trip of a $20 ticket at the current pool state (fee tier by date and market cap, impact on
    the pool's own k = X * y, network fees), as a fraction of the stake."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return None
    X, y = float(bars.X[k - 1]), float(bars.y[k - 1])
    if not (X > 0 and y > 0):
        return None
    sol_in = SIZE_USD / snap.sol_usd
    return C.round_trip_pct(sol_in, snap.price, X * y, snap.t, cost or C.CostModel()) / 100.0


def entry_decision(snap: C.AsOf, p: Mapping[str, Any], cls: str | None = None) -> tuple[bool, dict]:
    """PLAN 4.5 entry: bid_alive, mech_age >= 10 min, drift_pred60 >= m x round trip, no precursor in the MECH
    window (age and class are checked by :func:`strategy`)."""
    mb = mech_bar(snap)
    info = dict(mb, cls=cls, precursor=None, round_trip=None, drift_over_cost=None)
    if not (mb["ok"] and mb["fires"] and mb["bid_alive"] and mb["mech_age_min"] >= MECH_AGE_MIN):
        return False, info
    pr = precursors(snap, j_from=mb["k"] - W_BARS)
    info["precursor"] = bool(pr["dump"] or pr["lp"])
    if info["precursor"]:
        return False, info
    rt = round_trip_frac(snap)
    info["round_trip"] = rt
    if rt is None or rt <= 0 or mb["drift_pred60"] is None:
        return False, info
    info["drift_over_cost"] = mb["drift_pred60"] / rt
    return bool(mb["drift_pred60"] >= float(p["m"]) * rt), info


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return 0
    return int(min(max((tau - int(bars.minute_ts[0])) // 60, 0), k))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """Rhythm break (2 completed minutes after the entry decision both below 0.5 x the entry floor) and, for the
    ``rhythm+prec`` exit set, any precursor in a bar completed after the entry decision. The stop (-10 %) and the
    time limit are mechanical (ExitSpec). Placebo positions carry no state: their floor is recomputed from the bars
    completed at THEIR decision, so they run the same rule."""
    bars = snap.bars
    k = len(bars)
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    f_ref = (pos.state or {}).get("floor")
    if f_ref is None:
        f_ref = mech_bar(snap, k_end=k_dec)["floor"]
    if f_ref is not None and f_ref >= FLOOR_MIN_SOL and k - k_dec >= RHYTHM_BARS:
        b = bid_series(bars, k)
        if bool((b[k - RHYTHM_BARS:k] < CARRY_FRAC * f_ref).all()):
            return C.Exit("rhythm")
    if p["exit"] == "rhythm+prec":
        pr = precursors(snap, j_from=k_dec)
        if pr["dump"]:
            return C.Exit("precursor_dump")
        if pr["lp"]:
            return C.Exit("precursor_lp")
    return None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The M1 strategy for common.backtest (one entry per coin)."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    cls = m1_class(snap)
    if cls not in ALLOWED_CLASSES:
        return C.SKIP                 # FACTORY or unresolvable: static from g + 420 s, never trade this coin
    ok, info = entry_decision(snap, p, cls)
    if not ok:
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=MAX_HOLD_S), tag=cls,
                   state={"floor": info["floor"]})


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe (PLAN 3.4 'same eligible coins'): an allowed class and alive."""
    return m1_class(snap) in ALLOWED_CLASSES and snap.alive()


# =========================================================================== MECH-wallet (PLAN verbatim; diagnostic)

MW_MIN_BUYS, MW_MAX_SELL_FRAC, MW_MAX_GAP_CV, MW_MAX_SIZE_CV = 6, 0.10, 0.25, 0.5


def _creator_h(address: str | None) -> int | None:
    if not address:
        return None
    try:
        import s1  # the lab2 cityHash64 port (checked on 917 real pairs)
        return int(s1.wallet_h(address))
    except Exception:
        return None


def mech_wallets(snap: C.AsOf, window_s: float = 1800.0) -> list[dict] | None:
    """PLAN 4.5 MECH wallets in (tau - 30 min, tau] from B1 pool trades (``snap.trades``); None without B1.

    AGENT = research/flow detect_agent ("robust") on the prefix's pool buys in [g, g + 420 s), causal (as_of tau).
    CREATOR = cityHash64 of ``snap['creator']`` when the creation was scanned. Pooled accounts are dropped."""
    tr = snap.trades
    if tr is None:
        return None
    pool = tr[tr["venue"] == 1]
    if not len(pool):
        return []
    tau, g = snap.tau, snap.g
    ts = pool["ts"].to_numpy(float)
    wal = pool["wallet_h"].to_numpy()
    buy = pool["is_buy"].to_numpy(bool)
    usol = pool["usol"].to_numpy(float) / 1e9
    vk = pool["virt_ksol"].to_numpy(float) if "virt_ksol" in pool.columns else np.zeros(len(pool))
    # pre-trade price of every pool trade (pooled accounts included: their trades move the price too)
    price = (pool["x0"].to_numpy(float) + np.nan_to_num(vk) * 1000.0) / np.maximum(pool["y0"].to_numpy(float), 1.0)
    pooled = pool["pooled"].to_numpy(bool) if "pooled" in pool.columns else np.zeros(len(pool), bool)
    excl = set(wal[pooled].tolist())
    cands: dict[Any, dict] = {}
    early = (ts >= g) & (ts < g + C.AGENT_WINDOW_S) & ~pooled
    for w, t, s, isb in zip(wal[early], ts[early], usol[early], buy[early]):
        d = cands.setdefault(w, {"ts": [], "sol": [], "sells": 0})
        if isb:
            d["ts"].append(int(t))
            d["sol"].append(float(s))
    for w in cands:
        cands[w]["sells"] = int(((wal == w) & ~buy).sum())
    ag = C.flow_features.detect_agent(cands, int(g), rule="robust", as_of=int(tau)) if cands else None
    if ag is not None and ag["known_at"] <= tau:
        excl.add(ag["wallet"])
    ch = _creator_h(snap.get("creator"))
    if ch is not None:
        excl.add(ch)
    win = ts > tau - window_s
    out = []
    for w in np.unique(wal[win & buy]):
        if w in excl:
            continue
        mw = win & (wal == w)
        bsel = mw & buy
        bts, bsz = ts[bsel], usol[bsel]
        if len(bts) < MW_MIN_BUYS:
            continue
        sell_sol = float(usol[mw & ~buy].sum())
        if sell_sol > MW_MAX_SELL_FRAC * float(bsz.sum()):
            continue
        gaps = np.diff(bts)
        if _cv(gaps) >= MW_MAX_GAP_CV or _cv(bsz) >= MW_MAX_SIZE_CV:
            continue
        idx_b = np.flatnonzero(bsel)
        i60 = np.searchsorted(ts, bts - 60.0, side="left")
        ret_before = price[idx_b] / price[i60] - 1.0
        rho = spearman(bsz, ret_before)
        if abs(rho) >= SPEARMAN_MAX:
            continue
        first = float(ts[(wal == w) & buy].min())
        out.append({"wallet_h": w, "n_buys": int(len(bts)), "buy_sol": float(bsz.sum()), "sell_sol": sell_sol,
                    "median_gap_s": float(np.median(gaps)), "gap_cv": _cv(gaps), "size_cv": _cv(bsz),
                    "spearman": rho, "mech_age_min": (tau - first) / 60.0, "last_buy_ts": float(bts[-1])})
    return out


# =========================================================================== labels and groupings (never features)


def _grid_time(cd: C.CoinData, target: float) -> float:
    """The last decision-grid time (minute boundary + 20 s) at or before ``target``."""
    j = int(math.floor((target - C.GRID_OFFSET_S - cd.m0) / 60.0))
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def _rug_in(bars: C.Bars, j0: int, j1: int) -> bool:
    """Any minute in [j0, j1] whose low is < 50 % of max(open, previous close)."""
    o, l, c = bars.o, bars.l, bars.c
    for j in range(max(j0, 1), min(j1, len(bars) - 1) + 1):
        ref = max(float(o[j]), float(c[j - 1]))
        if ref > 0 and float(l[j]) < RUG_DROP * ref:
            return True
    return False


def model_check_obs(ds: C.Dataset, mints: Iterable[str] | None = None, with_wallet: bool = True) -> pd.DataFrame:
    """Detector-firing decisions on the 10-minute grid (ages 35..115 min) with their LABEL, the realized 60-minute
    mid-price change (read through AsOf 60 min later). Allowed classes only."""
    rows = []
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        cls = None
        for a in MC_AGES_MIN:
            t = _grid_time(cd, cd.g + 60.0 * a)
            snap = ds.asof(m, t)
            if cls is None:
                cls = m1_class(snap)
                if cls not in ALLOWED_CLASSES:
                    break
            mb = mech_bar(snap)
            if not (mb["fires"] and mb["bid_alive"] and mb["mech_age_min"] >= MECH_AGE_MIN):
                continue
            later = ds.asof(m, t + MC_HORIZON_S)
            if later.k - snap.k < int(MC_HORIZON_S // 60):
                continue                              # horizon not inside the data window
            row = {"mint": m, "class": cls, "age_min": a, "t": t, "drift_pred60": mb["drift_pred60"],
                   "mech_bid_h": mb["mech_bid_h"], "X": mb["X"], "floor": mb["floor"],
                   "realized60": later.price / snap.price - 1.0,
                   "rug_in_window": _rug_in(later.bars, snap.k, later.k - 1)}
            if with_wallet:
                mw = mech_wallets(snap)
                row["wallet_mech"] = None if mw is None else bool(mw)
            rows.append(row)
    cols = ["mint", "class", "age_min", "t", "drift_pred60", "mech_bid_h", "X", "floor", "realized60",
            "rug_in_window", "wallet_mech"]
    return pd.DataFrame(rows, columns=cols)


def ols(x: np.ndarray, y: np.ndarray) -> dict | None:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    syy = float(((y - ym) ** 2).sum())
    if sxx <= 0:
        return None
    sxy = float(((x - xm) * (y - ym)).sum())
    slope = sxy / sxx
    return {"slope": slope, "intercept": float(ym - slope * xm), "r2": (sxy * sxy / (sxx * syy)) if syy > 0 else 0.0,
            "n": int(len(x))}


def _boot_slope(obs: pd.DataFrame, B: int, seed: int = 0) -> tuple[float, float] | None:
    coins = obs["mint"].to_numpy(object)
    codes, uniq = pd.factorize(pd.Series(coins))
    if len(uniq) < 2:
        return None
    x, y = obs["drift_pred60"].to_numpy(float), obs["realized60"].to_numpy(float)
    groups = [np.flatnonzero(codes == i) for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(uniq), len(uniq))])
        f = ols(x[idx], y[idx])
        if f is not None:
            out.append(f["slope"])
    if len(out) < 10:
        return None
    return float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))


def model_check(obs: pd.DataFrame, B: int = 2000, hide: bool = False,
                clusters: Mapping[str, str] | None = None) -> dict:
    """Stop rule 5. PASS / KILL / UNDERPOWERED (fewer than 30 coins or 100 observations). Diagnostics never decide.
    ``hide`` (debug split) returns counts only."""
    n_obs, n_coins = int(len(obs)), int(obs["mint"].nunique()) if len(obs) else 0
    out: dict[str, Any] = {"n_obs": n_obs, "n_coins": n_coins,
                           "by_class": obs["class"].value_counts().to_dict() if n_obs else {},
                           "n_clusters": int(obs["mint"].map(clusters).nunique()) if (n_obs and clusters) else None,
                           "need": {"coins": MC_MIN_COINS, "obs": MC_MIN_OBS, "slope": MC_MIN_SLOPE, "r2": MC_MIN_R2}}
    if "wallet_mech" in obs and obs["wallet_mech"].notna().any():
        wm = obs["wallet_mech"].dropna().astype(bool)
        out["wallet_agreement"] = {"obs_with_b1": int(len(wm)), "wallet_mech_present": int(wm.sum())}
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    fit = ols(obs["drift_pred60"], obs["realized60"]) if n_obs else None
    out["fit"] = fit
    if n_coins < MC_MIN_COINS or n_obs < MC_MIN_OBS or fit is None:
        out["decision"] = "UNDERPOWERED"
    elif fit["slope"] < MC_MIN_SLOPE or fit["r2"] < MC_MIN_R2:
        out["decision"] = "KILL"
    else:
        out["decision"] = "PASS"
    if fit is not None:
        out["slope_ci95_coin"] = _boot_slope(obs, B)
        first = obs.sort_values(["mint", "t"]).groupby("mint").head(1)
        lo, hi = np.quantile(obs["realized60"], [0.05, 0.95])
        out["diagnostics"] = {
            "one_obs_per_coin": ols(first["drift_pred60"], first["realized60"]),
            "realized_winsorized_5_95": ols(obs["drift_pred60"], obs["realized60"].clip(lo, hi)),
            "log_log": ols(np.log1p(obs["drift_pred60"]), np.log1p(obs["realized60"].clip(lower=-0.999))),
            "without_rug_windows": ols(obs.loc[~obs["rug_in_window"], "drift_pred60"],
                                       obs.loc[~obs["rug_in_window"], "realized60"]),
            "rug_window_share": float(obs["rug_in_window"].mean()),
            "mean_pred": float(obs["drift_pred60"].mean()), "mean_realized": float(obs["realized60"].mean()),
        }
    return out


def cluster_table(ds: C.Dataset) -> pd.DataFrame:
    """Operator-cluster proxy for the bootstrap / concentration checks (a grouping, never a feature): connected
    components of allowed-class coins that share a creator, an upper-cased symbol, or ANY of their top-5 early
    (w120) pool buyers (AGENT and pooled accounts excluded) -- the PLAN links operators by co-appearing wallets.
    Fields are read through AsOf at the end of each coin's window. Other coins are their own cluster. Over-merging
    only widens the cluster CIs (conservative); under-merging would narrow them."""
    parent: dict[str, str] = {}
    cls_of: dict[str, str | None] = {}

    def find(a: str) -> str:
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for m in ds.mints:
        cd = ds.coin(m)
        snap = ds.asof(m, cd.g + 60 * C.N_BARS + C.DECISION_LAG_S)
        node = "m:" + m
        find(node)
        cls_of[m] = m1_class(snap)
        if cls_of[m] not in ALLOWED_CLASSES:
            continue
        cr, sy = snap.get("creator"), snap.get("symbol")
        if cr:
            union(node, "c:" + str(cr))
        if sy and str(sy).strip():
            union(node, "s:" + str(sy).strip().upper())
        top = snap.top_buyers("w120", exclude_agent=True) or ()
        for w in sorted(top, key=lambda w: (-float(w[1]), str(w[0])))[:CLUSTER_TOP_K]:
            union(node, "w:" + str(w[0]))
    return pd.DataFrame({"mint": ds.mints, "cls": [cls_of[m] for m in ds.mints],
                         "cluster": [find("m:" + m) for m in ds.mints]}, columns=["mint", "cls", "cluster"])


def clusters_for(ds: C.Dataset) -> dict[str, str]:
    """mint -> operator-cluster id (see :func:`cluster_table`)."""
    t = cluster_table(ds)
    return dict(zip(t["mint"], t["cluster"]))


def rug_hits(ds: C.Dataset, trades: pd.DataFrame) -> np.ndarray:
    """LABEL per trade: a > 50 % one-minute drop between the fill bar and the exit bar (read after the exit)."""
    out = np.zeros(len(trades), bool)
    for i, r in enumerate(trades.itertuples(index=False)):
        cd = ds.coin(r.mint)
        j0, j1 = cd.bar_of(r.t_in), min(cd.bar_of(r.t_out), C.N_BARS - 1)
        later = ds.asof(r.mint, cd.bar_start(min(j1 + 1, C.N_BARS)) + C.DECISION_LAG_S)
        out[i] = _rug_in(later.bars, j0, j1)
    return out


# =========================================================================== evaluation


def _empty_result_frame() -> pd.DataFrame:
    return C._frame([])


def _cluster_stats(t: pd.DataFrame, clusters: Mapping[str, str], B: int) -> dict:
    if not len(t):
        return {"n_clusters": 0, "ci90_cluster": None, "largest_cluster": None, "mean_without_largest": None}
    cl = t["mint"].map(clusters).fillna(t["mint"]).to_numpy(object)
    r = t["ret_net"].to_numpy(float)
    vc = pd.Series(cl).value_counts()
    prof = pd.Series(r).groupby(cl).sum()
    big = sorted(vc.index, key=lambda c: (-int(vc[c]), -float(prof[c]), str(c)))[0]
    rest = r[cl != big]
    return {"n_clusters": int(len(vc)), "ci90_cluster": C.coin_bootstrap_ci(r, cl, 0.90, B),
            "largest_cluster": {"id": str(big), "trades": int(vc[big]), "share_of_trades": float(vc[big] / len(r))},
            "mean_without_largest": float(rest.mean()) if len(rest) else None}


def evaluate(res: C.Result, ds: C.Dataset, clusters: Mapping[str, str], *, B: int, hide: bool,
             n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, classes, exit reasons) -- never returns."""
    t = res.trades
    rugs = rug_hits(ds, t) if (len(t) and not hide) else np.zeros(0, bool)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_class_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "reasons": t["reason"].value_counts().to_dict() if len(t) else {}, "n_placebo": int(len(res.placebo)),
            "n_clusters": int(pd.Series(t["mint"].map(clusters)).nunique()) if len(t) else 0,
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:     # rug hits are an outcome label: hidden like returns
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["rug_hits"] = int(rugs.sum())
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "top_coin_share",
                                        "top3_coin_share", "mean_without_top2", "halves", "mean_hold_min",
                                        "deflated_sharpe")})
    base["rug_rate"] = float(rugs.mean()) if len(t) else None
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["clusters"] = _cluster_stats(t, clusters, B)
    base["by_class"] = {c: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for c, g in t.groupby("tag")} \
        if len(t) else {}
    return base


def m1_extras(ev_cand: Mapping[str, Any], ev_twin: Mapping[str, Any] | None) -> list[dict]:
    """PLAN 4.5 pass items beyond common.verdict_entry: power (>= 60 trades, >= 3 clusters), the cluster-bootstrap
    90 % CI above 0, positive without the largest cluster, rug rate < half of the no-precursor twin's."""
    cl = ev_cand.get("clusters") or {}
    out = [{"id": "M1.1", "name": "power: >= 60 trades from >= 3 operator clusters",
            "pass": bool(ev_cand["n"] >= PASS_MIN_TRADES and ev_cand["n_clusters"] >= PASS_MIN_CLUSTERS),
            "value": {"n": ev_cand["n"], "clusters": ev_cand["n_clusters"]}}]
    ci = cl.get("ci90_cluster")
    out.append({"id": "M1.2", "name": "90% CI lower bound > 0 resampling operator clusters",
                "pass": None if not ci else bool(ci[0] > 0), "value": ci})
    mw = cl.get("mean_without_largest")
    out.append({"id": "M1.3", "name": "mean > 0 without the largest cluster", "pass": None if mw is None else bool(mw > 0),
                "value": mw})
    rc, rt = ev_cand.get("rug_rate"), (ev_twin or {}).get("rug_rate")
    if rc is None or rt is None:
        p = None
    elif rt == 0:
        p = None                    # no rug in the twin's holds: the criterion is vacuous (non-blocking)
    else:
        p = bool(rc < 0.5 * rt)
    out.append({"id": "M1.4", "name": "rug-hit rate < 1/2 of the no-precursor twin", "pass": p,
                "value": {"candidate": rc, "twin": rt}, "blocking_when_none": False})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 (from common.verdict_entry) + the M1 extras. Item 9 (FINAL mean > 0) is judged in the
    overall verdict once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    if not crit.get(1) or extras[0]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras[1:]):
        return "FAIL"
    if any(v is None for v in rest) or any(e["pass"] is None and e.get("blocking_when_none", True)
                                           for e in extras[1:]):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """Shortlist rule (PREREG 7): the candidate exit set is fixed (rhythm+prec); m* is chosen on TRAIN; the shortlist
    is the PAIR (m*, rhythm) + (m*, rhythm+prec) so VAL / TEST can also measure the precursor exit's rug criterion."""
    rows = []
    for m in M_GRID:
        e = evals[config_key(make_params(m, CANDIDATE_EXIT))]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_clusters"] >= TRAIN_MIN_CLUSTERS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0)
        ci = e.get("ci90")
        rows.append({"m": m, "powered": powered, "qualifies": bool(good), "n": e["n"], "clusters": e["n_clusters"],
                     "mean": e.get("mean"), "ci90_lo": ci[0] if ci else None, "placebo_diff": pc})
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-r["ci90_lo"], -r["mean"], -r["m"]))[0]
        sl = [make_params(best["m"], TWIN_EXIT), make_params(best["m"], CANDIDATE_EXIT)]
        return {"verdict": "SHORTLISTED", "m_star": best["m"], "rows": rows, "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered candidate failed the mean / top-2 / matched-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no candidate reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_CLUSTERS} operator clusters "
               f"(best: {max(r['n'] for r in rows)} trades, {max(r['clusters'] for r in rows)} clusters)")
    return {"verdict": v, "reason": why, "rows": rows, "shortlist": [], "shortlist_hashes": []}


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
    """PREREG 8: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = (test_doc.get("verdict") or {})
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: M1 failed TEST, CONFIRM not spent"


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def data_gates(flow: Path | None = None) -> tuple[bool, list[str]]:
    """PLAN 8 rule 1 (data first): V1 labels, V2 reserve chain >= 99 %, V3 cross-source >= 95 %, V4 ordering."""
    v = _read_json((flow or C.flow_dir()) / "validation.json")
    if v is None:
        return False, ["FLOW/validation.json missing: run research/flow/validate.py first"]
    bad = []
    try:
        if not v["V1"].get("pass"):
            bad.append("V1 labels failed")
        if v["V2"]["chain_ok"] / max(v["V2"]["transitions"], 1) < 0.99:
            bad.append("V2 reserve chain < 99 %")
        if v["V3"]["both"] / max(v["V3"]["coin_windows"], 1) < 0.95:
            bad.append("V3 cross-source < 95 %")
        if not v["V4"].get("pass"):
            bad.append("V4 ordering failed")
    except (KeyError, TypeError) as e:
        bad.append(f"validation.json unreadable: {e!r}")
    return not bad, bad


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
    ex = cov.get("excluded") or {}
    miss = int(ex.get("b2_window_incomplete", 0)) + int(ex.get("no_b2_row", 0))
    trad = int(cov.get("tradeable") or 0)
    if trad and miss / trad > 0.05:
        notes.append(f"{miss}/{trad} tradeable coins lack a complete B2 window")
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)] the stage runs. TEST / CONFIRM / FINAL log the twin as ``M1-twin`` because
    common allows one run per (hypothesis, split) there."""
    if stage in ("debug", "train"):
        return [(config_key(p), HYP, p) for p in GRID]
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        return []
    by_exit = {c["exit"]: c for c in sl["configs"]}
    cand, twin = by_exit.get(CANDIDATE_EXIT), by_exit.get(TWIN_EXIT)
    if stage == "val":
        return [("twin", HYP, twin), ("candidate", HYP, cand)]
    return [("candidate", HYP, cand), ("twin", HYP_TWIN, twin)]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`M1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise M1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise M1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise M1Refused("PREREG.md changed after the first official TRAIN run; record changes in M1/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = data_gates(flow)
    if not ok:
        raise M1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock)}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise M1Refused("TRAIN already ran on complete data (M1/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise M1Refused("no TRAIN result (M1/train.json): run --stage train first")
    if train.get("provisional"):
        raise M1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_MODEL_CHECK":
        raise M1Refused("M1 is dead: the model check failed on TRAIN (PLAN 8 stop rule 5)")
    if tv != "SHORTLISTED":
        raise M1Refused(f"TRAIN decision {tv}: M1 stopped before VAL")
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        raise M1Refused("no VAL shortlist for M1 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise M1Refused("the M1 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise M1Refused("VAL already ran (M1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise M1Refused("no VAL result (M1/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise M1Refused(f"VAL decision {vv}: M1 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise M1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok, why = confirm_allowed(test)
        if not ok:
            raise M1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise M1Refused(f"{stage.upper()} already ran (M1/{stage}.json exists): one run per hypothesis")
    for h in (HYP, HYP_TWIN):
        if any(r.get("hypothesis") == h and r.get("split") == split and not r.get("debug")
               for r in _runs(ledger_path)):
            raise M1Refused(f"{h} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise M1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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
    f = flow or C.flow_dir()
    g, c, b = (C._read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    census = census if census is not None else C.Census.load()
    if split == "final":
        return {s: C.Dataset.from_frames(s, g, c, b, census=census, guard=False).coverage for s in C.FINAL_SPLITS}
    return C.Dataset.from_frames(split, g, c, b, census=census, guard=False).coverage


def _span_days(ds: C.Dataset) -> float:
    c = ds.coins["created_for_split"] if len(ds) else pd.Series(dtype=float)
    if ds.split in C.SPLIT_BOUNDS and ds.coverage.get("complete"):
        lo, hi = C.SPLIT_BOUNDS[ds.split]
        return (hi - lo) / 86400.0
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9) if len(c) else float("nan")


def _event_counts(ds: C.Dataset) -> dict:
    """Counts only (no prices, no returns): how often the detector and each entry condition fire."""
    n_cls: dict[str, int] = {}
    fire_coins, alive_coins, entry_ok = set(), set(), {m: set() for m in M_GRID}
    for m in ds.mints:
        cd = ds.coin(m)
        snap0 = ds.asof(m, _grid_time(cd, cd.g + AGE_MIN_S + 60))
        cls = m1_class(snap0)
        n_cls[str(cls)] = n_cls.get(str(cls), 0) + 1
        if cls not in ALLOWED_CLASSES:
            continue
        for a in range(int(AGE_MIN_S // 60), int(AGE_MAX_S // 60) + 1):
            snap = ds.asof(m, _grid_time(cd, cd.g + 60 * a))
            mb = mech_bar(snap)
            if mb["fires"]:
                fire_coins.add(m)
                if mb["bid_alive"] and mb["mech_age_min"] >= MECH_AGE_MIN:
                    alive_coins.add(m)
                    for mm in M_GRID:
                        if m not in entry_ok[mm] and entry_decision(snap, {"m": mm}, cls)[0]:
                            entry_ok[mm].add(m)
    return {"coins": len(ds), "class_counts": n_cls, "coins_detector_fires": len(fire_coins),
            "coins_bid_alive_age10": len(alive_coins), "coins_entry_condition": {f"m{k:g}": len(v)
                                                                               for k, v in entry_ok.items()}}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write M1/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "m1_debug_trials.json"   # debug means never reach the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise M1Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise M1Refused("no configs to run (shortlist missing or malformed)")
    if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
        try:
            for _, h, p in configs:
                C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
        except C.SplitLocked as e:
            raise M1Refused(str(e)) from e
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
    ctab = cluster_table(ds)
    clusters = dict(zip(ctab["mint"], ctab["cluster"]))
    allowed = ctab[ctab["cls"].isin(ALLOWED_CLASSES)]
    doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                           "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                           "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                           "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds),
                           "allowed_coins": {str(k): int(v) for k, v in allowed["cls"].value_counts().items()},
                           "clusters_allowed": int(allowed["cluster"].nunique()),
                           "clusters_operator": int(allowed.loc[allowed["cls"] == "OPERATOR", "cluster"].nunique())}
    # ---- model check (TRAIN: before any P&L; debug: counts only)
    if stage in ("train", "debug"):
        obs = model_check_obs(ds)
        mc = model_check(obs, B=min(B, 2000), hide=debug, clusters=clusters)
        doc["model_check"] = mc
        mc_run = C.record_run(HYP_MC, MC_PARAMS, split, {"n": mc["n_obs"], "mean": None}, ledger_path, debug=debug)
        doc["model_check"]["trial"] = mc_run
        if debug:
            doc["event_counts"] = _event_counts(ds)
        elif mc["decision"] != "PASS":
            v = "KILLED_MODEL_CHECK" if mc["decision"] == "KILL" else "UNDERPOWERED_MODEL_CHECK"
            doc["decision"] = {"verdict": v, "shortlist_written": False,
                               "note": "PLAN 4.5: the model check precedes any P&L; the grid was not run"}
            return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
    # ---- the configs
    results: dict[str, C.Result] = {}
    for role, h, p in configs:
        results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, placebo=True, n_placebo=n_placebo,
                                   placebo_eligible=placebo_ok, stress=STRESS, declarations=DECL,
                                   ledger_path=ledger_path, shortlist_path=shortlist_path)
    n_tr = C.n_trials(ledger_path)
    evals = {role: evaluate(r, ds, clusters, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
    doc["configs"] = evals
    doc["n_trials_total"] = n_tr
    if not debug:
        _write_trades(out_dir, stage, provisional, results)
    if debug:
        days = doc["span_days"]
        doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
        doc["decision"] = {"verdict": "DEBUG", "note": "mechanics only; returns hidden"}
    elif stage == "train":
        dec = decide_train(evals)
        dec["shortlist_written"] = False
        if dec["verdict"] == "SHORTLISTED" and not provisional:
            C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                              note=f"{VERSION}: PREREG 7 pair rule, m* = {dec['m_star']:g}")
            dec["shortlist_written"] = True
        doc["decision"] = dec
    elif stage == "val":
        doc["decision"] = decide_val(evals["candidate"])
    elif stage in ("test", "confirm"):
        val_t = _read_trades(out_dir, "val", "candidate")
        val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
        base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
        extras = m1_extras(evals["candidate"], evals.get("twin"))
        doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "m1_extras": extras}
        doc["decision"] = doc["verdict"]
    elif stage == "final":
        t = results["candidate"].trades
        doc["decision"] = {"verdict": "REPORTED", "mean_positive": None if not len(t) else bool(t["ret_net"].mean() > 0),
                           "n": int(len(t)), "per_third": {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())}
                                                          for s, g in t.groupby("split")} if len(t) else {}}
    return _finish(doc, out_dir, stage, provisional, t0, ledger_path)


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"]), hypothesis=r.meta["hypothesis"])
              for role, r in results.items()]
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
    if tv == "KILLED_MODEL_CHECK":
        return "KILLED (model check failed: PLAN 8 stop rule 5)"
    if tv == "UNDERPOWERED_MODEL_CHECK":
        return "UNDERPOWERED (too few detector-firing coins for the model check on TRAIN)"
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
    L = [f"# M1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days; "
         f"allowed-class coins {doc.get('allowed_coins')} in {doc.get('clusters_allowed')} operator clusters "
         f"(OPERATOR coins: {doc.get('clusters_operator')} clusters).",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall M1 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    mc = doc.get("model_check")
    if mc:
        L += ["## Model check (PLAN 8 stop rule 5)", "",
              f"- Observations: {mc['n_obs']} from {mc['n_coins']} coins in {mc.get('n_clusters')} operator clusters "
              f"(need ≥ {MC_MIN_OBS} and ≥ {MC_MIN_COINS} coins); by class: {mc.get('by_class')}.",
              f"- Decision: **{mc['decision']}**."]
        if mc.get("fit"):
            f = mc["fit"]
            L.append(f"- OLS realized60 = {f['intercept']:+.4f} + {f['slope']:.3f} × drift_pred60; R² = {f['r2']:.4f} "
                     f"(need slope ≥ {MC_MIN_SLOPE}, R² ≥ {MC_MIN_R2}); slope 95% CI by coin "
                     f"{mc.get('slope_ci95_coin')}.")
        if mc.get("wallet_agreement"):
            L.append(f"- MECH-wallet agreement on B1 coins: {mc['wallet_agreement']}.")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (no returns)", "",
              f"- Classes at age 31 min: {ec['class_counts']}.",
              f"- Coins where MECH-bar fires at any age in [30, 120] min: {ec['coins_detector_fires']}; "
              f"with bid alive and mech_age ≥ 10: {ec['coins_bid_alive_age10']}; meeting every entry condition: "
              f"{ec['coins_entry_condition']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | classes | exit reasons | placebo trades | horizon exits | entries/day |",
                  "|---|---:|---:|---|---|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_class_n']} | {e['reasons']} | "
                         f"{e['n_placebo']} | {e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | clusters | mean | 90% CI coin | 90% CI cluster | w/o top 2 | "
                  "placebo diff | costs ×1.5 | rug rate |", "|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|"]
            for k, e in cf.items():
                cl = e.get("clusters") or {}
                pc = (e.get("placebo") or {}).get("mean_diff")
                rug = "n/a" if e.get("rug_rate") is None else f"{100 * e['rug_rate']:.1f}%"
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {e['n_clusters']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(cl.get('ci90_cluster'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct(pc)} | {_pct((e.get('stress') or {}).get('costs_x1.5'))} | {rug} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    if dec.get("rows"):
        for r in dec["rows"]:
            L.append(f"- m = {r['m']:g} (rhythm+prec): n {r['n']}, clusters {r['clusters']}, mean {_pct(r['mean'])}, "
                     f"90% CI low {_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, qualifies "
                     f"{r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']}"
                 + (f" (m* = {dec['m_star']:g}: both exit sets)" if dec.get("m_star") is not None else "") + ".")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("m1_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
    if dec.get("base"):
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
    ap = argparse.ArgumentParser(description="M1 mechanical-bid riding (PLAN 4.5): pre-registered stages; "
                                             "see research/lab2/M1/PREREG.md")
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
    except M1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
