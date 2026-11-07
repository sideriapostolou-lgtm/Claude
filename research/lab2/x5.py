"""X5 (wave-2 sweep, designer x5): R1, a market regime gate -- switch a host on only when the whole market is hot.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X5/PREREG.md``.

Mechanism (PREREG 1)
--------------------
Every fresh graduate sells to the same pool of speculators. When the fresh-graduate market is hot (many graduations,
much SOL through fresh pools, most fresh coins alive at g + 30 min), a host's entries should do better than the same
host's entries in a cold market. X5 measures three market-wide signals on a 15-minute grid, compares each with its
own trailing 24 hours, and lets the host's FIRST entry signal through only in an ON regime:

* ``GR`` graduation rate: tradeable graduations per hour in the last 2 h (structure, known at g);
* ``AV`` aggregate post-graduation volume: SOL per hour traded in fresh pools at age >= 10 min in the last 2 h;
* ``SV`` survival share: share of the graduates whose g + 30 min fell in the last 2 h that were ``alive`` then.

ON iff S(s) >= the q-quantile of S at the 96 previous 15-minute points; OFF / UNKNOWN -> the coin is skipped.
Host: ``R0`` (g1.host_r0, PLAN 4.1 random entry into alive coins). The M1 host (m1.strategy at m = 1, rhythm+prec) was
dropped in review X5-M1HOST: it was M1's own candidate rule, so an X5 look at a sealed split was a second, unguarded look
at M1 (PREREG 4). M1's code never runs under X5; ``m1`` is imported for its Spearman helper only.
Prior (PREREG 1): weak. Wave 1 found the hourly ICC of returns ~0; the likely outcome is NO EDGE, at best a veto.

No lookahead
------------
* Host decisions are the hosts' own code, all through :class:`common.AsOf`.
* Every regime RECORD is another coin's fact read through :class:`common.AsOf` at its legal time and stamped with its
  known time kappa (g for a graduation; bar start + 60 s for a bar's volume; g + 1800 s for survival). A decision at
  cutoff tau uses the grid point s = floor(tau / 900) * 900 <= tau and only records with kappa <= s, never the traded
  coin's own records (PLAN 6.6 rule 1).
* Outcome records (AV, SV) come only from the stage's history splits (:data:`HISTORY_SPLITS`: earlier in time and
  already opened); structure (GR) from every graduate created before the end of the split being run (g1's registry
  rule: later splits never feed an earlier one). A point whose window the pool cannot fully cover is UNKNOWN.

CLI::

    python research/lab2/x5.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x5.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x5.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x5.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x5.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x5.py --stage final
    python research/lab2/x5.py --stage val --check             # prerequisites only

Each stage writes ``X5/<stage>.json`` and ``X5/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlist, no stage after a model-check KILL, TEST / CONFIRM / FINAL once each, never
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import g1  # noqa: E402  (the R0 host, verbatim)
import m1  # noqa: E402  (m1.spearman only: M1's strategy never runs under X5, review X5-M1HOST)

VERSION = "x5-v1"
OUT_DIR = HERE / "X5"
HYP, HYP_MC = "X5", "X5-modelcheck"
HOST_HYP = {"R0": "X5.host-R0"}             # the M1 arm was dropped (review X5-M1HOST, PREREG 4)
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
# PREREG 2.3: outcome records (AV, SV) come only from splits earlier in time and already opened at the stage
HISTORY_SPLITS = {"debug": ("final_train",), "train": ("train",), "val": ("train", "val"),
                  "test": ("train", "val", "test"), "confirm": ("confirm",),
                  "final": ("train", "val", "test", "final_train", "final_val", "final_test")}

# =========================================================================== pre-registered constants (PREREG 2-9)
SIGNALS = ("GR", "AV", "SV")
WINDOW_S = 7200.0            # N: every signal aggregates records with known time in (s - N, s]
STEP_S = 900                 # the regime grid (15 min); decision cutoff tau -> s = floor(tau / 900) * 900
BASE_N = 96                  # baseline: the 96 previous grid points (24 h)
SLACK_S = 6 * 3600.0         # a coin created before the pool start can graduate after it: skip the first 6 h
AV_MIN_AGE_S = 600.0         # AV counts bars starting at age >= 10 min (BOOST and the first-minute pumps excluded)
SV_AGE_S = 1800.0            # SV: alive at age 30 min
SV_MIN_RECORDS = 10          # SV is UNKNOWN with fewer records in the window
Q_BY_HOST = {"R0": (0.5, 0.8)}
HOST_ORDER = ("R0",)
LABEL_QS = (0.5, 0.8)        # every host trade is labelled at both cuts
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0)}
# model check (stop rule, PREREG 7)
MC_MIN_OBS = 200
MC_HORIZON_S = 3600.0
MC_B = 2000
# selection and verdict bars (PREREG 8)
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 60, 40
VETO_MIN_ARM, VETO_MIN_CONTRAST = 60, 0.05
EDGE_SHORTLIST_MAX, VETO_SHORTLIST_MAX = 2, 1
MAX_CENSORED = C.MAX_CENSORED_SHARE
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03          # PLAN 3.5 item 2
X5_MIN_BLOCKS = 6             # X5.2: ON trades in >= 6 distinct 6-hour blocks
CONTRAST_MIN_ARM = 10         # X5.1 needs >= 10 trades in each arm
CONTRAST_B = 2000
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED", "VETO_SELECTED")

R0_HOST = dict(g1.R0_PARAMS)
HOST_PARAMS = {"R0": R0_HOST}
FILL_DESC = "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits"

FIXED = {
    "version": VERSION, "window_s": WINDOW_S, "step_s": STEP_S, "baseline_n": BASE_N, "slack_s": SLACK_S,
    "av_min_age_s": AV_MIN_AGE_S, "sv_age_s": SV_AGE_S, "sv_min_records": SV_MIN_RECORDS, "direction": "hot = high",
    "gate": "ON iff S(s) >= q-quantile of the 96 previous points; filter on the host's first entry; OFF/UNKNOWN skip",
    "own_coin": "excluded from every window", "history_splits": {k: list(v) for k, v in HISTORY_SPLITS.items()},
    "gr_pool": "tradeable graduates created before the split's end (structure)", "fill": FILL_DESC,
    "placebo": "random alive coins at +-120 s whose regime state is known (ON or OFF, own coin removed) at the draw",
}


def make_params(host: str, signal: str, q: float) -> dict:
    if host not in HOST_ORDER or signal not in SIGNALS or float(q) not in Q_BY_HOST[host]:
        raise ValueError(f"({host}, {signal}, q={q}) is not in the pre-registered grid")
    return {**FIXED, "x5_host": host, "signal": signal, "q": float(q), "host_params": dict(HOST_PARAMS[host])}


def host_config(host: str) -> dict:
    """The ungated host baseline's params (its own params verbatim + the X5 fill)."""
    return {**HOST_PARAMS[host], "x5_version": VERSION, "x5_role": "host", "x5_host": host, "fill": FILL_DESC}


GRID = [make_params(h, s, q) for h in HOST_ORDER for s in SIGNALS for q in Q_BY_HOST[h]]
GRID_HASHES = frozenset(C.params_hash(p) for p in GRID)
assert len(GRID) == 6 and len(GRID) + len(HOST_ORDER) + 1 == 8       # PREREG 6: 8 trials in all
MC_PARAMS = {"version": VERSION, "test": "model_check", "label": "realized 60-min mid change at the R0 decision",
             "statistic": "Spearman(pct, label)", "rule": "PASS iff rho > 0 with >= 200 observations",
             "min_obs": MC_MIN_OBS, "signals": list(SIGNALS), "fixed": FIXED, "r0": R0_HOST}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class X5Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['x5_host']}|{p['signal']}|q{float(p['q']):g}"


def state_col(signal: str, q: float) -> str:
    return f"st_{signal}_q{float(q):g}"


# =========================================================================== hosts and the gate


def host_fn(host: str) -> Callable:
    """The host strategy (looked up at call time, so the host is always g1's current code)."""
    if host != "R0":
        raise ValueError(f"{host!r} is not an X5 host (PREREG 4; the M1 arm was dropped in review X5-M1HOST)")
    return g1.host_r0


def r0_eligible(snap: C.AsOf) -> bool:
    """R0's universe: alive (its own thresholds)."""
    return snap.alive(R0_HOST["alive_vol_usd_15m"], R0_HOST["alive_mcap_usd"])


def placebo_spec(host: str) -> dict:
    """PREREG 4: the host's placebo universe (R0: random alive coins)."""
    if host != "R0":
        raise ValueError(f"{host!r} is not an X5 host (PREREG 4)")
    return {"eligible": r0_eligible, "strata": None}


def placebo_eligible(regime: "Regime", p: Mapping[str, Any]) -> Callable[[C.AsOf], bool]:
    """PREREG 4: the host's placebo universe AND a known regime state at the draw's own cutoff (the drawn coin's records
    removed, exactly as for a trade). The gated rule never enters in an UNKNOWN regime, so the control is a random-STATE
    entry among the regimes the rule can see (review X5-PLACEBO-UNKNOWN), not a draw from the warm-up."""
    base, sig = placebo_spec(p["x5_host"])["eligible"], p["signal"]

    def ok(snap: C.AsOf) -> bool:
        return regime.values(sig, int(math.floor(float(snap.tau) / STEP_S)), snap.mint) is not None and base(snap)

    ok.__name__ = f"x5_placebo_known_{sig}"
    return ok


def make_strategy(regime: "Regime") -> Callable:
    """The gated rule: the host's own decisions; its FIRST Enter passes only in an ON regime (else SKIP)."""

    def x5_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        hfn, hp = host_fn(p["x5_host"]), p["host_params"]
        if pos is not None:
            return hfn(snap, hp, pos)                   # the host's exits, unchanged (placebos included)
        act = hfn(snap, hp, None)
        if not isinstance(act, C.Enter):
            return act
        if regime.state(p["signal"], p["q"], snap.tau, snap.mint)["state"] != "ON":
            return C.SKIP                               # OFF or UNKNOWN: fail closed, never this coin
        return C.Enter(exits=act.exits, tag=act.tag, state=act.state)

    return x5_strategy


# =========================================================================== the regime (cross-coin, causal)


class Records:
    """Records (known time kappa, value, mint) sorted by kappa, with prefix sums; per-mint copies for exclusion."""

    def __init__(self, kappa: Sequence[float], value: Sequence[float], mints: Sequence[str]) -> None:
        k = np.asarray(kappa, float)
        o = np.argsort(k, kind="stable")
        self.kappa = k[o]
        self.value = np.asarray(value, float)[o]
        self.cs = np.concatenate([[0.0], np.cumsum(self.value)])
        self.own: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        if len(k):
            df = pd.DataFrame({"m": np.asarray(mints, object)[o], "k": self.kappa, "v": self.value})
            for m, g in df.groupby("m", sort=False):
                self.own[str(m)] = (g["k"].to_numpy(float), np.concatenate([[0.0], np.cumsum(g["v"].to_numpy(float))]))

    def __len__(self) -> int:
        return len(self.kappa)

    @staticmethod
    def _win(kappa: np.ndarray, cs: np.ndarray, s: np.ndarray, width: float) -> tuple[np.ndarray, np.ndarray]:
        lo = np.searchsorted(kappa, s - width, side="right")
        hi = np.searchsorted(kappa, s, side="right")
        return cs[hi] - cs[lo], (hi - lo).astype(float)

    def window(self, s: np.ndarray, width: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(sum, count) of the records with kappa in (s - width, s] (default N), for every point of ``s``."""
        return self._win(self.kappa, self.cs, np.asarray(s, float), WINDOW_S if width is None else width)

    def own_window(self, mint: str, s: np.ndarray, width: float | None = None) -> tuple[np.ndarray, np.ndarray] | None:
        """The same sums over one coin's own records (None when it has none)."""
        o = self.own.get(str(mint))
        if o is None:
            return None
        return self._win(o[0], o[1], np.asarray(s, float), WINDOW_S if width is None else width)


def split_creation_bounds(split: str, census: C.Census) -> tuple[float, float]:
    """Creation-time range [lo, hi) of a split (the census thirds by the lab's bounds; FINAL open-ended)."""
    if split in C.SPLIT_BOUNDS:
        lo, hi = C.SPLIT_BOUNDS[split]
        return float(lo), float(hi)
    t_hi, v_hi = float(census.train_hi) + 1.0, float(census.val_hi) + 1.0
    return {"final_train": (float(C.FINAL_LO), t_hi), "final_val": (t_hi, v_hi), "final_test": (v_hi, math.inf),
            "final": (float(C.FINAL_LO), math.inf)}[split]


def history_bounds(stage: str, census: C.Census) -> tuple[float, float]:
    """[lo, hi) of the stage's history pool; the history splits are contiguous by construction (checked)."""
    b = sorted(split_creation_bounds(s, census) for s in HISTORY_SPLITS[stage])
    for (_, h0), (l1, _) in zip(b, b[1:]):
        if abs(h0 - l1) > 1.0:
            raise ValueError(f"history splits of {stage!r} are not contiguous: {b}")
    return b[0][0], b[-1][1]


@dataclass
class Regime:
    """S(signal) at every 15-minute grid point k0..k1 (s = k * 900), its coverage mask, and the records."""

    k0: int
    k1: int
    recs: dict[str, Records]
    sums: dict[str, np.ndarray]
    cnts: dict[str, np.ndarray]
    known: dict[str, np.ndarray]
    meta: dict = field(default_factory=dict)

    def points(self) -> np.ndarray:
        return np.arange(self.k0, self.k1 + 1, dtype=np.int64) * STEP_S

    @staticmethod
    def _signal(sig: str, sm: np.ndarray, cn: np.ndarray) -> np.ndarray:
        if sig == "GR":
            return cn * 3600.0 / WINDOW_S
        if sig == "AV":
            return sm * 3600.0 / WINDOW_S
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cn >= SV_MIN_RECORDS, sm / np.maximum(cn, 1.0), np.nan)

    def series(self, sig: str, mint: str | None = None) -> np.ndarray:
        """S at every grid point (NaN where unknown); ``mint`` removes that coin's records."""
        sm, cn = self.sums[sig].copy(), self.cnts[sig].copy()
        if mint is not None:
            own = self.recs[sig].own_window(mint, self.points().astype(float))
            if own is not None:
                sm, cn = sm - own[0], cn - own[1]
        v = self._signal(sig, sm, cn)
        return np.where(self.known[sig], v, np.nan)

    def values(self, sig: str, k: int, mint: str | None) -> np.ndarray | None:
        """S at grid points k - 96 .. k (the baseline and the current point), the coin's own records removed; None
        when any of them is unknown or outside the computed range."""
        lo = k - BASE_N
        if lo < self.k0 or k > self.k1:
            return None
        idx = np.arange(lo - self.k0, k - self.k0 + 1)
        if not bool(self.known[sig][idx].all()):
            return None
        sm, cn = self.sums[sig][idx].copy(), self.cnts[sig][idx].copy()
        if mint is not None:
            own = self.recs[sig].own_window(mint, (np.arange(lo, k + 1) * STEP_S).astype(float))
            if own is not None:
                sm, cn = sm - own[0], cn - own[1]
        v = self._signal(sig, sm, cn)
        return None if bool(np.isnan(v).any()) else v

    def state(self, sig: str, q: float, tau: float, mint: str | None) -> dict:
        """PREREG 3 at decision cutoff ``tau``: ON / OFF / UNKNOWN, the current S, the threshold and the percentile."""
        return self.states(sig, (q,), tau, mint)[float(q)]

    def states(self, sig: str, qs: Iterable[float], tau: float, mint: str | None) -> dict[float, dict]:
        k = int(math.floor(float(tau) / STEP_S))
        v = self.values(sig, k, mint)
        if v is None:
            return {float(q): {"state": "UNKNOWN", "S": None, "thr": None, "pct": None, "s": k * STEP_S}
                    for q in qs}
        cur, base = float(v[-1]), v[:-1]
        pct = float(((base < cur).sum() + 0.5 * (base == cur).sum()) / len(base))
        out = {}
        for q in qs:
            thr = float(np.quantile(base, float(q)))
            out[float(q)] = {"state": "ON" if cur >= thr else "OFF", "S": cur, "thr": thr, "pct": pct,
                             "s": k * STEP_S}
        return out


def _gr_records(graduates: pd.DataFrame, census: C.Census, hi: float, t_lo: float, t_hi: float) -> Records:
    """GR records: tradeable graduations (sol_quoted and not mayhem, read through AsOf at g) of every graduate created
    before ``hi`` (g1's registry rule), graduated in [t_lo, t_hi]."""
    g = C._normalize_graduates(graduates, census)
    g = g[(g["created_for_split"] < hi) & (g["g_ts"] >= t_lo) & (g["g_ts"] <= t_hi)]
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    ks, ms = [], []
    for r in g.to_dict("records"):
        cd = C._make_coin(r, empty, None, pooled)
        snap = C.AsOf(cd, cd.g + C.DECISION_LAG_S)            # tau = g: a graduate from now on
        if snap["sol_quoted"] and not snap["mayhem"]:
            ks.append(float(snap["g_ts"]))
            ms.append(cd.mint)
    return Records(ks, np.ones(len(ks)), ms)


def _outcome_records(history: Sequence[C.Dataset]) -> tuple[Records, Records, int]:
    """AV and SV records of the usable coins of the history datasets (each coin once), read through AsOf."""
    av_k, av_v, av_m, sv_k, sv_v, sv_m = [], [], [], [], [], []
    seen: set[str] = set()
    for hds in history:
        for m in hds.mints:
            if m in seen:
                continue
            seen.add(m)
            cd = hds.coin(m)
            s30 = C.AsOf(cd, cd.g + SV_AGE_S + C.DECISION_LAG_S, hds.sol)     # tau = g + 30 min
            sv_k.append(cd.g + SV_AGE_S)
            sv_v.append(1.0 if s30.alive() else 0.0)
            sv_m.append(m)
            b = C.AsOf(cd, cd.m0 + 60 * C.N_BARS + C.DECISION_LAG_S, hds.sol).bars   # every completed bar
            mt = np.asarray(b.minute_ts, float)
            vol = np.asarray(b.buy_sol, float) + np.asarray(b.sell_sol, float)
            sel = (mt >= cd.g + AV_MIN_AGE_S) & (vol > 0)
            av_k.extend((mt[sel] + 60.0).tolist())                          # known once the minute ended
            av_v.extend(vol[sel].tolist())
            av_m.extend([m] * int(sel.sum()))
    return Records(av_k, av_v, av_m), Records(sv_k, sv_v, sv_m), len(seen)


def _curve_ok(s: np.ndarray, curve_hours: frozenset | set) -> np.ndarray:
    """Every chain hour overlapping (s - N, s] is fully scanned (curve), so the graduation count is complete."""
    out = np.zeros(len(s), bool)
    for i, x in enumerate(s):
        h0, h1 = int((x - WINDOW_S) // 3600 * 3600), int(x // 3600 * 3600)
        out[i] = all(h in curve_hours for h in range(h0, h1 + 1, 3600))
    return out


def build_regime(stage: str, ds: C.Dataset, history: Sequence[C.Dataset], graduates: pd.DataFrame,
                 census: C.Census, curve_hours: Iterable[int] | None = None) -> Regime:
    """The stage's regime over the decision span of ``ds`` (+ the 24-h baseline), from the pools of PREREG 2.3."""
    g_all = ds.coins["g_ts"].to_numpy(float) if len(ds) else np.zeros(0)
    if not len(g_all):
        raise X5Refused("no usable coins: nothing to gate")
    k1 = int(math.floor((float(g_all.max()) + C.B2_HORIZON_S + 120.0) / STEP_S))
    k0 = int(math.floor(float(g_all.min()) / STEP_S)) - BASE_N - 1
    pts = np.arange(k0, k1 + 1, dtype=np.int64) * STEP_S
    s = pts.astype(float)
    hi_gr = split_creation_bounds(ds.split, census)[1]
    lo_h, hi_h = history_bounds(stage, census)
    recs = {"GR": _gr_records(graduates, census, hi_gr, float(pts[0]) - WINDOW_S - 60.0, float(pts[-1]))}
    recs["AV"], recs["SV"], n_hist = _outcome_records(history)
    if curve_hours is None:          # synthetic frames: an hour with any graduate is scanned (common's bars-only rule)
        curve_hours = set((graduates["g_ts"].to_numpy(np.int64) // 3600 * 3600).tolist())
    ch = frozenset(int(h) for h in curve_hours)
    known = {"GR": (s < hi_gr) & _curve_ok(s, ch),
             "AV": (s - WINDOW_S - C.B2_HORIZON_S >= lo_h + SLACK_S) & (s - AV_MIN_AGE_S < hi_h),
             "SV": (s - WINDOW_S - SV_AGE_S >= lo_h + SLACK_S) & (s - SV_AGE_S < hi_h)}
    sums, cnts = {}, {}
    for sig in SIGNALS:
        sums[sig], cnts[sig] = recs[sig].window(s)
    meta = {"stage": stage, "split": ds.split, "grid_utc": [C.utc_str(pts[0]), C.utc_str(pts[-1])],
            "gr_pool_created_before_utc": C.utc_str(hi_gr) if math.isfinite(hi_gr) else "open",
            "history_splits": list(HISTORY_SPLITS[stage]), "history_coins": n_hist,
            "history_created_utc": [C.utc_str(lo_h), C.utc_str(hi_h) if math.isfinite(hi_h) else "open"],
            "records": {sig: len(recs[sig]) for sig in SIGNALS},
            "known_points": {sig: int(known[sig].sum()) for sig in SIGNALS}, "points": int(len(pts)),
            "first_known_utc": {sig: (C.utc_str(pts[np.argmax(known[sig])]) if known[sig].any() else None)
                                for sig in SIGNALS}}
    return Regime(k0=k0, k1=k1, recs=recs, sums=sums, cnts=cnts, known=known, meta=meta)


def label_states(regime: Regime, trades: pd.DataFrame, qs: Iterable[float] = LABEL_QS) -> pd.DataFrame:
    """Host trades + one column per (signal, q): the regime state at the trade's decision (own coin removed)."""
    t = trades.copy()
    qs = tuple(float(q) for q in qs)
    cols: dict[str, list] = {state_col(sig, q): [] for sig in SIGNALS for q in qs}
    for r in t.itertuples(index=False):
        for sig in SIGNALS:
            st = regime.states(sig, qs, float(r.t_dec) - C.DECISION_LAG_S, r.mint)
            for q in qs:
                cols[state_col(sig, q)].append(st[q]["state"])
    for c, v in cols.items():
        t[c] = v if len(t) else pd.Series(dtype=object)
    return t


# =========================================================================== model check (stop rule, PREREG 7)


def _first_grid_at_or_after(cd: C.CoinData, t_min: float) -> float | None:
    for j in range(C.N_BARS):
        t = float(cd.bar_start(j + 1) + C.GRID_OFFSET_S)
        if t >= t_min:
            return t
    return None


def model_check_obs(ds: C.Dataset, regime: Regime, with_label: bool = True) -> pd.DataFrame:
    """One observation per coin: the R0 decision (first grid time >= g + the seeded target age) where the coin is
    alive; per signal its percentile (own coin removed) when known. LABEL = the realized 60-minute mid change, read
    through AsOf 60 minutes later (never a feature); not computed when ``with_label`` is False (debug)."""
    rows = []
    for m in ds.mints:
        cd = ds.coin(m)
        t = _first_grid_at_or_after(cd, cd.g + g1.r0_target_age_s(m, R0_HOST))
        if t is None:
            continue
        snap = ds.asof(m, t)
        if not r0_eligible(snap):
            continue
        row = {"mint": m, "t": t, "age_min": (t - cd.g) / 60.0}
        for sig in SIGNALS:
            row[f"pct_{sig}"] = regime.state(sig, 0.5, snap.tau, m)["pct"]
        if with_label:
            later = ds.asof(m, t + MC_HORIZON_S)
            row["realized60"] = later.price / snap.price - 1.0
        rows.append(row)
    cols = ["mint", "t", "age_min"] + [f"pct_{s}" for s in SIGNALS] + (["realized60"] if with_label else [])
    return pd.DataFrame(rows, columns=cols)


def _block_spearman_ci(x: np.ndarray, y: np.ndarray, blocks: np.ndarray, B: int, seed: int = 0):
    ub = np.unique(blocks)
    if len(ub) < 2:
        return None
    groups = [np.flatnonzero(blocks == b) for b in ub]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        drawn = [groups[i] for i in rng.integers(0, len(groups), len(groups))]      # blocks, then obs inside them
        idx = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in drawn])
        out.append(m1.spearman(x[idx], y[idx]))
    return float(np.quantile(out, 0.05)), float(np.quantile(out, 0.95))


def model_check(obs: pd.DataFrame, B: int = MC_B, hide: bool = False) -> dict:
    """Per signal: UNDERPOWERED (< 200 observations) / FAIL (rho <= 0) / PASS. ``hide``: counts only."""
    out: dict[str, Any] = {"n_coins_alive_at_r0_decision": int(len(obs)), "need_obs": MC_MIN_OBS, "signals": {}}
    for sig in SIGNALS:
        o = obs[obs[f"pct_{sig}"].notna()] if len(obs) else obs
        d: dict[str, Any] = {"n_obs": int(len(o))}
        if hide:
            d["decision"] = "HIDDEN (debug split: no outcome statistics)"
        else:
            x, y = o[f"pct_{sig}"].to_numpy(float), o["realized60"].to_numpy(float)
            rho = m1.spearman(x, y) if len(o) >= 3 else None
            d["rho"] = rho
            d["rho_ci90_block"] = (_block_spearman_ci(x, y, (o["t"].to_numpy(float) // C.BLOCK_S).astype(np.int64),
                                                      B) if len(o) >= 3 else None)
            d["decision"] = ("UNDERPOWERED" if len(o) < MC_MIN_OBS or rho is None
                             else ("PASS" if rho > 0 else "FAIL"))
        out["signals"][sig] = d
    if hide:
        out["decision"] = "HIDDEN"
        out["pass_signals"] = list(SIGNALS)
        return out
    dec = [out["signals"][s]["decision"] for s in SIGNALS]
    out["pass_signals"] = [s for s in SIGNALS if out["signals"][s]["decision"] == "PASS"]
    out["decision"] = ("PASS" if out["pass_signals"] else
                       ("KILL" if any(d == "FAIL" for d in dec) else "UNDERPOWERED"))
    return out


def regime_diagnostics(regime: Regime) -> dict:
    """Never decisive: persistence (S over (s - N, s] vs (s, s + N], non-overlapping 2-h steps) and the pairwise rank
    correlations of the three signals (aggregate series, all coins)."""
    step = int(WINDOW_S // STEP_S)
    ser = {sig: regime.series(sig) for sig in SIGNALS}
    pers = {}
    for sig, v in ser.items():
        a, b = v[:-step:step], v[step::step]
        n = min(len(a), len(b))
        ok = np.isfinite(a[:n]) & np.isfinite(b[:n])
        pers[sig] = {"n": int(ok.sum()), "spearman": m1.spearman(a[:n][ok], b[:n][ok]) if ok.sum() >= 3 else None}
    corr = {}
    for i, a in enumerate(SIGNALS):
        for b in SIGNALS[i + 1:]:
            ok = np.isfinite(ser[a]) & np.isfinite(ser[b])
            corr[f"{a}~{b}"] = {"n": int(ok.sum()),
                                "spearman": m1.spearman(ser[a][ok], ser[b][ok]) if ok.sum() >= 3 else None}
    return {"persistence_2h": pers, "rank_correlation": corr}


# =========================================================================== evaluation


def contrast(host: pd.DataFrame, states: Sequence[str], B: int = CONTRAST_B, seed: int = 0) -> dict:
    """ON mean - OFF mean over the host's known-regime trades, with a 6-hour block bootstrap 90 % CI (resample
    6-hour blocks of entry times, then trades inside each drawn block; draws with an empty arm are skipped)."""
    st = np.asarray(list(states), object)
    r = host["ret_net"].to_numpy(float) if len(host) else np.zeros(0)
    on, off = st == "ON", st == "OFF"
    out = {"n_on": int(on.sum()), "n_off": int(off.sum()), "n_unknown": int((~on & ~off).sum()),
           "mean_on": float(r[on].mean()) if on.any() else None, "mean_off": float(r[off].mean()) if off.any() else None,
           "diff": float(r[on].mean() - r[off].mean()) if on.any() and off.any() else None, "ci90_block": None}
    keep = on | off
    if out["diff"] is None or keep.sum() < 2:
        return out
    blocks = (host["t_in"].to_numpy(float)[keep] // C.BLOCK_S).astype(np.int64)
    rk, ok = r[keep], on[keep]
    ub = np.unique(blocks)
    if len(ub) < 2:
        return out
    per = [(rk[blocks == b], ok[blocks == b]) for b in ub]
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(B):
        so = no = sf = nf = 0.0
        for bi in rng.integers(0, len(per), len(per)):
            rr, oo = per[bi]
            idx = rng.integers(0, len(rr), len(rr))
            rs, os_ = rr[idx], oo[idx]
            so += rs[os_].sum()
            no += os_.sum()
            sf += rs[~os_].sum()
            nf += (~os_).sum()
        if no and nf:
            diffs.append(so / no - sf / nf)
    if len(diffs) >= 10:
        out["ci90_block"] = (float(np.quantile(diffs, 0.05)), float(np.quantile(diffs, 0.95)))
    return out


def _veto(host: pd.DataFrame, states: Sequence[str], oos: tuple[pd.DataFrame, Sequence[str]] | None = None,
          B: int = 10_000) -> dict:
    """common.verdict_veto on the known-regime host trades, flagged = OFF (optionally with an out-of-sample host)."""
    st = np.asarray(list(states), object)
    keep = st != "UNKNOWN"
    h = host[keep].reset_index(drop=True) if len(host) else host
    kw = {}
    if oos is not None:
        ost = np.asarray(list(oos[1]), object)
        ok = ost != "UNKNOWN"
        kw = {"oos_host": oos[0][ok].reset_index(drop=True), "oos_flagged": ost[ok] == "OFF"}
    return C.verdict_veto(h, st[keep] == "OFF", B=B, **kw)


def _blocks(t: pd.DataFrame) -> int:
    return int(len(set((t["t_in"].to_numpy(float) // C.BLOCK_S).astype(np.int64).tolist()))) if len(t) else 0


def evaluate_host(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    t = res.trades
    base = {"hypothesis": res.meta["hypothesis"], "host": res.meta["params"].get("x5_host"),
            "params_hash": C.params_hash(res.meta["params"]), "n": int(len(t)),
            "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_tag_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "ci90", "ci90_block", "n_blocks",
                                        "censored_share", "mean_without_top2", "reasons")})
    return base


def evaluate(res: C.Result, host_lab: pd.DataFrame, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per gated config. Debug: counts only (trades, host states, known share) -- never returns or exit reasons."""
    p = res.meta["params"]
    t = res.trades
    col = state_col(p["signal"], p["q"])
    st = host_lab[col] if len(host_lab) else pd.Series(dtype=object)
    counts = {k: int(v) for k, v in st.value_counts().items()}
    on_keys = set(zip(host_lab.loc[st == "ON", "mint"], host_lab.loc[st == "ON", "t_dec"])) if len(host_lab) else set()
    got = set(zip(t["mint"], t["t_dec"])) if len(t) else set()
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "host": p["x5_host"], "signal": p["signal"], "q": p["q"], "n": int(len(t)),
            "n_coins": int(t["mint"].nunique()) if len(t) else 0, "n_placebo": int(len(res.placebo)),
            "host_n": int(len(host_lab)), "host_states": counts,
            "known_share": (counts.get("ON", 0) + counts.get("OFF", 0)) / len(host_lab) if len(host_lab) else None,
            "on_blocks": _blocks(t), "gate_consistent": got == on_keys,
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
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["contrast"] = contrast(host_lab, st.tolist(), B=min(B, CONTRAST_B))
    base["veto_in_sample"] = _veto(host_lab, st.tolist(), B=min(B, 4000)) if len(host_lab) else None
    return base


def x5_extras(ev: Mapping[str, Any]) -> list[dict]:
    """PREREG 8.4: X5.1 the ON - OFF contrast > 0 with its 6-h block-bootstrap 90 % CI lower bound > 0; X5.2 the ON
    trades fall in >= 6 distinct 6-hour blocks."""
    c = ev.get("contrast") or {}
    ci = c.get("ci90_block")
    if c.get("n_on", 0) < CONTRAST_MIN_ARM or c.get("n_off", 0) < CONTRAST_MIN_ARM or c.get("diff") is None or not ci:
        p1 = None
    else:
        p1 = bool(c["diff"] > 0 and ci[0] > 0)
    return [{"id": "X5.1", "name": "ON beats OFF: contrast > 0, 6-h block 90% CI lower bound > 0", "pass": p1,
             "value": {"diff": c.get("diff"), "ci90_block": ci, "n_on": c.get("n_on"), "n_off": c.get("n_off")}},
            {"id": "X5.2", "name": f"power in time: ON trades in >= {X5_MIN_BLOCKS} six-hour blocks",
             "pass": bool(ev.get("on_blocks", 0) >= X5_MIN_BLOCKS), "value": ev.get("on_blocks")}]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 + 3.6 (common.verdict_entry) + X5.1 / X5.2. Item 9 (FINAL) is judged overall."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1) or extras[1]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or extras[0]["pass"] is False:
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or extras[0]["pass"] is None:
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def _rank_key_edge(r: Mapping[str, Any]) -> tuple:
    lo = r["ci90_block_lo"] if r["ci90_block_lo"] is not None else -math.inf
    return (-lo, -r["mean"], Q_BY_HOST["R0"].index(r["q"]) if r["q"] in Q_BY_HOST["R0"] else 9,
            HOST_ORDER.index(r["host"]), SIGNALS.index(r["signal"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]], configs: Sequence[Mapping[str, Any]]) -> dict:
    """PREREG 8.2: EDGE qualifiers ranked by the 6-h block CI lower bound -> top 2; else the best VETO -> top 1."""
    rows = []
    for p in configs:
        e = evals[config_key(p)]
        c = e.get("contrast") or {}
        pc = (e.get("placebo") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        edge = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and c.get("diff") is not None and c["diff"] > 0
                and cs is not None and cs <= MAX_CENSORED)
        veto = (c.get("n_on", 0) >= VETO_MIN_ARM and c.get("n_off", 0) >= VETO_MIN_ARM and c.get("diff") is not None
                and c["diff"] >= VETO_MIN_CONTRAST)
        cib = e.get("ci90_block")
        cci = c.get("ci90_block")
        rows.append({"config": config_key(p), "host": p["x5_host"], "signal": p["signal"], "q": p["q"],
                     "powered": bool(powered), "edge_qualifies": bool(edge), "veto_qualifies": bool(veto),
                     "n": e["n"], "coins": e["n_coins"], "mean": e.get("mean"),
                     "mean_without_top2": e.get("mean_without_top2"),
                     "ci90_block_lo": cib[0] if cib else None, "placebo_diff": pc, "contrast": c.get("diff"),
                     "contrast_ci90_lo": cci[0] if cci else None, "n_off": c.get("n_off"), "censored_share": cs})
    by_key = {config_key(p): p for p in configs}
    q = [r for r in rows if r["edge_qualifies"]]
    if q:
        q.sort(key=_rank_key_edge)
        top = q[:EDGE_SHORTLIST_MAX]
        track, verdict = "EDGE", "SHORTLISTED_EDGE"
    else:
        q = [r for r in rows if r["veto_qualifies"]]
        q.sort(key=lambda r: (-(r["contrast_ci90_lo"] if r["contrast_ci90_lo"] is not None else -math.inf),
                              -r["contrast"], HOST_ORDER.index(r["host"]), SIGNALS.index(r["signal"])))
        top = q[:VETO_SHORTLIST_MAX]
        track, verdict = ("VETO", "SHORTLISTED_VETO") if top else (None, None)
    if top:
        sl = [by_key[r["config"]] for r in top]
        hosts = sorted({p["x5_host"] for p in sl}, key=HOST_ORDER.index)
        return {"verdict": verdict, "track": track, "rows": rows, "ranked": [r["config"] for r in top],
                "shortlist": sl, "shortlist_hashes": [C.params_hash(p) for p in sl], "hosts": hosts}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "powered configs failed the EDGE bars and no contrast reached the VETO bar"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max((r['n'] for r in rows), default=0)} trades)")
    return {"verdict": v, "track": None, "reason": why, "rows": rows, "ranked": [], "shortlist": [],
            "shortlist_hashes": [], "hosts": []}


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


def decide_val_veto(ev: Mapping[str, Any]) -> dict:
    vt = ev.get("veto_in_sample") or {}
    if vt.get("verdict") == "UNDERPOWERED" or not vt:
        v = "VETO_UNDERPOWERED"
    else:
        crit = {c["id"]: c["pass"] for c in vt.get("criteria", [])}
        v = "VETO_SELECTED" if crit.get(1) and crit.get(3) else "VETO_FAIL_VAL"
    return {"verdict": v, "veto": vt, "proceed": v in PROCEED_VAL}


def decide_val(evals: Mapping[str, Mapping[str, Any]], ranked_roles: list[str], track: str) -> dict:
    """PREREG 8.3: VAL is a filter, never a ranking. EDGE: the first shortlisted config (TRAIN rank order) that
    proceeds; VETO: the veto bar's criteria 1 and 3 on the VAL host trades."""
    if track == "VETO":
        role = ranked_roles[0]
        d = decide_val_veto(evals[role])
        return {**d, "track": track, "candidate_role": role if d["proceed"] else None,
                "candidate_config": evals[role]["config"] if d["proceed"] else None,
                "candidate_hash": evals[role]["params_hash"] if d["proceed"] else None}
    per = {role: decide_val_one(evals[role]) for role in ranked_roles}
    for role in ranked_roles:
        if per[role]["proceed"]:
            return {"verdict": per[role]["verdict"], "track": track, "candidate_role": role,
                    "candidate_config": evals[role]["config"], "candidate_hash": evals[role]["params_hash"],
                    "per_config": per, "proceed": True}
    v = "FAIL_VAL" if any(d["verdict"] == "FAIL_VAL" for d in per.values()) else "UNDERPOWERED_VAL"
    return {"verdict": v, "track": track, "candidate_role": None, "candidate_config": None, "candidate_hash": None,
            "per_config": per, "proceed": False}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 8.5: TEST not REJECTED and (EDGE: TEST mean > 0 or n < 5; VETO: the TEST veto verdict is not FAIL)."""
    v = (test_doc.get("verdict") or {}).get("verdict")
    if v == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    if test_doc.get("track") == "VETO":
        return (v != "FAIL", "ok" if v != "FAIL" else "the TEST veto verdict is FAIL: CONFIRM not spent")
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: X5 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(cand: pd.DataFrame, host_lab: pd.DataFrame, col: str, track: str) -> dict:
    """PLAN 3.5 item 9 on the census thirds X5 never looked at (the TRAIN third hosted the debug run: reported apart).
    EDGE: the candidate's mean > 0; VETO: the contrast ON - OFF > 0 on the host's trades."""
    judged = cand[cand["split"].isin(FINAL_JUDGED)] if len(cand) else cand
    hj = host_lab[host_lab["split"].isin(FINAL_JUDGED)] if len(host_lab) else host_lab
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in cand.groupby("split")} \
        if len(cand) else {}
    con = contrast(hj, hj[col].tolist() if len(hj) else [], B=500)
    dbg = cand[cand["split"] == FINAL_DEBUG] if len(cand) else cand
    return {"verdict": "REPORTED", "track": track, "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0),
            "contrast": con, "contrast_positive": None if con["diff"] is None else bool(con["diff"] > 0),
            "per_third": per,
            "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
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


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def _on_grid(sl: Mapping[str, Any]) -> bool:
    """Every shortlisted config is a config of the registered grid (a stale shortlist, e.g. an M1-hosted config of the
    dropped arm, never reaches VAL or a sealed split)."""
    cfgs = list(sl.get("configs") or [])
    return bool(cfgs) and all(isinstance(c, Mapping) and c.get("x5_host") in HOST_ORDER and C.params_hash(c) in
                              GRID_HASHES for c in cfgs) and set(sl.get("hashes") or []) <= GRID_HASHES


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)]: hosts + the grid (debug / train; TRAIN drops model-check failures later), the
    shortlist in rank order + its hosts (val), the VAL candidate + its host (test / confirm / final)."""
    if stage in ("debug", "train"):
        return [(f"host-{h}", HOST_HYP[h], host_config(h)) for h in HOST_ORDER] + \
               [(config_key(p), HYP, p) for p in GRID]
    sl = _shortlist(HYP, shortlist_path)
    if not sl or not _on_grid(sl):
        return []
    if stage == "val":
        cfgs = list(sl["configs"])
        hosts = sorted({c["x5_host"] for c in cfgs}, key=HOST_ORDER.index)
        return [(f"host-{h}", HOST_HYP[h], host_config(h)) for h in hosts] + \
               [(f"rank{i + 1}", HYP, c) for i, c in enumerate(cfgs)]
    val = _read_json(Path(out_dir) / "val.json") or {}
    h = (val.get("decision") or {}).get("candidate_hash")
    cand = [c for c in sl["configs"] if C.params_hash(c) == h]
    if not cand:
        return []
    host = cand[0]["x5_host"]
    return [(f"host-{host}", HOST_HYP[host], host_config(host)), ("candidate", HYP, cand[0])]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`X5Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X5Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X5Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X5Refused("PREREG.md changed after the first official TRAIN run; record changes in X5/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise X5Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X5Refused("TRAIN already ran on complete data (X5/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X5Refused("no TRAIN result (X5/train.json): run --stage train first")
    if train.get("provisional"):
        raise X5Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_MODEL_CHECK":
        raise X5Refused("X5 is dead: no regime signal passed the model check on TRAIN (stop rule, PREREG 7)")
    if tv not in ("SHORTLISTED_EDGE", "SHORTLISTED_VETO"):
        raise X5Refused(f"TRAIN decision {tv}: X5 stopped before VAL")
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        raise X5Refused("no VAL shortlist for X5 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise X5Refused("the X5 shortlist on disk differs from the one TRAIN wrote")
    off = [h for h in train["decision"].get("hosts", []) if h not in HOST_ORDER]
    if not _on_grid(sl) or off:
        raise X5Refused(f"the X5 shortlist is not in the registered grid (hosts {off or 'ok'}; PREREG 6: R0 only, the "
                        "M1 arm was dropped in review X5-M1HOST): re-run --stage train")
    for h in train["decision"].get("hosts", []):
        hs = _shortlist(HOST_HYP[h], shortlist_path)
        if not hs or hs.get("hashes") != [C.params_hash(host_config(h))]:
            raise X5Refused(f"the {HOST_HYP[h]} host shortlist is missing or differs from the fixed host")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X5Refused("VAL already ran (X5/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise X5Refused(f"no VAL result (X5/val.json): {stage.upper()} needs a VAL decision first")
    vd = val.get("decision") or {}
    if vd.get("verdict") not in PROCEED_VAL:
        raise X5Refused(f"VAL decision {vd.get('verdict')}: X5 stopped (PLAN 8 rule 7 input); {stage.upper()} is not "
                        "spent")
    if vd.get("candidate_hash") not in sl.get("hashes", []):
        raise X5Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X5Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise X5Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X5Refused(f"{stage.upper()} already ran (X5/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise X5Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X5Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    return info


# =========================================================================== stage runner


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
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


def history_datasets(stage: str, ds: C.Dataset, flow: Path | None, census: C.Census | None) -> list[C.Dataset]:
    """The stage's own dataset plus its other history splits (PREREG 2.3), read for their AV / SV records only through
    a counts-level loader that is never handed to a strategy; each is earlier in time and already opened."""
    own = set(C.FINAL_SPLITS) if ds.split == "final" else {ds.split}
    out = [ds]
    for s in HISTORY_SPLITS[stage]:
        if s not in own:
            out.append(C.coverage_dataset(s, flow, census))
    return out


def _host_run(host: str, split: str, ds: C.Dataset, *, ledger_path, shortlist_path) -> C.Result:
    return C.backtest(host_fn(host), split, host_config(host), hypothesis=HOST_HYP[host], ds=ds, cfg=FILL,
                      placebo=False, stress={}, declarations=DECL, ledger_path=ledger_path,
                      shortlist_path=shortlist_path)


def _gated_run(p: Mapping[str, Any], split: str, ds: C.Dataset, regime: Regime, *, ledger_path, shortlist_path,
               n_placebo: int) -> C.Result:
    ps = placebo_spec(p["x5_host"])
    return C.backtest(make_strategy(regime), split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                      n_placebo=n_placebo, placebo_eligible=placebo_eligible(regime, p), placebo_strata=ps["strata"],
                      stress=STRESS, declarations=DECL, ledger_path=ledger_path, shortlist_path=shortlist_path)


def _known_share_of_coins(ds: C.Dataset, regime: Regime) -> dict:
    """Counts only: the share of the split's coins whose decision span (g + 30 .. g + 120 min) has a known regime
    point at g + 60 min, per signal (a structural coverage figure, no outcome)."""
    out = {}
    for sig in SIGNALS:
        n = 0
        for m in ds.mints:
            cd = ds.coin(m)
            k = int(math.floor((cd.g + 3600.0) / STEP_S))
            n += regime.values(sig, k, None) is not None
        out[sig] = round(n / len(ds), 3) if len(ds) else None
    return out


def _grad_delay_counts(ds: C.Dataset) -> dict:
    """Debug check on SLACK (PREREG 2.3): how many graduates took > 6 h from creation (counts only)."""
    d = ds.coins["grad_delay_s"].to_numpy(float) if len(ds) else np.zeros(0)
    ok = np.isfinite(d)
    return {"exact": int(ok.sum()), "over_6h": int((d[ok] > SLACK_S).sum()), "over_1h": int((d[ok] > 3600).sum()),
            "unscanned_creation": int((~ok).sum())}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, history: Sequence[C.Dataset] | None = None,
              graduates: pd.DataFrame | None = None, curve_hours: Iterable[int] | None = None,
              census: C.Census | None = None, flow: Path | None = None, ledger_path: Path | None = None,
              shortlist_path: Path | None = None, B: int = 10_000, n_placebo: int = 20,
              env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X5/<stage>.json + .md (``ds`` / ``history`` / ``graduates`` injection is for
    tests; ``curve_hours`` None with injected frames = any hour with a graduate counts as scanned)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x5_debug_trials.json"   # debug never reaches the real ledger
    census_ = census if census is not None else (C.Census.empty() if ds is not None else C.Census.load())
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census_)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X5Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise X5Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise X5Refused("no configs to run (shortlist or VAL candidate missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X5Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():      # archive, never overwrite, an official run
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    pth = out_dir / f"train.{ext}"
                    if pth.exists():
                        pth.rename(out_dir / f"train_prev_{stamp}.{ext}")
        f = Path(flow or C.flow_dir())
        if ds is None:
            ds = C.load(split, flow=flow, census=census_, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        hist = list(history) if history is not None else history_datasets(stage, ds, flow, census_)
        hist_cov = {h.split: {"usable": len(h), "complete": h.coverage.get("complete")} for h in hist}
        if not debug:
            for h in hist:
                if h is ds:
                    continue
                C.check_sol_coverage(h)
                if not _skip_coverage:
                    ok_h, notes_h = coverage_check(h.coverage)
                    if not ok_h and not provisional:
                        raise X5Refused(f"history split {h.split} incomplete: " + "; ".join(notes_h[:4]))
        gr = graduates
        ch = curve_hours
        if gr is None:
            if not (f / "graduates.parquet").exists():
                raise X5Refused("graduates.parquet missing: the GR pool needs it")
            gr = C._read_parquet(f / "graduates.parquet")
            ch = C.completeness_from_flow(f, with_bar_hours=False).curve_hours if ch is None else ch
        regime = build_regime(stage, ds, hist, gr, census_, ch)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds),
                               "regime": regime.meta, "history_coverage": hist_cov,
                               "known_share_at_g60": _known_share_of_coins(ds, regime)}
        if debug:
            doc["grad_delay_counts"] = _grad_delay_counts(ds)
        else:
            doc["regime_diagnostics"] = regime_diagnostics(regime)
        run_cfgs = list(configs)
        # ---- model check (TRAIN: before any P&L; debug: counts only)
        if stage in ("train", "debug"):
            obs = model_check_obs(ds, regime, with_label=not debug)
            mc = model_check(obs, B=min(B, MC_B), hide=debug)
            mc["trial"] = C.record_run(HYP_MC, MC_PARAMS, split, {"n": int(len(obs)), "mean": None}, ledger_path,
                                       debug=debug)
            doc["model_check"] = mc
            if not debug:
                if mc["decision"] != "PASS":
                    v = "KILLED_MODEL_CHECK" if mc["decision"] == "KILL" else "UNDERPOWERED_MODEL_CHECK"
                    doc["decision"] = {"verdict": v, "track": None, "shortlist_written": False,
                                       "note": "PREREG 7: the model check precedes any P&L; no host or grid ran"}
                    return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
                run_cfgs = [c for c in configs if c[1] != HYP or c[2]["signal"] in mc["pass_signals"]]
                doc["grid_run"] = [config_key(p) for _, h, p in run_cfgs if h == HYP]
        # ---- hosts (ungated baselines) and their regime labels
        hosts_needed = sorted({p["x5_host"] for _, h, p in run_cfgs}, key=HOST_ORDER.index)
        host_res: dict[str, C.Result] = {}
        host_lab: dict[str, pd.DataFrame] = {}
        for h in hosts_needed:
            host_res[h] = _host_run(h, split, ds, ledger_path=ledger_path, shortlist_path=shortlist_path)
            host_lab[h] = label_states(regime, host_res[h].trades)
        # ---- gated configs
        results: dict[str, C.Result] = {}
        for role, h, p in run_cfgs:
            if h != HYP:
                continue
            results[role] = _gated_run(p, split, ds, regime, ledger_path=ledger_path, shortlist_path=shortlist_path,
                                       n_placebo=n_placebo)
        n_tr = C.n_trials(ledger_path)
        doc["hosts"] = {h: evaluate_host(r, B=B, hide=debug, n_trials_total=n_tr) for h, r in host_res.items()}
        evals = {role: evaluate(r, host_lab[r.meta["params"]["x5_host"]], B=B, hide=debug, n_trials_total=n_tr)
                 for role, r in results.items()}
        doc["configs"] = evals
        doc["n_trials_total"] = n_tr
        if not debug:
            _write_trades(out_dir, stage, provisional, results, host_lab)
        if debug:
            days = doc["span_days"]
            doc["signals_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None)
                                      for k, e in evals.items()}
            doc["host_trades_per_day"] = {h: (e["n"] / days if days == days and days > 0 else None)
                                          for h, e in doc["hosts"].items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals, [p for _, h, p in run_cfgs if h == HYP])
            dec["shortlist_written"] = False
            if dec["verdict"] in ("SHORTLISTED_EDGE", "SHORTLISTED_VETO") and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 8.2 {dec['track']} track, rank order {dec['ranked']}")
                for h in dec["hosts"]:
                    C.write_shortlist(HOST_HYP[h], [host_config(h)], path=shortlist_path, ledger_path=ledger_path,
                                      note=f"{VERSION}: fixed host of the shortlisted configs")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            track = ((_read_json(out_dir / "train.json") or {}).get("decision") or {}).get("track")
            doc["track"] = track
            doc["decision"] = decide_val(evals, [r for r, h, _ in run_cfgs if h == HYP], track)
        elif stage in ("test", "confirm"):
            vdoc = _read_json(out_dir / "val.json") or {}
            vdec = vdoc.get("decision") or {}
            track = vdec.get("track")
            doc["track"] = track
            ev = evals["candidate"]
            p = results["candidate"].meta["params"]
            col = state_col(p["signal"], p["q"])
            val_t = _read_trades(out_dir, "val", vdec.get("candidate_role"))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = x5_extras(ev)
            val_host = _read_trades(out_dir, "val", f"host-{p['x5_host']}")
            hl = host_lab[p["x5_host"]]
            veto = (_veto(val_host, val_host[col].tolist(), oos=(hl, hl[col].tolist()), B=min(B, 4000))
                    if val_host is not None and col in val_host else None)
            edge_v = combine_verdict(base, extras)
            doc["verdict"] = {"verdict": edge_v if track == "EDGE" else (veto or {}).get("verdict", "INCOMPLETE"),
                              "track": track, "edge": {"verdict": edge_v, "base": base, "x5_extras": extras},
                              "veto": veto}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            vdec = (_read_json(out_dir / "val.json") or {}).get("decision") or {}
            p = results["candidate"].meta["params"]
            doc["track"] = vdec.get("track")
            doc["decision"] = final_decision(results["candidate"].trades, host_lab[p["x5_host"]],
                                             state_col(p["signal"], p["q"]), vdec.get("track"))
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x5 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate + its host inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise X5Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result],
                  host_lab: Mapping[str, pd.DataFrame]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"])) for role, r in results.items()]
    frames += [t.assign(role=f"host-{h}", config=f"host-{h}") for h, t in host_lab.items()]
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
    td = tr.get("decision") or {}
    tv = td.get("verdict")
    if tv == "KILLED_MODEL_CHECK":
        return "KILLED (no regime signal ranks the next hour of a random alive coin: model check)"
    if tv == "UNDERPOWERED_MODEL_CHECK":
        return "UNDERPOWERED (model check)"
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN)"
    track = td.get("track")
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vv = (va.get("decision") or {}).get("verdict")
    if vv in ("FAIL_VAL", "VETO_FAIL_VAL"):
        return "NO EDGE (failed VAL; PLAN 8 rule 7 input)"
    if vv in ("UNDERPOWERED_VAL", "VETO_UNDERPOWERED"):
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
    fd = fi.get("decision") or {}
    if track == "VETO":
        return ("LOSS REDUCER (veto, not an edge)" if fd.get("contrast_positive")
                else "NO EDGE (FINAL contrast <= 0)")
    return "EDGE" if fd.get("mean_positive") else "NO EDGE (FINAL mean <= 0)"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    rg = doc.get("regime") or {}
    L = [f"# X5 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X5 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, alive rates, signal values "
              "and every outcome statistic are hidden; no parameter was chosen here.**", ""]
    L += ["## Regime coverage (counts)", "",
          f"- Grid {rg.get('grid_utc')} ({rg.get('points')} points of 15 min). GR pool: tradeable graduates created "
          f"before {rg.get('gr_pool_created_before_utc')}. AV/SV pool: {rg.get('history_coins')} usable coins of "
          f"{rg.get('history_splits')} created in {rg.get('history_created_utc')}.",
          f"- Records: {rg.get('records')}; known grid points: {rg.get('known_points')}; first known point: "
          f"{rg.get('first_known_utc')}.",
          f"- Share of the split's coins with a known regime at g + 60 min (current point and its 24-h baseline): "
          f"{doc.get('known_share_at_g60')}."]
    if doc.get("grad_delay_counts"):
        L.append(f"- SLACK check (PREREG 2.3), graduation delays: {doc['grad_delay_counts']}.")
    L.append("")
    mc = doc.get("model_check")
    if mc:
        L += ["## Model check (stop rule, PREREG 7)", "",
              f"- Coins alive at their R0 decision: {mc.get('n_coins_alive_at_r0_decision')} (need ≥ "
              f"{MC_MIN_OBS} observations with a known state per signal)."]
        for sig, d in (mc.get("signals") or {}).items():
            extra = "" if "rho" not in d else (f"; ρ = {d['rho'] if d['rho'] is None else round(d['rho'], 4)}, "
                                               f"6-h block 90% CI {d.get('rho_ci90_block')}")
            L.append(f"- {sig}: {d['n_obs']} observations{extra}; **{d['decision']}**.")
        L += [f"- Decision: **{mc.get('decision')}**; signals in the grid: {mc.get('pass_signals')}.", ""]
    rd = doc.get("regime_diagnostics")
    if rd:
        L += ["## Regime diagnostics (never decisive)", "", f"- Persistence over 2 h: {rd['persistence_2h']}.",
              f"- Rank correlations: {rd['rank_correlation']}.", ""]
    hs = doc.get("hosts") or {}
    if hs:
        L += ["## Hosts (ungated)", ""]
        for h, e in hs.items():
            if doc.get("debug_only"):
                L.append(f"- {h}: {e['n']} trades from {e['n_coins']} coins; by tag {e.get('by_tag_n')}; per day "
                         f"{(doc.get('host_trades_per_day') or {}).get(h)}.")
            else:
                L.append(f"- {h}: n {e['n']}, mean {_pct(e.get('mean'))}, 90% CI coin {_ci(e.get('ci90'))}, 6-h block "
                         f"{_ci(e.get('ci90_block'))}, w/o top 2 {_pct(e.get('mean_without_top2'))}.")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Gated configs", ""]
        if doc.get("debug_only"):
            L += ["| config | gated trades | coins | host states ON/OFF/UNKNOWN | known share | ON blocks | placebo trades "
                  "| signals/day | gate == host ∩ ON |", "|---|---:|---:|---|---:|---:|---:|---:|---|"]
            for k, e in cf.items():
                hs_ = e.get("host_states") or {}
                spd = (doc.get("signals_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {hs_.get('ON', 0)}/{hs_.get('OFF', 0)}/"
                         f"{hs_.get('UNKNOWN', 0)} | {e.get('known_share') if e.get('known_share') is None else round(e['known_share'], 3)} | "
                         f"{e.get('on_blocks')} | {e['n_placebo']} | {'n/a' if spd is None else f'{spd:.1f}'} | "
                         f"{e.get('gate_consistent')} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "contrast ON−OFF [6-h block 90% CI] | n OFF | costs ×1.5 |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---|---:|---:|"]
            for k, e in cf.items():
                c = e.get("contrast") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | {_pct(c.get('diff'))} "
                         f"{_ci(c.get('ci90_block'))} | {c.get('n_off')} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**" + (f" (track {dec.get('track')})" if dec.get("track") else "")
          + "."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, mean {_pct(r['mean'])}, block CI low {_pct(r['ci90_block_lo'])}, "
                 f"placebo diff {_pct(r['placebo_diff'])}, contrast {_pct(r['contrast'])}; EDGE {r['edge_qualifies']}, "
                 f"VETO {r['veto_qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} {dec.get('ranked') or ''}.")
    ed = dec.get("edge") or {}
    if ed.get("base"):
        L.append(f"- EDGE verdict: **{ed['verdict']}**.")
        for c in ed["base"]["criteria"]:
            L.append(f"  - PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in ed.get("x5_extras", []):
            L.append(f"  - {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if ed["base"].get("auto_rejections"):
            L.append(f"  - Auto-rejections: {ed['base']['auto_rejections']}.")
    if dec.get("veto"):
        L.append(f"- VETO verdict (PLAN 3.5 veto bar): **{dec['veto'].get('verdict')}** {dec['veto'].get('criteria')}.")
    for k in ("reason", "note"):
        if dec.get(k):
            L.append(f"- {dec[k]}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}; contrast on the judged thirds: {dec.get('contrast')}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="X5 market regime gate (PLAN R1): pre-registered stages; "
                                             "see research/lab2/X5/PREREG.md")
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
    except X5Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
