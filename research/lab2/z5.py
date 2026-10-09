"""Z5: the fee-tier cost optimizer -- does paying the cheapest pool-fee tiers alone flip a host positive? Expected: no.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Z5/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; NULL stays
None). Outcomes (trade returns, fill prices, exit reasons) are never features; they are hidden on the debug split.

Mechanism (PREREG 1-4): the PumpSwap pool fee falls with market cap (``common.fee_bps_at``) and a $20 ticket's impact
falls with the pricing reserve X = x + v, so the exact round trip ``rt`` is known at every decision. Z5 takes two FROZEN
hosts -- R0 (PLAN 4.1 random alive entry, identical to ``g1.host_r0``) and M1 (``m1.strategy`` at m = 1,
``rhythm+prec``) -- and VETOES every host entry whose ``rt`` is above c (3.40 % = the 115-bps tier or cheaper,
3.00 % = the 100-bps tier or cheaper). The kept trades are a subset of the host's own trades, so the comparison with
the host baseline is exact: net gain = cost saving + selection (PREREG 7). One config per host adds the TIER GUARD:
sell before the price falls into a dearer tier than the one the buy paid.

CLI::

    python research/lab2/z5.py --debug                         # census TRAIN third: counts and decision-time costs
    python research/lab2/z5.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/z5.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/z5.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/z5.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/z5.py --stage final
    python research/lab2/z5.py --stage val --check             # prerequisites only

Each stage writes ``Z5/<stage>.json`` and ``Z5/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8 data
gates V1-V4, PREREG frozen after the first official TRAIN run, the M1 host pinned, and the host-first rule: no look at
M1's entries on a split before M1's own look there).
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
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import m1 as M1  # noqa: E402  (the frozen M1 host; pinned below)

VERSION = "z5-v1"
OUT_DIR = HERE / "Z5"
HYP = "Z5"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-6)
SIZE_USD = 20.0
C_GRID = (0.034, 0.030)          # max exact round trip: 3.40 % = 115-bps tier or cheaper, 3.00 % = 100-bps or cheaper
GUARD_C = 0.034                  # the tier guard runs once per host, at c = 3.40 %
GUARD_ARM = 0.05                 # no guard on a boundary within 5 % below the entry fill's market cap
GUARD_MARGIN = 0.02              # exit when the last close is < 1.02 x the guarded boundary
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
HOST_ORDER = ("R0", "M1")
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS, MIN_CLUSTERS = 60, 40, 3
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03             # PLAN 3.5 item 2
MAX_CENSORED = C.MAX_CENSORED_SHARE
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
# predictions (PREREG 7.3): reports, never decisive
PRED_MAX_SAVING = 0.015
PRED_MAX_GUARD_FEE = 0.001

# ---- hosts (PREREG 3): frozen, never searched
R0_PARAMS = {"host": "R0_random_alive", "seed": 0, "age_lo_min": 30.0, "age_hi_min": 115.0,
             "alive_vol_usd_15m": 1500.0, "alive_mcap_usd": 6000.0, "stop_pct": 0.50, "max_hold_s": 3600.0}
R0_PIN = "27a79bc60126"          # == C.params_hash(g1.R0_PARAMS) when this file was written
M1_VERSION_PIN, M1_PIN = "m1-v1", "9c0a14afb895"
M1_M, M1_EXIT = 1.0, "rhythm+prec"
M1_PARAMS = M1.make_params(M1_M, M1_EXIT)


def r0_target_age_s(mint: str, hp: Mapping[str, Any]) -> float:
    """G1.R0's seeded random entry age in [age_lo, age_hi] minutes (sha256 of '<seed>:<mint>')."""
    h = int(hashlib.sha256(f"{hp['seed']}:{mint}".encode()).hexdigest()[:12], 16) / float(16 ** 12)
    return 60.0 * (hp["age_lo_min"] + h * (hp["age_hi_min"] - hp["age_lo_min"]))


def host_r0(snap: C.AsOf, hp: Mapping[str, Any], pos: C.PositionView | None):
    """PLAN 4.1 R0 (identical to ``g1.host_r0``): at the seeded random age, enter if alive, else never."""
    if pos is not None:
        return None
    if snap.age_s < r0_target_age_s(snap.mint, hp):
        return None
    if snap.alive(hp["alive_vol_usd_15m"], hp["alive_mcap_usd"]):
        return C.Enter(exits=C.ExitSpec(stop_pct=hp["stop_pct"], max_hold_s=hp["max_hold_s"]), tag="R0")
    return C.SKIP


HOST_FN: dict[str, Callable] = {"R0": host_r0, "M1": M1.strategy}
HOST_PARAMS: dict[str, Mapping[str, Any]] = {"R0": R0_PARAMS, "M1": M1_PARAMS}


def host_pin_problems() -> list[str]:
    """The hosts must be the ones the PREREG registered (a changed host is a new Z5 version)."""
    out = []
    if C.params_hash(R0_PARAMS) != R0_PIN:
        out.append(f"R0 params hash {C.params_hash(R0_PARAMS)} != pinned {R0_PIN}")
    if M1.VERSION != M1_VERSION_PIN:
        out.append(f"m1.VERSION {M1.VERSION!r} != pinned {M1_VERSION_PIN!r}")
    h = C.params_hash(M1.make_params(M1_M, M1_EXIT))
    if h != M1_PIN:
        out.append(f"M1 host params hash {h} != pinned {M1_PIN} (m1.py changed its FIXED constants)")
    return out


FIXED = {
    "version": VERSION, "size_usd": SIZE_USD,
    "filter": "veto at the host's own entry decision: Enter if rt <= c, else SKIP the coin; rt unknown -> SKIP",
    "rt": "common.round_trip_pct($20 at SOL/USD before tau, last close, k = X*y after the last bar, fee schedule at t, "
          "2 network fees, no rent)",
    "guard_arm": GUARD_ARM, "guard_margin": GUARD_MARGIN,
    "guard_rule": "G = largest fee boundary <= entry-fill mcap / (1 + arm); exit when last close mcap < G (1 + margin)",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(host: str, c: float | None, guard: bool) -> dict:
    if host not in HOST_FN:
        raise ValueError(f"host {host!r} not in {tuple(HOST_FN)}")
    if c is not None and c not in C_GRID:
        raise ValueError(f"c = {c!r} is not in the pre-registered grid {C_GRID}")
    if guard and c != GUARD_C:
        raise ValueError(f"the tier guard is registered only at c = {GUARD_C}")
    return {**FIXED, "host": host, "host_params": dict(HOST_PARAMS[host]), "c": None if c is None else float(c),
            "guard": bool(guard)}


GRID = [make_params(h, c, g) for h in HOST_ORDER for (c, g) in ((None, False), (C_GRID[0], False), (C_GRID[1], False),
                                                                 (GUARD_C, True))]
assert len(GRID) == 8 <= 12
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "open_fills": dataclasses.replace(FILL, entry_fill="open", exit_fill="open")}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


class Z5Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    c = "c-none" if p["c"] is None else f"c{100 * float(p['c']):.2f}"
    return f"{p['host']}|{c}|{'guard' if p['guard'] else 'hx'}"


def baseline_of(p: Mapping[str, Any]) -> dict:
    """The host baseline (no filter, host exits) a filtered config is compared with: its twin."""
    return make_params(p["host"], None, False)


# =========================================================================== features (AsOf only)


def round_trip_frac(snap: C.AsOf, cost: C.CostModel | None = None) -> float | None:
    """The exact $20 round trip at the pool state after the last completed bar (fee tier by date and market cap,
    Ultra, buffer, impact on the pool's own k = X * y, two network fees), as a fraction of the stake."""
    bars = snap.bars
    k = len(bars)
    if k == 0:
        return None
    X, y = float(bars.X[k - 1]), float(bars.y[k - 1])
    if not (X > 0 and y > 0 and math.isfinite(X) and math.isfinite(y)):
        return None
    return C.round_trip_pct(SIZE_USD / snap.sol_usd, snap.price, X * y, snap.t, cost or C.CostModel()) / 100.0


def tier_boundaries(ts: float) -> list[float]:
    """Market caps (SOL) where the PumpSwap fee steps down, from the schedule in force at ``ts``."""
    return sorted(float(u) for u, _ in C.fee_schedule_at(ts) if math.isfinite(u))


def guard_level(mcap_in_sol: float, ts: float) -> float | None:
    """The boundary the tier guard defends: the largest fee boundary <= the entry fill's market cap / (1 + ARM)."""
    if not (mcap_in_sol > 0 and math.isfinite(mcap_in_sol)):
        return None
    bs = [b for b in tier_boundaries(ts) if b <= mcap_in_sol / (1.0 + GUARD_ARM)]
    return max(bs) if bs else None


def guard_exit(snap: C.AsOf, pos: C.PositionView) -> C.Exit | None:
    """Sell before the price falls into a dearer fee tier than the one the buy paid (PREREG 4.2)."""
    g = guard_level(pos.entry_price * C.TOKEN_SUPPLY, pos.t_in)
    if g is None or snap.k == 0:
        return None
    return C.Exit("tier_guard") if snap.mcap_sol < g * (1.0 + GUARD_MARGIN) else None


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """Z5 for common.backtest: the host's own decisions, its entries vetoed when rt > c, plus the optional guard."""
    fn, hp = HOST_FN[p["host"]], p["host_params"]
    if pos is not None:
        if p["guard"]:
            ex = guard_exit(snap, pos)
            if ex is not None:
                return ex
        return fn(snap, hp, pos)
    act = fn(snap, hp, None)
    if p["c"] is None or not isinstance(act, C.Enter):
        return act
    rt = round_trip_frac(snap)
    if rt is None or rt > float(p["c"]):
        return C.SKIP                         # veto: never enter this coin later (the host's own timing only)
    return act


# =========================================================================== controls (PREREG 8)


def alive_ok(snap: C.AsOf) -> bool:
    """R0's universe: alive (15-min volume >= $1.5k and market cap >= $6k)."""
    return snap.alive(R0_PARAMS["alive_vol_usd_15m"], R0_PARAMS["alive_mcap_usd"])


def cost_band(c: float) -> Callable[[C.AsOf], bool]:
    def f(snap: C.AsOf) -> bool:
        rt = round_trip_frac(snap)
        return rt is not None and rt <= c
    f.__name__ = f"cost_band_{c:g}"
    return f


def class_cost_band(c: float) -> Callable[[C.AsOf], tuple]:
    cb = cost_band(c)

    def f(snap: C.AsOf) -> tuple:
        return (M1.placebo_stratum(snap), cb(snap))
    f.__name__ = f"m1_class_cost_band_{c:g}"
    return f


def placebo_spec(p: Mapping[str, Any]) -> tuple[Callable | None, Callable | None, dict]:
    """(judged eligible, judged strata, diagnostic controls) of a config."""
    c = p["c"]
    if p["host"] == "R0":
        ctl = {"class_matched": {"eligible": alive_ok, "strata": M1.placebo_stratum}}
        if c is not None:
            ctl["cost_band"] = {"eligible": alive_ok, "strata": cost_band(float(c))}
        return alive_ok, None, ctl
    ctl = {"unmatched": {"eligible": M1.placebo_ok, "strata": None}}
    if c is not None:
        ctl["cost_band"] = {"eligible": M1.placebo_ok, "strata": class_cost_band(float(c))}
    return M1.placebo_ok, M1.placebo_stratum, ctl


# =========================================================================== analysis (outcomes: never on debug)


def _mean(x: Any) -> float | None:
    a = np.asarray(x, float)
    a = a[np.isfinite(a)]
    return float(a.mean()) if len(a) else None


def _quantiles(x: Any) -> dict | None:
    a = np.asarray(x, float)
    a = a[np.isfinite(a)]
    if not len(a):
        return None
    return {"n": int(len(a)), "p10": float(np.quantile(a, 0.10)), "p25": float(np.quantile(a, 0.25)),
            "median": float(np.median(a)), "p75": float(np.quantile(a, 0.75)), "p90": float(np.quantile(a, 0.90)),
            "mean": float(a.mean())}


STATE_COLS = ["rt_dec", "mcap_dec_sol", "fee_bps_dec", "class_dec"]


def decision_state(ds: C.Dataset, t: pd.DataFrame, with_class: bool = False) -> pd.DataFrame:
    """Decision-time state of each trade (rt, market cap, fee tier and, optionally, the PLAN 4.2 class of
    ``m1.m1_class`` at t_dec): all known at the decision."""
    rows = []
    for m, td in zip(t["mint"], t["t_dec"]):
        s = ds.asof(str(m), float(td))
        rt = round_trip_frac(s)
        rows.append({"rt_dec": np.nan if rt is None else rt, "mcap_dec_sol": s.mcap_sol,
                     "fee_bps_dec": C.fee_bps_at(s.t, s.mcap_sol),
                     "class_dec": str(M1.m1_class(s)) if with_class else None})
    return pd.DataFrame(rows, columns=STATE_COLS, index=t.index)


def _keys(t: pd.DataFrame) -> list[tuple[str, float]]:
    return list(zip(t["mint"].astype(str), np.round(t["t_dec"].to_numpy(float), 3)))


def cost_rate(t: pd.DataFrame) -> np.ndarray:
    """Per trade, the share of the gross outcome lost to costs: 1 - (1 + net) / (1 + gross). Unlike gross - net, it
    does not grow with the price move (a winner pays its exit fee on a larger amount), so it never confounds the cost
    saving with selection (PREREG 7.1)."""
    net, gross = t["ret_net"].to_numpy(float), t["ret_mid"].to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(1.0 + gross > 1e-9, 1.0 - (1.0 + net) / (1.0 + gross), np.nan)


def _parts(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"n": 0, "net": None, "gross": None, "cost_rate": None}
    net, gross = t["ret_net"].to_numpy(float), t["ret_mid"].to_numpy(float)
    return {"n": int(len(t)), "net": float(net.mean()), "gross": float(gross.mean()), "cost_rate": _mean(cost_rate(t))}


def attribution_label(host_net: float | None, counterfactual: float | None) -> str | None:
    """PREREG 7.2: 'host already positive' (nothing to flip), 'cost' (the host's own trades at the filtered set's cost
    are positive), else 'selection, not cost'."""
    if host_net is None or counterfactual is None:
        return None
    if host_net > 0:
        return "host already positive"
    return "cost" if counterfactual > 0 else "selection, not cost"


def decompose(ds: C.Dataset, f: pd.DataFrame, b: pd.DataFrame, B: int = 2000) -> dict:
    """PREREG 7.1: filtered config ``f`` against its host baseline ``b`` (matched on mint and decision time)."""
    out: dict[str, Any] = {"n_host": int(len(b)), "n_filtered": int(len(f))}
    if not len(b):
        return out
    kb, kf = _keys(b), set(_keys(f))
    kept = np.array([k in kf for k in kb], bool)
    out["subset_of_host"] = bool(kf <= set(kb))
    out["kept_share"] = float(len(f) / len(b))
    host, filt, vet = _parts(b), _parts(f), _parts(b[~kept])
    out.update(host=host, filtered=filt, vetoed=vet)
    if filt["n"] and host["cost_rate"] is not None and filt["cost_rate"] is not None:
        out["net_gain"] = filt["net"] - host["net"]
        out["cost_saving"] = host["cost_rate"] - filt["cost_rate"]
        out["selection"] = filt["gross"] - host["gross"]
        # the host's own trades (its gross moves) at the filtered set's cost rate
        out["cost_alone_counterfactual"] = (1.0 + host["gross"]) * (1.0 - filt["cost_rate"]) - 1.0
        out["cost_alone_flips_host"] = bool(host["net"] <= 0 < out["cost_alone_counterfactual"])
        out["attribution"] = attribution_label(host["net"], out["cost_alone_counterfactual"])
    rb, rf = decision_state(ds, b)["rt_dec"], decision_state(ds, f)["rt_dec"]
    hb, hf = _mean(rb), _mean(rf)
    out["ex_ante_rt"] = {"host": hb, "filtered": hf, "saving": None if hb is None or hf is None else hb - hf}
    if 0 < int(kept.sum()) < len(kept):
        v = C.verdict_veto(b.reset_index(drop=True), ~kept, B=B)
        out["veto_view"] = {"verdict": v["verdict"], "n_flagged": v["n_flagged"], "n_unflagged": v["n_unflagged"],
                            "criteria": v.get("criteria")}
    return out


def guard_pair(g: pd.DataFrame, h: pd.DataFrame) -> dict:
    """PREREG 7.1: the guard config ``g`` against the same-c host-exit config ``h`` (same entries, other exits)."""
    hk = {k: i for i, k in enumerate(_keys(h))}
    gi, hi = [], []
    for i, k in enumerate(_keys(g)):
        if k in hk:
            gi.append(i)
            hi.append(hk[k])
    out: dict[str, Any] = {"n_guard": int(len(g)), "n_host_exit": int(len(h)), "n_matched": len(gi)}
    if not gi:
        return out
    gg, hh = g.iloc[gi].reset_index(drop=True), h.iloc[hi].reset_index(drop=True)
    fired = (gg["reason"] == "signal:tier_guard").to_numpy(bool)
    out["guard_exit_share"] = float(fired.mean())
    out["exit_fee_saving"] = float(((hh["fee_bps_out"] - gg["fee_bps_out"]) / 1e4).mean())
    out["exit_fee_saving_when_fired"] = float(((hh["fee_bps_out"] - gg["fee_bps_out"])[fired] / 1e4).mean()) \
        if fired.any() else None
    out["net_diff"] = float((gg["ret_net"] - hh["ret_net"]).mean())
    if fired.any():
        lv = [guard_level(float(p) * C.TOKEN_SUPPLY, float(t)) for p, t in zip(gg["entry_price"][fired],
                                                                               gg["t_in"][fired])]
        ok = [lvl is not None and float(px) * C.TOKEN_SUPPLY >= lvl for lvl, px in zip(lv, gg["exit_price"][fired])]
        out["guard_sale_at_or_above_boundary"] = float(np.mean(ok))
    return out


def cluster_stats(t: pd.DataFrame, clusters: Mapping[str, str] | None, hide: bool = False) -> dict:
    """Operator-cluster concentration (``m1.cluster_table``: coins linked by creator, symbol or a top-5 early pool
    buyer; a grouping, never a feature). The largest cluster = most trades, ties to the most profitable (the
    conservative removal). ``hide``: counts only."""
    if clusters is None:
        return {"n_clusters": None}
    if not len(t):
        out = {"n_clusters": 0, "largest_cluster_trades": 0, "largest_cluster_share": None}
        return out if hide else {**out, "mean_without_largest_cluster": None}
    cl = t["mint"].map(clusters).fillna(t["mint"]).astype(str)
    vc = cl.value_counts()
    prof = t["ret_net"].groupby(cl).sum() if not hide else pd.Series(0.0, index=vc.index)
    big = sorted(vc.index, key=lambda c: (-int(vc[c]), -float(prof[c]), str(c)))[0]
    out = {"n_clusters": int(len(vc)), "largest_cluster_trades": int(vc[big]),
           "largest_cluster_share": float(vc[big] / len(t))}
    if not hide:
        rest = t.loc[(cl != big).to_numpy(), "ret_net"]
        out["mean_without_largest_cluster"] = float(rest.mean()) if len(rest) else None
    return out


def evaluate(res: C.Result, ds: C.Dataset, clusters: Mapping[str, str] | None, *, B: int, hide: bool,
             n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts and DECISION-time costs only -- never returns, exit reasons, fill
    prices, the fee paid at the fills, the cost decomposition or placebo outcomes."""
    t = res.trades
    p = res.meta["params"]
    st = decision_state(ds, t, with_class=True) if len(t) else pd.DataFrame(columns=STATE_COLS)
    cls = st["class_dec"].astype(str) if len(t) else pd.Series(dtype=str)
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "host": p["host"], "c": p["c"], "guard": p["guard"],
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_tag_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "by_class_n": cls.value_counts().to_dict() if len(t) else {},
            **cluster_stats(t, clusters, hide=hide),
            "n_placebo": int(len(res.placebo)), "n_controls": {k: int(len(v)) for k, v in res.controls.items()},
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "decision_rt": _quantiles(st["rt_dec"]), "decision_mcap_sol": _quantiles(st["mcap_dec_sol"]),
            "decision_fee_bps": {str(k): int(v) for k, v in st["fee_bps_dec"].value_counts().sort_index().items()},
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
        base["cost_decomposition"] = {
            "mean_gross_move_worst_fills": float(mid.mean()), "mean_cost": float((mid - net).mean()),
            "mean_cost_rate": _mean(cost_rate(t)),
            "side_bps_in": {str(k): int(v) for k, v in t["fee_bps_in"].value_counts().sort_index().items()},
            "side_bps_out": {str(k): int(v) for k, v in t["fee_bps_out"].value_counts().sort_index().items()}}
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_tag"] = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} \
        if len(t) else {}
    base["by_class"] = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())}
                        for s, g in t.groupby(cls.to_numpy())} if len(t) else {}
    non_op = t.loc[(cls != "OPERATOR").to_numpy(), "ret_net"] if len(t) else pd.Series(dtype=float)
    base["mean_without_operator"] = float(non_op.mean()) if len(non_op) else None
    base.update(robust_check(p["host"], base))
    return base


def robust_check(host: str, e: Mapping[str, Any]) -> dict:
    """PREREG 9 concentration check (TRAIN qualifier and Z5.4). R0: mean > 0 on the non-OPERATOR trades (the cheap
    tiers are where one operator's coins sit). M1: M1's own check, mean > 0 without the largest operator cluster."""
    if host == "R0":
        return {"robust_check": "mean without OPERATOR-class coins", "robust_mean": e.get("mean_without_operator")}
    return {"robust_check": "mean without the largest operator cluster",
            "robust_mean": e.get("mean_without_largest_cluster")}


def analysis(ds: C.Dataset, results: Mapping[str, C.Result], B: int = 2000) -> dict:
    """PREREG 7.1 for every filtered config present whose baseline (and, for the guard, same-c host-exit config) also
    ran in this stage. Keys: the filtered config's role."""
    by_cfg = {config_key(r.meta["params"]): (role, r) for role, r in results.items()}
    out: dict[str, Any] = {}
    for role, r in results.items():
        p = r.meta["params"]
        if p["c"] is None:
            continue
        b = by_cfg.get(config_key(baseline_of(p)))
        if b is None:
            continue
        doc = {"config": config_key(p), "vs": config_key(baseline_of(p)),
               **decompose(ds, r.trades, b[1].trades, B=B)}
        if p["guard"]:
            h = by_cfg.get(config_key(make_params(p["host"], p["c"], False)))
            doc["guard_vs_host_exit"] = guard_pair(r.trades, h[1].trades) if h is not None else None
        out[role] = doc
    return out


def score_predictions(evals: Mapping[str, Mapping[str, Any]], dec: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 7.3 predictions P0-P4 (held = the expected negative result). Never decisive."""
    filt = {k: e for k, e in evals.items() if e.get("c") is not None}
    r0b = evals.get(config_key(make_params("R0", None, False))) or {}
    ci = (r0b.get("placebo") or {}).get("diff_ci95")
    sav = {k: d.get("cost_saving") for k, d in dec.items()}
    cf = {k: d.get("cost_alone_counterfactual") for k, d in dec.items()}
    gf = {k: (d.get("guard_vs_host_exit") or {}).get("exit_fee_saving") for k, d in dec.items()
          if d.get("guard_vs_host_exit") is not None}
    return {
        "P0_r0_baseline_control_ci_contains_0": {"held": None if not ci else bool(ci[0] <= 0 <= ci[1]), "ci95": ci},
        "P1_no_filtered_config_mean_net_above_0": {"held": all(e.get("mean") is None or e["mean"] <= 0
                                                               for e in filt.values()),
                                                   "values": {k: e.get("mean") for k, e in filt.items()}},
        "P2_cost_saving_below_1.5_points": {"held": all(v is None or v < PRED_MAX_SAVING for v in sav.values()),
                                            "values": sav, "bar": PRED_MAX_SAVING},
        "P3_cost_alone_flips_no_host": {"held": all(v is None or v <= 0 for v in cf.values()), "values": cf},
        "P4_guard_exit_fee_saving_below_0.1_point": {"held": all(v is None or v < PRED_MAX_GUARD_FEE
                                                                 for v in gf.values()),
                                                     "values": gf, "bar": PRED_MAX_GUARD_FEE},
        "note": "predictions are reports (PREREG 7.3); the TRAIN decision is decide_train's",
    }


# =========================================================================== pre-registered decisions (PREREG 9)


def _grid_index(key: str) -> int:
    return [config_key(p) for p in GRID].index(key)


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """Qualifiers among the filtered configs; shortlist = (best qualifier, its host baseline)."""
    rows = []
    for p in GRID:
        if p["c"] is None:
            continue
        key, bkey = config_key(p), config_key(baseline_of(p))
        e, b = evals[key], evals[bkey]
        pc = (e.get("placebo") or {}).get("mean_diff")
        cs = e.get("censored_share")
        powered = (e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
                   and (p["host"] != "M1" or (e.get("n_clusters") or 0) >= MIN_CLUSTERS))
        adds = None if e.get("mean") is None or b.get("mean") is None else e["mean"] - b["mean"]
        mwc = e.get("robust_mean")
        good = bool(powered and e.get("mean") is not None and e["mean"] > 0
                    and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                    and mwc is not None and mwc > 0
                    and pc is not None and pc > 0 and cs is not None and cs <= MAX_CENSORED
                    and adds is not None and adds > 0)
        ci = e.get("ci90")
        rows.append({"config": key, "baseline": bkey, "host": p["host"], "powered": bool(powered), "qualifies": good,
                     "n": e["n"], "coins": e["n_coins"], "clusters": e.get("n_clusters"), "mean": e.get("mean"),
                     "mean_without_top2": e.get("mean_without_top2"), "robust_check": e.get("robust_check"),
                     "robust_mean": mwc,
                     "ci90_lo": ci[0] if ci else None, "control_diff": pc, "filter_adds": adds,
                     "censored_share": cs})
    q = sorted((r for r in rows if r["qualifies"]),
               key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                              _grid_index(r["config"])))
    if q:
        best = next(p for p in GRID if config_key(p) == q[0]["config"])
        sl = [baseline_of(best), best]
        return {"verdict": "SHORTLISTED", "rows": rows, "candidate": config_key(best), "twin": config_key(sl[0]),
                "shortlist": sl, "shortlist_hashes": [C.params_hash(x) for x in sl]}
    if any(r["powered"] for r in rows):
        v = "NO_CONFIG"
        why = ("a powered filtered config failed the mean / top-2 / concentration / control / censoring / "
               "filter-adds bars")
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no filtered config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (M1 host: and "
               f">= {MIN_CLUSTERS} operator clusters); best: {max((r['n'] for r in rows), default=0)} trades")
    return {"verdict": v, "reason": why, "rows": rows, "shortlist": [], "shortlist_hashes": []}


def decide_val(ev_c: Mapping[str, Any], ev_t: Mapping[str, Any] | None) -> dict:
    n = ev_c["n"]
    mean, mw2 = ev_c.get("mean"), ev_c.get("mean_without_top2")
    tm = (ev_t or {}).get("mean")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0) and (tm is None or mean > tm)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "twin_mean": tm, "proceed": v in PROCEED_VAL}


def z5_extras(ev_c: Mapping[str, Any], ev_t: Mapping[str, Any] | None, dec: Mapping[str, Any] | None) -> list[dict]:
    """PREREG 9 TEST / CONFIRM extras: Z5.1 the filter adds (blocking), Z5.2 M1-host clusters (power), Z5.3 the
    attribution (a label, never blocking), Z5.4 positive without the largest operator cluster (blocking)."""
    cm, tm = ev_c.get("mean"), (ev_t or {}).get("mean")
    out = [{"id": "Z5.1", "name": "the filter adds: candidate mean - twin mean > 0",
            "pass": None if cm is None or tm is None else bool(cm - tm > 0),
            "value": None if cm is None or tm is None else cm - tm}]
    if ev_c.get("host") == "M1":
        nc = ev_c.get("n_clusters")
        out.append({"id": "Z5.2", "name": f"M1 host: >= {MIN_CLUSTERS} operator clusters",
                    "pass": None if nc is None else bool(nc >= MIN_CLUSTERS), "value": nc})
    else:
        out.append({"id": "Z5.2", "name": "M1 host: operator clusters (not applicable to R0)", "pass": None,
                    "value": None, "blocking_when_none": False})
    d = dec or {}
    out.append({"id": "Z5.3", "name": "attribution: cost saving vs selection (label)", "pass": None,
                "blocking_when_none": False,
                "value": {k: d.get(k) for k in ("cost_saving", "selection", "net_gain", "cost_alone_counterfactual",
                                                "cost_alone_flips_host", "attribution")}})
    rc = robust_check(str(ev_c.get("host")), ev_c)
    mwc = rc["robust_mean"]
    out.append({"id": "Z5.4", "name": f"concentration: {rc['robust_check']} > 0",
                "pass": None if mwc is None else bool(mwc > 0),
                "value": {"robust_mean": mwc, "by_class_n": ev_c.get("by_class_n"),
                          "largest_cluster_share": ev_c.get("largest_cluster_share"),
                          "n_clusters": ev_c.get("n_clusters")}})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 + 3.6 (common.verdict_entry) and the Z5 extras. Item 9 (FINAL mean > 0) is judged in
    the overall verdict once FINAL ran."""
    if base.get("auto_rejections"):
        return "REJECTED"
    ex = {e["id"]: e for e in extras}
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1) or ex["Z5.2"]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or ex["Z5.1"]["pass"] is False or ex["Z5.4"]["pass"] is False:
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(
            e["pass"] is None and e.get("blocking_when_none", True) for e in extras):
        return "INCOMPLETE"
    return "PASS"


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Z5 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame, twin: pd.DataFrame | None = None) -> dict:
    """PLAN 3.5 item 9 on the census thirds Z5 never looked at (the TRAIN third hosted the debug run: apart)."""
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


def _pair(sl: Mapping[str, Any] | None) -> tuple[dict | None, dict | None]:
    """(candidate, twin) of a shortlist: the filtered config and its host baseline."""
    if not sl:
        return None, None
    cand = [c for c in sl.get("configs", []) if c.get("c") is not None]
    twin = [c for c in sl.get("configs", []) if c.get("c") is None]
    return (cand[0] if cand else None), (twin[0] if twin else None)


def stage_configs(stage: str, shortlist_path: Path | None = None) -> list[tuple[str, dict]]:
    """[(role, params)]: the grid (debug / train), else the shortlisted pair (candidate, twin)."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    cand, twin = _pair(_shortlist(shortlist_path))
    if cand is None or twin is None:
        return []
    return [("candidate", cand), ("twin", twin)]


def m1_blocker(stage: str, ledger_path: Path | None = None, m1_out: Path | None = None) -> str | None:
    """Host-first rule (PREREG 9): None when Z5 may look at M1's entries on ``stage``'s split, else the reason.

    Allowed once M1 had its own look at that split group (trials ledger), or when M1 can no longer reach it."""
    split = STAGE_SPLIT[stage]
    grp = C.split_group(split)
    with C._ledger(ledger_path, write=False) as led:
        if C._family_looks(led, "M1", grp):
            return None
    d = Path(m1_out or M1.OUT_DIR)
    train = _read_json(d / "train.json")
    if not train or train.get("provisional"):
        return f"M1 has not finished TRAIN ({d}/train.json): M1 may still look at {split}"
    if (train.get("decision") or {}).get("verdict") != "SHORTLISTED":
        return None                                       # M1 stopped at TRAIN: it will never look at this split
    if stage == "val":
        return "M1 has not had its own VAL look yet"
    val = _read_json(d / "val.json")
    if not val:
        return f"M1 has not had its own VAL look yet, so it may still look at {split}"
    if (val.get("decision") or {}).get("verdict") not in M1.PROCEED_VAL:
        return None                                       # M1 stopped at VAL
    if stage == "test":
        return "M1 has not had its own TEST look yet"
    test = _read_json(d / "test.json")
    if not test:
        return f"M1 has not had its own TEST look yet, so it may still look at {split}"
    if stage == "confirm" and not M1.confirm_allowed(test)[0]:
        return None                                       # M1 will never spend CONFIRM
    return f"M1 has not had its own {stage.upper()} look yet"


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None, m1_out: Path | None = None) -> dict:
    """Raise :class:`Z5Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Z5Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Z5Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Z5Refused("PREREG.md changed after the first official TRAIN run; record changes in Z5/AMENDMENTS.md "
                        "as a new version instead")
    pins = host_pin_problems()
    if pins:
        raise Z5Refused("the registered hosts changed (a new Z5 version is needed): " + "; ".join(pins))
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Z5Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Z5Refused("TRAIN already ran on complete data (Z5/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Z5Refused("no TRAIN result (Z5/train.json): run --stage train first")
    if train.get("provisional"):
        raise Z5Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Z5Refused(f"TRAIN decision {tv}: Z5 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Z5Refused("no VAL shortlist for Z5 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise Z5Refused("the Z5 shortlist on disk differs from the one TRAIN wrote")
    cand, _twin = _pair(sl)
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Z5Refused("VAL already ran (Z5/val.json exists): VAL is evaluated once")
    else:
        val = _read_json(out_dir / "val.json")
        if not val:
            raise Z5Refused(f"no VAL result (Z5/val.json): {stage.upper()} needs a VAL decision first")
        vd = val.get("decision") or {}
        if vd.get("verdict") not in PROCEED_VAL:
            raise Z5Refused(f"VAL decision {vd.get('verdict')}: Z5 stopped (PLAN 8 rule 7 input); {stage.upper()} is "
                            "not spent")
        test = _read_json(out_dir / "test.json")
        if stage in ("confirm", "final") and not test:
            raise Z5Refused(f"never {stage.upper()} before TEST: run --stage test first")
        if stage == "confirm":
            ok_c, why = confirm_allowed(test)
            if not ok_c:
                raise Z5Refused(why)
        if (out_dir / f"{stage}.json").exists():
            raise Z5Refused(f"{stage.upper()} already ran (Z5/{stage}.json exists): one run per hypothesis")
        if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
               C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
            raise Z5Refused(f"{HYP} already had its one {split} run (trials ledger)")
        if env.get(STAGE_ENV[stage]) != "1":
            raise Z5Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    if cand is not None and cand.get("host") == "M1":
        why = m1_blocker(stage, ledger_path, m1_out)
        if why:
            raise Z5Refused(f"host-first rule: {why}")
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


def event_counts(ds: C.Dataset, results: Mapping[str, C.Result], days: float) -> dict:
    """Counts and DECISION-time costs only (no outcome): for each host, its entry decisions (the baseline's trades,
    whose t_dec is a decision, not an outcome), the quoted round trip and fee tier there, the share each c keeps, the
    ex-ante saving it quotes, and whether every filtered config's trades are a subset of the host's."""
    out: dict[str, Any] = {}
    by_cfg = {config_key(r.meta["params"]): r for r in results.values()}
    for host in HOST_ORDER:
        b = by_cfg.get(config_key(make_params(host, None, False)))
        if b is None:
            continue
        t = b.trades
        st = decision_state(ds, t, with_class=True) if len(t) else pd.DataFrame(columns=STATE_COLS)
        rt = st["rt_dec"].to_numpy(float)
        band = np.where(~np.isfinite(rt), "rt unknown", np.where(rt <= C_GRID[1], "rt <= 3.00%",
                                                                 np.where(rt <= C_GRID[0], "3.00-3.40%", "rt > 3.40%")))
        h: dict[str, Any] = {"host_entries": int(len(t)),
                             "host_entries_per_day": (len(t) / days) if math.isfinite(days) and days > 0 else None,
                             "decision_rt": _quantiles(rt), "decision_mcap_sol": _quantiles(st["mcap_dec_sol"]),
                             "decision_fee_bps": {str(k): int(v) for k, v in
                                                  st["fee_bps_dec"].value_counts().sort_index().items()},
                             "class_by_band": {str(bd): {str(k): int(v) for k, v in
                                                         st.loc[band == bd, "class_dec"].value_counts().items()}
                                               for bd in sorted(set(band.tolist()))},
                             "by_c": {}}
        for c in C_GRID:
            keep = np.isfinite(rt) & (rt <= c)
            f = by_cfg.get(config_key(make_params(host, c, False)))
            h["by_c"][f"c{100 * c:.2f}"] = {
                "quoted_kept": int(keep.sum()), "quoted_kept_share": float(keep.mean()) if len(rt) else None,
                "ex_ante_saving": (_mean(rt) - _mean(rt[keep])) if keep.any() else None,
                "filtered_trades": None if f is None else int(len(f.trades)),
                "subset_of_host": None if f is None else bool(set(_keys(f.trades)) <= set(_keys(t)))}
        g = by_cfg.get(config_key(make_params(host, GUARD_C, True)))
        hx = by_cfg.get(config_key(make_params(host, GUARD_C, False)))
        if g is not None and hx is not None:
            h["guard_config_trades"] = int(len(g.trades))
            h["guard_same_entries"] = bool(set(_keys(g.trades)) == set(_keys(hx.trades)))
        out[host] = h
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, m1_out: Path | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Z5/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason, m1_out=m1_out)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "z5_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Z5Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Z5Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Z5Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Z5Refused(str(e)) from e
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
        ct = M1.cluster_table(ds)                    # operator clusters for every config (PREREG 10, 13)
        clusters = dict(zip(ct["mint"], ct["cluster"]))
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "hosts": {"R0": {"params_hash": C.params_hash(R0_PARAMS)},
                                         "M1": {"version": M1.VERSION, "params_hash": C.params_hash(M1_PARAMS),
                                                "m1_py_sha256": _sha(Path(M1.__file__))}},
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds)}
        results: dict[str, C.Result] = {}
        for role, p in configs:
            elig, strata, ctl = placebo_spec(p)
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=elig, placebo_strata=strata,
                                       placebo_controls=ctl, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, ds, clusters, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        doc["n_trials_total"] = n_tr
        if debug:
            days = doc["span_days"]
            doc["event_counts"] = event_counts(ds, results, days)
            doc["entries_per_day"] = {k: (e["n"] / days if math.isfinite(days) and days > 0 else None)
                                     for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics, counts and decision-time costs only; returns "
                                                           "hidden"}
            return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
        _write_trades(out_dir, stage, provisional, results)
        dec = analysis(ds, results, B=min(B, 2000))
        doc["decomposition"] = dec
        if stage == "train":
            d = decide_train(evals)
            d["shortlist_written"] = False
            if d["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, d["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 9 pair rule, candidate {d['candidate']}")
                d["shortlist_written"] = True
            doc["decision"] = d
            doc["predictions"] = score_predictions(evals, dec)
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"], evals.get("twin"))
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = z5_extras(evals["candidate"], evals.get("twin"), dec.get("candidate"))
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "z5_extras": extras}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades,
                                             results["twin"].trades if "twin" in results else None)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"z5 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate + twin inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Z5Refused(str(e)) from e


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
    if not (fi.get("decision") or {}).get("mean_positive"):
        return "NO EDGE (FINAL mean <= 0)"
    lab = ((co.get("decomposition") or {}).get("candidate") or {}).get("attribution")
    return f"EDGE ({lab or 'attribution unknown'}: PREREG 7.2)"


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
    L = [f"# Z5 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Hosts:** R0 `{doc['hosts']['R0']['params_hash']}`; M1 {doc['hosts']['M1']['version']} "
         f"`{doc['hosts']['M1']['params_hash']}` (m1.py sha256 `{doc['hosts']['M1']['m1_py_sha256'][:12]}`).",
         f"- **Overall Z5 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics, counts and decision-time costs only. Returns, exit "
              "reasons, fill prices and placebo outcomes are hidden, and no parameter was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Host entry decisions and their quoted cost (no outcomes)", "",
              "| host | entries | per day | decision rt | decision mcap (SOL) | fee tier at decision (bps: n) |",
              "|---|---:|---:|---|---|---|"]
        for h, e in ec.items():
            epd = e["host_entries_per_day"]
            L.append(f"| {h} | {e['host_entries']} | {'n/a' if epd is None else round(epd, 1)}"
                     f" | {_q(e['decision_rt'], 100, '{:.2f}%')} | {_q(e['decision_mcap_sol'], 1, '{:,.0f}')} | "
                     f"{e['decision_fee_bps']} |")
        L += ["", "| host | c | kept (quoted) | kept share | ex-ante saving (quoted rt) | filtered trades | "
              "subset of host |", "|---|---|---:|---:|---:|---:|---|"]
        for h, e in ec.items():
            for c, v in e["by_c"].items():
                L.append(f"| {h} | {c} | {v['quoted_kept']} | {_pct(v['quoted_kept_share'], 1)} | "
                         f"{_pct(v['ex_ante_saving'], 2)} | {v['filtered_trades']} | {v['subset_of_host']} |")
        for h, e in ec.items():
            L.append(f"- {h}: PLAN 4.2 class at the entry decision, by quoted round trip: {e.get('class_by_band')}.")
        for h, e in ec.items():
            if "guard_config_trades" in e:
                L.append(f"- {h} guard config: {e['guard_config_trades']} trades; same entries as the c3.40 host-exit "
                         f"config: {e['guard_same_entries']}.")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | class at decision | operator clusters | largest cluster trades | "
                  "placebo trades | controls | horizon exits | entries/day |",
                  "|---|---:|---:|---|---:|---:|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e.get('by_class_n')} | "
                         f"{e.get('n_clusters')} | "
                         f"{e.get('largest_cluster_trades')} | {e['n_placebo']} | {e['n_controls']} | "
                         f"{e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | coins | classes | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | "
                  "concentration check | judged control diff | class-matched diff | cost-band diff | costs ×1.5 | "
                  "open fills | gross move | cost rate | censored |",
                  "|---|---|---:|---:|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ctl = e.get("controls") or {}
                cd = e.get("cost_decomposition") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {e.get('by_class_n')} | "
                         f"{_pct(e.get('mean'))} | {_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | "
                         f"{_pct(e.get('mean_without_top2'))} | {_pct(e.get('robust_mean'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('class_matched') or {}).get('mean_diff'))} | "
                         f"{_pct((ctl.get('cost_band') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                         f"{_pct((e.get('stress') or {}).get('open_fills'))} | "
                         f"{_pct(cd.get('mean_gross_move_worst_fills'))} | {_pct(cd.get('mean_cost_rate'), 2)} | "
                         f"{_pct(e.get('censored_share'), 0)} |")
        L.append("")
    dc = doc.get("decomposition")
    if dc:
        L += ["## Decomposition against the host baseline (PREREG 7)", "",
              "| role | config | kept share | net gain | cost saving | selection | ex-ante saving | host net | "
              "cost-alone counterfactual | cost alone flips host | veto view |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for k, d in dc.items():
            L.append(f"| {k} | {d['config']} | {_pct(d.get('kept_share'), 0)} | {_pct(d.get('net_gain'), 2)} | "
                     f"{_pct(d.get('cost_saving'), 2)} | {_pct(d.get('selection'), 2)} | "
                     f"{_pct((d.get('ex_ante_rt') or {}).get('saving'), 2)} | "
                     f"{_pct((d.get('host') or {}).get('net'))} | "
                     f"{_pct(d.get('cost_alone_counterfactual'), 2)} | {d.get('cost_alone_flips_host')} | "
                     f"{(d.get('veto_view') or {}).get('verdict')} |")
        for k, d in dc.items():
            gp = d.get("guard_vs_host_exit")
            if gp:
                L.append(f"- {k} guard vs host exit: matched {gp['n_matched']}, guard closed "
                         f"{_pct(gp.get('guard_exit_share'), 0)}, exit-fee saving "
                         f"{_pct(gp.get('exit_fee_saving'), 3)}, "
                         f"net difference {_pct(gp.get('net_diff'), 2)}, guard sales at or above the boundary "
                         f"{_pct(gp.get('guard_sale_at_or_above_boundary'), 0)}.")
        L.append("")
    pr = doc.get("predictions")
    if pr:
        L += ["## Pre-registered predictions (PREREG 7.3; reports, never decisive)", ""]
        for key, v in pr.items():
            if isinstance(v, dict) and "held" in v:
                L.append(f"- {key}: held = {v['held']}.")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, clusters {r['clusters']}, mean {_pct(r['mean'])}, "
                 f"{r.get('robust_check')} {_pct(r.get('robust_mean'))}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, control diff {_pct(r['control_diff'])}, filter adds "
                 f"{_pct(r['filter_adds'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (candidate {dec.get('candidate')}, twin "
                 f"{dec.get('twin')}).")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("z5_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    if "twin_mean" in dec:
        L.append(f"- VAL candidate n {dec.get('n')}, mean {_pct(dec.get('mean'))}; twin mean "
                 f"{_pct(dec.get('twin_mean'))}.")
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
    ap = argparse.ArgumentParser(description="Z5 fee-tier cost optimizer: pre-registered stages; see "
                                             "research/lab2/Z5/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: counts and decision-time costs only")
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
    except Z5Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
