"""Q7 (PS1): is a mint without the "pump" suffix -- a coin created outside the pump.fun app -- a coin to skip?

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Q7/PREREG.md``
(idea-mill queue item q7 · PS1, ``scratchpad/ideas/mill/QUEUE.md``).

Every FEATURE comes from :class:`common.AsOf` (cutoff tau = t - 20 s; NULL stays None). The two flags are static coin
facts fixed at creation (PREREG 2):

* ``SFX0`` = the mint does not end in ``pump`` (the app grinds that vanity suffix; scripts and custom tooling do not);
* ``CU``   = the CreateEvent's signer ``create_user`` differs from its ``creator`` (unknown when either is NULL).

PS1 is a VETO (PLAN 3.5): two fixed random hosts -- R0 (``g1.host_r0``) and R30 (``y5.host_r30``) -- run once per
split; their trades are annotated at the decision time with the flags and with G1's class at g + 140 s; four
pre-registered veto configs (PREREG 5) are judged with ``common.verdict_veto`` against a random veto at the same rate
stratified by G1 class (PREREG 6). Outcomes (trade returns, exit reasons) are never features and are hidden on the
debug split.

CLI::

    python research/lab2/q7.py --debug                         # census TRAIN third: counts only (no returns)
    python research/lab2/q7.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/q7.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/q7.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/q7.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/q7.py --stage final
    python research/lab2/q7.py --stage val --check             # prerequisites only

Each stage writes ``Q7/<stage>.json`` and ``Q7/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the shortlist TRAIN wrote, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8
data gates, PREREG frozen after the first official TRAIN run, both host pins).
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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C
import g1 as G1
import y5 as Y5

VERSION = "ps1-v1"
OUT_DIR = HERE / "Q7"
HYP = "PS1"
HOSTS = ("R0", "R30")
HYP_HOST = {"R0": "PS1.R0", "R30": "PS1.R30"}
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-8)
SUFFIX = "pump"                              # the pump.fun app's vanity mint suffix (case-sensitive)
CLASS_T_S = float(G1.LABEL_T_S)              # G1 class and instant read at g + 140 s (tau = g + 120 s)
CLASSES = ("OPERATOR", "FACTORY", "COMPLETED", "UNRESOLVED", "ORGANIC")
FLAG_COL = {"SFX0": "sfx0", "CU": "cu"}
SUBSETS = ("ALL", "ORGANIC")
VETO_MIN = int(C.PLAN_MIN["veto_val_flagged"])     # 30 flagged and 30 unflagged (common.verdict_veto)
VETO_MARGIN = 0.10                                  # verdict_veto criterion 1 (documented; common applies it)
WIN_REMOVED_MAX = 0.25                              # verdict_veto criterion 3 (documented; common applies it)
PLACEBO_B = 2000                                    # random vetoes per evaluation (PREREG 6)
PLACEBO_SEED = 0
PLACEBO_P_MAX = 0.05
VAL_MIN_SIGN = 5
TEST_MIN_SIDE = 5
MAX_CENSORED = C.MAX_CENSORED_SHARE
CU_SHARE_BOUNDS = (0.02, 0.98)                      # PREREG 2.3 withdrawal rule (structure, census TRAIN third)
CU_LIST_N = 20
DOSE_B = 2000
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"
SIZE_USD = 20.0

FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; every triggered exit fills in the NEXT bar (QUEUE rule 2)
STRESS = {"costs_x1.5": FILL.stressed(1.5)}

# ---- hosts (PREREG 3): fixed, imported, pinned
HOST_FN = {"R0": G1.host_r0, "R30": Y5.host_r30}
HOST_PARAMS = {"R0": dict(G1.R0_PARAMS), "R30": dict(Y5.R30_PARAMS)}
HOST_PINS = {"R0": "27a79bc60126", "R30": "a995b4907d17"}

GRID_SPEC = (("R0", "SFX0", "ALL"), ("R0", "SFX0", "ORGANIC"), ("R30", "SFX0", "ALL"), ("R0", "CU", "ALL"))
FIXED = {
    "version": VERSION, "size_usd": SIZE_USD,
    "flags": {"SFX0": f"not mint.endswith({SUFFIX!r}) (always legal)",
              "CU": "create_user != creator via AsOf (CREATE_COLS); NULL / empty -> unknown, outside the set"},
    "class": f"g1.classify(g1.g1_features(AsOf(g + {CLASS_T_S:.0f} s)))",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
    "veto_bar": {"lib": "common.verdict_veto", "margin": VETO_MARGIN, "win_removed_max": WIN_REMOVED_MAX,
                 "min_side": VETO_MIN},
    "placebo": {"rule": "within-G1-class permutation of the flags", "draws": PLACEBO_B, "seed": PLACEBO_SEED,
                "p_max": PLACEBO_P_MAX},
    "train_qualify": "powered & crit 1 & crit 3 & placebo p <= 0.05 & censored <= 10 %; rank by CI upper bound",
    "val": {"min_sign": VAL_MIN_SIGN}, "test_min_side": TEST_MIN_SIDE, "max_censored": MAX_CENSORED,
}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


def make_params(host: str, flag: str, subset: str) -> dict:
    """One registered veto config (PREREG 5). Anything outside the grid raises."""
    if (host, flag, subset) not in GRID_SPEC:
        raise ValueError(f"({host!r}, {flag!r}, {subset!r}) is not in the pre-registered grid {GRID_SPEC}")
    return {**FIXED, "host": host, "host_params": dict(HOST_PARAMS[host]), "host_pin": HOST_PINS[host],
            "flag": flag, "subset": subset}


GRID = [make_params(*s) for s in GRID_SPEC]
assert len(GRID) == 4           # PREREG 5 (<= 12 configs)


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['host']}|{p['flag']}|{p['subset']}"


def grid_index(key: str) -> int:
    return [config_key(p) for p in GRID].index(key)


def params_of(key: str) -> dict:
    return GRID[grid_index(key)]


class Q7Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def host_pin_problems() -> list[str]:
    """The hosts must be the ones the PREREG registered (a changed host is a new PS1 version)."""
    out = []
    for h in HOSTS:
        got = C.params_hash(HOST_PARAMS[h])
        if got != HOST_PINS[h]:
            out.append(f"{h} host params hash {got} != pinned {HOST_PINS[h]}")
    return out


# =========================================================================== flags and classes (AsOf only)


def _nz(v: Any) -> Any:
    return None if v is None or (isinstance(v, str) and not v.strip()) else v


def sfx0(snap: C.AsOf) -> bool:
    """PREREG 2.1: the mint lacks the app's ``pump`` vanity suffix. The mint is legal at every tau."""
    return not str(snap["mint"]).endswith(SUFFIX)


def cu_flag(snap: C.AsOf) -> bool | None:
    """PREREG 2.2: create_user != creator; None when either is NULL / empty or not yet legal at tau."""
    cr, cu = _nz(snap.get("creator")), _nz(snap.get("create_user"))
    if cr is None or cu is None:
        return None
    return bool(str(cu) != str(cr))


def class_facts(snap: C.AsOf) -> dict:
    """G1's class and instant flag at ``snap`` (PREREG 4: read at g + 140 s)."""
    f = G1.g1_features(snap, None)
    return {"g1_class": G1.classify(f)["g1_class"], "instant": f.get("instant"), "grad_delay_s": f.get("grad_delay_s")}


def coin_facts(ds: C.Dataset, mint: str) -> dict:
    """Every coin-level fact PS1 uses, read through AsOf at g + 140 s (all legal by then; static afterwards)."""
    cd = ds.coin(mint)
    s = ds.asof(mint, cd.g + CLASS_T_S)
    out = {"mint": mint, "g_ts": cd.g, "sfx0": sfx0(s), "cu": cu_flag(s),
           "creator": _nz(s.get("creator")), "create_user": _nz(s.get("create_user")),
           "token_program": _nz(s.get("token_program"))}
    out.update(class_facts(s))
    return out


FACT_COLS = ("mint", "g_ts", "sfx0", "cu", "creator", "create_user", "token_program", "g1_class", "instant",
             "grad_delay_s")


def facts_table(ds: C.Dataset) -> pd.DataFrame:
    return pd.DataFrame([coin_facts(ds, m) for m in ds.mints], columns=list(FACT_COLS))


ANN_COLS = ("sfx0", "cu", "g1_class", "instant")


def annotate(trades: pd.DataFrame, ds: C.Dataset, facts: pd.DataFrame) -> pd.DataFrame:
    """Host trades + the flags read AT THE DECISION (what a live veto sees) + G1's class / instant at g + 140 s."""
    by = facts.set_index("mint") if len(facts) else None
    rows = []
    for r in trades.itertuples(index=False):
        s = ds.asof(r.mint, r.t_dec)
        rows.append({"sfx0": sfx0(s), "cu": cu_flag(s), "g1_class": by.at[r.mint, "g1_class"],
                     "instant": by.at[r.mint, "instant"]})
    extra = pd.DataFrame(rows, columns=list(ANN_COLS), index=trades.index)
    return pd.concat([trades, extra], axis=1)


# =========================================================================== evaluation sets


def _tri(v: Any) -> bool | None:
    """True / False / None from a bool, numpy bool, 'True' / 'False' (CSV) or NaN."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (float, np.floating)) and math.isnan(float(v)):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        return True if s == "true" else (False if s == "false" else None)
    if isinstance(v, (int, np.integer)):
        return bool(v)
    return None


def eval_set(t: pd.DataFrame, p: Mapping[str, Any]) -> tuple[pd.DataFrame, np.ndarray, int]:
    """(the config's evaluation set, its flags, trades left out because the flag is unknown) (PREREG 5)."""
    if not len(t):
        return t.iloc[0:0], np.zeros(0, bool), 0
    sel = np.ones(len(t), bool)
    if p["subset"] == "ORGANIC":
        sel &= (t["g1_class"].astype(str) == "ORGANIC").to_numpy(bool)
    fl = [_tri(v) for v in t[FLAG_COL[p["flag"]]]]
    known = np.array([v is not None for v in fl], bool)
    n_unknown = int((sel & ~known).sum())
    keep = sel & known
    sub = t[keep].reset_index(drop=True)
    f = np.array([bool(v) for v, k in zip(fl, keep) if k], bool)
    return sub, f, n_unknown


# =========================================================================== statistics


def stratified_placebo(r: np.ndarray, f: np.ndarray, strata: Sequence[Any], B: int = PLACEBO_B,
                       seed: int = PLACEBO_SEED, hide: bool = False) -> dict:
    """PREREG 6: B random vetoes, each flagging inside every G1-class stratum exactly as many trades as the real flag
    does there. p = (1 + #{d_b <= d}) / (1 + B), one-sided. ``hide`` (debug): strata counts only."""
    r = np.asarray(r, float)
    f = np.asarray(f, bool)
    s = np.asarray(["NONE" if x is None else str(x) for x in strata], object)
    uniq = sorted(set(s.tolist()))
    groups = {u: np.flatnonzero(s == u) for u in uniq}
    out: dict[str, Any] = {"B": int(B), "seed": int(seed),
                           "strata": {u: {"n": len(g), "n_flagged": int(f[g].sum())} for u, g in groups.items()}}
    n, nf = len(r), int(f.sum())
    if hide:
        return out
    if nf == 0 or nf == n:
        out.update({"diff": None, "p": None, "draws_mean": None, "draws_q05": None})
        return out
    d = float(r[f].mean() - r[~f].mean())
    rng = np.random.default_rng(seed)
    tot = float(r.sum())
    plan = [(g, int(f[g].sum())) for g in groups.values()]
    diffs = np.empty(B)
    for b in range(B):
        sf = 0.0
        for g, k in plan:
            if k == 0:
                continue
            if k == len(g):
                sf += float(r[g].sum())
            else:
                sf += float(r[rng.choice(g, size=k, replace=False)].sum())
        diffs[b] = sf / nf - (tot - sf) / (n - nf)
    p = (1.0 + float((diffs <= d + 1e-12).sum())) / (1.0 + B)
    out.update({"diff": d, "p": p, "draws_mean": float(diffs.mean()), "draws_q05": float(np.quantile(diffs, 0.05))})
    return out


def _pos(x: float | None) -> bool:
    """A usable positive span (not None, not NaN, > 0)."""
    return x is not None and math.isfinite(float(x)) and float(x) > 0


def _mean(r: np.ndarray, m: np.ndarray) -> float | None:
    return float(r[m].mean()) if m.any() else None


def dose_report(sub: pd.DataFrame, f: np.ndarray, *, B: int = DOSE_B, hide: bool = False, seed: int = 0) -> dict:
    """PREREG 7: SFX0 x instant cells, dose D = SFX0 + instant, and the interaction (SFX0 gap among instant - among
    slow) with a coin-bootstrap 95 % CI. ``hide`` (debug): cell counts only."""
    inst = np.array([_tri(v) for v in sub["instant"]], object) if len(sub) else np.zeros(0, object)
    is_i = np.array([v is True for v in inst], bool)
    is_s = np.array([v is False for v in inst], bool)
    unk = ~(is_i | is_s)
    r = sub["ret_net"].to_numpy(float) if (len(sub) and not hide) else np.zeros(len(sub))
    masks = {"sfx0|instant": f & is_i, "sfx0|slow": f & is_s, "sfx0|unknown": f & unk,
             "pump|instant": ~f & is_i, "pump|slow": ~f & is_s, "pump|unknown": ~f & unk}
    out: dict[str, Any] = {"cells": {k: {"n": int(m.sum())} for k, m in masks.items()}}
    if hide:
        return out
    for k, m in masks.items():
        out["cells"][k]["mean"] = _mean(r, m)
    dose = f.astype(int) + is_i.astype(int)
    known = ~unk
    dm = {d: _mean(r, known & (dose == d)) for d in (0, 1, 2)}
    out["dose_means"] = {str(d): v for d, v in dm.items()}
    out["dose_n"] = {str(d): int((known & (dose == d)).sum()) for d in (0, 1, 2)}
    out["monotone_non_increasing"] = (None if any(v is None for v in dm.values())
                                      else bool(dm[0] >= dm[1] >= dm[2]))
    cell = [masks["sfx0|instant"], masks["pump|instant"], masks["sfx0|slow"], masks["pump|slow"]]
    means = [_mean(r, m) for m in cell]
    if any(v is None for v in means):
        out.update({"interaction": None, "interaction_ci95": None})
        return out
    out["gap_instant"], out["gap_slow"] = means[0] - means[1], means[2] - means[3]
    out["interaction"] = out["gap_instant"] - out["gap_slow"]
    codes, _ = pd.factorize(pd.Series(list(sub["mint"])))
    nc = int(codes.max()) + 1
    sums = [np.bincount(codes, weights=r * m, minlength=nc) for m in cell]
    cnts = [np.bincount(codes, weights=m.astype(float), minlength=nc) for m in cell]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        w = np.bincount(rng.integers(0, nc, nc), minlength=nc).astype(float)
        c = [float(w @ x) for x in cnts]
        if min(c) <= 0:
            continue
        mm = [float(w @ s) / cc for s, cc in zip(sums, c)]
        vals.append((mm[0] - mm[1]) - (mm[2] - mm[3]))
    out["interaction_ci95"] = (float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))) \
        if len(vals) >= 20 else None
    return out


def by_class(sub: pd.DataFrame, f: np.ndarray, hide: bool) -> dict:
    """QUEUE rule 4: flagged / unflagged n (and mean) inside every G1 class at g + 140 s."""
    cls = sub["g1_class"].astype(str).to_numpy(object) if len(sub) else np.zeros(0, object)
    r = sub["ret_net"].to_numpy(float) if (len(sub) and not hide) else None
    out = {}
    for c in CLASSES:
        m = cls == c
        cell: dict[str, Any] = {"n_flagged": int((m & f).sum()), "n_unflagged": int((m & ~f).sum())}
        if r is not None:
            cell["flagged_mean"], cell["unflagged_mean"] = _mean(r, m & f), _mean(r, m & ~f)
        out[c] = cell
    return out


def _crit(verdict: Mapping[str, Any] | None, cid: int) -> dict | None:
    for c in ((verdict or {}).get("criteria") or []):
        if c.get("id") == cid:
            return c
    return None


def _veto(sub: pd.DataFrame, f: np.ndarray, B: int, oos: tuple[pd.DataFrame, np.ndarray] | None = None) -> dict:
    if not len(sub):
        return {"verdict": "UNDERPOWERED", "n_flagged": 0, "n_unflagged": 0, "criteria": []}
    kw = {} if oos is None else {"oos_host": oos[0], "oos_flagged": oos[1]}
    return C.verdict_veto(sub, f, B=min(B, 4000), **kw)


def evaluate(p: Mapping[str, Any], host_t: pd.DataFrame, *, B: int, hide: bool, placebo_b: int = PLACEBO_B,
             stress_t: pd.DataFrame | None = None, span_days: float | None = None,
             n_trials_total: int | None = None) -> dict:
    """One veto config on one split's annotated host trades. ``hide`` (debug): counts only, never returns."""
    sub, f, n_unk = eval_set(host_t, p)
    nf, nu = int(f.sum()), int((~f).sum())
    out: dict[str, Any] = {
        "config": config_key(p), "params_hash": C.params_hash(p), "host": p["host"], "flag": p["flag"],
        "subset": p["subset"], "n_host": len(host_t), "n_eval": len(sub), "n_unknown_flag": n_unk,
        "n_flagged": nf, "n_unflagged": nu, "flagged_share": (nf / len(sub)) if len(sub) else None,
        "flagged_per_day": (nf / span_days) if _pos(span_days) else None,
        "by_class": by_class(sub, f, hide),
        "placebo": stratified_placebo(sub["ret_net"].to_numpy(float) if (len(sub) and not hide) else np.zeros(len(sub)),
                                      f, list(sub["g1_class"]) if len(sub) else [], B=placebo_b, hide=hide),
    }
    if p["flag"] == "SFX0":
        out["dose"] = dose_report(sub, f, B=min(B, DOSE_B), hide=hide)
    if hide:
        out["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return out
    r = sub["ret_net"].to_numpy(float)
    coins = sub["mint"].to_numpy(object)
    out["flagged_mean"], out["unflagged_mean"] = _mean(r, f), _mean(r, ~f)
    out["eval_mean"] = float(r.mean()) if len(r) else None
    diff, ci = G1.boot_subset_diff(r, coins, f, ~f, B) if len(r) else (None, None)
    out["diff"], out["diff_ci95"] = diff, ci
    wins = r[r > 0].sum()
    out["winning_profit_removed"] = float(r[f & (r > 0)].sum() / wins) if wins > 0 else None
    out["pnl_usd"] = {"host_eval_set": float(r.sum() * SIZE_USD), "gated": float(r[~f].sum() * SIZE_USD)}
    out["host_censored_share"] = C.censored_share(host_t)
    out["veto_in_sample"] = _veto(sub, f, B)
    g = sub[~f]
    d = C.describe(g, B=B, n_trials_total=n_trials_total) if len(g) else {"n": 0}
    out["gated"] = {k: d.get(k) for k in ("n", "n_coins", "mean", "median", "win_rate", "ci90", "ci90_block",
                                          "mean_without_top2", "censored_share", "deflated_sharpe")}
    if stress_t is not None and len(stress_t):
        ss, sf, _ = eval_set(stress_t, p)
        rs = ss["ret_net"].to_numpy(float)
        out["stress_costs_x1.5"] = {"n": len(ss), "flagged_mean": _mean(rs, sf), "unflagged_mean": _mean(rs, ~sf),
                                    "diff": (_mean(rs, sf) - _mean(rs, ~sf)) if sf.any() and (~sf).any() else None}
    return out


# =========================================================================== pre-registered decisions (PREREG 8)


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """Qualify each config (powered, veto criteria 1 and 3, placebo p, censored); shortlist the top 2 by the 95 % CI
    upper bound of the difference (ties: grid order)."""
    rows = []
    for p in GRID:
        k = config_key(p)
        e = evals[k]
        ve = e.get("veto_in_sample") or {}
        c1, c3 = _crit(ve, 1), _crit(ve, 3)
        powered = e["n_flagged"] >= VETO_MIN and e["n_unflagged"] >= VETO_MIN
        pl = (e.get("placebo") or {}).get("p")
        cens = e.get("host_censored_share")
        checks = {"powered": powered, "crit1": bool(c1 and c1["pass"]), "crit3": bool(c3 and c3["pass"]),
                  "placebo": pl is not None and pl <= PLACEBO_P_MAX,
                  "censored": cens is not None and cens <= MAX_CENSORED}
        rows.append({"config": k, "grid_index": grid_index(k), "qualifies": all(checks.values()), "checks": checks,
                     "n_flagged": e["n_flagged"], "n_unflagged": e["n_unflagged"], "diff": e.get("diff"),
                     "ci95_hi": (c1 or {}).get("ci95", (None, None))[1] if c1 else None,
                     "win_removed": (c3 or {}).get("value"), "placebo_p": pl, "censored": cens})
    q = sorted((r for r in rows if r["qualifies"]), key=lambda r: (r["ci95_hi"], r["grid_index"]))[:2]
    dec: dict[str, Any] = {"rows": rows}
    if q:
        sl = [params_of(r["config"]) for r in q]
        hosts = [h for h in HOSTS if any(p["host"] == h for p in sl)]
        dec.update({"verdict": "SHORTLISTED", "shortlist": [r["config"] for r in q],
                    "shortlist_hashes": {HYP: [C.params_hash(p) for p in sl],
                                         **{HYP_HOST[h]: [C.params_hash(HOST_PARAMS[h])] for h in hosts}}})
        return dec
    if any(r["checks"]["powered"] for r in rows):
        dec.update({"verdict": "NO_CONFIG", "reason": "powered configs failed their TRAIN bars"})
    else:
        dec.update({"verdict": "UNDERPOWERED_TRAIN",
                    "reason": f"no config reached {VETO_MIN} flagged and {VETO_MIN} unflagged trades"})
    dec["shortlist"], dec["shortlist_hashes"] = [], {}
    return dec


def decide_val(e: Mapping[str, Any]) -> dict:
    nf, nu = e["n_flagged"], e["n_unflagged"]
    fm, um = e.get("flagged_mean"), e.get("unflagged_mean")
    c1 = _crit(e.get("veto_in_sample"), 1)
    if nf < VAL_MIN_SIGN or fm is None or um is None:
        v = "UNDERPOWERED_VAL"
    elif fm >= um:
        v = "FAIL_VAL"
    elif nf < VETO_MIN or nu < VETO_MIN:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED" if (c1 and c1["pass"]) else "FAIL_VAL"
    return {"verdict": v, "n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm, "unflagged_mean": um,
            "diff": e.get("diff"), "proceed": v in PROCEED_VAL}


def pick_candidate(decisions: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The one config that goes to TEST: SELECTED before SELECTED_UNDERPOWERED, then the lower VAL difference."""
    ok = [(k, d) for k, d in decisions.items() if d.get("proceed")]
    if not ok:
        return None
    ok.sort(key=lambda kd: (0 if kd[1]["verdict"] == "SELECTED" else 1,
                            kd[1]["diff"] if kd[1].get("diff") is not None else math.inf, grid_index(kd[0])))
    return ok[0][0]


def combine(formal: str, extras: Sequence[Mapping[str, Any]]) -> str:
    """FAIL > UNDERPOWERED > INCOMPLETE > PASS (PREREG 8 TEST / CONFIRM)."""
    if formal == "FAIL" or any(e["pass"] is False for e in extras):
        return "FAIL"
    if formal == "UNDERPOWERED":
        return "UNDERPOWERED"
    if formal != "PASS" or any(e["pass"] is None for e in extras):
        return "INCOMPLETE"
    return "PASS"


def test_extras(e_test: Mapping[str, Any]) -> list[dict]:
    nf, nu = e_test["n_flagged"], e_test["n_unflagged"]
    fm, um = e_test.get("flagged_mean"), e_test.get("unflagged_mean")
    ok = None if (nf < TEST_MIN_SIDE or nu < TEST_MIN_SIDE or fm is None or um is None) else bool(fm < um)
    return [{"id": "PS1.1", "name": "TEST sign: flagged mean < unflagged mean", "pass": ok,
             "value": {"flagged_mean": fm, "unflagged_mean": um, "n_flagged": nf, "n_unflagged": nu}}]


def confirm_extras(e_conf: Mapping[str, Any]) -> list[dict]:
    pl = (e_conf.get("placebo") or {}).get("p")
    cens = e_conf.get("host_censored_share")
    return [{"id": "PS1.2", "name": f"placebo p <= {PLACEBO_P_MAX}", "pass": None if pl is None else bool(pl <= PLACEBO_P_MAX),
             "value": pl},
            {"id": "PS1.3", "name": f"censored share <= {MAX_CENSORED:.0%}",
             "pass": None if cens is None else bool(cens <= MAX_CENSORED), "value": cens}]


def final_decision(t: pd.DataFrame, p: Mapping[str, Any]) -> dict:
    """FINAL: flagged mean < unflagged mean on the census thirds PS1 never looked at; the debug third apart."""
    def cell(x: pd.DataFrame) -> dict:
        sub, f, unk = eval_set(x, p)
        r = sub["ret_net"].to_numpy(float) if len(sub) else np.zeros(0)
        fm, um = _mean(r, f), _mean(r, ~f)
        return {"n_flagged": int(f.sum()), "n_unflagged": int((~f).sum()), "n_unknown_flag": unk,
                "flagged_mean": fm, "unflagged_mean": um,
                "flagged_worse": None if fm is None or um is None else bool(fm < um)}
    sp = t["split"].astype(str) if len(t) else pd.Series(dtype=str)
    judged = cell(t[sp.isin(FINAL_JUDGED)] if len(t) else t)
    per = {s: cell(t[sp == s]) for s in C.FINAL_SPLITS} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), **judged, "per_third": per,
            "design_third_note": f"{FINAL_DESIGN}: the debug third, reported apart, not judged"}


# =========================================================================== structure (counts only, any split)


def structure_counts(facts: pd.DataFrame) -> dict:
    """Coin-level counts of the flags, the classes and their crosstabs (no outcomes)."""
    if not len(facts):
        return {"n_coins": 0}
    s = facts["sfx0"].astype(bool)
    cu = facts["cu"].map(_tri)
    inst = facts["instant"].map(_tri)
    known = cu.notna()

    def lab(v):
        t = _tri(v)
        return "unknown" if t is None else str(t)
    return {
        "n_coins": len(facts), "sfx0": int(s.sum()), "sfx0_share": float(s.mean()),
        "cu_known": int(known.sum()), "cu_true": int((cu == True).sum()),
        "cu_share_of_known": float((cu[known] == True).mean()) if known.any() else None,
        "instant": {lab(k): int(v) for k, v in inst.map(lab).value_counts().items()},
        "classes": {str(k): int(v) for k, v in facts["g1_class"].value_counts().items()},
        "sfx0_by_class": {c: {"n": int((facts["g1_class"] == c).sum()), "sfx0": int(((facts["g1_class"] == c) & s).sum())}
                          for c in CLASSES},
        "sfx0_by_instant": {k: {"n": int((inst.map(lab) == k).sum()), "sfx0": int(((inst.map(lab) == k) & s).sum())}
                            for k in ("True", "False", "unknown")},
        "cu_by_sfx0": {k: {"cu_true": int(((cu == True) & (s == sv)).sum()),
                           "cu_false": int(((cu == False) & (s == sv)).sum()),
                           "cu_unknown": int((cu.isna() & (s == sv)).sum())} for k, sv in (("sfx0", True), ("pump", False))},
    }


def cu_meaning(facts: pd.DataFrame, k: int = CU_LIST_N) -> dict:
    """PREREG 2.3: what CU is on the coins at hand (structure only) and the pre-registered withdrawal rule."""
    if not len(facts):
        return {"n_cu": 0, "rule": "no coins", "withdraw_config4": None}
    cu = facts["cu"].map(_tri)
    known = cu.notna()
    share = float((cu[known] == True).mean()) if known.any() else None
    users = facts["create_user"].dropna().value_counts()
    creators = facts["creator"].dropna().value_counts()
    creator_set = set(creators.index)
    rows = facts[cu == True]
    listing = []
    for r in rows.head(k).itertuples(index=False):
        listing.append({"mint": r.mint, "creator": r.creator, "create_user": r.create_user,
                        "signer_coins": int(users.get(r.create_user, 0)), "creator_coins": int(creators.get(r.creator, 0)),
                        "signer_is_another_coins_creator": bool(r.create_user in creator_set),
                        "sfx0": bool(r.sfx0), "grad_delay_s": r.grad_delay_s, "instant": _tri(r.instant),
                        "token_program": r.token_program, "g1_class": r.g1_class})
    lo, hi = CU_SHARE_BOUNDS
    withdraw = None if share is None else bool(share < lo or share > hi)
    sub = rows if len(rows) else facts.iloc[0:0]
    return {"n_known": int(known.sum()), "n_cu": len(rows), "cu_share_of_known": share,
            "rule": f"withdraw config 4 if the CU share of known coins is < {lo:.0%} or > {hi:.0%}",
            "withdraw_config4": withdraw,
            "summary": {"signers_on_1_coin": int(sum(1 for x in sub["create_user"] if users.get(x, 0) == 1)),
                        "signers_on_2plus_coins": int(sum(1 for x in sub["create_user"] if users.get(x, 0) >= 2)),
                        "signer_is_another_coins_creator": int(sum(1 for x in sub["create_user"] if x in creator_set)),
                        "sfx0": int(sub["sfx0"].astype(bool).sum()) if len(sub) else 0,
                        "instant": int(sum(1 for x in sub["instant"] if _tri(x) is True)),
                        "token_programs": {str(a): int(b) for a, b in sub["token_program"].value_counts(dropna=False).items()}},
            "coins": listing}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and the common data-contract problems."""
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


def _test_verdict(out_dir: Path) -> str | None:
    return ((_read_json(Path(out_dir) / "test.json") or {}).get("decision") or {}).get("verdict")


def _confirm_verdict(out_dir: Path) -> str | None:
    return ((_read_json(Path(out_dir) / "confirm.json") or {}).get("decision") or {}).get("verdict")


def candidate_of(out_dir: Path) -> str | None:
    return ((_read_json(Path(out_dir) / "val.json") or {}).get("decision") or {}).get("candidate")


def stage_plan(stage: str, out_dir: Path = OUT_DIR, shortlist_path: Path | None = None) -> list[dict]:
    """The veto configs the stage evaluates (TRAIN: the grid; VAL: the shortlist; later: the VAL candidate)."""
    if stage in ("debug", "train"):
        return list(GRID)
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        return []
    if stage == "val":
        return [dict(c) for c in sl["configs"]]
    cand = candidate_of(out_dir)
    return [dict(c) for c in sl["configs"] if config_key(c) == cand]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Q7Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Q7Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Q7Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Q7Refused("PREREG.md changed after the first official TRAIN run; record changes in Q7/AMENDMENTS.md as a "
                        "new version instead")
    pins = host_pin_problems()
    if pins:
        raise Q7Refused("host pins (PREREG 3): " + "; ".join(pins))
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Q7Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Q7Refused("TRAIN already ran on complete data (Q7/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Q7Refused("no TRAIN result (Q7/train.json): run --stage train first")
    if train.get("provisional"):
        raise Q7Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    dec = train.get("decision") or {}
    if dec.get("verdict") != "SHORTLISTED":
        raise Q7Refused(f"TRAIN decision {dec.get('verdict')}: PS1 stopped before VAL")
    for h, want in (dec.get("shortlist_hashes") or {}).items():
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Q7Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(want):
            raise Q7Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Q7Refused("VAL already ran (Q7/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Q7Refused("no VAL result (Q7/val.json): TEST needs a VAL decision first")
    if not candidate_of(out_dir):
        raise Q7Refused(f"VAL decision {(val.get('decision') or {}).get('verdict')}: no candidate, PS1 stopped at VAL")
    if stage == "test" and not _trades_path(out_dir, "val", False).exists():
        raise Q7Refused("Q7/val_trades.csv missing: the TEST verdict takes criteria 1 and 3 from the VAL trades")
    if stage in ("confirm", "final"):
        if not (out_dir / "test.json").exists():
            raise Q7Refused(f"never {stage.upper()} before TEST: run --stage test first")
        if _test_verdict(out_dir) == "FAIL":
            raise Q7Refused(f"the TEST verdict is FAIL: PS1 stopped, {stage.upper()} is not spent")
    if stage == "final" and (out_dir / "confirm.json").exists() and _confirm_verdict(out_dir) != "PASS":
        raise Q7Refused(f"CONFIRM verdict {_confirm_verdict(out_dir)}: PS1 stopped, FINAL is not spent")
    if (out_dir / f"{stage}.json").exists():
        raise Q7Refused(f"{stage.upper()} already ran (Q7/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and not r.get("debug")
           and C.split_group(r.get("split", "")) == C.split_group(split) for r in _runs(ledger_path)):
        raise Q7Refused(f"PS1 already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Q7Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    info["candidate"] = candidate_of(out_dir)
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


def host_summary(res: C.Result, t: pd.DataFrame, *, B: int, hide: bool, span: float,
                 n_trials_total: int | None) -> dict:
    out: dict[str, Any] = {"hypothesis": res.meta["hypothesis"], "params_hash": C.params_hash(res.meta["params"]),
                           "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")},
                           "n": len(t), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
                           "per_day": (len(t) / span) if _pos(span) else None,
                           "by_class_n": {str(k): int(v) for k, v in t["g1_class"].value_counts().items()} if len(t) else {},
                           "sfx0_n": int(t["sfx0"].astype(bool).sum()) if len(t) else 0,
                           "cu_n": {"true": int(sum(1 for v in t["cu"] if _tri(v) is True)),
                                    "false": int(sum(1 for v in t["cu"] if _tri(v) is False)),
                                    "unknown": int(sum(1 for v in t["cu"] if _tri(v) is None))} if len(t) else {},
                           "entry_age_min_median": float(t["age_dec_s"].median() / 60.0) if len(t) else None,
                           "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0}
    if hide:
        out["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return out
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    out.update({k: d.get(k) for k in ("mean", "median", "win_rate", "ci90", "ci95", "ci90_block", "censored_share",
                                       "mean_without_top2", "reasons")})
    out["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    out["auto_rejections"] = C.auto_rejections(res)
    return out


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return Path(out_dir) / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, ann: Mapping[str, pd.DataFrame]) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    frames = [t.reset_index(drop=True).assign(host=h) for h, t in ann.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, host: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["host"] == host].reset_index(drop=True)


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              placebo_b: int = PLACEBO_B, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Q7/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "q7_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    cov_notes: list[str] = []
    if not (debug or _skip_coverage or stage == "final"):
        ok, cov_notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Q7Refused(f"{split} data incomplete: " + "; ".join(cov_notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov and "usable" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Q7Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_plan(stage, out_dir, shortlist_path)
    if not configs:
        raise Q7Refused("no configs to run (shortlist missing or malformed, or no candidate)")
    hosts = [h for h in HOSTS if any(p["host"] == h for p in configs)]

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for h in hosts:
                    C._check_run_allowed(HYP_HOST[h], HOST_PARAMS[h], split, ledger_path, shortlist_path)
                for p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Q7Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        if ds is None:
            cen = census if census is not None else C.Census.load()
            ds = C.load(split, flow=flow, census=cen, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        facts = facts_table(ds)
        span = _span_days(ds)
        doc: dict[str, Any] = {
            "hypothesis": HYP, "version": VERSION, "stage": stage, "split": split, "utc": C.utc_str(time.time()),
            "provisional": provisional, "debug_only": debug, "prereg_sha256": info["prereg_sha256"],
            "rerun_reason": rerun_reason, "q7_sha256": _sha(Path(__file__)), "common_sha256": _sha(Path(C.__file__)),
            "host_pins": dict(HOST_PINS), "coverage_notes": cov_notes, "n_coins": len(ds), "span_days": span,
            "configs_run": [config_key(p) for p in configs], "hosts_run": hosts,
            "structure": structure_counts(facts)}
        if stage in ("debug", "train"):
            doc["cu_meaning"] = cu_meaning(facts)
        results = {h: C.backtest(HOST_FN[h], split, HOST_PARAMS[h], hypothesis=HYP_HOST[h], ds=ds, cfg=FILL,
                                 placebo=False, stress=STRESS, declarations=DECL, ledger_path=ledger_path,
                                 shortlist_path=shortlist_path) for h in hosts}
        ann = {h: annotate(r.trades, ds, facts) for h, r in results.items()}
        stress_ann = {h: annotate(r.stress["costs_x1.5"], ds, facts) for h, r in results.items()}
        n_tr = C.n_trials(ledger_path)
        doc["hosts"] = {h: host_summary(results[h], ann[h], B=B, hide=debug, span=span, n_trials_total=n_tr)
                        for h in hosts}
        evals = {}
        for p in configs:
            e = evaluate(p, ann[p["host"]], B=B, hide=debug, placebo_b=placebo_b, stress_t=stress_ann[p["host"]],
                         span_days=span, n_trials_total=n_tr)
            e["trial"] = C.record_run(HYP, p, split, {"n": e["n_eval"], "mean": None if debug else e.get("unflagged_mean")},
                                      ledger_path, debug=debug)
            evals[config_key(p)] = e
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, ann)
        # ---- decisions (PREREG 8)
        if debug:
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, [params_of(k) for k in dec["shortlist"]], path=shortlist_path,
                                  ledger_path=ledger_path, note=f"{VERSION}: PREREG 8 rule")
                for h in HOSTS:
                    if HYP_HOST[h] in dec["shortlist_hashes"]:
                        C.write_shortlist(HYP_HOST[h], [HOST_PARAMS[h]], path=shortlist_path, ledger_path=ledger_path,
                                          note=f"{VERSION}: fixed host")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            per = {k: decide_val(e) for k, e in evals.items()}
            cand = pick_candidate(per)
            doc["decision"] = {"verdict": "CANDIDATE" if cand else "STOPPED", "candidate": cand, "per_config": per}
        elif stage in ("test", "confirm"):
            p = configs[0]
            k = config_key(p)
            own = ann[p["host"]]
            sub, f, _ = eval_set(own, p)
            if stage == "test":
                vt = _read_trades(out_dir, "val", p["host"])
                vs, vf, _ = eval_set(vt if vt is not None else own.iloc[0:0], p)
                formal = _veto(vs, vf, B, oos=(sub, f))
                extras = test_extras(evals[k])
            else:
                formal = _veto(sub, f, B, oos=(sub, f))
                extras = confirm_extras(evals[k])
            doc["decision"] = {"verdict": combine(formal["verdict"], extras), "candidate": k, "formal_veto": formal,
                               "extras": extras}
        elif stage == "final":
            p = configs[0]
            doc["decision"] = {**final_decision(ann[p["host"]], p), "candidate": config_key(p)}
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"q7 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: PS1's ONE look (host and veto inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Q7Refused(str(e)) from e


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
    """PS1's status from every stage written so far (``pending`` = the stage being written)."""
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
        return "NO VETO (nothing qualified on TRAIN)"
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vd = va.get("decision") or {}
    cand = vd.get("candidate")
    if not cand:
        per = [d.get("verdict") for d in (vd.get("per_config") or {}).values()]
        if per and all(v == "UNDERPOWERED_VAL" for v in per):
            return "UNDERPOWERED (VAL)"
        return "NO VETO (failed VAL)"
    te = doc("test")
    if not te:
        return f"PENDING TEST ({cand})"
    tv = (te.get("decision") or {}).get("verdict")
    if tv == "FAIL":
        return f"NO VETO (TEST FAIL, {cand})"
    co = doc("confirm")
    if not co:
        return f"PENDING CONFIRM ({cand}; TEST {tv})"
    cv = (co.get("decision") or {}).get("verdict")
    if cv == "UNDERPOWERED":
        return f"UNDERPOWERED (CONFIRM, {cand})"
    if cv != "PASS":
        return f"NO VETO (CONFIRM {cv}, {cand})"
    fi = doc("final")
    if not fi:
        return f"PENDING FINAL ({cand})"
    fw = (fi.get("decision") or {}).get("flagged_worse")
    return f"VETO ({cand})" if fw else f"NO VETO (FINAL, {cand})"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def _num(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def render_md(doc: Mapping[str, Any]) -> str:
    L = [f"# PS1 (q7) {doc['stage']} ({doc['split']})", "",
         (f"Run {doc['utc']} UTC, {doc.get('runtime_s')} s. Version `{doc['version']}`, PREREG sha256 "
         f"`{doc['prereg_sha256'][:12]}`, common.py `{doc['common_sha256'][:12]}`. Trials in the ledger: "
         f"{doc.get('n_trials_total')}. **Overall: {doc.get('overall')}.**"), ""]
    if doc.get("provisional"):
        L += ["**PROVISIONAL: partial TRAIN data, no lock and no shortlist written.**", ""]
    if doc.get("debug_only"):
        L += ["**DEBUG (census TRAIN third): counts only. Returns, exit reasons and decisions are hidden.**", ""]
    s = doc.get("structure") or {}
    L += ["## Structure (coins, no outcomes)", "",
          f"- Usable coins: {doc['n_coins']} over {_num(doc.get('span_days'), 2)} days of creation.",
          f"- SFX0 (no `pump` suffix): {s.get('sfx0')} ({_num(100 * (s.get('sfx0_share') or 0))} %).",
          (f"- CU known {s.get('cu_known')}, CU true {s.get('cu_true')} "
          f"({_num(100 * (s.get('cu_share_of_known') or 0))} % of known)."),
          f"- Instant: {s.get('instant')}. Classes at g + 140 s: {s.get('classes')}.",
          f"- SFX0 by class: {s.get('sfx0_by_class')}.",
          f"- SFX0 by instant: {s.get('sfx0_by_instant')}.", f"- CU by SFX0: {s.get('cu_by_sfx0')}.", ""]
    cm = doc.get("cu_meaning")
    if cm:
        L += ["## CU meaning check (PREREG 2.3, structure only)", "",
              (f"- {cm.get('n_cu')} CU coins of {cm.get('n_known')} known (share "
              f"{_num(100 * (cm.get('cu_share_of_known') or 0))} %). Rule: {cm.get('rule')}. Withdraw config 4: "
              f"**{cm.get('withdraw_config4')}**."), f"- Summary: {cm.get('summary')}.", "",
              ("| mint | signer coins | creator coins | signer is another coin's creator | SFX0 | grad delay s | "
              "token program | class |"), "|---|---:|---:|---|---|---:|---|---|"]
        for c in cm.get("coins", []):
            L.append(f"| `{c['mint'][:10]}…{c['mint'][-4:]}` | {c['signer_coins']} | {c['creator_coins']} | "
                     f"{c['signer_is_another_coins_creator']} | {c['sfx0']} | {_num(c['grad_delay_s'], 0)} | "
                     f"`{str(c['token_program'])[:8]}…` | {c['g1_class']} |")
        L.append("")
    L += ["## Hosts", "", ("| Host | trades | per day | median decision age (min) | SFX0 | CU t/f/unknown | by class | "
          "mean | 95% CI | costs x1.5 | horizon exits |"), "|---|---:|---:|---:|---:|---|---|---:|---|---:|---:|"]
    for h, e in (doc.get("hosts") or {}).items():
        cu = e.get("cu_n") or {}
        L.append(f"| {h} | {e['n']} | {_num(e.get('per_day'))} | {_num(e.get('entry_age_min_median'))} | "
                 f"{e.get('sfx0_n')} | {cu.get('true')}/{cu.get('false')}/{cu.get('unknown')} | {e.get('by_class_n')} | "
                 f"{_pct(e.get('mean'))} | {_ci(e.get('ci95'))} | {_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                 f"{e.get('horizon_exits')} |")
    L += ["", "## Veto configs", "", ("| Config | eval set | unknown | flagged | unflagged | flagged/day | flagged mean | "
          "unflagged mean | diff [95% CI] | win profit removed | placebo p | in-sample veto |"),
          "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|"]
    for k, e in (doc.get("configs") or {}).items():
        L.append(f"| {k} | {e['n_eval']} | {e['n_unknown_flag']} | {e['n_flagged']} | {e['n_unflagged']} | "
                 f"{_num(e.get('flagged_per_day'))} | {_pct(e.get('flagged_mean'))} | {_pct(e.get('unflagged_mean'))} | "
                 f"{_pct(e.get('diff'))} {_ci(e.get('diff_ci95'))} | "
                 f"{_num(None if e.get('winning_profit_removed') is None else 100 * e['winning_profit_removed'])} % | "
                 f"{_num((e.get('placebo') or {}).get('p'), 3)} | {(e.get('veto_in_sample') or {}).get('verdict', 'n/a')} |")
    L += ["", "### By G1 class (flagged / unflagged)", ""]
    for k, e in (doc.get("configs") or {}).items():
        parts = []
        for c, v in (e.get("by_class") or {}).items():
            if v["n_flagged"] or v["n_unflagged"]:
                m = (f" ({_pct(v.get('flagged_mean'))} / {_pct(v.get('unflagged_mean'))})"
                     if "flagged_mean" in v else "")
                parts.append(f"{c} {v['n_flagged']}/{v['n_unflagged']}{m}")
        L.append(f"- {k}: " + ("; ".join(parts) or "no trades"))
    L += ["", "### Dose report (SFX0 x instant)", ""]
    for k, e in (doc.get("configs") or {}).items():
        dz = e.get("dose")
        if not dz:
            continue
        cells = ", ".join(f"{c} {v['n']}" + (f" ({_pct(v.get('mean'))})" if "mean" in v else "")
                          for c, v in dz["cells"].items())
        extra = ""
        if "interaction" in dz:
            extra = (f" Dose means {dz.get('dose_means')}, monotone {dz.get('monotone_non_increasing')}; "
                     f"interaction {_pct(dz.get('interaction'))} {_ci(dz.get('interaction_ci95'))}.")
        L.append(f"- {k}: {cells}.{extra}")
    L += ["", "## Decision", "", "```", json.dumps(doc.get("decision"), indent=1, default=str)[:4000], "```", ""]
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PS1 (q7) 'pump' suffix veto: pre-registered stages; see Q7/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third, counts only (returns hidden)")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", default=None, help="TRAIN only: the data correction that justifies a re-run")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--bootstrap", type=int, default=10_000)
    a = ap.parse_args(argv)
    stage = "debug" if a.debug else a.stage
    if stage is None:
        ap.error("--stage or --debug is required")
    try:
        if a.check:
            info = check_prereqs(stage, rerun_reason=a.rerun_reason)
            print(json.dumps({"prerequisites": "ok", **info}, indent=1, default=str))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.bootstrap)
    except Q7Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"PS1 {stage}: wrote {OUT_DIR / (name + '.json')} and .md in {doc['runtime_s']} s")
    print(json.dumps({"structure": doc.get("structure"), "decision": doc.get("decision"), "overall": doc.get("overall")},
                     indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
