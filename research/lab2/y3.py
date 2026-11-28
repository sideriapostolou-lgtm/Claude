"""Y3: buy a broad-buying breakout from a quiet range (volatility compression -> expansion), g + 60 -> g + 180 min.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Y3/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; the AGENT
column only once knowable; NULL stays None). Outcomes (trade returns) are never features.

Mechanism (PREREG 1): attention reaches a coin in waves. After the post-migration distribution has run (age >= 60 min),
a coin trading in a narrow range has balanced flow; a minute that breaks above the range on BROAD buying (many distinct
wallets >= 0.01 SOL, not concentrated in the top 5 buyers, net buying) is the first wave of a cascade whose later waves
push a constant-product pool further. The range low is a cheap thesis stop.

* box = the N completed bars before the last one (its first minute at or after g + 60 min); COMPRESSED when
  max(high) / min(low) - 1 <= theta and >= 50 % of its minutes traded;
* BREAKOUT: the last completed bar closes above the box high and moves >= 3 % close to close;
* BROAD: buyers in that bar >= max(5, 2 x the box mean), top-5 buy share < 0.85, net buying > 0 (AGENT removed);
* ELIGIBLE: market cap >= $6,000.

Entry: first SETUP at age <= 130 min; worst fill on the next bar. Exits: a close below the box low (next-bar fill at the
bar's low), a 25 % catastrophe stop and a 30-minute time exit filled on the NEXT bar at its low, the g + 178 min
deadline. Grid: N in {10, 20} x theta in {0.06, 0.12} x flow in {broad, chart}; ``chart`` = the same rule without BROAD
(wave 1 F2's squeeze under Y3's rules), a pre-registered control that is never selected.

CLI::

    python research/lab2/y3.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/y3.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/y3.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/y3.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/y3.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/y3.py --stage final
    python research/lab2/y3.py --stage val --check             # prerequisites only

Each stage writes ``Y3/<stage>.json`` and ``Y3/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
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

VERSION = "y3-v1"
OUT_DIR = HERE / "Y3"
HYP = "Y3"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-7)
N_GRID = (10, 20)                    # box length, completed bars
THETA_GRID = (0.06, 0.12)            # max box range: box_hi / box_lo - 1
FLOW_GRID = ("broad", "chart")       # chart = no flow rule: a pre-registered control, never selectable
SELECTABLE_FLOW, TWIN_FLOW = "broad", "chart"
BOX_MIN_AGE_S = 3600.0               # the box's first minute starts at or after g + 60 min
TRADED_MIN = 0.5                     # >= half of the box minutes traded (a quiet market, not a frozen one)
RET_BO_MIN = 0.03                    # breakout bar close-to-close move >= ~one round trip
BUYERS_MIN = 5                       # breakout minute: >= 5 wallets buying >= 0.01 SOL ...
BUYERS_MULT = 2.0                    # ... and >= 2 x the box's mean buyers per minute
TOP5_MAX = 0.85                      # top-5 buyers' share of the minute's buy SOL < 0.85 (G1's concentration bar)
AGENT_MIN_SOL = 0.01                 # an AGENT minute buy >= 0.01 SOL counts it as one of n_buyers
MCAP_USD_MIN = 6000.0                # AsOf.alive's floor guard (its volume floor is not used: PREREG 3)
AGE_MAX_S = 130 * 60.0               # last entry decision; a 30-min hold then ends by ~g + 161 min
STOP_PCT = 0.25                      # catastrophe stop, intrabar, filled on the next bar
HOLD_S = 1800.0
EXIT_BY_AGE_S = 178 * 60.0           # registered deadline: never binds with the age cap and hold above
SIZE_USD = 20.0
INSTANT_MAX_DELAY_S = 5.0            # stratum (placebo matching and reports only)
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS = 60, 40
MAX_CENSORED = C.MAX_CENSORED_SHARE
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                 # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FIXED = {
    "version": VERSION, "box_min_age_s": BOX_MIN_AGE_S, "traded_min": TRADED_MIN, "ret_bo_min": RET_BO_MIN,
    "buyers_min": BUYERS_MIN, "buyers_mult": BUYERS_MULT, "top5_max": TOP5_MAX, "net_buy": "> 0",
    "mcap_usd_min": MCAP_USD_MIN, "age_max_s": AGE_MAX_S, "box_stop": "close below box_lo -> sell, next-bar fill",
    "stop_pct": STOP_PCT, "max_hold_s": HOLD_S, "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD,
    "placebo": "eligible (mcap >= $6k), stratum-matched (instant / slow)",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(N: int, theta: float, flow: str) -> dict:
    if int(N) not in N_GRID or float(theta) not in THETA_GRID or flow not in FLOW_GRID:
        raise ValueError(f"(N={N}, theta={theta}, flow={flow!r}) is not in the pre-registered grid")
    return {**FIXED, "N": int(N), "theta": float(theta), "flow": flow}


GRID = [make_params(N, th, f) for N in N_GRID for th in THETA_GRID for f in FLOW_GRID]
assert len(GRID) <= 12
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0)}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class Y3Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"N{int(p['N'])}|th{float(p['theta']):g}|{p['flow']}"


def twin_of(p: Mapping[str, Any]) -> dict:
    """The chart-only twin of a config (same N and theta, no flow rule)."""
    return make_params(int(p["N"]), float(p["theta"]), TWIN_FLOW)


# =========================================================================== features (AsOf only)


def _k_end(snap: C.AsOf, k_end: int | None) -> int:
    k = snap.k
    return k if k_end is None else max(0, min(int(k_end), k))


def _buyers_ex_agent(bars: C.Bars, lo: int, hi: int) -> np.ndarray:
    """Per-minute n_buyers of bars [lo, hi) minus 1 where the (knowable) AGENT bought >= 0.01 SOL."""
    nb = np.asarray(bars.n_buyers[lo:hi], float)
    ag = np.nan_to_num(np.asarray(bars.agent_buy_sol[lo:hi], float), nan=0.0)
    return np.clip(nb - (ag >= AGENT_MIN_SOL), 0.0, None)


def setup(snap: C.AsOf, N: int, theta: float, k_end: int | None = None) -> dict:
    """PREREG 3 at ``snap`` (or as of an earlier cutoff: the first ``k_end`` completed bars). The breakout bar is the
    last completed bar b = k - 1, the box the N bars before it.

    -> {ok, in_window, compressed, breakout, broad, fires_chart, fires_broad, box_hi, box_lo, r_box, traded_frac,
    ret_bo, nb_bo, nb_box, top5_share, net_bo, k, N, theta}."""
    N, theta = int(N), float(theta)
    k = _k_end(snap, k_end)
    out: dict[str, Any] = {"ok": False, "in_window": False, "compressed": False, "breakout": False, "broad": False,
                           "fires_chart": False, "fires_broad": False, "box_hi": None, "box_lo": None, "r_box": None,
                           "traded_frac": None, "ret_bo": None, "nb_bo": None, "nb_box": None, "top5_share": None,
                           "net_bo": None, "k": k, "N": N, "theta": theta}
    if k < N + 1:
        return out
    bars = snap.bars
    b, a = k - 1, k - 1 - N                       # breakout bar b; box [a, b)
    h = np.asarray(bars.h[a:b], float)
    lo = np.asarray(bars.l[a:b], float)
    c = np.asarray(bars.c[:k], float)
    box_hi, box_lo = float(h.max()), float(lo.min())
    r_box = box_hi / box_lo - 1.0 if box_lo > 0 else math.inf
    traded = float(np.asarray(bars.traded[a:b], float).mean())
    in_window = bool(int(bars.minute_ts[a]) >= snap.g + BOX_MIN_AGE_S)
    ret_bo = float(c[b] / c[b - 1] - 1.0) if c[b - 1] > 0 else None
    nb_bo = float(_buyers_ex_agent(bars, b, b + 1)[0])
    nb_box = float(_buyers_ex_agent(bars, a, b).mean())
    buy_b = float(bars.buy_sol[b])
    ag_b = float(np.nan_to_num(float(bars.agent_buy_sol[b]), nan=0.0))
    top5 = float(bars.top5_buy_sol[b]) / buy_b if buy_b > 0 else None
    net_bo = buy_b - ag_b - float(bars.sell_sol[b])
    compressed = bool(in_window and r_box <= theta and traded >= TRADED_MIN)
    breakout = bool(ret_bo is not None and c[b] > box_hi and ret_bo >= RET_BO_MIN)
    broad = bool(nb_bo >= max(BUYERS_MIN, BUYERS_MULT * nb_box) and top5 is not None and top5 < TOP5_MAX
                 and net_bo > 0)
    out.update(ok=True, in_window=in_window, compressed=compressed, breakout=breakout, broad=broad,
               fires_chart=compressed and breakout, fires_broad=compressed and breakout and broad,
               box_hi=box_hi, box_lo=box_lo, r_box=r_box, traded_frac=traded, ret_bo=ret_bo, nb_bo=nb_bo,
               nb_box=nb_box, top5_share=top5, net_bo=net_bo)
    return out


def eligible(snap: C.AsOf) -> bool:
    """ELIGIBLE (PREREG 3 rule 4): market cap >= $6,000 (AsOf.alive's floor guard, without its volume floor)."""
    return bool(snap.mcap_usd >= MCAP_USD_MIN)


def stratum(snap: C.AsOf) -> str:
    """instant (graduated <= 5 s after creation; known at g) or slow (incl. creation not scanned: > 30 min)."""
    d = snap.get("grad_delay_s")
    return "instant" if d is not None and d <= INSTANT_MAX_DELAY_S else "slow"


def entry_decision(snap: C.AsOf, p: Mapping[str, Any]) -> tuple[bool, dict]:
    """SETUP: ELIGIBLE and COMPRESSED and BREAKOUT (and BROAD for flow ``broad``). The age cap is in :func:`strategy`."""
    s = setup(snap, int(p["N"]), float(p["theta"]))
    fires = s["fires_broad"] if p["flow"] == "broad" else s["fires_chart"]
    if not fires:
        return False, s
    s["eligible"] = eligible(snap)
    return bool(s["eligible"]), s


def _k_at(snap: C.AsOf, tau: float) -> int:
    """Number of bars that had completed at cutoff ``tau`` (<= the snap's own count)."""
    bars = snap.bars
    if len(bars) == 0:
        return 0
    return int(min(max((tau - int(bars.minute_ts[0])) // 60, 0), len(bars)))


def exit_decision(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView) -> C.Exit | None:
    """Box stop: the last completed bar, completed after the entry decision, closed below the box low. Placebo
    positions carry no state: their box low is recomputed from the N bars before the last bar completed at THEIR
    decision. Catastrophe stop, time and deadline exits are mechanical (ExitSpec)."""
    k = snap.k
    k_dec = _k_at(snap, pos.t_dec - C.DECISION_LAG_S)
    if k <= k_dec:
        return None
    st = pos.state or {}
    box_lo = st.get("box_lo")
    if box_lo is None:
        box_lo = setup(snap, int(p["N"]), float(p["theta"]), k_end=k_dec)["box_lo"]
    if box_lo is None:
        return None
    if float(snap.bars.c[k - 1]) < float(box_lo):
        return C.Exit("box_fail")
    return None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The Y3 strategy for common.backtest (one entry per coin)."""
    if pos is not None:
        return exit_decision(snap, p, pos)
    if snap.age_s > AGE_MAX_S:
        return C.SKIP
    if snap.age_s < BOX_MIN_AGE_S + 60.0 * int(p["N"]):
        return None                                  # the box cannot lie in g + 60 min yet
    ok, s = entry_decision(snap, p)
    if not ok:
        return None
    return C.Enter(exits=C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=HOLD_S, exit_by_age_s=EXIT_BY_AGE_S),
                   tag=stratum(snap), state={"box_lo": s["box_lo"], "box_hi": s["box_hi"], "r_box": s["r_box"],
                                             "nb_bo": s["nb_bo"]})


# =========================================================================== controls


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe: ELIGIBLE coins."""
    return eligible(snap)


def placebo_stratum(snap: C.AsOf) -> str:
    return stratum(snap)


def compressed_ok(N: int, theta: float):
    """Control isolating the breakout-and-flow part: ELIGIBLE and COMPRESSED (the config's N and theta)."""
    def ok(snap: C.AsOf) -> bool:
        return eligible(snap) and bool(setup(snap, N, theta)["compressed"])
    ok.__name__ = f"compressed_N{int(N)}_th{float(theta):g}"
    return ok


def placebo_controls(p: Mapping[str, Any]) -> dict:
    return {"compressed": {"eligible": compressed_ok(int(p["N"]), float(p["theta"])), "strata": placebo_stratum},
            "unmatched": {"eligible": placebo_ok, "strata": None}}


# =========================================================================== evaluation


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, strata, ages, placebo counts) -- never returns,
    exit reasons or placebo outcomes."""
    t = res.trades
    ages = (t["age_dec_s"] / 60.0) if len(t) else pd.Series(dtype=float)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "flow": res.meta["params"]["flow"], "hypothesis": res.meta["hypothesis"], "n": int(len(t)),
            "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_stratum_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "entry_age_min": {"70-90": int((ages < 90).sum()), "90-110": int(((ages >= 90) & (ages < 110)).sum()),
                              "110-131": int((ages >= 110).sum())},
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


def broad_minus_chart(ev_cand: Mapping[str, Any], ev_twin: Mapping[str, Any] | None) -> float | None:
    a, b = ev_cand.get("mean"), (ev_twin or {}).get("mean")
    return None if a is None or b is None else float(a) - float(b)


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 7: ``broad`` qualifiers (sample, mean, top-2, both matched controls, beats its chart twin, censoring),
    ranked by the coin-bootstrap 90 % CI lower bound; shortlist = the PAIR (rank-1 broad config, its chart twin)."""
    rows = []
    for p in GRID:
        if p["flow"] != SELECTABLE_FLOW:
            continue
        e = evals[config_key(p)]
        tw = evals.get(config_key(twin_of(p))) or {}
        pc = (e.get("placebo") or {}).get("mean_diff")
        pm = ((e.get("controls") or {}).get("compressed") or {}).get("mean_diff")
        bc = broad_minus_chart(e, tw)
        cs = e.get("censored_share")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and pm is not None and pm > 0 and bc is not None and bc > 0
                and cs is not None and cs <= MAX_CENSORED)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "N": int(p["N"]), "theta": float(p["theta"]), "powered": bool(powered),
                     "qualifies": bool(good), "n": e["n"], "coins": e["n_coins"], "mean": e.get("mean"),
                     "mean_without_top2": e.get("mean_without_top2"), "ci90_lo": ci[0] if ci else None,
                     "placebo_diff": pc, "compressed_diff": pm, "broad_minus_chart": bc, "twin_n": tw.get("n"),
                     "censored_share": cs})
    q = [r for r in rows if r["qualifies"]]
    if q:
        q.sort(key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"], r["N"],
                              r["theta"]))
        best = q[0]
        cand = make_params(best["N"], best["theta"], SELECTABLE_FLOW)
        sl = [cand, twin_of(cand)]
        return {"verdict": "SHORTLISTED", "rows": rows, "candidate": best["config"], "twin": config_key(sl[1]),
                "shortlist": sl, "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered broad config failed the mean / top-2 / control / twin / censoring bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no broad config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (best: "
               f"{max(r['n'] for r in rows)} trades, {max(r['coins'] for r in rows)} coins)")
    return {"verdict": v, "reason": why, "rows": rows, "candidate": None, "twin": None, "shortlist": [],
            "shortlist_hashes": []}


def decide_val(ev_cand: Mapping[str, Any]) -> dict:
    """PREREG 8 VAL, on the candidate's trades (the twin is reported only)."""
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
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Y3 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame, twin: pd.DataFrame | None = None) -> dict:
    """PLAN 3.5 item 9 on the census thirds Y3 never looked at (the TRAIN third hosted the debug run: reported apart)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    out = {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
           "mean": float(judged["ret_net"].mean()) if len(judged) else None,
           "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
           "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                           "note": "census TRAIN third: hosted the debug run (PREREG 13), not judged"}}
    if twin is not None:
        tj = twin[twin["split"].isin(FINAL_JUDGED)] if len(twin) else twin
        out["twin_judged"] = {"n": int(len(tj)), "mean": float(tj["ret_net"].mean()) if len(tj) else None}
    return out


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
    """[(role, params)] the stage runs: the grid (debug / train), else the shortlisted pair (candidate, twin)."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    by_flow = {c.get("flow"): c for c in sl["configs"]}
    return [("candidate", by_flow.get(SELECTABLE_FLOW)), ("twin", by_flow.get(TWIN_FLOW))]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Y3Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Y3Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Y3Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Y3Refused("PREREG.md changed after the first official TRAIN run; record changes in Y3/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Y3Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Y3Refused("TRAIN already ran on complete data (Y3/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Y3Refused("no TRAIN result (Y3/train.json): run --stage train first")
    if train.get("provisional"):
        raise Y3Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Y3Refused(f"TRAIN decision {tv}: Y3 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Y3Refused("no VAL shortlist for Y3 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise Y3Refused("the Y3 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Y3Refused("VAL already ran (Y3/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Y3Refused(f"no VAL result (Y3/val.json): {stage.upper()} needs a VAL decision first")
    vv = (val.get("decision") or {}).get("verdict")
    if vv not in PROCEED_VAL:
        raise Y3Refused(f"VAL decision {vv}: Y3 stopped (PLAN 8 rule 7 input); {stage.upper()} is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Y3Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Y3Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Y3Refused(f"{stage.upper()} already ran (Y3/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise Y3Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Y3Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


EC_CONDS = ("in_window", "compressed", "breakout", "broad", "fires_chart", "fires_broad", "eligible_chart",
            "eligible_broad")


def event_counts(ds: C.Dataset) -> dict:
    """Counts only (no prices, no returns): coins (and coin-minutes) where each SETUP condition holds at some decision
    with age <= 130 min, per (N, theta)."""
    keys = [(N, th) for N in N_GRID for th in THETA_GRID]
    coins = {key: {c: set() for c in EC_CONDS} for key in keys}
    minutes = {key: {c: 0 for c in EC_CONDS} for key in keys}
    strata: dict[str, int] = {}
    n_dec = 0
    elig_coins: set[str] = set()
    for m in ds.mints:
        cd = ds.coin(m)
        strata_done = False
        for j in range(1, C.N_BARS + 1):          # the engine's decision grid: t = bar_start(j) + 20 s
            t = float(cd.bar_start(j) + C.GRID_OFFSET_S)
            age = t - cd.g
            if age < BOX_MIN_AGE_S + 60.0 * min(N_GRID) or age > AGE_MAX_S:
                continue
            snap = ds.asof(m, t)
            if not strata_done:
                s = stratum(snap)
                strata[s] = strata.get(s, 0) + 1
                strata_done = True
            n_dec += 1
            el = eligible(snap)
            if el:
                elig_coins.add(m)
            for key in keys:
                N, th = key
                if age < BOX_MIN_AGE_S + 60.0 * N:
                    continue
                st = setup(snap, N, th)
                flags = {c: bool(st[c]) for c in EC_CONDS[:6]}
                flags["eligible_chart"] = el and flags["fires_chart"]
                flags["eligible_broad"] = el and flags["fires_broad"]
                for c, v in flags.items():
                    if v:
                        coins[key][c].add(m)
                        minutes[key][c] += 1
    name = {key: f"N{key[0]}|th{key[1]:g}" for key in keys}
    return {"coins": len(ds), "strata": strata, "decision_minutes": n_dec, "coins_eligible_at_some_decision":
            len(elig_coins),
            "coins_with_condition": {name[k]: {c: len(v) for c, v in coins[k].items()} for k in keys},
            "coin_minutes_with_condition": {name[k]: dict(minutes[k]) for k in keys}}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Y3/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "y3_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Y3Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Y3Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Y3Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Y3Refused(str(e)) from e
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
                                  note=f"{VERSION}: PREREG 7 pair rule, candidate {dec['candidate']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            dec = decide_val(evals["candidate"])
            dec["broad_minus_chart"] = broad_minus_chart(evals["candidate"], evals.get("twin"))
            doc["decision"] = dec
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base,
                              "broad_minus_chart": broad_minus_chart(evals["candidate"], evals.get("twin"))}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades,
                                             results["twin"].trades if "twin" in results else None)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"y3 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate + twin inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Y3Refused(str(e)) from e


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
    L = [f"# Y3 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Y3 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (no returns)", "",
              f"- Coins {ec['coins']} (strata {ec['strata']}); decision minutes at ages 70-130: "
              f"{ec['decision_minutes']}; coins ELIGIBLE (mcap ≥ $6k) at some such decision: "
              f"{ec['coins_eligible_at_some_decision']}.",
              "", "| box | condition | coins | coin-minutes |", "|---|---|---:|---:|"]
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
                  "compressed diff | unmatched diff | costs ×1.5 | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('compressed') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('unmatched') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | {_pct(e.get('censored_share'), 0)} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, compressed diff "
                 f"{_pct(r['compressed_diff'])}, broad − chart {_pct(r['broad_minus_chart'])}, qualifies "
                 f"{r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (candidate {dec.get('candidate')}, twin "
                 f"{dec.get('twin')}).")
    if "broad_minus_chart" in dec and dec.get("base") is None:
        L.append(f"- broad − chart (candidate − twin mean, reported only): {_pct(dec.get('broad_minus_chart'))}.")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append(f"- broad − chart (reported, never judged): {_pct(dec.get('broad_minus_chart'))}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    if dec.get("reason"):
        L.append(f"- Reason: {dec['reason']}.")
    if dec.get("note"):
        L.append(f"- {dec['note']}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}; twin on the judged thirds: {dec.get('twin_judged')}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Y3 compression -> broad-buying breakout: pre-registered stages; see "
                                             "research/lab2/Y3/PREREG.md")
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
    except Y3Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
