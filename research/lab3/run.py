"""Lab 3 stage runner: TRAIN (shortlist <= 2) -> VAL (candidate) -> TEST (one look) per hypothesis, PLAN 5 rules.

    python research/lab3/run.py --hyp T1 --stage train
    python research/lab3/run.py --hyp T1 --stage val
    LAB3_ALLOW_TEST=1 python research/lab3/run.py --hyp T1 --stage test
    python research/lab3/run.py --benchmarks --stage train        # buy-and-hold / SOL / BTC / cash, not trials

Writes research/lab3/<HYP>/<stage>.json and .md. Every non-benchmark run is a counted trial in trials.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import core as C  # noqa: E402
import hypotheses as H  # noqa: E402

# PLAN 5 bars
TRAIN_MIN_SHARPE = 0.5
SHORTLIST_N = 2
N_PLACEBO = 200
BENCHMARKS = {"buy_hold_ew": None, "sol_only": ["SOL"], "btc_only": ["BTC"]}


def _load() -> tuple[C.Panel, pd.DataFrame]:
    P = C.panel(C.load_daily())
    return P, C.universe_mask(P)


def evaluate(
    P: C.Panel,
    U: pd.DataFrame,
    target: pd.DataFrame,
    split: str,
    *,
    costs: C.Costs,
    n_placebo: int,
    bench: Mapping[str, dict],
    n_trials: int,
    seed: int = 0,
) -> dict[str, Any]:
    run = C.backtest(P, target, split, costs, U)
    d = C.describe(run.ret, run.exposure, run.turnover, run.cost)
    d["stress_x2"] = C.describe(C.backtest(P, target, split, costs.stressed(2.0), U).ret).get("sharpe")
    d["gross_sharpe"] = C.describe(run.gross).get("sharpe")
    pl = C.placebo_runs(P, target, split, costs, U, n=n_placebo, seed=seed) if n_placebo else []
    d["placebo"] = C.placebo_compare(run, pl)
    bh = bench.get("buy_hold_ew") or {}
    d["vs_buy_hold"] = {
        "sharpe_diff": (d["sharpe"] or 0.0) - (bh.get("sharpe") or 0.0),
        "cagr_diff": (d["cagr"] or 0.0) - (bh.get("cagr") or 0.0),
        "mdd_better": d["max_drawdown"] > (bh.get("max_drawdown") or -1.0),
    }
    d["deflated_sharpe"] = C.deflated_sharpe(run.ret, n_trials)
    d["by_year"] = {str(y): round(float((1 + g).prod() - 1), 4) for y, g in run.ret.groupby(run.ret.index.year)}
    d["n_universe_mean"] = float(run.n_universe.mean())
    return d


def benchmarks(P: C.Panel, U: pd.DataFrame, split: str, costs: C.Costs) -> dict[str, dict]:
    out = {}
    for name, assets in BENCHMARKS.items():
        U_b = U if assets is None else U.where(U.columns.isin(assets), False)  # a single-asset sleeve: its own universe
        run = C.backtest(P, C.buy_and_hold(P, U_b, assets), split, costs, U_b)
        out[name] = C.describe(run.ret, run.exposure, run.turnover, run.cost)
    out["cash"] = {"sharpe": 0.0, "cagr": 0.0, "max_drawdown": 0.0}
    return out


def qualifies(ev: Mapping[str, Any], bh: Mapping[str, Any]) -> tuple[bool, list[str]]:
    why = []
    sh = ev.get("sharpe") or -9
    if sh <= TRAIN_MIN_SHARPE:
        why.append(f"sharpe {sh:.2f} <= {TRAIN_MIN_SHARPE}")
    if sh <= (bh.get("sharpe") or 0):
        why.append("sharpe <= buy-and-hold")
    if ev["max_drawdown"] <= (bh.get("max_drawdown") or -1):
        why.append("drawdown not better than buy-and-hold")
    ci = (ev.get("placebo") or {}).get("excess_ci95")
    if not ci or ci[0] <= 0:
        why.append("excess vs exposure-matched placebo CI95 not above 0")
    return (not why), why


def decide_train(evals: Mapping[str, Mapping[str, Any]], bench: Mapping[str, dict], grid: Mapping[str, dict]) -> dict:
    rows = []
    for key, ev in evals.items():
        ok, why = qualifies(ev, bench["buy_hold_ew"])
        rows.append(
            {
                "config": key,
                "sharpe": ev.get("sharpe"),
                "cagr": ev.get("cagr"),
                "mdd": ev["max_drawdown"],
                "placebo_excess_ci95": (ev.get("placebo") or {}).get("excess_ci95"),
                "qualifies": ok,
                "why": why,
            }
        )
    good = sorted([r for r in rows if r["qualifies"]], key=lambda r: -(r["sharpe"] or 0))
    top = good[:SHORTLIST_N]
    verdict = "SHORTLISTED" if top else "NO_CONFIG"
    return {
        "verdict": verdict,
        "rows": rows,
        "shortlist_keys": [r["config"] for r in top],
        "shortlist": [grid[r["config"]] for r in top],
        "bars": {"min_sharpe": TRAIN_MIN_SHARPE, "vs": "buy_hold_ew"},
    }


def decide_val(evals: Mapping[str, Mapping[str, Any]], shortlist_keys: list[str]) -> dict:
    cands = [(k, evals[k]) for k in shortlist_keys if k in evals]
    if not cands:
        return {"verdict": "NO_CANDIDATE"}
    k, ev = max(cands, key=lambda kv: kv[1].get("sharpe") or -9)
    ex = (ev.get("placebo") or {}).get("excess_daily_mean") or 0.0
    ok = (ev.get("sharpe") or 0) > 0 and ex > 0
    return {
        "verdict": "SELECTED" if ok else "FAIL_VAL",
        "candidate": k,
        "candidate_params": None,
        "twin": [c for c, _ in cands if c != k][:1],
        "val_sharpe": ev.get("sharpe"),
        "val_excess_daily": ex,
        "note": "the judge reads VAL before any TEST look",
    }


def decide_test(ev: Mapping[str, Any], bh: Mapping[str, Any]) -> dict:
    ci = (ev.get("placebo") or {}).get("excess_ci95")
    crit = {
        "sharpe_gt_0": (ev.get("sharpe") or 0) > 0,
        "placebo_excess_ci95_lo_gt_0": bool(ci and ci[0] > 0),
        "mdd_better_than_buy_hold": ev["max_drawdown"] > (bh.get("max_drawdown") or -1),
    }
    return {
        "verdict": "PASS" if all(crit.values()) else "FAIL",
        "criteria": crit,
        "note": "a PASS never funds real money by itself (PLAN 5)",
    }


def _md(hyp: dict, stage: str, doc: dict) -> str:
    L = [
        f"# {hyp['HYP']} {stage}: {hyp['name']}",
        "",
        f"- Split `{stage}` {C.SPLITS[stage]}; written {doc['utc']} UTC; runtime {doc['runtime_s']} s; "
        f"trials so far {doc['n_trials_total']} (lab 2 + lab 3).",
        "",
        "| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    f = lambda x, nd=2: "n/a" if x is None else f"{x:.{nd}f}"  # noqa: E731
    pct = lambda x: "n/a" if x is None else f"{100 * x:+.1f}%"  # noqa: E731
    for k, e in doc["configs"].items():
        pl = e.get("placebo") or {}
        ci = pl.get("excess_ci95")
        ci_s = "n/a" if not ci else f"[{100 * ci[0]:+.3f}%, {100 * ci[1]:+.3f}%]/day"
        dsr = (e.get("deflated_sharpe") or {}).get("dsr")
        L.append(
            f"| {k} | {f(e.get('sharpe'))} | {pct(e.get('cagr'))} | {pct(e.get('max_drawdown'))} | "
            f"{f(e.get('exposure'))} | {f(e.get('turnover_per_year'), 1)} | {pct(e.get('cost_drag_per_year'))} | "
            f"{f(e.get('gross_sharpe'))} | {f(e.get('stress_x2'))} | {f(pl.get('placebo_sharpe_mean'))} | "
            f"{f(pl.get('sharpe_p_value'))} | {pct(pl.get('excess_ann'))} | {ci_s} | {f(dsr)} |"
        )
    L += [
        "",
        "## Benchmarks (same split, same costs)",
        "",
        "| benchmark | Sharpe | CAGR | max DD |",
        "|---|---:|---:|---:|",
    ]
    for k, b in doc["benchmarks"].items():
        L.append(f"| {k} | {f(b.get('sharpe'))} | {pct(b.get('cagr'))} | {pct(b.get('max_drawdown'))} |")
    L += ["", "## By year", ""]
    for k, e in doc["configs"].items():
        L.append(f"- {k}: {e.get('by_year')}")
    dec = doc.get("decision") or {}
    L += ["", "## Decision", "", f"- **{dec.get('verdict')}**"]
    for r in dec.get("rows") or []:
        L.append(
            f"- {r['config']}: Sharpe {f(r['sharpe'])}, CAGR {pct(r['cagr'])}, DD {pct(r['mdd'])}, "
            f"qualifies {r['qualifies']} {r['why']}"
        )
    for key in ("shortlist_keys", "candidate", "twin", "val_sharpe", "criteria", "note"):
        if dec.get(key) is not None:
            L.append(f"- {key}: {dec[key]}")
    L.append("")
    return "\n".join(L)


def run_stage(
    hyp_name: str,
    stage: str,
    *,
    n_placebo: int = N_PLACEBO,
    out_root: Path = HERE,
    ledger: Path | None = None,
    P: C.Panel | None = None,
    env=None,
) -> dict:
    t0 = time.time()
    hyp = H.REGISTRY[hyp_name]
    out = Path(out_root) / hyp_name
    C.check_split_allowed(hyp_name, stage, out, env)
    if P is None:
        P, U = _load()
    else:
        U = C.universe_mask(P)
    costs = C.Costs()
    bench = benchmarks(P, U, stage, costs)
    grid_all = {hyp["config_key"](p): p for p in hyp["GRID"]}
    if stage == "train":
        grid = grid_all
    else:
        prev = json.loads((out / ("train.json" if stage == "val" else "val.json")).read_text())
        if stage == "val":
            keys = prev["decision"]["shortlist_keys"]
            if not keys:
                raise C.Refused(f"{hyp_name}: TRAIN shortlisted nothing")
        else:
            if prev["decision"].get("verdict") != "SELECTED":
                raise C.Refused(f"{hyp_name}: VAL did not select a candidate ({prev['decision'].get('verdict')})")
            keys = [prev["decision"]["candidate"]]
        grid = {k: grid_all[k] for k in keys}
    evals: dict[str, Any] = {}
    n_tr = None
    for key, p in grid.items():
        target = hyp["signal"](P, p)
        info = C.record_run(hyp_name, {**p, "hyp": hyp_name}, stage, {}, ledger)
        n_tr = info["n_trials_total"]
        evals[key] = evaluate(P, U, target, stage, costs=costs, n_placebo=n_placebo, bench=bench, n_trials=n_tr)
        C.record_run(hyp_name, {**p, "hyp": hyp_name}, stage, evals[key], ledger)  # the metrics, same config id
    doc: dict[str, Any] = {
        "hyp": hyp_name,
        "stage": stage,
        "split": C.SPLITS[stage],
        "utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "configs": evals,
        "benchmarks": bench,
        "n_trials_total": n_tr,
        "costs": dataclasses_asdict(costs),
    }
    if stage == "train":
        doc["decision"] = decide_train(evals, bench, grid_all)
    elif stage == "val":
        doc["decision"] = decide_val(evals, list(grid))
        doc["decision"]["candidate_params"] = grid_all.get(doc["decision"].get("candidate"))
    else:
        doc["decision"] = decide_test(evals[list(grid)[0]], bench["buy_hold_ew"])
    doc["runtime_s"] = round(time.time() - t0, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stage}.json").write_text(json.dumps(doc, indent=1, default=str))
    (out / f"{stage}.md").write_text(_md(hyp, stage, doc))
    return doc


def dataclasses_asdict(c: C.Costs) -> dict:
    import dataclasses

    return dataclasses.asdict(c)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hyp", choices=sorted(H.REGISTRY))
    ap.add_argument("--stage", choices=list(C.SPLITS), required=True)
    ap.add_argument("--n-placebo", type=int, default=N_PLACEBO)
    ap.add_argument("--benchmarks", action="store_true", help="print the benchmarks for the split and exit")
    a = ap.parse_args(argv)
    if a.benchmarks:
        P, U = _load()
        print(json.dumps(benchmarks(P, U, a.stage, C.Costs()), indent=1))
        return 0
    if not a.hyp:
        ap.error("--hyp is required")
    try:
        doc = run_stage(a.hyp, a.stage, n_placebo=a.n_placebo)
    except C.Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"wrote research/lab3/{a.hyp}/{a.stage}.json and .md; decision: {doc['decision'].get('verdict')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
