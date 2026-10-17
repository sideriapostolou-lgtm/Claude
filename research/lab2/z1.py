"""Z1: buy when the sellers run out while the price holds (seller exhaustion, B2 bars only).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Z1/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; the AGENT
column only once knowable; NULL stays None). Outcomes (trade returns) are never features.

Mechanism (PREREG 1): the post-graduation overhang of curve-bought supply is finite and front-loaded. In a window of
the last K completed bars, split into an early and a late half, Z1 calls a coin EXHAUSTED when

* the early half had a real selling wave (sell SOL >= 1 % of the pricing reserve, >= 1 seller a minute),
* sell SOL AND seller-minutes both fell by at least half,
* sells shrank faster than buys (the sell share of volume fell: not "everyone left"),
* the price held (close now >= close before the window) and the coin is not in D1's dip state (dd15 < 0.25).

Entry: first such decision at age 30-120 min on an ``alive`` coin; exits: 25 % stop and time exits filled on the next
bar at its low, the g + 178 min deadline, and (exit set ``sret60``) "the sellers came back".

CLI::

    python research/lab2/z1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/z1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/z1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/z1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/z1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/z1.py --stage final
    python research/lab2/z1.py --stage val --check             # prerequisites only

Each stage writes ``Z1/<stage>.json`` and ``Z1/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8 data
gates V1-V4, PREREG frozen after the first TRAIN run, provisional included).
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
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "z1-v1"
OUT_DIR = HERE / "Z1"
HYP = "Z1"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-7)
K_GRID = (10, 20)                    # window length in completed bars (halves of 5 and 10 minutes)
EXIT_GRID = ("t30", "t60", "sret60")
HOLD_S = {"t30": 1800.0, "t60": 3600.0, "sret60": 3600.0}
DECLINE_RATIO = 0.5                  # late half <= 0.5 x early half, for sell SOL AND seller-minutes
MIN_EARLY_SELL_FRAC_X = 0.01         # early-half sell SOL >= 1 % of the pricing reserve (alone ~2 % of price)
MIN_SELLERS_PER_MIN = 1.0            # early-half seller-minutes >= 1 per minute of the half
PRICE_HOLD_MIN_RET = 0.0             # close now >= close just before the window
DIP_WINDOW_BARS = 15                 # D1 E1's dd15 window
DIP_DD_MAX = 0.25                    # D1 E1's dip threshold: Z1 never enters while dd15 >= 0.25
AGE_MIN_S, AGE_MAX_S = 1800.0, 7200.0
STOP_PCT = 0.25
EXIT_BY_AGE_S = 178 * 60.0           # registered deadline: sell no later than g + 178 min (never censored)
SIZE_USD = 20.0
INSTANT_MAX_DELAY_S = 5.0            # stratum: instant graduate (placebo matching and reports only)
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 60, 40
MAX_CENSORED = C.MAX_CENSORED_SHARE
SHORTLIST_MAX = 2
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                 # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "decline_ratio": DECLINE_RATIO, "min_early_sell_frac_x": MIN_EARLY_SELL_FRAC_X,
    "min_sellers_per_min": MIN_SELLERS_PER_MIN, "price_hold_min_ret": PRICE_HOLD_MIN_RET,
    "dip_window_bars": DIP_WINDOW_BARS, "dip_dd_max": DIP_DD_MAX, "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S,
    "alive": "common.AsOf.alive() ($1.5k / 15 min, mcap $6k)", "stop_pct": STOP_PCT, "exit_by_age_s": EXIT_BY_AGE_S,
    "size_usd": SIZE_USD, "placebo": "alive, stratum-matched (instant / slow)",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(K: int, exit_set: str) -> dict:
    if int(K) not in K_GRID or exit_set not in EXIT_GRID:
        raise ValueError(f"(K={K}, exit={exit_set!r}) is not in the pre-registered grid")
    return {**FIXED, "K": int(K), "exit": exit_set, "max_hold_s": HOLD_S[exit_set]}


GRID = [make_params(K, e) for K in K_GRID for e in EXIT_GRID]
assert len(GRID) <= 12
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class Z1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"K{int(p['K'])}|{p['exit']}"


# =========================================================================== features (AsOf only)


def _k_end(snap: C.AsOf, k_end: int | None) -> int:
    k = snap.k
    return k if k_end is None else max(0, min(int(k_end), k))


def exhaustion(snap: C.AsOf, K: int, k_end: int | None = None) -> dict:
    """PREREG 3 on the last K completed bars at ``snap`` (or as of an earlier cutoff: the first ``k_end`` bars).

    -> {ok, fires, active, decline, share_falls, holds, no_dip, price_ok, S_E, S_L, N_E, N_L, B_E, B_L, share_E,
    share_L, X_ref, ret_K, dd15, k, K}. ``price_ok`` = holds and no_dip (the price-matched control's condition)."""
    K = int(K)
    h = K // 2
    k = _k_end(snap, k_end)
    out: dict[str, Any] = {"ok": False, "fires": False, "active": False, "decline": False, "share_falls": False,
                           "holds": False, "no_dip": False, "price_ok": False, "S_E": None, "S_L": None, "N_E": None,
                           "N_L": None, "B_E": None, "B_L": None, "share_E": None, "share_L": None, "X_ref": None,
                           "ret_K": None, "dd15": None, "k": k, "K": K}
    if k < max(K + 1, DIP_WINDOW_BARS):
        return out
    bars = snap.bars
    sell = np.asarray(bars.sell_sol[:k], float)
    ns = np.asarray(bars.n_sellers[:k], float)
    buy = np.asarray(bars.buy_sol[:k], float) - np.nan_to_num(np.asarray(bars.agent_buy_sol[:k], float), nan=0.0)
    buy = np.clip(buy, 0.0, None)
    c = np.asarray(bars.c[:k], float)
    hi = np.asarray(bars.h[:k], float)
    X = np.asarray(bars.X[:k], float)
    e, m = k - K, k - h                               # early half [e, m), late half [m, k)
    S_E, S_L = float(sell[e:m].sum()), float(sell[m:k].sum())
    N_E, N_L = float(ns[e:m].sum()), float(ns[m:k].sum())
    B_E, B_L = float(buy[e:m].sum()), float(buy[m:k].sum())
    sh_E = S_E / (S_E + B_E) if S_E + B_E > 0 else None
    sh_L = S_L / (S_L + B_L) if S_L + B_L > 0 else None
    X_ref = float(X[e - 1])
    ret = float(c[k - 1] / c[e - 1] - 1.0)
    dd = float(1.0 - c[k - 1] / hi[k - DIP_WINDOW_BARS:k].max())
    active = bool(S_E >= MIN_EARLY_SELL_FRAC_X * X_ref and N_E >= MIN_SELLERS_PER_MIN * (K - h))
    decline = bool(S_L <= DECLINE_RATIO * S_E and N_L <= DECLINE_RATIO * N_E)
    share_falls = bool(sh_E is not None and sh_L is not None and sh_L < sh_E)
    holds = bool(ret >= PRICE_HOLD_MIN_RET)
    no_dip = bool(dd < DIP_DD_MAX)
    out.update(ok=True, active=active, decline=decline, share_falls=share_falls, holds=holds, no_dip=no_dip,
               price_ok=holds and no_dip, fires=active and decline and share_falls and holds and no_dip,
               S_E=S_E, S_L=S_L, N_E=N_E, N_L=N_L, B_E=B_E, B_L=B_L, share_E=sh_E, share_L=sh_L, X_ref=X_ref,
               ret_K=ret, dd15=dd)
    return out


def stratum(snap: C.AsOf) -> str:
    """instant (graduated <= 5 s after creation; known at g) or slow (incl. creation not scanned: > 30 min)."""
    d = snap.get("grad_delay_s")
    return "instant" if d is not None and d <= INSTANT_MAX_DELAY_S else "slow"


def entry_decision(snap: C.AsOf, p: Mapping[str, Any]) -> tuple[bool, dict]:
    """``alive`` and EXHAUSTED (the age window is checked by :func:`strategy`)."""
    if not snap.alive():
        return False, {"alive": False}
    ex = exhaustion(snap, int(p["K"]))
    ex["alive"] = True
    return bool(ex["fires"]), ex


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    bars = snap.bars
    if len(bars) == 0:
        return 0
    return int(min(max((tau - int(bars.minute_ts[0])) // 60, 0), len(bars)))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """``sret60`` only: once >= h bars completed after the entry decision, exit when the last h completed bars have
    sell SOL >= S_E or seller-minutes >= N_E of the entry window. Placebo positions carry no state: S_E / N_E are
    recomputed from the bars completed at THEIR decision; when that early half fails the activity minimum the exit
    is off (no selling wave to compare with). Stop, time and deadline exits are mechanical (ExitSpec)."""
    if p["exit"] != "sret60":
        return None
    K = int(p["K"])
    h = K // 2
    k = snap.k
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    st = pos.state or {}
    if "S_E" in st:
        S_ref, N_ref, ref_ok = float(st["S_E"]), float(st["N_E"]), bool(st["active"])
    else:
        ex = exhaustion(snap, K, k_end=k_dec)
        S_ref, N_ref, ref_ok = ex["S_E"], ex["N_E"], bool(ex["active"])
    if not ref_ok or k - k_dec < h:
        return None
    bars = snap.bars
    S_R = float(np.asarray(bars.sell_sol[k - h:k], float).sum())
    N_R = float(np.asarray(bars.n_sellers[k - h:k], float).sum())
    if S_R >= S_ref or N_R >= N_ref:
        return C.Exit("sellers_return")
    return None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The Z1 strategy for common.backtest (one entry per coin)."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    ok, ex = entry_decision(snap, p)
    if not ok:
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=HOLD_S[p["exit"]], exit_by_age_s=EXIT_BY_AGE_S),
                   tag=stratum(snap), state={"S_E": ex["S_E"], "N_E": ex["N_E"], "active": ex["active"]})


# =========================================================================== controls


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe (PLAN 3.4 'same eligible coins'): alive."""
    return snap.alive()


def placebo_stratum(snap: C.AsOf) -> str:
    return stratum(snap)


def price_matched_ok(K: int):
    """Control isolating the seller part: alive AND the price part of EXHAUSTED (ret_K >= 0, dd15 < 0.25)."""
    def ok(snap: C.AsOf) -> bool:
        return snap.alive() and bool(exhaustion(snap, K)["price_ok"])
    ok.__name__ = f"price_matched_K{int(K)}"
    return ok


def placebo_controls(p: Mapping[str, Any]) -> dict:
    return {"price_matched": {"eligible": price_matched_ok(int(p["K"])), "strata": placebo_stratum},
            "unmatched": {"eligible": placebo_ok, "strata": None}}


# =========================================================================== evaluation


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, strata, ages, placebo counts) -- never returns,
    exit reasons or placebo outcomes."""
    t = res.trades
    ages = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_stratum_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "entry_age_min": {"30-45": int(((ages >= 0) & (ages < 45)).sum()), "45-60": int(((ages >= 45) & (ages < 60)).sum()),
                              "60-90": int(((ages >= 60) & (ages < 90)).sum()), "90-121": int((ages >= 90).sum())},
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


def _exit_rank(e: str) -> int:
    return EXIT_GRID.index(e) if e in EXIT_GRID else len(EXIT_GRID)


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 7: qualifiers (sample, mean, top-2, both matched controls, censoring), ranked by the coin-bootstrap
    90 % CI lower bound; shortlist = the top 2 in rank order."""
    rows = []
    for p in GRID:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        pm = ((e.get("controls") or {}).get("price_matched") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and pm is not None and pm > 0
                and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "K": int(p["K"]), "exit": p["exit"], "powered": bool(powered),
                     "qualifies": bool(good), "n": e["n"], "coins": e["n_coins"], "mean": e.get("mean"),
                     "mean_without_top2": e.get("mean_without_top2"), "ci90_lo": ci[0] if ci else None,
                     "placebo_diff": pc, "price_matched_diff": pm, "censored_share": cs})
    q = [r for r in rows if r["qualifies"]]
    if q:
        q.sort(key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"], r["K"],
                              _exit_rank(r["exit"])))
        top = q[:SHORTLIST_MAX]
        sl = [make_params(r["K"], r["exit"]) for r in top]
        return {"verdict": "SHORTLISTED", "rows": rows, "ranked": [r["config"] for r in top], "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / matched-control / censoring bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max(r['n'] for r in rows)} trades, {max(r['coins'] for r in rows)} coins)")
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
    """PREREG 8 VAL: VAL is a filter, never a ranking. Candidate = the TRAIN rank-1 config if it proceeds, else the
    rank-2 config if it proceeds; else FAIL_VAL (some config failed) or UNDERPOWERED_VAL."""
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
    return False, f"TEST mean {mean} <= 0 on {n} trades: Z1 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Z1 never looked at (the TRAIN third hosted the debug run: reported apart)."""
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
    """[(role, params)] the stage runs: the grid (debug / train), the shortlist in rank order (val), the VAL candidate
    (test / confirm / final)."""
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
    """Raise :class:`Z1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Z1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Z1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    # The first TRAIN run of ANY kind freezes PREREG.md: a provisional run shows TRAIN returns too. A train_prelim.json
    # without a lock (written before that rule) pins the sha it recorded.
    frozen = (lock or {}).get("sha256") or (_read_json(out_dir / "train_prelim.json") or {}).get("prereg_sha256")
    if frozen and frozen != _sha(prereg):
        raise Z1Refused("PREREG.md changed after the first TRAIN run (provisional runs included); record changes in "
                        "Z1/AMENDMENTS.md as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Z1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(frozen),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Z1Refused("TRAIN already ran on complete data (Z1/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Z1Refused("no TRAIN result (Z1/train.json): run --stage train first")
    if train.get("provisional"):
        raise Z1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Z1Refused(f"TRAIN decision {tv}: Z1 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Z1Refused("no VAL shortlist for Z1 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise Z1Refused("the Z1 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Z1Refused("VAL already ran (Z1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Z1Refused(f"no VAL result (Z1/val.json): {stage.upper()} needs a VAL decision first")
    vd = val.get("decision") or {}
    if vd.get("verdict") not in PROCEED_VAL:
        raise Z1Refused(f"VAL decision {vd.get('verdict')}: Z1 stopped (PLAN 8 rule 7 input); {stage.upper()} is not "
                        "spent")
    if vd.get("candidate_hash") not in sl.get("hashes", []):
        raise Z1Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Z1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Z1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Z1Refused(f"{stage.upper()} already ran (Z1/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise Z1Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Z1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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
    """Counts only (no prices, no returns): coins (and coin-minutes) where each EXHAUSTED condition holds at some
    decision in the age window, per K."""
    conds = ("alive", "active", "decline", "share_falls", "holds", "no_dip", "fires", "alive_and_fires")
    coins = {K: {c: set() for c in conds} for K in K_GRID}
    minutes = {K: {c: 0 for c in conds} for K in K_GRID}
    strata: dict[str, int] = {}
    n_dec = 0
    for m in ds.mints:
        cd = ds.coin(m)
        first = True
        for j in range(1, C.N_BARS + 1):          # the engine's decision grid: t = bar_start(j) + 20 s
            t = float(cd.bar_start(j) + C.GRID_OFFSET_S)
            if t - cd.g < AGE_MIN_S or t - cd.g > AGE_MAX_S:
                continue
            snap = ds.asof(m, t)
            if first:
                s = stratum(snap)
                strata[s] = strata.get(s, 0) + 1
                first = False
            n_dec += 1
            alive = snap.alive()
            for K in K_GRID:
                ex = exhaustion(snap, K)
                flags = {"alive": alive, **{c: bool(ex[c]) for c in conds[1:7]},
                         "alive_and_fires": alive and bool(ex["fires"])}
                for c, v in flags.items():
                    if v:
                        coins[K][c].add(m)
                        minutes[K][c] += 1
    return {"coins": len(ds), "strata": strata, "decision_minutes": n_dec,
            "coins_with_condition": {f"K{K}": {c: len(v) for c, v in coins[K].items()} for K in K_GRID},
            "coin_minutes_with_condition": {f"K{K}": dict(minutes[K]) for K in K_GRID}}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Z1/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "z1_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Z1Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Z1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Z1Refused("no configs to run (shortlist or VAL candidate missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Z1Refused(str(e)) from e
        if stage == "train":
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():      # the first TRAIN run, provisional or not, locks PREREG
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time()),
                                                                 "locked_by": "provisional TRAIN" if provisional
                                                                 else "TRAIN"}, indent=1))
            # archive, never overwrite, an official run
            if not provisional and rerun_reason and (out_dir / "train.json").exists():
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
        if debug:
            doc["event_counts"] = event_counts(ds)
        results: dict[str, C.Result] = {}
        for role, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok,
                                       placebo_strata=placebo_stratum, placebo_controls=placebo_controls(p),
                                       stress=STRESS, declarations=DECL, ledger_path=ledger_path,
                                       shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
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
                                  note=f"{VERSION}: PREREG 7, rank order {dec['ranked']}")
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

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"z1 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise Z1Refused(str(e)) from e


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


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# Z1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Z1 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (no returns)", "",
              f"- Coins {ec['coins']} (strata {ec['strata']}); decision minutes at ages 30-120: {ec['decision_minutes']}.",
              "", "| K | condition | coins | coin-minutes |", "|---|---|---:|---:|"]
        for kk, cc in ec["coins_with_condition"].items():
            for c, n in cc.items():
                L.append(f"| {kk} | {c} | {n} | {ec['coin_minutes_with_condition'][kk][c]} |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | strata | entry age (min) | placebo trades | controls | horizon exits | "
                  "entries/day |", "|---|---:|---:|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_stratum_n']} | {e['entry_age_min']} | "
                         f"{e['n_placebo']} | {e['n_controls']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "price-matched diff | unmatched diff | costs ×1.5 | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('price_matched') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('unmatched') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | {_pct(e.get('censored_share'), 0)} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, price-matched diff "
                 f"{_pct(r['price_matched_diff'])}, qualifies {r['qualifies']}.")
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
    ap = argparse.ArgumentParser(description="Z1 seller exhaustion: pre-registered stages; see "
                                             "research/lab2/Z1/PREREG.md")
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
    except Z1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
