"""X2: buy the broadest buying among concurrent graduates (cross-sectional breadth rank at a fixed checkpoint).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X2/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; AGENT fields
only once knowable). The cross-sectional rank of coin i at its checkpoint time t_i compares its breadth with the
breadth of OTHER coins of the same split, each computed through AsOf at THEIR OWN checkpoint time t_j, and only for
t_i - 3 h < t_j <= t_i: no coin that reaches the checkpoint later, and no datum after tau_i, enters the rank.
Labels (the dose-response returns) are outcomes from ``common.run_entries`` and never feed a decision.

Mechanism (PREREG 1): attention is allocated by rankings; the coin with the most distinct buyers per minute among
the coins of the same age keeps attracting buyers. Breadth = mean per-minute ``n_buyers`` (>= 0.01 SOL) with the
AGENT removed; it is NOT "organic" (bots, wash and MECH wallets are inside bar counts), so X2 never declares
organic flow. Net flow / pool depth is a monotone function of the window's own return on a constant-product pool,
so it is only an entry gate (net flow > 0) and a diagnostic rank.

CLI::

    python research/lab2/x2.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x2.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x2.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x2.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x2.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x2.py --stage final
    python research/lab2/x2.py --stage val --check             # prerequisites only

Each stage writes ``X2/<stage>.json`` and ``X2/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlist, nothing after a dose-gate KILL, TEST / CONFIRM / FINAL once each, never
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "x2-v1"
OUT_DIR = HERE / "X2"
HYP, HYP_DOSE = "X2", "X2-dose"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-8)
WIN_BARS = 10               # breadth / net-flow window: the last 10 completed minutes
AGENT_MIN_SOL = 0.01        # the AGENT counts as one buyer in a minute where its buys reach this (n_buyers rule)
REF_WINDOW_S = 3 * 3600.0   # reference pool: other coins whose checkpoint time lies in (t - 3 h, t]
REF_MIN = 30                # no decision with fewer reference coins (warm-up)
TOP_PCT = 0.90              # top decile (fixed, never searched)
STOP_PCT = 0.50             # catastrophe stop (PLAN X1 exit 6)
EXIT_BY_AGE_S = 178 * 60.0  # registered deadline inside the B2 window; never binds for c + H <= 120 min
FADE_BARS = 5               # fade exit: breadth / net flow over the last 5 completed bars ...
FADE_BREADTH_FRAC = 0.5     # ... breadth < 0.5 x the entry breadth and net flow < 0 (EXPERIENCE G31 / EX-11)
SIZE_USD = 20.0
CHECKPOINTS_MIN = (30, 60)
HOLDS_MIN = (30, 60)
EXIT_SETS = ("time", "time+fade")
# operator / factory classes (PLAN 4.2 rules, as m1.m1_class): diagnostics, the class-matched control and X2.1
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MAX_DELAY_S = 5.0
FACTORY_MIN_TOP5 = 0.85
# dose-response gate (PREREG 8)
DOSE_HOLD_MIN = 60
DOSE_BINS = (0.0, 0.5, 0.8, 0.9)   # bin lower edges on the causal percentile; the last bin is the traded decile
DOSE_MIN_TOP = 30
DOSE_MAX_INVERSIONS = 1
# selection and verdict bars
TRAIN_MIN_TRADES = 30
VAL_MIN_SIGN, VAL_MIN_TRADES = 10, 30
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                       # PLAN 3.5 default bar
X21_MIN_TRADES = 10
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

MAIN_CFG = C.FillConfig(exit_delay_bars=1)  # worst fills; stops / time / fade exits fill on the NEXT bar
STRESS = {"costs_x1.5": MAIN_CFG.stressed(1.5), "rent_0.22": dataclasses.replace(MAIN_CFG, rent_usd=0.22),
          "latency_60s": dataclasses.replace(MAIN_CFG, latency_s=60.0)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}

FIXED = {
    "version": VERSION, "score": "breadth", "win_bars": WIN_BARS, "agent_min_sol": AGENT_MIN_SOL,
    "ref_window_s": REF_WINDOW_S, "ref_min": REF_MIN, "top_pct": TOP_PCT, "gate": "alive & netflow > 0",
    "stop_pct": STOP_PCT, "exit_by_age_s": EXIT_BY_AGE_S, "fade_bars": FADE_BARS,
    "fade_breadth_frac": FADE_BREADTH_FRAC, "size_usd": SIZE_USD,
    "placebo": "random alive & netflow > 0 & n_ref >= ref_min at the draw (entry conditions 1-3), +-120 s",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exits",
}


def make_params(checkpoint_min: float, hold_min: float, exit_set: str) -> dict:
    if checkpoint_min not in CHECKPOINTS_MIN or hold_min not in HOLDS_MIN or exit_set not in EXIT_SETS:
        raise ValueError(f"({checkpoint_min}, {hold_min}, {exit_set!r}) is not in the X2 grid")
    return {**FIXED, "checkpoint_min": int(checkpoint_min), "hold_min": int(hold_min), "exit": exit_set}


GRID = [make_params(c, h, e) for c in CHECKPOINTS_MIN for h in HOLDS_MIN for e in EXIT_SETS]
DOSE_PARAMS = {"version": VERSION, "test": "dose_response", "checkpoints_min": list(CHECKPOINTS_MIN),
               "hold_min": DOSE_HOLD_MIN, "exit": "time", "bins": list(DOSE_BINS), "min_top": DOSE_MIN_TOP,
               "max_inversions": DOSE_MAX_INVERSIONS, "fixed": FIXED}


class X2Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"c{p['checkpoint_min']}|h{p['hold_min']}|{p['exit']}"


# =========================================================================== features (AsOf only)


def window_stats(bars: C.Bars, k_end: int, n: int) -> dict | None:
    """Breadth and net flow over completed bars [k_end - n, k_end) (``bars`` is an AsOf view: completed bars only).

    breadth = mean per-minute buyers (>= 0.01 SOL) with the AGENT removed as one buyer in each minute where its
    knowable buys reach 0.01 SOL; netflow = buy SOL - AGENT buy SOL - sell SOL. None with fewer than n bars."""
    k_end = int(min(k_end, len(bars)))
    if k_end < n or n <= 0:
        return None
    sl = slice(k_end - n, k_end)
    nb = np.asarray(bars.n_buyers[sl], float)
    buy = np.asarray(bars.buy_sol[sl], float)
    sell = np.asarray(bars.sell_sol[sl], float)
    ag = np.nan_to_num(np.asarray(bars.agent_buy_sol[sl], float), nan=0.0)
    agent_buyer = (ag >= AGENT_MIN_SOL).astype(float)
    return {"breadth": float(np.clip(nb - agent_buyer, 0.0, None).mean()), "netflow": float((buy - ag - sell).sum()),
            "buy_sol": float((buy - ag).sum())}


def features(snap: C.AsOf) -> dict:
    """X2 features at ``snap`` -> {ok, breadth, netflow, pressure, alive, X, ret10, mcap_sol}."""
    bars = snap.bars
    k = len(bars)
    out = {"ok": False, "breadth": None, "netflow": None, "pressure": None, "alive": False, "X": None,
           "ret10": None, "mcap_sol": snap.mcap_sol}
    w = window_stats(bars, k, WIN_BARS)
    if w is None:
        return out
    X = float(bars.X[k - 1])
    out.update(ok=bool(X > 0), breadth=w["breadth"], netflow=w["netflow"], X=X,
               pressure=w["netflow"] / X if X > 0 else None, alive=bool(snap.alive()),
               ret10=snap.ret(60.0 * WIN_BARS))
    return out


def x2_class(snap: C.AsOf) -> str | None:
    """PLAN 4.2 rules in PLAN order (the same rules as ``m1.m1_class``): OPERATOR, FACTORY, else OTHER. None when an
    input is NULL or not yet knowable. Diagnostic / control stratum / X2.1 only; never an entry condition."""
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


def checkpoint_time(cd: C.CoinData, c_min: float) -> float:
    """First decision-grid time (minute boundary + 20 s) with age >= c_min minutes: the engine's first decision at
    that age."""
    j = math.ceil((cd.g + 60.0 * c_min - C.GRID_OFFSET_S - cd.m0) / 60.0)
    return float(cd.m0 + 60 * max(j, 1) + C.GRID_OFFSET_S)


# =========================================================================== the cross-sectional reference


@dataclass(frozen=True)
class Reference:
    """Scores of alive coins at their own checkpoint time, sorted by that time. A query at t sees only entries with
    t - window < t_j <= t from OTHER coins (PREREG 4)."""

    c_min: float
    score_name: str
    t: np.ndarray
    score: np.ndarray
    mint: tuple
    window_s: float = REF_WINDOW_S

    def pool(self, t: float, mint: str) -> np.ndarray:
        lo = int(np.searchsorted(self.t, float(t) - self.window_s, side="right"))
        hi = int(np.searchsorted(self.t, float(t), side="right"))
        keep = [i for i in range(lo, hi) if self.mint[i] != mint]
        return self.score[keep]

    def percentile(self, s: float, t: float, mint: str) -> tuple[float | None, int]:
        ref = self.pool(t, mint)
        n = int(len(ref))
        if n == 0 or s is None:
            return None, n
        return float(((ref < s).sum() + 0.5 * (ref == s).sum()) / n), n


def build_reference(ds: C.Dataset, c_min: float, score: str = "breadth", mints: Iterable[str] | None = None,
                    window_s: float = REF_WINDOW_S) -> Reference:
    """Reference of checkpoint ``c_min``: every usable coin of ``ds`` that is alive at its own checkpoint time, with
    its ``score`` (``breadth`` or ``pressure``) read through AsOf at that time."""
    rows = []
    for m in (mints if mints is not None else ds.mints):
        cd = ds.coin(m)
        t = checkpoint_time(cd, c_min)
        f = features(ds.asof(m, t))
        if f["ok"] and f["alive"] and f[score] is not None:
            rows.append((t, float(f[score]), m))
    rows.sort(key=lambda r: (r[0], r[2]))
    return Reference(c_min=float(c_min), score_name=score, t=np.array([r[0] for r in rows], float),
                     score=np.array([r[1] for r in rows], float), mint=tuple(r[2] for r in rows), window_s=window_s)


def references(ds: C.Dataset, scores: Iterable[str] = ("breadth",),
               checkpoints: Iterable[float] = CHECKPOINTS_MIN) -> dict[tuple[str, float], Reference]:
    return {(s, float(c)): build_reference(ds, c, s) for s in scores for c in checkpoints}


# =========================================================================== entry / exit


def entry_decision(snap: C.AsOf, ref: Reference) -> tuple[bool, dict]:
    """PREREG 5 at the coin's checkpoint: alive, net flow > 0, >= 30 reference coins, breadth percentile >= 0.90."""
    f = features(snap)
    info = dict(f, pct=None, n_ref=0, cls=None, gate=False)
    if not (f["ok"] and f["alive"] and f["netflow"] is not None and f["netflow"] > 0):
        return False, info
    pct, n = ref.percentile(f["breadth"], snap.t, snap.mint)
    info.update(pct=pct, n_ref=n, gate=True)
    if n < REF_MIN or pct is None:
        return False, info
    info["cls"] = x2_class(snap)
    return bool(pct >= TOP_PCT), info


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return 0
    return int(min(max((tau - int(bars.minute_ts[0])) // 60, 0), k))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """Fade exit (``time+fade`` only): >= 5 completed bars after the entry decision, breadth over the last 5 < 0.5 x
    the entry breadth and net flow over them < 0. Placebo positions carry no state: their entry breadth is recomputed
    from the bars completed at THEIR decision. Stop, time and deadline exits are mechanical (ExitSpec)."""
    if p["exit"] != "time+fade":
        return None
    bars = snap.bars
    k = len(bars)
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    if k - k_dec < FADE_BARS:
        return None
    b_ref = (pos.state or {}).get("breadth")
    if b_ref is None:
        w = window_stats(bars, k_dec, WIN_BARS)
        b_ref = None if w is None else w["breadth"]
    if b_ref is None or b_ref <= 0:
        return None
    now = window_stats(bars, k, FADE_BARS)
    if now is not None and now["breadth"] < FADE_BREADTH_FRAC * b_ref and now["netflow"] < 0:
        return C.Exit("fade")
    return None


class X2Strategy:
    """The X2 strategy for common.backtest: one look per coin at its checkpoint (Enter or SKIP), then exits.
    ``refs`` maps the checkpoint (minutes) to its breadth :class:`Reference`."""

    def __init__(self, refs: Mapping[float, Reference]):
        self.refs = {float(k): v for k, v in refs.items()}

    def __call__(self, snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return exit_decision(snap, p, pos)
        c = float(p["checkpoint_min"])
        if snap.age_s < 60.0 * c:
            return None
        ok, info = entry_decision(snap, self.refs[c])
        if not ok:
            return C.SKIP
        return C.Enter(exits=exit_spec(p), tag=str(info["cls"]), state={"breadth": info["breadth"],
                                                                       "pct": info["pct"], "n_ref": info["n_ref"]})


def exit_spec(p: Mapping[str, Any]) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=60.0 * float(p["hold_min"]), exit_by_age_s=EXIT_BY_AGE_S)


def strategy_for(ds: C.Dataset, refs: Mapping[tuple[str, float], Reference] | None = None) -> X2Strategy:
    refs = refs if refs is not None else references(ds)
    return X2Strategy({c: r for (s, c), r in refs.items() if s == "breadth"})


def placebo_ok(snap: C.AsOf) -> bool:
    """Entry conditions 1-2 (alive and net flow > 0). The matched control adds condition 3: :func:`placebo_eligible`."""
    f = features(snap)
    return bool(f["ok"] and f["alive"] and f["netflow"] is not None and f["netflow"] > 0)


def placebo_eligible(ref: Reference):
    """Matched random control universe (PREREG 10): entry conditions 1-3 without the rank -- alive, net flow > 0 and
    >= REF_MIN reference coins at the draw's OWN decision time, the drawn coin excluded (review X2-PLACEBO-NREF: n_ref
    is a market-activity condition, so a control drawn from quiet hours X2 can never trade would mix the rank with
    the regime)."""

    def ok(snap: C.AsOf) -> bool:
        return len(ref.pool(snap.t, snap.mint)) >= REF_MIN and placebo_ok(snap)

    ok.__name__ = f"placebo_ok_nref_c{ref.c_min:g}"
    return ok


def placebo_stratum(snap: C.AsOf) -> str | None:
    return x2_class(snap)


def placebo_spec(strat: "X2Strategy", p: Mapping[str, Any]) -> tuple[Any, dict]:
    """(eligible, placebo_controls) for ``common.backtest`` on config ``p``: the matched control and the class-matched
    diagnostic control, both on entry conditions 1-3 at the config's checkpoint reference."""
    ok = placebo_eligible(strat.refs[float(p["checkpoint_min"])])
    return ok, {"class_matched": {"eligible": ok, "strata": placebo_stratum}}


# =========================================================================== dose-response gate (PREREG 8)


def _bin_of(pct: float) -> int:
    return int(np.searchsorted(np.asarray(DOSE_BINS), pct, side="right") - 1)


def dose_obs(ds: C.Dataset, refs: Mapping[tuple[str, float], Reference], with_labels: bool = True) -> pd.DataFrame:
    """Every coin meeting entry conditions 1-3 (alive, net flow > 0, >= 30 reference coins) at each checkpoint, with
    its causal breadth and pressure percentiles and its LABEL: the net return of a $20 entry at that decision with
    a 60-minute hold and the -50 % stop (MAIN_CFG fills), via common.run_entries (unlogged; the gate is logged once
    as ``X2-dose``)."""
    rows, entries = [], []
    for c in CHECKPOINTS_MIN:
        rb, rp = refs[("breadth", float(c))], refs.get(("pressure", float(c)))
        for m in ds.mints:
            cd = ds.coin(m)
            t = checkpoint_time(cd, c)
            snap = ds.asof(m, t)
            f = features(snap)
            if not (f["ok"] and f["alive"] and f["netflow"] is not None and f["netflow"] > 0):
                continue
            pct, n = rb.percentile(f["breadth"], t, m)
            if n < REF_MIN or pct is None:
                continue
            pp = rp.percentile(f["pressure"], t, m) if rp is not None else (None, 0)
            rows.append({"mint": m, "c": int(c), "t": t, "breadth": f["breadth"], "pressure": f["pressure"],
                         "netflow": f["netflow"], "pct": pct, "n_ref": n, "bin": _bin_of(pct),
                         "pct_pressure": pp[0], "bin_pressure": None if pp[0] is None else _bin_of(pp[0]),
                         "cls": x2_class(snap)})
            entries.append((m, t, C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=60.0 * DOSE_HOLD_MIN,
                                                           exit_by_age_s=EXIT_BY_AGE_S), tag=f"dose{c}")))
    cols = ["mint", "c", "t", "breadth", "pressure", "netflow", "pct", "n_ref", "bin", "pct_pressure",
            "bin_pressure", "cls", "label"]
    obs = pd.DataFrame(rows, columns=cols[:-1])
    obs["label"] = np.nan
    if with_labels and len(entries):
        strat = X2Strategy({})
        tr = C.run_entries(ds, strat, {"exit": "time", "checkpoint_min": 0, "hold_min": DOSE_HOLD_MIN}, MAIN_CFG,
                           entries)
        lab = {(r.mint, float(r.t_dec)): float(r.ret_net) for r in tr.itertuples(index=False)}
        obs["label"] = [lab.get((m, float(t)), np.nan) for m, t in zip(obs["mint"], obs["t"])]
    return obs[cols]


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return None
    ra, rb = pd.Series(a[ok]).rank().to_numpy(), pd.Series(b[ok]).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _dose_table(o: pd.DataFrame, bin_col: str, pct_col: str, hide: bool) -> dict:
    nb = len(DOSE_BINS)
    counts = [int((o[bin_col] == b).sum()) for b in range(nb)]
    out: dict[str, Any] = {"n": int(len(o)), "bin_counts": counts}
    if hide:
        return out
    lab = o["label"].to_numpy(float)

    def _mean(x: np.ndarray) -> float | None:
        x = x[np.isfinite(x)]
        return float(x.mean()) if len(x) else None
    means = [_mean(lab[(o[bin_col] == b).to_numpy()]) for b in range(nb)]
    out["bin_means"] = means
    out["mean_all"] = _mean(lab)
    have = [m for m in means if m is not None]
    out["inversions"] = int(sum(1 for a, b in zip(have, have[1:]) if b < a))
    out["top_minus_all"] = (means[-1] - out["mean_all"]) if (means[-1] is not None and out["mean_all"] is not None) \
        else None
    out["spearman_pct_label"] = _spearman(o[pct_col].to_numpy(float), lab)
    return out


def dose_check(obs: pd.DataFrame, hide: bool = False) -> dict:
    """PREREG 8: per checkpoint UNDERPOWERED (< 30 coins in the top bin, or an empty bin) / PASS (top > all and <= 1
    inversion of the four bin means) / FAIL; X2: KILL (no PASS, some FAIL), UNDERPOWERED (no PASS, no FAIL) or PASS
    (the passing checkpoints go on). ``hide`` (debug split): counts only. The pressure table is diagnostic only."""
    per: dict[str, Any] = {}
    for c in CHECKPOINTS_MIN:
        o = obs[obs["c"] == c]
        tb = _dose_table(o, "bin", "pct", hide)
        tb["by_class"] = {str(k): int(v) for k, v in o["cls"].astype(str).value_counts().items()} if len(o) else {}
        op = o[o["bin_pressure"].notna()]
        tp = _dose_table(op.assign(bin_pressure=op["bin_pressure"].astype(int)), "bin_pressure", "pct_pressure", hide)
        tb["pressure_diagnostic"] = tp
        if tb["bin_counts"][-1] < DOSE_MIN_TOP or min(tb["bin_counts"]) == 0:
            tb["decision"] = "UNDERPOWERED"
        elif hide:
            tb["decision"] = "HIDDEN"
        else:
            good = (tb["top_minus_all"] is not None and tb["top_minus_all"] > 0
                    and tb["inversions"] <= DOSE_MAX_INVERSIONS and None not in tb["bin_means"])
            tb["decision"] = "PASS" if good else "FAIL"
        per[str(c)] = tb
    ds_ = [v["decision"] for v in per.values()]
    if hide:
        overall = "HIDDEN (debug split: no outcome statistics)"
    elif "PASS" in ds_:
        overall = "PASS"
    elif "FAIL" in ds_:
        overall = "KILL"
    else:
        overall = "UNDERPOWERED"
    return {"per_checkpoint": per, "decision": overall,
            "passing_checkpoints": [int(c) for c in CHECKPOINTS_MIN if per[str(c)]["decision"] == "PASS"],
            "need": {"top_bin_coins": DOSE_MIN_TOP, "max_inversions": DOSE_MAX_INVERSIONS, "bins": list(DOSE_BINS)}}


# =========================================================================== evaluation


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, classes, placebo n, horizon exits)."""
    t = res.trades
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_class_n": t["tag"].value_counts().to_dict() if len(t) else {}, "n_placebo": int(len(res.placebo)),
            "horizon_exits": int(cens.sum()),
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:     # exit reasons (stop vs time vs fade) are outcome labels: hidden like returns
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    pc = res.controls.get("class_matched") if res.controls else None
    base["placebo_class_matched"] = C.placebo_compare(t, pc, B=B) if pc is not None and len(pc) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_class"] = {c: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for c, g in t.groupby("tag")} \
        if len(t) else {}
    nf = t[t["tag"] != "FACTORY"] if len(t) else t
    base["non_factory"] = {"n": int(len(nf)), "mean": float(nf["ret_net"].mean()) if len(nf) else None}
    return base


def x2_extras(ev: Mapping[str, Any]) -> list[dict]:
    """X2.1 (PREREG 11): >= 10 non-FACTORY trades with a mean > 0."""
    nf = ev.get("non_factory") or {}
    n, mean = int(nf.get("n") or 0), nf.get("mean")
    return [{"id": "X2.1", "name": f"positive outside FACTORY coins (>= {X21_MIN_TRADES} trades, mean > 0)",
             "pass": bool(n >= X21_MIN_TRADES and mean is not None and mean > 0), "value": {"n": n, "mean": mean}}]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 + 10 (common.verdict_entry) and X2.1. Item 9 (FINAL) is judged in the overall verdict."""
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


def decide_train(evals: Mapping[str, Mapping[str, Any]], passing_checkpoints: Iterable[int]) -> dict:
    """PREREG 9: the qualifier (>= 30 trades, mean > 0, mean w/o top 2 > 0, matched-control diff > 0) with the highest
    coin-bootstrap 90 % CI lower bound (ties: higher mean, then grid order) is the ONE shortlisted config."""
    ok_c = {int(c) for c in passing_checkpoints}
    rows = []
    for i, p in enumerate(GRID):
        key = config_key(p)
        if int(p["checkpoint_min"]) not in ok_c or key not in evals:
            continue
        e = evals[key]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0)
        ci = e.get("ci90")
        rows.append({"config": key, "order": i, "powered": powered, "qualifies": bool(good), "n": e["n"],
                     "mean": e.get("mean"), "ci90_lo": ci[0] if ci else None, "placebo_diff": pc})
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
        why = f"no config reached >= {TRAIN_MIN_TRADES} trades (best: {max([r['n'] for r in rows] or [0])})"
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
    return False, f"TEST mean {mean} <= 0 on {n} trades: X2 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds X2 never looked at; the TRAIN third (debugged on) is reported apart."""
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
    """Raise :class:`X2Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X2Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X2Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X2Refused("PREREG.md changed after the first official TRAIN run; record changes in X2/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = data_gates(flow, STAGE_SPLIT[stage])
    if not ok and stage != "debug":
        raise X2Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X2Refused("TRAIN already ran on complete data (X2/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X2Refused("no TRAIN result (X2/train.json): run --stage train first")
    if train.get("provisional"):
        raise X2Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_DOSE":
        raise X2Refused("X2 is dead: the dose-response gate failed on TRAIN (PREREG 8 stop rule)")
    if tv != "SHORTLISTED":
        raise X2Refused(f"TRAIN decision {tv}: X2 stopped before VAL")
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        raise X2Refused("no VAL shortlist for X2 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise X2Refused("the X2 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X2Refused("VAL already ran (X2/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise X2Refused("no VAL result (X2/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise X2Refused(f"VAL decision {vv}: X2 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X2Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok, why = confirm_allowed(test)
        if not ok:
            raise X2Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X2Refused(f"{stage.upper()} already ran (X2/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise X2Refused(f"X2 already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X2Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def _q(x: np.ndarray) -> dict | None:
    x = np.asarray(x, float)
    if not len(x):
        return None
    return {k: float(np.quantile(x, q)) for k, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9), ("max", 1.0))}


def event_counts(ds: C.Dataset, refs: Mapping[tuple[str, float], Reference]) -> dict:
    """Counts only (features, never outcomes): how often each entry condition holds per checkpoint, reference sizes,
    the breadth distribution of alive coins, and the AMM identity check Spearman(pressure, ret10) (PREREG 2.5)."""
    out: dict[str, Any] = {"coins": len(ds)}
    for c in CHECKPOINTS_MIN:
        rb = refs[("breadth", float(c))]
        n_ok = n_alive = n_flow = n_warm = n_top = 0
        nref, br, pr, r10 = [], [], [], []
        cls: dict[str, int] = {}
        for m in ds.mints:
            cd = ds.coin(m)
            t = checkpoint_time(cd, c)
            snap = ds.asof(m, t)
            f = features(snap)
            if not f["ok"]:
                continue
            n_ok += 1
            if not f["alive"]:
                continue
            n_alive += 1
            br.append(f["breadth"])
            if f["pressure"] is not None and f["ret10"] is not None:
                pr.append(f["pressure"])
                r10.append(f["ret10"])
            if not f["netflow"] > 0:
                continue
            n_flow += 1
            pct, n = rb.percentile(f["breadth"], t, m)
            nref.append(n)
            if n < REF_MIN:
                n_warm += 1
                continue
            if pct >= TOP_PCT:
                n_top += 1
                k = str(x2_class(snap))
                cls[k] = cls.get(k, 0) + 1
        out[str(c)] = {"coins_with_window": n_ok, "alive": n_alive, "alive_netflow_pos": n_flow,
                       "warmup_skips": n_warm, "top_decile_entries": n_top, "entries_by_class": cls,
                       "n_ref": _q(np.array(nref)), "breadth_alive": _q(np.array(br)),
                       "reference_size": int(len(rb.t)),
                       "spearman_pressure_ret10_alive": _spearman(np.array(pr), np.array(r10))}
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X2/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x2_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X2Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise X2Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise X2Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X2Refused(str(e)) from e
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
        scores = ("breadth", "pressure") if stage in ("train", "debug") else ("breadth",)
        refs = references(ds, scores)
        strat = strategy_for(ds, refs)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds),
                               "reference_sizes": {f"{s}@{c:g}": int(len(r.t)) for (s, c), r in refs.items()}}
        run_cfgs = configs
        # ---- dose-response gate (TRAIN: before any strategy P&L; debug: counts only)
        if stage in ("train", "debug"):
            obs = dose_obs(ds, refs, with_labels=not debug)
            dc = dose_check(obs, hide=debug)
            doc["dose"] = dc
            dr = C.record_run(HYP_DOSE, DOSE_PARAMS, split, {"n": int(len(obs)), "mean": None}, ledger_path,
                              debug=debug, cfg=MAIN_CFG)
            doc["dose"]["trial"] = dr
            if debug:
                doc["event_counts"] = event_counts(ds, refs)
            elif dc["decision"] != "PASS":
                v = "KILLED_DOSE" if dc["decision"] == "KILL" else "UNDERPOWERED_DOSE"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "PREREG 8: the dose-response gate precedes any strategy P&L; the grid "
                                           "was not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
            else:
                keep = set(dc["passing_checkpoints"])
                run_cfgs = [x for x in configs if int(x[2]["checkpoint_min"]) in keep]
        # ---- the configs
        results: dict[str, C.Result] = {}
        for role, h, p in run_cfgs:
            pl_ok, pl_controls = placebo_spec(strat, p)
            results[role] = C.backtest(strat, split, p, hypothesis=h, ds=ds, cfg=MAIN_CFG, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=pl_ok,
                                       placebo_controls=pl_controls, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals, doc["dose"]["passing_checkpoints"])
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
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = x2_extras(evals["candidate"])
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "x2_extras": extras}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x2 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise X2Refused(str(e)) from e


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
    if tv == "KILLED_DOSE":
        return "KILLED (dose-response gate failed on TRAIN)"
    if tv == "UNDERPOWERED_DOSE":
        return "UNDERPOWERED (too few top-decile coins for the dose-response gate on TRAIN)"
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
    L = [f"# X2 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days; "
         f"reference sizes (alive coins at their checkpoint): {doc.get('reference_sizes')}.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X2 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and bin means "
              "are hidden, and no parameter was chosen here.**", ""]
    dose = doc.get("dose")
    if dose:
        L += ["## Dose-response gate (PREREG 8)", "", f"- Decision: **{dose['decision']}**; passing checkpoints: "
              f"{dose.get('passing_checkpoints')}.",
              "", "| checkpoint | obs | coins per bin [0-.5, .5-.8, .8-.9, .9-1] | bin means | top − all | "
                  "inversions | decision | pressure-rank bin means (diagnostic) |",
              "|---|---:|---|---|---:|---:|---|---|"]
        for c, tb in (dose.get("per_checkpoint") or {}).items():
            bm = tb.get("bin_means")
            pm = (tb.get("pressure_diagnostic") or {}).get("bin_means")
            L.append(f"| {c} min | {tb['n']} | {tb['bin_counts']} | "
                     f"{'hidden' if bm is None else [_pct(x) for x in bm]} | {_pct(tb.get('top_minus_all'))} | "
                     f"{tb.get('inversions', 'n/a')} | {tb['decision']} | "
                     f"{'hidden' if pm is None else [_pct(x) for x in pm]} |")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (features only, no returns)", "",
              "| checkpoint | coins with a window | alive | alive & net flow > 0 | warm-up skips (< 30 refs) | "
              "top-decile entries | entries by class | n_ref p10/p50/p90 | breadth of alive p10/p50/p90/max | "
              "Spearman(pressure, 10-min return) |",
              "|---|---:|---:|---:|---:|---:|---|---|---|---:|"]
        for c in CHECKPOINTS_MIN:
            e = ec.get(str(c)) or {}
            nr, ba = e.get("n_ref") or {}, e.get("breadth_alive") or {}
            sp = e.get("spearman_pressure_ret10_alive")
            L.append(f"| {c} min | {e.get('coins_with_window')} | {e.get('alive')} | {e.get('alive_netflow_pos')} | "
                     f"{e.get('warmup_skips')} | {e.get('top_decile_entries')} | {e.get('entries_by_class')} | "
                     f"{nr.get('p10', 'n/a')}/{nr.get('p50', 'n/a')}/{nr.get('p90', 'n/a')} | "
                     f"{ba.get('p10', 0):.1f}/{ba.get('p50', 0):.1f}/{ba.get('p90', 0):.1f}/{ba.get('max', 0):.1f} | "
                     f"{'n/a' if sp is None else f'{sp:.3f}'} |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | classes | placebo trades | horizon exits | entries/day |",
                  "|---|---:|---:|---|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_class_n']} | "
                         f"{e['n_placebo']} | {e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "class-matched diff | costs ×1.5 | non-FACTORY n / mean | reasons |",
                  "|---|---|---:|---:|---|---|---:|---:|---:|---:|---|---|"]
            for k, e in cf.items():
                nf = e.get("non_factory") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {_pct(e.get('mean'))} | {_ci(e.get('ci90'))} | "
                         f"{_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('placebo_class_matched') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | {nf.get('n')} / {_pct(nf.get('mean'))} | "
                         f"{e.get('reasons')} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, mean {_pct(r['mean'])}, 90% CI low {_pct(r['ci90_lo'])}, placebo "
                 f"diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']}"
                 + (f" (candidate {dec['candidate']})" if dec.get("candidate") else "") + ".")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("x2_extras", []):
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
    ap = argparse.ArgumentParser(description="X2 cross-sectional buyer breadth: pre-registered stages; "
                                             "see research/lab2/X2/PREREG.md")
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
    except X2Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
