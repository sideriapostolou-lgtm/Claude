"""Q8 (idea-mill queue q8, code CA1): conviction accumulators, i.e. repeat buyers who never sell.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Q8/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s): wallet trades through ``snap.trades``
(B1 rows with ts <= tau), static fields through ``snap.get`` at their legal time, bars through ``snap.bars`` /
``snap.alive()``. Nothing here reads a Dataset / CoinData column as a feature. B1 is mandatory: the rule is
wallet-level (who keeps buying, who never sells), so there is no bar-only proxy that runs as "Q8".

The rule
--------
* A = wallets with >= 3 PumpSwap buys in distinct clock minutes since g, >= 0.3 SOL bought, and no pool sell since g;
  never the AGENT, the completer, the creator, a pooled account, or a wallet that M1's MECH-wallet test flags at any
  minute cutoff since g. ``count_A`` = |A|; ``share_A`` = A's buy SOL / every non-AGENT buy SOL since g.
* Entry: the first decision at age 10-60 min with count_A >= K, share_A >= X and the coin alive.
* Exits: E1 = >= 2 members of the entry cohort sell in one completed minute; E2 = the last close <= 75 % of the highest
  close since the entry bar; both with a -30 % stop and the g + 118 min deadline (B1 ends at g + 120 min).
* Controls: the class-matched random placebo (common.backtest), and the SHUFFLED-WALLET control ``Q8-shuffle``:
  count_A recomputed after relabelling wallet ids with an independent random permutation in every clock minute
  (does repeat identity matter, or only the number of buys?).

CLI::

    python research/lab2/q8.py --debug                     # census TRAIN third: counts only (synthetic B1 tapes)
    python research/lab2/q8.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/q8.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/q8.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/q8.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/q8.py --stage final
    python research/lab2/q8.py --stage train --check       # prerequisites and B1 coverage only

Each stage writes ``Q8/<stage>.json`` and ``Q8/<stage>.md`` and REFUSES (exit code 2) while its prerequisites are
missing: no stage before B1 covers >= 95 % of the split's B1-universe coins, no VAL without the written shortlist,
TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8 data gates, PREREG frozen after the
first official TRAIN run.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import d1 as D1  # noqa: E402  (wallet hashing, pooled hashes, the coin-clustered difference CI, synthetic B1 tapes)
import g1 as G1  # noqa: E402  (G1 class at g + 140 s: reporting and placebo strata)
import m1 as M1  # noqa: E402  (stage helpers and the MECH-wallet test's constants and statistics)
import s1 as S1  # noqa: E402  (the B1 universe mask, = b1_select.py's selection)

VERSION = "q8-v1"
OUT_DIR = HERE / "Q8"
HYP, HYP_SHUF = "Q8", "Q8-shuffle"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-7)
LAMPORTS = 1e9
GRAD_DELAY_MIN_S = 5.0          # B1 universe: graduated > 5 s after creation (slow, non-factory)
B1_HORIZON_S = 7200             # B1 holds [c, g + 120 min)
B1_MIN_COVERAGE = 0.95          # S1 / D1's minimum share of the split's B1-universe coins with B1 rows
# A (conviction accumulators)
MIN_BUY_MINUTES = 3             # >= 3 pool buys in distinct clock minutes since g
MIN_BUY_SOL = 0.3               # >= 0.3 SOL bought since g
# M1's MECH-wallet test (m1.mech_wallets), evaluated at every minute cutoff since g
MECH_WINDOW_S = 1800.0
MECH_RET_S = 60.0
# entry / exits
ENTRY_AGE_MIN_S, ENTRY_AGE_MAX_S = 600.0, 3600.0   # decision age t - g in [10, 60] min
STOP_PCT = 0.30
EXIT_BY_AGE_S = 118 * 60.0      # QUEUE shared rule 2: g + 118 min for specs reading B1
TRAIL_CLOSE = 0.25              # E2: last close <= 75 % of the highest close since the entry bar
COHORT_MIN_SELLERS = 2          # E1: >= 2 cohort members sell in one completed minute
K_GRID = (3, 5)
X_GRID = (0.0, 0.2)
EXIT_GRID = ("E1", "E2")
SHUFFLE_SEED = 0
CFG = C.FillConfig(exit_delay_bars=1)            # QUEUE shared rule 2: worst fills, mechanical exits one bar later
STRESS = {"costs_x1.5": CFG.stressed(1.5)}
N_PLACEBO = 20
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 30, 20
SHUFFLE_MIN_TRADES = 10          # fewer shuffled-control trades: the identity criterion is vacuous
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"

FIXED = {
    "version": VERSION, "universe": "B1 (s1.universe_mask) with B1 rows", "min_buy_minutes": MIN_BUY_MINUTES,
    "min_buy_sol": MIN_BUY_SOL, "no_sells_since_g": True,
    "excluded": ["AGENT", "completer", "creator", "pooled", "MECH-wallet (m1, any minute cutoff since g)"],
    "mech": {"window_s": MECH_WINDOW_S, "min_buys": M1.MW_MIN_BUYS, "max_sell_frac": M1.MW_MAX_SELL_FRAC,
             "max_gap_cv": M1.MW_MAX_GAP_CV, "max_size_cv": M1.MW_MAX_SIZE_CV, "spearman_max": M1.SPEARMAN_MAX,
             "ret_before_s": MECH_RET_S},
    "entry_age_s": [ENTRY_AGE_MIN_S, ENTRY_AGE_MAX_S], "alive": "common.AsOf.alive() defaults",
    "stop_pct": STOP_PCT, "exit_by_age_s": EXIT_BY_AGE_S, "trail_close": TRAIL_CLOSE,
    "cohort_min_sellers": COHORT_MIN_SELLERS, "size_usd": CFG.size_usd,
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits",
    "placebo": "B1 universe with B1 rows, alive, G1 class at g + 140 s",
}


def make_params(K: int, X: float, exit_set: str) -> dict:
    if exit_set not in EXIT_GRID:
        raise ValueError(f"exit set {exit_set!r} not in {EXIT_GRID}")
    return {**FIXED, "K": int(K), "X": float(X), "exit": exit_set}


def make_shuffle_params(K: int, X: float, seed: int = SHUFFLE_SEED) -> dict:
    return {**FIXED, "K": int(K), "X": float(X), "exit": "E2", "shuffle": "per-minute wallet permutation",
            "shuffle_seed": int(seed)}


GRID = [make_params(k, x, e) for k in K_GRID for x in X_GRID for e in EXIT_GRID]
SHUFFLE_GRID = [make_shuffle_params(k, x) for k in K_GRID for x in X_GRID]
EXITS = C.ExitSpec(stop_pct=STOP_PCT, exit_by_age_s=EXIT_BY_AGE_S)
DECL = {"uses_organic_flow": True, "organic_excludes": ["AGENT", "BOT", "WASH", "DUST", "MECH"],
        "uses_wallet_reputation": False, "uses_truncated_windows": False, "uses_current_state_fields": False,
        "notes": ["BOT and WASH excluded by construction: an A member has no pool sell since g",
                  "DUST is absent from B1 (trades < 0.01 SOL dropped at collection)",
                  "A is an in-coin flow feature of the coin's own trades up to tau, not a cross-coin reputation",
                  "minute-bar worst fills until X1 exists"]}


class Q8Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing."""


def config_key(p: Mapping[str, Any]) -> str:
    head = "shuffle|" if p.get("shuffle_seed") is not None else ""
    tail = "" if head else f"|{p['exit']}"
    return f"{head}K{p['K']}|X{p['X']:g}{tail}"


# =========================================================================== universe and exclusions (AsOf only)


def in_universe(snap: C.AsOf) -> tuple[bool, str]:
    """B1 universe (s1.universe_mask / b1_select.py) through AsOf, plus B1 rows for this coin."""
    if snap.get("curve_partial") is not False:
        return False, "creation_not_scanned"
    if not snap.get("created_exact"):
        return False, "creation_inexact"
    gd = snap.get("grad_delay_s")
    if gd is None or gd <= GRAD_DELAY_MIN_S:
        return False, "instant_or_unknown_grad_delay"
    if snap.trades is None:
        return False, "no_b1"
    return True, ""


def static_exclusions(snap: C.AsOf, tau: float) -> dict[str, int | None]:
    """B1 wallet ids of the AGENT (once known at ``tau``), the completer and the creator (None = unknown)."""
    agent = None
    if snap.agent_detected:
        ka = snap.get("agent_known_at")
        if ka is not None and ka <= tau:
            agent = D1.wallet_h(snap.get("agent_wallet"))
    return {"agent": agent, "completer": D1.wallet_h(snap.get("completer")),
            "creator": D1.wallet_h(snap.get("creator"))}


# =========================================================================== B1 pool rows and the MECH test


def _rows(snap: C.AsOf, tau: float) -> dict[str, np.ndarray] | None:
    """PumpSwap rows of the trade prefix with g <= ts <= tau, in chain order (None without B1)."""
    tr = snap.trades
    if tr is None:
        return None
    ts = tr["ts"].to_numpy(np.int64)
    i = np.flatnonzero((tr["venue"].to_numpy(np.int64) == 1) & (ts >= snap.g) & (ts <= tau))
    y0 = tr["y0"].to_numpy(np.float64)[i]
    virt = tr["virt_ksol"].to_numpy(np.float64)[i] if "virt_ksol" in tr else np.zeros(len(i))
    return {"ts": ts[i], "w": tr["wallet_h"].to_numpy(np.uint64)[i], "buy": tr["is_buy"].to_numpy().astype(bool)[i],
            "sol": tr["usol"].to_numpy(np.float64)[i] / LAMPORTS,
            # pre-trade price on X = x + v, exactly as m1.mech_wallets computes it
            "price": (tr["x0"].to_numpy(np.float64)[i] + np.nan_to_num(virt) * 1000.0) / np.maximum(y0, 1.0),
            "pooled": tr["pooled"].to_numpy().astype(bool)[i] if "pooled" in tr else np.zeros(len(i), bool)}


def cutoffs_since(g: float, tau: float) -> np.ndarray:
    """Minute boundaries c with g < c <= tau (every decision cutoff so far)."""
    m0 = int(g) // 60 * 60
    return np.arange(m0 + 60, int(math.floor(tau)) + 1, 60, dtype=np.int64)


def mech_flags(ts: np.ndarray, code: np.ndarray, buy: np.ndarray, sol: np.ndarray, price: np.ndarray,
               cand: Iterable[int], cutoffs: np.ndarray) -> set[int]:
    """Codes in ``cand`` that M1's MECH-wallet test (m1.mech_wallets, PLAN 4.5) flags at ANY cutoff in ``cutoffs``:
    over pool rows in (c - 30 min, c], >= 6 buys, sells <= 10 % of buy SOL, CV of buy gaps < 0.25, CV of buy sizes
    < 0.5, |Spearman(size, price change over the 60 s before the buy)| < 0.3. Rows are the pool prefix in chain order;
    at cutoff c only rows with ts <= c count (the return before a buy uses earlier rows only)."""
    cand = np.asarray(sorted(set(int(c) for c in cand)), np.int64)
    if not len(cand) or not len(cutoffs) or not len(ts):
        return set()
    tsf = ts.astype(np.float64)
    i60 = np.searchsorted(tsf, tsf - MECH_RET_S, side="left")
    ret = price / price[i60] - 1.0
    order = np.argsort(code, kind="stable")              # chain order kept inside each wallet
    cs = code[order]
    lo_w, hi_w = np.searchsorted(cs, cand, "left"), np.searchsorted(cs, cand, "right")
    cf = cutoffs.astype(np.float64)
    out: set[int] = set()
    for c, a, b in zip(cand.tolist(), lo_w.tolist(), hi_w.tolist()):
        rows = order[a:b]
        rb, rs = rows[buy[rows]], rows[~buy[rows]]
        if len(rb) < M1.MW_MIN_BUYS:
            continue
        bts, bsz, bret = tsf[rb], sol[rb], ret[rb]
        sts = tsf[rs]
        scum = np.concatenate([[0.0], np.cumsum(sol[rs])])
        lo, hi = np.searchsorted(bts, cf - MECH_WINDOW_S, "right"), np.searchsorted(bts, cf, "right")
        slo, shi = np.searchsorted(sts, cf - MECH_WINDOW_S, "right"), np.searchsorted(sts, cf, "right")
        ok = (hi - lo) >= M1.MW_MIN_BUYS
        for l, h, sl, sh in sorted(set(zip(lo[ok].tolist(), hi[ok].tolist(), slo[ok].tolist(), shi[ok].tolist()))):
            s = bsz[l:h]
            if scum[sh] - scum[sl] > M1.MW_MAX_SELL_FRAC * float(s.sum()):
                continue
            if M1._cv(np.diff(bts[l:h])) >= M1.MW_MAX_GAP_CV or M1._cv(s) >= M1.MW_MAX_SIZE_CV:
                continue
            if abs(M1.spearman(s, bret[l:h])) >= M1.SPEARMAN_MAX:
                continue
            out.add(int(c))
            break
    return out


# =========================================================================== features (AsOf only)


class _LRU(OrderedDict):
    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def get_or(self, key, fn):
        if key in self:
            self.move_to_end(key)
            return self[key]
        v = fn()
        self[key] = v
        if len(self) > self.cap:
            self.popitem(last=False)
        return v


_FEATS = _LRU(50_000)


def clear_cache() -> None:
    _FEATS.clear()


def _na(why: str, permanent: bool) -> dict:
    return {"ok": False, "why": why, "permanent": permanent, "count_A": None, "share_A": None, "cohort": ()}


def _fingerprint(r: Mapping[str, np.ndarray]) -> tuple:
    """Content of the rows the features use (datasets in the tests share mint names: never key by mint alone)."""
    return (len(r["ts"]), int(r["ts"].sum()), round(float(r["sol"].sum()), 9),
            int((r["w"] % np.uint64(1_000_003)).sum()), int(r["buy"].sum()), int(r["pooled"].sum()),
            round(float(np.nansum(np.log(np.maximum(r["price"], 1e-300)))), 6))


def _mint_key(mint: str) -> int:
    return int(hashlib.sha1(mint.encode()).hexdigest()[:8], 16)


def _a_mask(code: np.ndarray, minute: np.ndarray, buy: np.ndarray, sol: np.ndarray, W: int) -> np.ndarray:
    """Per code: >= 3 buys in distinct clock minutes, >= 0.3 SOL bought, no sell."""
    if W == 0:
        return np.zeros(0, bool)
    bc = code[buy]
    pairs = np.unique(bc.astype(np.int64) * (1 << 32) + minute[buy].astype(np.int64))
    dm = np.bincount((pairs >> 32).astype(np.int64), minlength=W)
    bsol = np.bincount(bc, weights=sol[buy], minlength=W)
    ns = np.bincount(code[~buy], minlength=W)
    return (dm >= MIN_BUY_MINUTES) & (bsol >= MIN_BUY_SOL - 1e-12) & (ns == 0)


def _compute(r: Mapping[str, np.ndarray], ex_static: tuple, agent: int | None, cutoffs: np.ndarray,
             shuffle_seed: int | None, mint: str) -> dict:
    ts, w, buy, sol, price = r["ts"], r["w"], r["buy"], r["sol"], r["price"]
    denom = float(sol[buy & (w != np.uint64(agent))].sum()) if agent is not None else float(sol[buy].sum())
    uw, code = np.unique(w, return_inverse=True)
    code = code.astype(np.int64)
    W = len(uw)
    ex = np.isin(uw, np.asarray([x for x in ex_static if x is not None], dtype=np.uint64))
    if r["pooled"].any():
        ex[np.unique(code[r["pooled"]])] = True
    minute = ts // 60
    pre = _a_mask(code, minute, buy, sol, W) & ~ex
    nb = np.bincount(code[buy], minlength=W)
    test = np.flatnonzero(((~ex) if shuffle_seed is not None else pre) & (nb >= M1.MW_MIN_BUYS))
    mech = mech_flags(ts, code, buy, sol, price, test, cutoffs)
    mech_mask = np.zeros(W, bool)
    if mech:
        mech_mask[list(mech)] = True
    out = {"ok": True, "why": "", "permanent": False, "n_rows": int(len(ts)), "n_wallets": W,
           "n_excluded": int(ex.sum()), "n_mech": int(mech_mask.sum()), "n_pre_mech": int(pre.sum()), "denom": denom}
    if shuffle_seed is None:
        A = pre & ~mech_mask
        a_sol = float(np.bincount(code[buy], weights=sol[buy], minlength=W)[A].sum()) if W else 0.0
        out.update(count_A=int(A.sum()), cohort=tuple(sorted(int(x) for x in uw[A])))
    else:
        elig = ~ex & ~mech_mask
        keep = elig[code]
        W2 = int(elig.sum())
        rank = np.cumsum(elig) - 1
        ec, em, eb, es = rank[code[keep]], minute[keep], buy[keep], sol[keep]
        new = np.empty_like(ec)
        mk = _mint_key(mint)
        um, inv = np.unique(em, return_inverse=True)
        order = np.argsort(inv, kind="stable")
        bounds = np.searchsorted(inv[order], np.arange(len(um) + 1))
        for i, mm in enumerate(um.tolist()):
            sel = order[bounds[i]:bounds[i + 1]]
            perm = np.random.default_rng([int(shuffle_seed), mk, int(mm)]).permutation(W2)
            new[sel] = perm[ec[sel]]
        A = _a_mask(new, em, eb, es, W2)
        a_sol = float(np.bincount(new[eb], weights=es[eb], minlength=W2)[A].sum()) if W2 else 0.0
        out.update(count_A=int(A.sum()), cohort=())
    out["share_A"] = (a_sol / denom) if denom > 0 else None
    return out


def ca_features(snap: C.AsOf, tau: float | None = None, shuffle_seed: int | None = None) -> dict:
    """count_A, share_A and the cohort A (B1 wallet ids) at ``tau`` (default ``snap.tau``; an earlier tau uses the
    snapshot's own prefix, so it never sees more than the snapshot). ``shuffle_seed`` = the shuffled-wallet control.
    ``ok`` False => do not trade (``permanent`` => skip the coin)."""
    tau = snap.tau if tau is None else min(float(tau), snap.tau)
    if snap.trades is None:
        return _na("no_b1", True)
    if tau >= snap.g + B1_HORIZON_S:
        return _na("beyond_b1_horizon", True)
    if tau < snap.g:
        return _na("before_graduation", False)
    r = _rows(snap, tau)
    st = static_exclusions(snap, tau)
    ex_static = (st["agent"], st["completer"], st["creator"]) + tuple(sorted(D1.pooled_hashes()))
    cut = cutoffs_since(snap.g, tau)
    key = (snap.mint, float(snap.g), float(tau), shuffle_seed, ex_static[:3], _fingerprint(r))
    return dict(_FEATS.get_or(key, lambda: _compute(r, ex_static, st["agent"], cut, shuffle_seed, snap.mint)))


def cohort_max_sellers(snap: C.AsOf, cohort: Iterable[int], tau_e: float) -> int:
    """Largest number of distinct cohort members with a pool sell in one COMPLETED clock minute after ``tau_e``."""
    coh = np.asarray(sorted(set(int(x) for x in cohort)), dtype=np.uint64)
    tr = snap.trades
    if tr is None or not len(coh):
        return 0
    cut = math.floor(snap.tau / 60.0) * 60.0          # minutes ending at or before tau
    ts = tr["ts"].to_numpy(np.int64)
    sel = ((tr["venue"].to_numpy(np.int64) == 1) & ~tr["is_buy"].to_numpy().astype(bool) & (ts > tau_e)
           & (ts < cut))
    if not sel.any():
        return 0
    w = tr["wallet_h"].to_numpy(np.uint64)[sel]
    mem = np.isin(w, coh)
    if not mem.any():
        return 0
    pairs = set(zip((ts[sel][mem] // 60).tolist(), w[mem].tolist()))
    per = pd.Series([p[0] for p in pairs]).value_counts()
    return int(per.max())


def close_trail_hit(snap: C.AsOf, t_in: float) -> bool:
    """E2: the last completed close <= (1 - 25 %) x the highest close since the entry fill bar (included)."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return False
    j_in = int((float(t_in) - float(bars.minute_ts[0])) // 60)
    if k - 1 < j_in:
        return False
    c = np.asarray(bars.c[max(j_in, 0):k], float)
    return bool(c[-1] <= (1.0 - TRAIL_CLOSE) * float(c.max()))


# =========================================================================== the strategy


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """E2: close trail. E1: cohort sells. Placebo positions carry no state: their cohort is recomputed from the
    placebo coin's own trades at the placebo's decision time, so they run the same rule. The stop and the deadline
    are mechanical (ExitSpec)."""
    if p["exit"] == "E2":
        return C.Exit("trail_close") if close_trail_hit(snap, pos.t_in) else None
    if snap.tau >= snap.g + B1_HORIZON_S:
        return None                                  # no B1 beyond g + 120 min (the deadline fires first)
    st = pos.state or {}
    tau_e = float(st.get("tau_e", pos.t_dec - C.DECISION_LAG_S))
    cohort = st.get("cohort")
    if cohort is None:
        f = ca_features(snap, tau=tau_e)
        cohort = f["cohort"] if f["ok"] else ()
    if cohort_max_sellers(snap, cohort, tau_e) >= COHORT_MIN_SELLERS:
        return C.Exit("cohort")
    return None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The Q8 strategy for common.backtest (one entry per coin)."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s < ENTRY_AGE_MIN_S:
        return None
    if snap.age_s > ENTRY_AGE_MAX_S:
        return C.SKIP
    ok, _ = in_universe(snap)
    if not ok:
        return C.SKIP
    if not snap.alive():
        return None
    f = ca_features(snap, shuffle_seed=p.get("shuffle_seed"))
    if not f["ok"]:
        return C.SKIP if f["permanent"] else None
    if f["count_A"] < p["K"] or f["share_A"] is None or f["share_A"] < p["X"]:
        return None
    return C.Enter(exits=EXITS, tag=p["exit"],
                   state={"cohort": f["cohort"], "tau_e": snap.tau, "count_A": f["count_A"], "share_A": f["share_A"]})


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe: B1 universe with B1 rows, alive."""
    return in_universe(snap)[0] and snap.alive()


def g1_class_map(ds: C.Dataset) -> dict[str, str]:
    """mint -> G1 class at g + 140 s (g1.classify on g1.g1_features read through AsOf; QUEUE shared rule 4)."""
    out = {}
    for m in ds.mints:
        f = G1.g1_features(ds.asof(m, ds.coin(m).g + G1.LABEL_T_S))
        out[m] = G1.classify(f)["g1_class"]
    return out


def make_strata(cmap: Mapping[str, str]) -> Callable[[C.AsOf], str | None]:
    def g1_class_at_g140(snap: C.AsOf) -> str | None:
        return cmap.get(snap.mint)
    return g1_class_at_g140


# =========================================================================== evaluation


def entry_feature_stats(ds: C.Dataset, trades: pd.DataFrame, shuffle_seed: int | None) -> dict:
    """count_A / share_A at each entry decision (features, not outcomes)."""
    if not len(trades):
        return {"count_A": None, "share_A": None}
    ca, sa = [], []
    for r in trades.itertuples(index=False):
        f = ca_features(ds.asof(r.mint, r.t_dec), shuffle_seed=shuffle_seed)
        ca.append(f["count_A"])
        sa.append(f["share_A"])
    q = lambda v: [float(x) for x in np.quantile([x for x in v if x is not None], [0.25, 0.5, 0.75])] \
        if any(x is not None for x in v) else None  # noqa: E731
    return {"count_A": q(ca), "share_A": q(sa)}


def evaluate(res: C.Result, ds: C.Dataset, cmap: Mapping[str, str], *, B: int, hide: bool,
             n_trials_total: int | None) -> dict:
    """Per-config report. Debug split: counts only (never returns or exit reasons)."""
    t = res.trades
    p = res.meta["params"]
    cls = t["mint"].map(cmap).fillna("NA") if len(t) else pd.Series(dtype=object)
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_class_n": cls.value_counts().to_dict() if len(t) else {}, "n_placebo": int(len(res.placebo)),
            "horizon_exits": int(cens.sum()),
            "entry_features": entry_feature_stats(ds, t, p.get("shuffle_seed")),
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_class"] = {str(c): {"n": int(len(g)), "mean": float(g["ret_net"].mean())}
                        for c, g in t.assign(_cls=cls.to_numpy()).groupby("_cls")} if len(t) else {}
    return base


def identity_diff(real_e2: pd.DataFrame, shuffled: pd.DataFrame, B: int) -> dict:
    """Entry-level identity test: Q8 (K, X, E2) minus Q8-shuffle (K, X), coin-clustered bootstrap (d1.diff_ci)."""
    d = D1.diff_ci(real_e2, shuffled, B=B)
    d["vacuous"] = d["n_b"] < SHUFFLE_MIN_TRADES
    return d


# =========================================================================== pre-registered decisions


def _ci_lo(e: Mapping[str, Any]) -> float:
    ci = e.get("ci90")
    return float(ci[0]) if ci else -math.inf


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 8 TRAIN shortlist rule: per entry definition (K, X), power (E2 config >= 30 trades from >= 20 coins),
    identity (E2 mean - shuffled mean > 0; vacuous with < 10 shuffled trades), a candidate exit (mean > 0, without the
    top 2 > 0, matched-control diff > 0; the higher 90 % CI lower bound). (K*, X*) = the best qualifier; shortlist =
    candidate + twin (other exit) for Q8, (K*, X*) for Q8-shuffle."""
    rows = []
    for K in K_GRID:
        for X in X_GRID:
            e = {ex: evals[config_key(make_params(K, X, ex))] for ex in EXIT_GRID}
            sh = evals[config_key(make_shuffle_params(K, X))]
            powered = e["E2"]["n"] >= TRAIN_MIN_TRADES and e["E2"]["n_coins"] >= TRAIN_MIN_COINS
            vac = sh["n"] < SHUFFLE_MIN_TRADES
            ident = None if (vac or e["E2"].get("mean") is None or sh.get("mean") is None) \
                else e["E2"]["mean"] - sh["mean"]
            ident_ok = True if vac else (ident is not None and ident > 0)
            exits = []
            for ex in EXIT_GRID:
                v = e[ex]
                pc = (v.get("placebo") or {}).get("mean_diff")
                good = (v.get("mean") is not None and v["mean"] > 0 and v.get("mean_without_top2") is not None
                        and v["mean_without_top2"] > 0 and pc is not None and pc > 0)
                exits.append({"exit": ex, "good": bool(good), "mean": v.get("mean"), "ci90_lo": _ci_lo(v),
                              "placebo_diff": pc})
            good = [x for x in exits if x["good"]]
            cand = sorted(good, key=lambda x: (-x["ci90_lo"], -x["mean"], 0 if x["exit"] == "E2" else 1))[0] \
                if good else None
            rows.append({"K": K, "X": X, "n": e["E2"]["n"], "n_coins": e["E2"]["n_coins"], "powered": powered,
                         "shuffle_n": sh["n"], "identity_diff": ident, "identity_vacuous": vac,
                         "identity_ok": ident_ok, "exits": exits, "candidate_exit": cand and cand["exit"],
                         "qualifies": bool(powered and ident_ok and cand is not None),
                         "rank_key": None if cand is None else [cand["ci90_lo"], cand["mean"]]})
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-r["rank_key"][0], -r["rank_key"][1], -r["K"], -r["X"]))[0]
        cex = best["candidate_exit"]
        tex = "E1" if cex == "E2" else "E2"
        cand, twin = make_params(best["K"], best["X"], cex), make_params(best["K"], best["X"], tex)
        shuf = make_shuffle_params(best["K"], best["X"])
        return {"verdict": "SHORTLISTED", "K": best["K"], "X": best["X"], "candidate_exit": cex, "rows": rows,
                "candidate": cand, "twin": twin, "shuffle": shuf,
                "shortlist_hashes": [C.params_hash(twin), C.params_hash(cand)],
                "shuffle_shortlist_hashes": [C.params_hash(shuf)]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered entry definition failed the identity, mean, top-2 or matched-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no entry definition reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max(r['n'] for r in rows)} trades, {max(r['n_coins'] for r in rows)} coins)")
    return {"verdict": v, "reason": why, "rows": rows}


def decide_val(ev_cand: Mapping[str, Any]) -> dict:
    """PREREG 8 VAL rule on the candidate (M1's rule, frozen here): UNDERPOWERED_VAL (n < 5), FAIL_VAL (mean <= 0 or
    without the top 2 <= 0), SELECTED_UNDERPOWERED (n < 15), SELECTED."""
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


def q8_extras(ev_real_e2: Mapping[str, Any], ev_shuffle: Mapping[str, Any]) -> list[dict]:
    """Q8.1 identity: (K*, X*, E2) mean minus the shuffled control's mean > 0; vacuous (non-blocking) when the
    shuffled control has < 10 trades."""
    vac = ev_shuffle["n"] < SHUFFLE_MIN_TRADES
    rm, sm = ev_real_e2.get("mean"), ev_shuffle.get("mean")
    diff = None if (rm is None or sm is None) else rm - sm
    return [{"id": "Q8.1", "name": "identity: real E2 entry beats the shuffled-wallet control",
             "pass": None if vac else (None if diff is None else bool(diff > 0)),
             "value": {"real_e2_mean": rm, "shuffle_mean": sm, "diff": diff, "shuffle_n": ev_shuffle["n"]},
             "blocking_when_none": not vac}]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 (common.verdict_entry) + Q8.1. Item 9 (FINAL mean > 0) is judged in the overall
    verdict once FINAL ran."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(
            e["pass"] is None and e.get("blocking_when_none", True) for e in extras):
        return "INCOMPLETE"
    return "PASS"


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 8: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Q8 failed TEST, CONFIRM not spent"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census VAL and TEST thirds; the TRAIN third was the debug third (reported apart)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": int(len(design)), "mean": float(design["ret_net"].mean()) if len(design) else None,
                            "note": "census TRAIN third: the debug third (PREREG 12), not judged"}}


# =========================================================================== data readiness (counts only)


def b1_coverage(split: str, flow: Path | None = None, ds: C.Dataset | None = None) -> dict:
    """Share of the split's B1-universe coins with B1 rows (counts only, no prices). From ``ds`` when given, else from
    the FLOW tables (common.coverage_dataset + the mint column of b1_trades.parquet)."""
    parts = C.FINAL_SPLITS if split == "final" else (split,)
    if ds is not None:
        co = ds.coins
        uni = list(co.loc[S1.universe_mask(co), "mint"]) if len(co) else []
        have = sum(1 for m in uni if ds.asof(m, ds.coin(m).g).trades is not None)
        any_b1 = any(ds.asof(m, ds.coin(m).g).trades is not None for m in ds.mints)
        src = "dataset"
    else:
        f = Path(flow or C.flow_dir())
        p = f / "b1_trades.parquet"
        any_b1 = p.exists()
        mints = set(pd.read_parquet(p, columns=["mint"])["mint"].unique()) if any_b1 else set()
        uni, have = [], 0
        for s in parts:
            co = C.coverage_dataset(s, f).coins
            u = list(co.loc[S1.universe_mask(co), "mint"]) if len(co) else []
            uni += u
            have += sum(1 for m in u if m in mints)
        src = str(p)
    n = len(uni)
    return {"split": split, "source": src, "b1_present": bool(any_b1), "universe": n, "with_b1": int(have),
            "frac": (have / n) if n else 0.0, "need": B1_MIN_COVERAGE}


def b1_problems(cov: Mapping[str, Any]) -> list[str]:
    if not cov["b1_present"]:
        return ["b1_trades.parquet does not exist / no B1 rows loaded (the B1 fetch, backfill phase P4b, has not run "
                "for this split: research/flow/run_b1.sh)"]
    if cov["universe"] == 0:
        return [f"no B1-universe coins in split {cov['split']!r}"]
    if cov["frac"] < B1_MIN_COVERAGE:
        return [f"B1 covers {cov['with_b1']}/{cov['universe']} B1-universe coins of {cov['split']!r} "
                f"({cov['frac']:.1%} < {B1_MIN_COVERAGE:.0%})"]
    return []


# =========================================================================== stage prerequisites


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return M1._read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def _family_looks(ledger_path: Path | None, split: str) -> list[str]:
    with C._ledger(ledger_path, write=False) as led:
        return C._family_looks(led, C.hypothesis_family(HYP), C.split_group(split))


def stage_configs(stage: str, out_dir: Path) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)]. TRAIN / debug: the 12 registered configs. Later stages: the candidate, the twin
    and the shuffled control written by TRAIN (their hashes are checked against the shortlist files)."""
    if stage in ("debug", "train"):
        return [(config_key(p), HYP, p) for p in GRID] + [(config_key(p), HYP_SHUF, p) for p in SHUFFLE_GRID]
    dec = (M1._read_json(Path(out_dir) / "train.json") or {}).get("decision") or {}
    if dec.get("verdict") != "SHORTLISTED":
        return []
    return [("candidate", HYP, dec["candidate"]), ("twin", HYP, dec["twin"]), ("shuffle", HYP_SHUF, dec["shuffle"])]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Q8Refused` when ``stage`` may not run (stage order, PREREG, data gates). B1 coverage and the B2
    coverage are data checks made by :func:`run_stage` before any data is read. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Q8Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Q8Refused(f"{prereg} missing: pre-register before any run")
    lock = M1._read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != M1._sha(prereg):
        raise Q8Refused("PREREG.md changed after the first official TRAIN run; record changes in Q8/AMENDMENTS.md as "
                        "a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Q8Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": M1._sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = M1._read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Q8Refused("TRAIN already ran on complete data (Q8/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        if (out_dir / "val.json").exists():
            raise Q8Refused("Q8 already ran on VAL: TRAIN is closed")
        return info
    if not train:
        raise Q8Refused("no TRAIN result (Q8/train.json): run --stage train first")
    if train.get("provisional"):
        raise Q8Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    dec = train.get("decision") or {}
    if dec.get("verdict") != "SHORTLISTED":
        raise Q8Refused(f"TRAIN decision {dec.get('verdict')}: Q8 stopped before VAL")
    for h, key in ((HYP, "shortlist_hashes"), (HYP_SHUF, "shuffle_shortlist_hashes")):
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Q8Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(dec.get(key, [])):
            raise Q8Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Q8Refused("VAL already ran (Q8/val.json exists): VAL is evaluated once")
        return info
    val = M1._read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise Q8Refused("no VAL result (Q8/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise Q8Refused(f"VAL decision {vv}: Q8 stopped; TEST is not spent")
    test = M1._read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Q8Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Q8Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Q8Refused(f"{stage.upper()} already ran (Q8/{stage}.json exists): one look per hypothesis family")
    prior = _family_looks(ledger_path, split)
    if prior:
        raise Q8Refused(f"Q8 already had its one {C.split_group(split)} look (trials ledger): {prior[0]}")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Q8Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    return info


# =========================================================================== stage runner


def debug_dataset(flow: Path | None = None, census: C.Census | None = None, seed: int = 0) -> tuple[C.Dataset, dict]:
    """The census TRAIN third with SYNTHETIC B1 tapes (d1.synth_b1, built through AsOf from the coins' real bars) on
    its B1-universe coins: B1 does not exist for it yet. Wallet flows are made up, so flow-condition counts say
    nothing about Q8's rate; the bar-based counts are real."""
    f = Path(flow or C.flow_dir())
    census = census if census is not None else C.Census.load()
    ds0 = C.load("final_train", flow=f, census=census)
    real = b1_coverage("final_train", ds=ds0)
    if not b1_problems(real):
        return ds0, {"b1_source": "real B1", **real}
    uni = list(ds0.coins.loc[S1.universe_mask(ds0.coins), "mint"]) if len(ds0) else []
    tr = D1.synth_b1(ds0, uni, seed=seed)
    g, c, b = (C._read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    ds = C.Dataset.from_frames("final_train", g, c, b, census=census, sol=ds0.sol, trades=tr, guard=False,
                               completeness=C.completeness_from_flow(f))
    ds.coverage["from_flow"] = True
    return ds, {"b1_source": "SYNTHETIC (d1.synth_b1: made-up wallets; flow-condition counts are meaningless)",
                "synthetic_coins": len(uni), "synthetic_rows": int(len(tr))}


def _event_counts(ds: C.Dataset, cmap: Mapping[str, str]) -> dict:
    """Counts only (no prices, no returns): the B1 universe, its G1 classes, and coins alive at some decision age in
    [10, 60] min (the ceiling on Q8 entries; bars are real even when the tapes are synthetic)."""
    reasons: dict[str, int] = {}
    alive_coins, cls_uni = 0, {}
    for m in ds.mints:
        cd = ds.coin(m)
        t0 = M1._grid_time(cd, cd.g + ENTRY_AGE_MIN_S + 60)
        ok, why = in_universe(ds.asof(m, t0))
        reasons[why or "in_universe"] = reasons.get(why or "in_universe", 0) + 1
        if not ok:
            continue
        cls_uni[cmap.get(m)] = cls_uni.get(cmap.get(m), 0) + 1
        for a in range(int(ENTRY_AGE_MIN_S // 60), int(ENTRY_AGE_MAX_S // 60) + 1):
            if ds.asof(m, M1._grid_time(cd, cd.g + 60 * a)).alive():
                alive_coins += 1
                break
    return {"coins": len(ds), "universe_reasons": reasons, "universe_by_g1_class": {str(k): v for k, v in cls_uni.items()},
            "universe_alive_10_60": alive_coins}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = N_PLACEBO, env: Mapping[str, str] | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Q8/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "q8_debug_trials.json"   # debug means never reach the real ledger
    b1 = None
    if not debug:
        b1 = b1_coverage(split, flow, ds)
        bp = b1_problems(b1)
        if bp:
            raise Q8Refused("B1 not ready (PREREG 2: no stage before B1 covers >= 95 % of the B1 universe): "
                            + "; ".join(bp))
    cov = ds.coverage if ds is not None else (None if debug else M1._coverage_counts(split, flow, census))
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = M1.coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Q8Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    if not debug:
        covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
        hard = [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
        if hard:
            raise Q8Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir)
    if not configs:
        raise Q8Refused("no configs to run (TRAIN decision or shortlist missing)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Q8Refused(str(e)) from e
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
        dbg_src = None
        if ds is None:
            if debug:
                ds, dbg_src = debug_dataset(flow, census)
            else:
                ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        clear_cache()
        cmap = g1_class_map(ds)
        strata = make_strata(cmap)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": ds.coverage if cov is None else cov, "b1_coverage": b1,
                               "n_coins": len(ds), "span_days": M1._span_days(ds),
                               "g1_classes": pd.Series(cmap).value_counts().to_dict() if cmap else {}}
        if debug:
            doc["b1_source"] = dbg_src or {"b1_source": "injected dataset"}
            doc["event_counts"] = _event_counts(ds, cmap)
        results: dict[str, C.Result] = {}
        for role, h, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, cfg=CFG, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok, placebo_strata=strata,
                                       stress=STRESS, declarations=DECL, ledger_path=ledger_path,
                                       shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, ds, cmap, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            doc["identity"] = {f"K{K}|X{X:g}": identity_diff(results[config_key(make_params(K, X, "E2"))].trades,
                                                            results[config_key(make_shuffle_params(K, X))].trades, B)
                               for K in K_GRID for X in X_GRID}
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, [dec["twin"], dec["candidate"]], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 8 TRAIN rule, K*={dec['K']} X*={dec['X']:g}, candidate "
                                       f"{dec['candidate_exit']} + twin")
                C.write_shortlist(HYP_SHUF, [dec["shuffle"]], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: shuffled-wallet control of (K*, X*)")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        else:
            real_e2 = "candidate" if results["candidate"].meta["params"]["exit"] == "E2" else "twin"
            doc["identity"] = identity_diff(results[real_e2].trades, results["shuffle"].trades, B)
            if stage == "val":
                doc["decision"] = decide_val(evals["candidate"])
            elif stage in ("test", "confirm"):
                val_t = _read_trades(out_dir, "val", "candidate")
                val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) \
                    if val_t is not None else None
                base = C.verdict_entry(results["candidate"], val=val_res, B=B)
                extras = q8_extras(evals[real_e2], evals["shuffle"])
                doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "q8_extras": extras}
                doc["decision"] = doc["verdict"]
            elif stage == "final":
                doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"q8 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate, twin, shuffle inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Q8Refused(str(e)) from e


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
    doc = M1._jsonable(doc)
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=False))
    (out_dir / f"{name}.md").write_text(render_md(doc))
    return doc


def overall_verdict(out_dir: Path, pending: Mapping[str, Any] | None = None) -> str:
    """The hypothesis-level status from every stage written so far (``pending`` = the stage being written)."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return M1._read_json(Path(out_dir) / f"{s}.json")

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


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    pct, ci = M1._pct, M1._ci
    L = [f"# Q8 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days; "
         f"G1 classes at g + 140 s: {doc.get('g1_classes')}.",
         f"- **B1:** {doc.get('b1_coverage') or doc.get('b1_source')}.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Q8 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden, the wallet tapes "
              "are synthetic, and no parameter was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (real bars; no returns)", "",
              f"- Universe reasons at g + 11 min: {ec['universe_reasons']}.",
              f"- B1-universe coins by G1 class: {ec['universe_by_g1_class']}.",
              f"- B1-universe coins alive at some decision age in [10, 60] min (entry ceiling): "
              f"{ec['universe_alive_10_60']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | by G1 class | count_A at entry (q25, q50, q75) | placebo trades | "
                  "horizon exits | entries/day |", "|---|---:|---:|---|---|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_class_n']} | "
                         f"{(e.get('entry_features') or {}).get('count_A')} | {e['n_placebo']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "costs ×1.5 | by G1 class |", "|---|---|---:|---:|---:|---|---|---:|---:|---:|---|"]
            for k, e in cf.items():
                bc = {c: f"{v['n']} @ {pct(v['mean'])}" for c, v in (e.get("by_class") or {}).items()}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {pct(e.get('mean'))} | "
                         f"{ci(e.get('ci90'))} | {ci(e.get('ci90_block'))} | {pct(e.get('mean_without_top2'))} | "
                         f"{pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{pct((e.get('stress') or {}).get('costs_x1.5'))} | {bc} |")
        L.append("")
    idt = doc.get("identity")
    if idt:
        L += ["## Identity: real E2 entry minus the shuffled-wallet control", ""]
        items = idt.items() if "diff" not in idt else [("K*, X*", idt)]
        for k, d in items:
            L.append(f"- {k}: diff {pct(d.get('diff'))}, 95% CI {ci(d.get('ci95'))}, n real {d.get('n_a')} / "
                     f"shuffled {d.get('n_b')}{' (vacuous: < 10 shuffled trades)' if d.get('vacuous') else ''}.")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- K = {r['K']}, X = {r['X']:g}: n {r['n']} from {r['n_coins']} coins, powered {r['powered']}, "
                 f"identity {pct(r['identity_diff'])}{' (vacuous)' if r['identity_vacuous'] else ''}, candidate exit "
                 f"{r['candidate_exit']}, qualifies {r['qualifies']}.")
    if dec.get("candidate"):
        L.append(f"- Shortlist: K* = {dec['K']}, X* = {dec['X']:g}, candidate {dec['candidate_exit']} + twin, "
                 f"written {dec.get('shortlist_written')}.")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("q8_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
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
    ap = argparse.ArgumentParser(description="Q8 conviction accumulators (idea-mill q8 / CA1): pre-registered "
                                             "stages; see research/lab2/Q8/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and B1 coverage, then exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial B2 data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=10_000, help="bootstrap draws")
    ap.add_argument("--n-placebo", type=int, default=N_PLACEBO)
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            out = check_prereqs(stage, rerun_reason=a.rerun_reason)
            if stage != "debug":
                out["b1_coverage"] = b1_coverage(STAGE_SPLIT[stage])
                out["b1_problems"] = b1_problems(out["b1_coverage"])
            print(json.dumps(M1._jsonable(out), indent=1))
            return 0 if not out.get("b1_problems") else 2
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B,
                        n_placebo=a.n_placebo)
    except (Q8Refused, C.SplitLocked) as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
