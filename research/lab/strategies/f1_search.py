"""F1 dip-rebound-plus parameter search (TRAIN only) and validation/robustness of finalists.

Every evaluated configuration is appended to ``LAB/f1/trials.jsonl`` (one line per config and
split) so the number of tries is auditable for multiple-testing correction.

    python research/lab/strategies/f1_search.py stageA      # entry structure grid, 2 exits
    python research/lab/strategies/f1_search.py stageB      # exit grid on the most stable entries
    python research/lab/strategies/f1_search.py stageC      # local refinement around the best
    python research/lab/strategies/f1_search.py summary     # print the train leaderboard
    python research/lab/strategies/f1_search.py validate    # the train shortlist on VALIDATION (logged)
    python research/lab/strategies/f1_search.py finalize S1 S2   # robustness + finalists JSON

The TEST split is never touched (the harness refuses it anyway).
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
import multiprocessing as mp
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LABDIR = HERE.parent
sys.path.insert(0, str(LABDIR))

from costs import CostModel  # noqa: E402
from harness import LAB, SimConfig, load_coins, run_per_coin, run_portfolio  # noqa: E402

OUT = LAB / "f1"
TRIALS = OUT / "trials.jsonl"
STRAT_PATH = HERE / "f1-dip-rebound-plus.py"


def load_strategy_module():
    spec = importlib.util.spec_from_file_location("f1_dip_rebound_plus", STRAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


S = load_strategy_module()
_COINS: dict[str, list] = {}


def coins_for(split: str):
    if split not in _COINS:
        _COINS[split] = load_coins(split=split)
    return _COINS[split]


SLIM_KEYS = ("trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor",
             "expectancy_usd", "exp_ci95_pct", "net_pnl_usd", "total_return_pct", "final_equity_usd",
             "max_drawdown_pct", "best_coin_share_pct", "top3_share_pct", "pnl_without_best_coin_usd",
             "pnl_without_top3_usd", "exit_reasons", "costs_usd", "avg_hold_min")


def slim(m: dict) -> dict:
    out = {}
    for k in SLIM_KEYS:
        v = m.get(k)
        if isinstance(v, float):
            v = round(v, 4)
        out[k] = v
    return out


def extra_stats(trades) -> dict:
    """Per-trade return stats without the best coin / top 3 coins (by summed P&L)."""
    by: dict[str, float] = {}
    for t in trades:
        by[t.mint] = by.get(t.mint, 0.0) + t.pnl_usd
    ranked = sorted(by, key=lambda k: by[k], reverse=True)
    out = {}
    for label, drop in (("wo_best", ranked[:1]), ("wo_top3", ranked[:3])):
        rest = [t.ret for t in trades if t.mint not in set(drop)]
        out[f"avg_ret_pct_{label}"] = round(100 * statistics.fmean(rest), 4) if rest else None
    return out


def evaluate(params: dict, split: str, cfg: SimConfig | None = None, bootstrap: int = 2000,
             modes=("portfolio", "per_coin"), coins=None) -> dict:
    coins = coins if coins is not None else coins_for(split)
    fac = S.make(**params)
    res = {}
    if "portfolio" in modes:
        r = run_portfolio(fac, coins, cfg)
        m = slim(r.metrics(bootstrap))
        m.update(extra_stats(r.trades))
        m["rejected"] = r.rejected
        res["portfolio"] = m
    if "per_coin" in modes:
        r = run_per_coin(fac, coins, cfg)
        m = slim(r.metrics(bootstrap))
        m.update(extra_stats(r.trades))
        res["per_coin"] = m
    return res


def _job(args):
    tid, stage, params, split = args
    t0 = time.time()
    try:
        res = evaluate(params, split)
        err = None
    except Exception as e:  # pragma: no cover - logged, never hidden
        res, err = {}, repr(e)
    return {"id": tid, "stage": stage, "split": split, "params": params, **res, "error": err,
            "secs": round(time.time() - t0, 2)}


def run_grid(stage: str, grid: list[dict], split: str = "train", procs: int = 4) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    done = load_trials()
    start = max([t["id"] for t in done], default=-1) + 1
    jobs = [(start + k, stage, p, split) for k, p in enumerate(grid)]
    coins_for(split)  # load before forking
    out = []
    with mp.get_context("fork").Pool(procs) as pool, TRIALS.open("a") as fh:
        for rec in pool.imap_unordered(_job, jobs):
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            out.append(rec)
            if len(out) % 25 == 0:
                print(f"  {stage}: {len(out)}/{len(jobs)}", flush=True)
    return out


def load_trials() -> list[dict]:
    if not TRIALS.exists():
        return []
    return [json.loads(line) for line in TRIALS.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ grids

DD_BANDS = [(0.4, 0.6), (0.6, 0.8), (0.4, 0.8)]
MAX_REB = [1.3, 1.6, 2.0]
CONFIRMS = ["green2", "break", "vol", "hl", "break+vol"]
MIN_AGE = [0.0, 30.0, 120.0]
MIN_VOL = [2000.0, 10000.0]
EXITS_A = {
    "E1": dict(exit="fixed", stop_pct=0.20, tp_pct=0.40, max_hold_min=60.0),
    "E2": dict(exit="fixed", stop_pct=0.50, tp_pct=None, max_hold_min=30.0),
}


def grid_a() -> list[dict]:
    g = []
    for ex_name, ex in EXITS_A.items():
        for (dmin, dmax), mr, cf, age, vol in itertools.product(DD_BANDS, MAX_REB, CONFIRMS, MIN_AGE, MIN_VOL):
            g.append(dict(dd_min=dmin, dd_max=dmax, max_reb=mr, confirm=cf, min_age_min=age, min_vol_usd=vol,
                          **ex))
    return g


EXITS_B = [
    dict(exit="fixed", stop_pct=0.10, tp_pct=0.20, max_hold_min=15.0),
    dict(exit="fixed", stop_pct=0.15, tp_pct=0.30, max_hold_min=30.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=0.40, max_hold_min=60.0),
    dict(exit="fixed", stop_pct=0.25, tp_pct=0.50, max_hold_min=60.0),
    dict(exit="fixed", stop_pct=0.30, tp_pct=0.60, max_hold_min=120.0),
    dict(exit="fixed", stop_pct=0.15, tp_pct=0.60, max_hold_min=60.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=1.00, max_hold_min=120.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=0.30, tp_frac=0.5, trail_pct=0.15, trail_after_tp=True, max_hold_min=60.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=0.30, tp_frac=0.5, trail_pct=0.30, trail_after_tp=True, max_hold_min=60.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=0.30, tp_frac=0.5, trail_pct=0.15, trail_after_tp=True, max_hold_min=120.0),
    dict(exit="fixed", stop_pct=0.20, tp_pct=0.30, tp_frac=0.5, trail_pct=0.30, trail_after_tp=True, max_hold_min=120.0),
    dict(exit="atr", atr_k=1.5, r_mult=1.5, max_hold_min=60.0),
    dict(exit="atr", atr_k=1.5, r_mult=3.0, max_hold_min=60.0),
    dict(exit="atr", atr_k=3.0, r_mult=1.5, max_hold_min=60.0),
    dict(exit="atr", atr_k=3.0, r_mult=3.0, max_hold_min=60.0),
    dict(exit="lowstop", r_mult=1.5, max_hold_min=30.0),
    dict(exit="lowstop", r_mult=3.0, max_hold_min=30.0),
    dict(exit="lowstop", r_mult=1.5, max_hold_min=120.0),
    dict(exit="lowstop", r_mult=3.0, max_hold_min=120.0),
    dict(exit="fixed", stop_pct=0.50, tp_pct=None, max_hold_min=15.0),
    dict(exit="fixed", stop_pct=0.50, tp_pct=None, max_hold_min=60.0),
]
ENTRY_KEYS = ("dd_min", "dd_max", "max_reb", "confirm", "min_age_min", "min_vol_usd")
EXIT_KEYS = ("exit", "stop_pct", "tp_pct", "tp_frac", "trail_pct", "trail_after_tp", "max_hold_min", "atr_k",
             "r_mult", "low_buf", "atr_min", "atr_max", "atr_n")


# ------------------------------------------------------------------ scoring

MIN_TRADES, MIN_COINS = 15, 10


def score(rec: dict) -> float | None:
    """Train score = portfolio total return %, only with enough trades/coins (else None)."""
    pf = rec.get("portfolio") or {}
    if not pf or (pf.get("trades") or 0) < MIN_TRADES or (pf.get("coins_traded") or 0) < MIN_COINS:
        return None
    return pf.get("total_return_pct")


def pc_avg(rec: dict) -> float | None:
    pc = rec.get("per_coin") or {}
    if (pc.get("trades") or 0) < MIN_TRADES:
        return None
    return pc.get("avg_ret_pct")


def _key(p: dict, keys) -> tuple:
    return tuple((k, p.get(k)) for k in keys)


def stability_a(recs: list[dict]) -> list[tuple[float, dict, list]]:
    """Stage-A stability: mean score of a config and its one-step neighbours in the ordinal
    dimensions (max_reb, min_age_min, min_vol_usd) and across dd bands (same confirm, same exit)."""
    idx = {}
    for r in recs:
        p = r["params"]
        idx[_key(p, ENTRY_KEYS + ("exit", "stop_pct", "tp_pct", "max_hold_min"))] = r
    out = []
    for r in recs:
        s = score(r)
        if s is None:
            continue
        p = r["params"]
        neigh = []
        for dim, vals in (("max_reb", MAX_REB), ("min_age_min", MIN_AGE), ("min_vol_usd", MIN_VOL)):
            k = vals.index(p[dim])
            for kk in (k - 1, k + 1):
                if 0 <= kk < len(vals):
                    q = dict(p, **{dim: vals[kk]})
                    neigh.append(q)
        for band in DD_BANDS:
            if band != (p["dd_min"], p["dd_max"]):
                neigh.append(dict(p, dd_min=band[0], dd_max=band[1]))
        ns = []
        for q in neigh:
            rr = idx.get(_key(q, ENTRY_KEYS + ("exit", "stop_pct", "tp_pct", "max_hold_min")))
            if rr is not None:
                sc = score(rr)
                ns.append(sc if sc is not None else -100.0)  # too few trades counts as a failure
        stab = statistics.fmean([s] + ns)
        out.append((stab, r, ns))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


# ------------------------------------------------------------------ stages


def stage_a():
    recs = run_grid("A", grid_a())
    print(f"stage A: {len(recs)} configs")


def top_entries_from_a(n: int = 6) -> list[dict]:
    recs = [r for r in load_trials() if r["stage"] == "A" and r["split"] == "train"]
    ranked = stability_a(recs)
    seen, out = set(), []
    for stab, r, _ in ranked:
        e = _key(r["params"], ENTRY_KEYS)
        if e in seen:
            continue
        seen.add(e)
        out.append({k: r["params"][k] for k in ENTRY_KEYS})
        if len(out) >= n:
            break
    return out


def stage_b(n_entries: int = 6):
    entries = top_entries_from_a(n_entries)
    print("stage B entries:", json.dumps(entries, indent=0))
    grid = []
    for e in entries:
        for ex in EXITS_B:
            for me in (1, 3):
                grid.append(dict(e, **ex, max_entries=me))
    recs = run_grid("B", grid)
    print(f"stage B: {len(recs)} configs")


STAGE_C_BASES = (658, 638, 223)  # chosen after stage B: best per-coin mean with >= 25 trades and a positive
#                                   portfolio, preferring the entry that is near the top for many exits
STAGE_C_VARIATIONS = [dict(min_mcap=40_000.0), dict(max_mcap=1_000_000.0), dict(min_since_high=15),
                      dict(min_since_high=30), dict(min_reb=1.15), dict(vol_mult=1.5), dict(vol_mult=3.0),
                      dict(vol_base=10), dict(lookback_min=120), dict(max_age_min=240.0),
                      dict(max_age_min=1440.0), dict(min_vol_usd=5000.0)]


def stage_c():
    """One-at-a-time sensitivity around the stage-C bases (also a stability check)."""
    by_id = {r["id"]: r for r in load_trials()}
    grid = []
    for tid in STAGE_C_BASES:
        p = by_id[tid]["params"]
        for var in STAGE_C_VARIATIONS:
            q = dict(p, **var)
            if q != p:
                grid.append(q)
    recs = run_grid("C", grid)
    print(f"stage C: {len(recs)} configs")


def summary(top: int = 25):
    recs = [r for r in load_trials() if r["split"] == "train"]
    print(f"configs evaluated on TRAIN: {len(recs)} (errors: {sum(1 for r in recs if r.get('error'))})")
    by_stage: dict[str, int] = {}
    for r in recs:
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
    print("by stage:", by_stage)
    sc = [score(r) for r in recs]
    ok = [s for s in sc if s is not None]
    print(f"with >= {MIN_TRADES} trades and >= {MIN_COINS} coins: {len(ok)}; positive portfolio return: "
          f"{sum(1 for s in ok if s > 0)}; per-coin avg > 0: "
          f"{sum(1 for r in recs if (pc_avg(r) or -1) > 0)}; per-coin CI low > 0: "
          f"{sum(1 for r in recs if (r.get('per_coin') or {}).get('exp_ci95_pct') and r['per_coin']['exp_ci95_pct'][0] > 0 and (r['per_coin'].get('trades') or 0) >= MIN_TRADES)}")
    ranked = sorted((r for r in recs if score(r) is not None), key=score, reverse=True)
    for r in ranked[:top]:
        pf, pc = r["portfolio"], r["per_coin"]
        print(f"#{r['id']:4d} {r['stage']} ret={pf['total_return_pct']:7.1f}% dd={pf['max_drawdown_pct']:5.1f} "
              f"pf_tr={pf['trades']:3d} | pc tr={pc['trades']:3d} coins={pc['coins_traded']:3d} "
              f"avg={pc['avg_ret_pct']:6.2f} ci={pc['exp_ci95_pct']} wobest={pc.get('avg_ret_pct_wo_best')} "
              f"wotop3={pc.get('avg_ret_pct_wo_top3')} | "
              + " ".join(f"{k}={r['params'].get(k)}" for k in r["params"]))


# ------------------------------------------------------------------ validation (shortlist -> finalists)

# Shortlist picked from TRAIN only (before any validation run): the entry that stayed near the top
# for many exits (dd 60-80 %, rebound <= 2x the low, volume >= 2x its 30-bar mean) with its three
# best-behaved exits, the best wider-band variant, and two stage-C one-at-a-time "peaks" kept as a
# deliberate overfitting control (if peaks beat their stable parents on validation, fine; if not,
# that is evidence the train differences were noise).
SHORTLIST = {
    "S1_vol_dip_fixed": (628, {}),
    "S2_vol_dip_lowstop": (658, {}),
    "S3_vol_dip_partial_trail": (638, {}),
    "S4_vol_dip_wideband_10k": (223, {}),
    "S5_lowstop_lookback120": (658, {"lookback_min": 120}),
    "S6_lowstop_minreb115": (658, {"min_reb": 1.15}),
}


def shortlist_params() -> dict[str, dict]:
    by_id = {r["id"]: r for r in load_trials()}
    return {name: dict(by_id[tid]["params"], **over) for name, (tid, over) in SHORTLIST.items()}


def train_record(params: dict) -> dict | None:
    for r in load_trials():
        if r["split"] == "train" and r["params"] == params:
            return r
    return None


def validate():
    """Evaluate every shortlisted config on VALIDATION (each run is logged as a try)."""
    OUT.mkdir(parents=True, exist_ok=True)
    done = load_trials()
    nid = max([t["id"] for t in done], default=-1) + 1
    out = {}
    with TRIALS.open("a") as fh:
        for name, params in shortlist_params().items():
            t0 = time.time()
            res = evaluate(params, "validation")
            rec = {"id": nid, "stage": "V", "split": "validation", "name": name, "params": params, **res,
                   "error": None, "secs": round(time.time() - t0, 2)}
            nid += 1
            fh.write(json.dumps(rec, default=str) + "\n")
            out[name] = rec
            tr = train_record(params)
            for split, r in (("train", tr), ("valid", rec)):
                pc, pf = r["per_coin"], r["portfolio"]
                print(f"{name:26s} {split}: pc tr={pc['trades']:3d} coins={pc['coins_traded']:3d} "
                      f"win={pc['win_rate_pct']} avg={pc['avg_ret_pct']} ci={pc['exp_ci95_pct']} "
                      f"wobest={pc['avg_ret_pct_wo_best']} | pf ret={pf.get('total_return_pct')} "
                      f"dd={pf.get('max_drawdown_pct')} tr={pf['trades']}")
    (OUT / "validation_shortlist.json").write_text(json.dumps(out, indent=1, default=str))


def _halves(coins):
    coins = sorted(coins, key=lambda c: (c.created_ts, c.mint))
    k = len(coins) // 2
    return coins[:k], coins[k:]


def robustness(params: dict, split: str = "validation", audit: bool = True) -> dict:
    coins = coins_for(split)
    out: dict[str, Any] = {}
    out["base"] = evaluate(params, split)
    out["zero_costs"] = evaluate(params, split, SimConfig(cost=CostModel(
        ultra_bps=0, mev_bps=0, fee_mult=0, impact_mult=1e-9, priority_sol=0, base_fee_lamports=0)))
    for f in (1.5, 2.0):
        out[f"costs_x{f}"] = evaluate(params, split, SimConfig(cost=CostModel().stressed(f)))
    out["latency_plus1_bar"] = evaluate(params, split, SimConfig(entry_delay_bars=2))
    out["size_10usd"] = evaluate(params, split, SimConfig(fixed_usd=10.0, position_pct=0.10, max_usd=10.0))
    out["size_40usd"] = evaluate(params, split, SimConfig(fixed_usd=40.0, position_pct=0.40, max_usd=40.0))
    out["wick_worst"] = evaluate(params, split, SimConfig(wick_fill="worst"))
    out["wick_touch"] = evaluate(params, split, SimConfig(wick_fill="touch"))
    a, b = _halves(coins)
    out["first_half"] = evaluate(params, split, coins=a)
    out["second_half"] = evaluate(params, split, coins=b)
    out["first_half"]["coins"] = [len(a), a[0].created_ts, a[-1].created_ts]
    out["second_half"]["coins"] = [len(b), b[0].created_ts, b[-1].created_ts]
    pc = out["base"]["per_coin"]
    out["without_best_coin"] = {"avg_ret_pct": pc.get("avg_ret_pct_wo_best"),
                                "pnl_usd": pc.get("pnl_without_best_coin_usd"),
                                "portfolio_pnl_usd": out["base"]["portfolio"].get("pnl_without_best_coin_usd")}
    out["without_top3_coins"] = {"avg_ret_pct": pc.get("avg_ret_pct_wo_top3"),
                                 "pnl_usd": pc.get("pnl_without_top3_usd")}
    if audit:
        from harness import audit_lookahead
        out["audit_lookahead"] = audit_lookahead(S.make(**params), coins, cuts_per_coin=3, seed=11)
    return out


def _row(label: str, r: dict) -> str:
    pc, pf = r.get("per_coin") or {}, r.get("portfolio") or {}
    f = lambda v: None if v is None else round(v, 2)  # noqa: E731
    return (f"  {label:18s} pc: tr={pc.get('trades')} win={f(pc.get('win_rate_pct'))} avg={f(pc.get('avg_ret_pct'))} "
            f"ci={pc.get('exp_ci95_pct')} | pf: ret={f(pf.get('total_return_pct'))} "
            f"dd={f(pf.get('max_drawdown_pct'))} tr={pf.get('trades')}")


FINALISTS: list[str] = []  # filled in after looking at validate() output (see report)


def finalize(names: list[str]):
    sl = shortlist_params()
    n_train = sum(1 for r in load_trials() if r["split"] == "train")
    n_val = sum(1 for r in load_trials() if r["split"] == "validation")
    val = json.loads((OUT / "validation_shortlist.json").read_text())
    rows = []
    for name in names:
        params = sl[name]
        tr = train_record(params)
        print(f"== {name}")
        rob = robustness(params, "validation")
        for k, v in rob.items():
            if isinstance(v, dict) and ("per_coin" in v or "portfolio" in v):
                print(_row(k, v))
        print("  without best coin:", rob["without_best_coin"], " audit:", rob["audit_lookahead"][:3])
        rob_tr = robustness(params, "train", audit=True)
        print("  TRAIN gates:", _row("costs_x2", rob_tr["costs_x2"]), _row("wick_worst", rob_tr["wick_worst"]),
              rob_tr["without_best_coin"], rob_tr["without_top3_coins"], "audit:", rob_tr["audit_lookahead"][:3])
        rows.append({
            "name": name, "strategy_class": "DipReboundPlus",
            "module": "research/lab/strategies/f1-dip-rebound-plus.py",
            "params": params,
            "configs_tried": {"train": n_train, "validation_shortlist": n_val,
                              "note": "every train config is in LAB/f1/trials.jsonl; validation runs only "
                                      "for the shortlist; robustness variants are not selection tries"},
            "train_metrics": {"portfolio": tr["portfolio"], "per_coin": tr["per_coin"]},
            "validation_metrics": {"portfolio": val[name]["portfolio"], "per_coin": val[name]["per_coin"]},
            "robustness": {"validation": rob, "train": {k: rob_tr[k] for k in (
                "costs_x2", "wick_worst", "zero_costs", "without_best_coin", "without_top3_coins",
                "audit_lookahead", "first_half", "second_half")}},
        })
    dst = LABDIR / "finalists" / "f1-dip-rebound-plus.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(rows, indent=1, default=str))
    print("wrote", dst)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "finalize":
        finalize(sys.argv[2:] or FINALISTS)
    else:
        {"stageA": stage_a, "stageB": stage_b, "stageC": stage_c, "summary": summary,
         "validate": validate}[cmd]()
