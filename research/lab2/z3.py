"""Z3: buy the dead-cat bounce after a single-seller crash (a rug), B2 bars only. Expected: no edge.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Z3/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; NULL stays
None). Outcomes (trade returns, later prices) are never features.

Mechanism (PREREG 1): a completed minute bar whose CLOSE is >= 70 % below where the minute started (max(open, previous
close)), with a pigeonhole proof that one wallet sold >= 25 % of the pricing reserve X = x + v in that minute (more
than half of the 0.452 X outflow a 70 % drop needs), leaves a thin pool in which a few SOL of dip buying make a large
bounce. Z3 buys right after the crash (``now``) or after the first green minute (``confirm``) and holds 5, 15 or 60 min,
with a 50 % catastrophe stop; time and stop exits fill on the NEXT bar at its low; deadline g + 178 min.

The placebo is drawdown-matched: random coins at the same age that are >= 70 % under their high but had no crash in
the last 15 bars (same thin pool and fee tier, random time). The unmatched control is any coin at the same age.

CLI::

    python research/lab2/z3.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/z3.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/z3.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/z3.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/z3.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/z3.py --stage final
    python research/lab2/z3.py --stage val --check             # prerequisites only

Each stage writes ``Z3/<stage>.json`` and ``Z3/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
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
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "z3-v1"
OUT_DIR = HERE / "Z3"
HYP = "Z3"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-6)
CRASH_DROP = 0.70                    # close_j <= 0.30 x max(open_j, close_{j-1})
BIG_SELLER_FRAC_X = 0.25             # sell_sol / max(n_sellers, 1) >= 0.25 x X_{j-1}: one wallet supplied > half of
                                     # the 1 - sqrt(0.30) = 0.452 X outflow a 70 % drop needs
MIN_CRASH_BAR = 2                    # bar 0 is the partial graduation minute; ref needs a full previous bar
STATE_DD = 0.70                      # post-crash state (control): last close <= 0.30 x highest open / close so far
STATE_QUIET_BARS = 15                # ... and no CRASH bar among the last 15 completed bars
STATE_MIN_BARS = 3
ENTRY_GRID = ("now", "confirm")
HOLD_GRID_MIN = (5, 15, 60)
AGE_MIN_S, AGE_MAX_S = 420.0, 7200.0  # after the BOOST / AGENT window; >= 58 min of hold data before the deadline
STOP_PCT = 0.50                      # catastrophe stop (second rug)
EXIT_BY_AGE_S = 178 * 60.0           # registered deadline: sell no later than g + 178 min (never censored)
SIZE_USD = 20.0
DEPTH_TAGS = ((0.90, "d90"), (0.80, "d80"), (0.0, "d70"))
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 60, 40
MAX_CENSORED = C.MAX_CENSORED_SHARE
SHORTLIST_MAX = 2
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                 # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
# pre-registered predictions (PREREG 7): scored on TRAIN, never decisive
PRED_OPEN_FILL_BAR = 0.03
PRED_CONTROL_MARGIN = 0.06
G35_MARGIN = -0.10

FIXED = {
    "version": VERSION, "crash_drop": CRASH_DROP, "crash_on": "close vs max(open, previous close)",
    "big_seller_frac_x": BIG_SELLER_FRAC_X, "min_crash_bar": MIN_CRASH_BAR, "state_dd": STATE_DD,
    "state_quiet_bars": STATE_QUIET_BARS, "age_min_s": AGE_MIN_S, "age_max_s": AGE_MAX_S, "stop_pct": STOP_PCT,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD,
    "placebo": "drawdown-matched (post-crash state, no crash in 15 bars); unmatched control",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(entry: str, hold_min: int) -> dict:
    if entry not in ENTRY_GRID or int(hold_min) not in HOLD_GRID_MIN or int(hold_min) != hold_min:
        raise ValueError(f"(entry={entry!r}, hold={hold_min}) is not in the pre-registered grid")
    return {**FIXED, "entry": entry, "hold_min": int(hold_min), "max_hold_s": 60.0 * int(hold_min)}


GRID = [make_params(e, h) for e in ENTRY_GRID for h in HOLD_GRID_MIN]
assert len(GRID) <= 12
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "open_fills": dataclasses.replace(FILL, entry_fill="open", exit_fill="open")}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class Z3Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['entry']}|t{int(p['hold_min'])}"


# =========================================================================== features (AsOf only)


def crash_arrays(bars: C.Bars, lo: int, hi: int) -> dict | None:
    """PREREG 3 for completed bars j in [lo, hi) of ``bars`` (a :class:`common.Bars` = completed bars at tau).

    -> {j, ref, drop, X_before, big_sol, sell_sol, n_sellers, traded, crash, single, fires} (arrays) or None."""
    k = len(bars)
    lo, hi = max(int(lo), MIN_CRASH_BAR), min(int(hi), k)
    if lo >= hi:
        return None
    j = np.arange(lo, hi)
    o, c, X = (np.asarray(getattr(bars, n), float) for n in ("o", "c", "X"))
    ss, ns = np.asarray(bars.sell_sol, float), np.asarray(bars.n_sellers, float)
    tr = np.asarray(bars.traded, float) > 0
    ref = np.maximum(o[j], c[j - 1])
    with np.errstate(divide="ignore", invalid="ignore"):
        drop = np.where(np.isfinite(ref) & (ref > 0), 1.0 - c[j] / ref, np.nan)
    big = ss[j] / np.maximum(ns[j], 1.0)
    xb = X[j - 1]
    crash = tr[j] & np.isfinite(drop) & (drop >= CRASH_DROP)
    single = np.isfinite(xb) & (xb > 0) & (big >= BIG_SELLER_FRAC_X * xb)
    return {"j": j, "ref": ref, "drop": drop, "X_before": xb, "big_sol": big, "sell_sol": ss[j], "n_sellers": ns[j],
            "traded": tr[j], "crash": crash, "single": single, "fires": crash & single}


def crash_at(bars: C.Bars, j: int) -> dict:
    """CRASH / SINGLE-SELLER CRASH of one completed bar j -> scalars (``ok`` False when j is out of range)."""
    a = crash_arrays(bars, j, j + 1) if j >= 0 else None
    if a is None or not len(a["j"]):
        return {"j": int(j), "ok": False, "crash": False, "single": False, "fires": False, "drop": None, "ref": None,
                "X_before": None, "big_sol": None, "sell_sol": None, "n_sellers": None}
    out = {"j": int(j), "ok": True}
    for key in ("crash", "single", "fires"):
        out[key] = bool(a[key][0])
    for key in ("drop", "ref", "X_before", "big_sol", "sell_sol", "n_sellers"):
        v = float(a[key][0])
        out[key] = v if math.isfinite(v) else None
    return out


def depth_tag(drop: float | None) -> str:
    for lo, tag in DEPTH_TAGS:
        if drop is not None and drop >= lo:
            return tag
    return "d70"


def signal(snap: C.AsOf, entry: str) -> tuple[bool, dict]:
    """PREREG 4 at ``snap``: ``now`` = the bar that just completed is a SINGLE-SELLER CRASH; ``confirm`` = the bar
    before it is, and the last completed bar traded and closed above the crash close (the first green minute)."""
    bars = snap.bars
    k = len(bars)
    if entry == "now":
        cr = crash_at(bars, k - 1)
        return bool(cr["fires"]), cr
    if entry != "confirm":
        raise ValueError(f"unknown entry mode {entry!r}")
    cr = crash_at(bars, k - 2)
    if not cr["fires"]:
        return False, dict(cr, green=None)
    green = bool(bars.traded[k - 1] > 0 and float(bars.c[k - 1]) > float(bars.c[k - 2]))
    return green, dict(cr, green=green)


def post_crash_state(snap: C.AsOf) -> dict:
    """The drawdown-matched control's eligibility (PREREG 3): >= 70 % under the highest open / close of the completed
    bars, and no CRASH bar (any seller pattern) among the last 15 completed bars."""
    bars = snap.bars
    k = len(bars)
    out: dict[str, Any] = {"ok": False, "state": False, "dd": None, "recent_crash": None}
    if k < STATE_MIN_BARS:
        return out
    o, c = np.asarray(bars.o, float), np.asarray(bars.c, float)
    peak = float(max(np.nanmax(o), np.nanmax(c)))
    if not (peak > 0 and math.isfinite(peak)):
        return out
    dd = 1.0 - float(c[k - 1]) / peak
    a = crash_arrays(bars, k - STATE_QUIET_BARS, k)
    recent = bool(a is not None and a["crash"].any())
    out.update(ok=True, dd=dd, recent_crash=recent, state=bool(dd >= STATE_DD and not recent))
    return out


def round_trip_frac(snap: C.AsOf, cost: C.CostModel | None = None) -> float | None:
    """costs.py round trip of a $20 ticket at the pool state after the last completed bar (fee tier by date and
    market cap, impact on the pool's own k = X * y, network fees), as a fraction of the stake. A cost, not an
    outcome: reported in the debug counts as the hurdle a bounce must clear."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return None
    X, y = float(bars.X[k - 1]), float(bars.y[k - 1])
    if not (X > 0 and y > 0):
        return None
    return C.round_trip_pct(SIZE_USD / snap.sol_usd, snap.price, X * y, snap.t, cost or C.CostModel()) / 100.0


def entry_decision(snap: C.AsOf, p: Mapping[str, Any]) -> tuple[bool, dict]:
    """The entry condition of the config's mode (the age window is checked by :func:`strategy`)."""
    return signal(snap, str(p["entry"]))


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The Z3 strategy for common.backtest (one entry per coin; every exit is mechanical)."""
    if pos is not None:
        return None
    if snap.age_s < AGE_MIN_S:
        return None
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    ok, info = entry_decision(snap, p)
    if not ok:
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=float(p["max_hold_s"]), exit_by_age_s=EXIT_BY_AGE_S),
                   tag=depth_tag(info["drop"]), state={"drop": info["drop"], "j_crash": info["j"]})


# =========================================================================== controls


def placebo_ok(snap: C.AsOf) -> bool:
    """Drawdown-matched random control (PREREG 10): the POST-CRASH STATE at a random time."""
    return bool(post_crash_state(snap)["state"])


PLACEBO_CONTROLS = {"unmatched": {"eligible": None, "strata": None}}


# =========================================================================== evaluation


def _age_bins(t: pd.DataFrame) -> dict:
    a = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    return {"7-15": int((a < 15).sum()), "15-30": int(((a >= 15) & (a < 30)).sum()),
            "30-60": int(((a >= 30) & (a < 60)).sum()), "60-121": int((a >= 60).sum())}


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, depth tags, ages, placebo / control counts) --
    never returns, exit reasons, fill prices, fee tiers paid or placebo outcomes."""
    t = res.trades
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_depth_n": t["tag"].value_counts().to_dict() if len(t) else {}, "entry_age_min": _age_bins(t),
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
    if len(t):
        mid, net = t["ret_mid"].to_numpy(float), t["ret_net"].to_numpy(float)
        base["cost_decomposition"] = {"mean_gross_move_worst_fills": float(mid.mean()),
                                      "mean_cost": float((mid - net).mean()),
                                      "fee_bps_in": {str(k): int(v) for k, v in t["fee_bps_in"].value_counts().items()}}
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_depth"] = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} \
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


def _rank_key(r: Mapping[str, Any]) -> tuple:
    return (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"], int(r["hold_min"]),
            ENTRY_GRID.index(r["entry"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 8: qualifiers (sample, mean, top-2, both controls, censoring), ranked by the coin-bootstrap 90 % CI lower
    bound; shortlist = the top 2 in rank order."""
    rows = []
    for p in GRID:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        pu = ((e.get("controls") or {}).get("unmatched") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and pu is not None and pu > 0
                and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "entry": p["entry"], "hold_min": int(p["hold_min"]),
                     "powered": bool(powered), "qualifies": bool(good), "n": e["n"], "coins": e["n_coins"],
                     "mean": e.get("mean"), "mean_without_top2": e.get("mean_without_top2"),
                     "ci90_lo": ci[0] if ci else None, "drawdown_matched_diff": pc, "unmatched_diff": pu,
                     "censored_share": cs})
    q = sorted((r for r in rows if r["qualifies"]), key=_rank_key)
    if q:
        top = q[:SHORTLIST_MAX]
        sl = [make_params(r["entry"], r["hold_min"]) for r in top]
        return {"verdict": "SHORTLISTED", "rows": rows, "ranked": [r["config"] for r in top], "shortlist": sl,
                "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / control / censoring bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max(r['n'] for r in rows)} trades, {max(r['coins'] for r in rows)} coins)")
    return {"verdict": v, "reason": why, "rows": rows, "ranked": [], "shortlist": [], "shortlist_hashes": []}


def score_predictions(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 7 predictions P1-P3 (held = the expected negative result) and the G35 by-product. Never decisive."""
    means = {k: e.get("mean") for k, e in evals.items()}
    opens = {k: (e.get("stress") or {}).get("open_fills") for k, e in evals.items()}
    diffs = {k: (e.get("placebo") or {}).get("mean_diff") for k, e in evals.items()}
    g35 = sorted(k for k, e in evals.items()
                 if ((e.get("placebo") or {}).get("diff_ci95") or (None, None))[1] is not None
                 and e["placebo"]["diff_ci95"][1] < G35_MARGIN)
    return {
        "P1_no_config_mean_net_above_0": {"held": all(v is None or v <= 0 for v in means.values()), "values": means},
        "P2_open_fills_below_plan_bar": {"held": all(v is None or v < PRED_OPEN_FILL_BAR for v in opens.values()),
                                         "values": opens, "bar": PRED_OPEN_FILL_BAR},
        "P3_control_margin_below_6pts": {"held": all(v is None or v < PRED_CONTROL_MARGIN for v in diffs.values()),
                                         "values": diffs, "bar": PRED_CONTROL_MARGIN},
        "g35_support_configs": g35,
        "note": "predictions are reports (PREREG 7); the TRAIN decision is decide_train's",
    }


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
    """PREREG 9 VAL: a filter, never a ranking. Candidate = the TRAIN rank-1 config if it proceeds, else rank 2."""
    per = {role: decide_val_one(evals[role]) for role in ranked_roles}
    for role in ranked_roles:
        if per[role]["proceed"]:
            return {"verdict": per[role]["verdict"], "candidate_role": role, "candidate_config": evals[role]["config"],
                    "candidate_hash": evals[role]["params_hash"], "per_config": per, "proceed": True}
    v = "FAIL_VAL" if any(d["verdict"] == "FAIL_VAL" for d in per.values()) else "UNDERPOWERED_VAL"
    return {"verdict": v, "candidate_role": None, "candidate_config": None, "candidate_hash": None, "per_config": per,
            "proceed": False}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Z3 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Z3 never looked at (the TRAIN third hosted the debug run: reported apart)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
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
    """Raise :class:`Z3Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Z3Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Z3Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Z3Refused("PREREG.md changed after the first official TRAIN run; record changes in Z3/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Z3Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Z3Refused("TRAIN already ran on complete data (Z3/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Z3Refused("no TRAIN result (Z3/train.json): run --stage train first")
    if train.get("provisional"):
        raise Z3Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Z3Refused(f"TRAIN decision {tv}: Z3 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Z3Refused("no VAL shortlist for Z3 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise Z3Refused("the Z3 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Z3Refused("VAL already ran (Z3/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Z3Refused(f"no VAL result (Z3/val.json): {stage.upper()} needs a VAL decision first")
    vd = val.get("decision") or {}
    if vd.get("verdict") not in PROCEED_VAL:
        raise Z3Refused(f"VAL decision {vd.get('verdict')}: Z3 stopped (PLAN 8 rule 7 input); {stage.upper()} is not "
                        "spent")
    if vd.get("candidate_hash") not in sl.get("hashes", []):
        raise Z3Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Z3Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Z3Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Z3Refused(f"{stage.upper()} already ran (Z3/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise Z3Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Z3Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def _quantiles(x: list[float]) -> dict | None:
    if not x:
        return None
    a = np.asarray(x, float)
    return {"n": int(len(a)), "p25": float(np.quantile(a, 0.25)), "median": float(np.median(a)),
            "p75": float(np.quantile(a, 0.75)), "max": float(a.max())}


def event_counts(ds: C.Dataset) -> dict:
    """Counts only (no outcomes): crash bars at the decision grid (ages 7-120 min, and before 7 min for information),
    the single-seller test, the confirm condition, the post-crash state (control availability), and the DECISION-time
    state of each coin's first ``now`` signal: crash depth, sellers in the crash minute, pricing reserve, market cap,
    fee tier and the $20 round trip at that state (the cost hurdle). No price after a decision is read."""
    n_dec = 0
    coins = {k: set() for k in ("crash", "single", "confirm", "state", "crash_before_age_min")}
    bars_n = {k: 0 for k in ("crash", "single", "stampede", "confirm", "state", "crash_before_age_min")}
    depth = {"d70": 0, "d80": 0, "d90": 0}
    ns_single, ns_stampede = [], []
    first_sig = {"drop": [], "n_sellers": [], "X_after": [], "mcap_usd": [], "round_trip": [], "round_trip_x1.5": [],
                 "fee_bps": {}}
    stressed = C.CostModel().stressed(1.5)
    for m in ds.mints:
        cd = ds.coin(m)
        seen = False
        for j in range(1, C.N_BARS + 1):            # the engine's decision grid: t = bar_start(j) + 20 s
            t = float(cd.bar_start(j) + C.GRID_OFFSET_S)
            age = t - cd.g
            if age > AGE_MAX_S:
                break
            snap = ds.asof(m, t)
            cr = crash_at(snap.bars, snap.k - 1)
            if age < AGE_MIN_S:
                if cr["crash"]:
                    coins["crash_before_age_min"].add(m)
                    bars_n["crash_before_age_min"] += 1
                continue
            n_dec += 1
            if cr["crash"]:
                coins["crash"].add(m)
                bars_n["crash"] += 1
                if cr["single"]:
                    coins["single"].add(m)
                    bars_n["single"] += 1
                    depth[depth_tag(cr["drop"])] += 1
                    ns_single.append(cr["n_sellers"])
                    if not seen:                     # the ``now`` entry decision of this coin
                        seen = True
                        bars = snap.bars
                        rt = round_trip_frac(snap)
                        first_sig["drop"].append(cr["drop"])
                        first_sig["n_sellers"].append(cr["n_sellers"])
                        first_sig["X_after"].append(float(bars.X[snap.k - 1]))
                        first_sig["mcap_usd"].append(snap.mcap_usd)
                        if rt is not None:
                            first_sig["round_trip"].append(rt)
                            first_sig["round_trip_x1.5"].append(round_trip_frac(snap, stressed))
                        fb = str(int(C.fee_bps_at(snap.t, snap.mcap_sol)))
                        first_sig["fee_bps"][fb] = first_sig["fee_bps"].get(fb, 0) + 1
                else:
                    bars_n["stampede"] += 1
                    ns_stampede.append(cr["n_sellers"])
            if signal(snap, "confirm")[0]:
                coins["confirm"].add(m)
                bars_n["confirm"] += 1
            if placebo_ok(snap):
                coins["state"].add(m)
                bars_n["state"] += 1
    days = _span_days(ds)
    return {"coins": len(ds), "span_days": days, "decision_minutes": n_dec,
            "coins_with": {k: len(v) for k, v in coins.items()}, "bars_with": bars_n,
            "single_seller_crash_depth": depth,
            "n_sellers_in_crash_minute": {"single_seller": _quantiles(ns_single), "stampede": _quantiles(ns_stampede)},
            "first_signal_decision_state": {
                "drop": _quantiles(first_sig["drop"]), "n_sellers": _quantiles(first_sig["n_sellers"]),
                "X_after_sol": _quantiles(first_sig["X_after"]), "mcap_usd": _quantiles(first_sig["mcap_usd"]),
                "round_trip": _quantiles(first_sig["round_trip"]),
                "round_trip_costs_x1.5": _quantiles(first_sig["round_trip_x1.5"]),
                "fee_bps_tier": first_sig["fee_bps"]},
            "signal_coins_per_day": (len(coins["single"]) / days) if days == days and days > 0 else None}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Z3/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "z3_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Z3Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Z3Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Z3Refused("no configs to run (shortlist or VAL candidate missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Z3Refused(str(e)) from e
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
        if debug:
            doc["event_counts"] = event_counts(ds)
        results: dict[str, C.Result] = {}
        for role, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok, placebo_strata=None,
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
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
                                  note=f"{VERSION}: PREREG 8, rank order {dec['ranked']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
            doc["predictions"] = score_predictions(evals)
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

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"z3 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look
            return _execute(ds)
    except C.SplitLocked as e:
        raise Z3Refused(str(e)) from e


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


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# Z3 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Z3 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        fs = ec["first_signal_decision_state"]
        L += ["## Event counts (no outcomes)", "",
              f"- Coins {ec['coins']}; decision minutes at ages 7-120 min: {ec['decision_minutes']}.",
              "", "| condition | coins | bars |", "|---|---:|---:|"]
        for k in ("crash", "single", "confirm", "state", "crash_before_age_min"):
            L.append(f"| {k} | {ec['coins_with'][k]} | {ec['bars_with'][k]} |")
        L += [f"| stampede (crash failing the single-seller bound) | | {ec['bars_with']['stampede']} |", "",
              f"- Single-seller crash depth (bars): {ec['single_seller_crash_depth']}.",
              f"- Sellers in the crash minute: single-seller {_q(ec['n_sellers_in_crash_minute']['single_seller'])}; "
              f"stampede {_q(ec['n_sellers_in_crash_minute']['stampede'])}.",
              f"- Signal coins per day: {ec.get('signal_coins_per_day') and round(ec['signal_coins_per_day'], 1)}.",
              "- At each coin's first `now` signal (decision-time state, no later price):",
              f"  - crash depth {_q(fs['drop'], 100, '{:.0f}%')}; pricing reserve X after the crash "
              f"{_q(fs['X_after_sol'], 1, '{:.1f} SOL')}; market cap {_q(fs['mcap_usd'], 1, '${:,.0f}')};",
              f"  - fee tier (bps, one side): {fs['fee_bps_tier']}; $20 round trip {_q(fs['round_trip'], 100, '{:.2f}%')}"
              f"; at costs × 1.5 {_q(fs['round_trip_costs_x1.5'], 100, '{:.2f}%')}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | depth tags | entry age (min) | placebo trades | controls | horizon exits | "
                  "entries/day |", "|---|---:|---:|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_depth_n']} | {e['entry_age_min']} | "
                         f"{e['n_placebo']} | {e['n_controls']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | drawdown-matched "
                  "diff | unmatched diff | costs ×1.5 | open fills | gross move | cost | censored |",
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
    pr = doc.get("predictions")
    if pr:
        L += ["## Pre-registered predictions (PREREG 7; reports, never decisive)", ""]
        for key in ("P1_no_config_mean_net_above_0", "P2_open_fills_below_plan_bar", "P3_control_margin_below_6pts"):
            L.append(f"- {key}: held = {pr[key]['held']}.")
        L += [f"- Configs supporting craft rule G35 (control diff 95% CI below −10 points): "
              f"{pr.get('g35_support_configs') or 'none'}.", ""]
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, drawdown-matched diff {_pct(r['drawdown_matched_diff'])}, unmatched diff "
                 f"{_pct(r['unmatched_diff'])}, qualifies {r['qualifies']}.")
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
    ap = argparse.ArgumentParser(description="Z3 rug bounce: pre-registered stages; see research/lab2/Z3/PREREG.md")
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
    except Z3Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
