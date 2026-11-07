"""Independent judge: reproduce finalists on VALIDATION, freeze them, then ONE pass on TEST.

    python research/lab/judge/judge.py validate          # reproduce every finalist on VALIDATION
    python research/lab/judge/judge.py freeze            # write frozen_finalists.json (hashes + rule)
    python research/lab/judge/judge.py dryrun            # the exact TEST pipeline, on VALIDATION
    LAB_ALLOW_TEST=1 python research/lab/judge/judge.py test   # the single TEST pass (refuses a 2nd run)

The TEST pass reads ONLY frozen_finalists.json, checks every hash, writes a marker before it
touches a TEST coin and refuses to run again once the marker exists. Results go to LAB/judge/.
Nothing under src/ or tests/ is touched; nightcrawler is imported read-only for its baseline.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
LABDIR = HERE.parent
sys.path.insert(0, str(LABDIR))

import harness as H  # noqa: E402
from costs import CostModel, SolUsd  # noqa: E402

OUT = H.LAB / "judge"
FROZEN = HERE / "frozen_finalists.json"
MARKER = OUT / "TEST_PASS_STARTED"
FINALIST_DIR = LABDIR / "finalists"
B_CI = 2000  # the lab's usual coin bootstrap for the 95 % CI (same seed as harness.metrics)
B_P = 200_000  # coin bootstrap draws for p-values (resolution 5e-6)
ALPHA = 0.05


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # the F4 pickles reference "f4_learned.FoldEnsemble"
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


F1 = _load("f1_dip_rebound_plus", LABDIR / "strategies" / "f1-dip-rebound-plus.py")
F4 = _load("f4_learned", LABDIR / "strategies" / "f4-learned.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lab_path(p: str) -> Path:
    """Finalist files write data paths as LAB/... and code paths as research/lab/..."""
    if p.startswith("LAB/"):
        return H.LAB / p[4:]
    return LABDIR.parent.parent / p


# =========================================================================== finalists


def load_finalists() -> list[dict]:
    out = []
    for f in sorted(FINALIST_DIR.glob("*.json")):
        for x in json.loads(f.read_text()):
            out.append({"family_file": f.name, **x})
    return out


_TABLES: dict[tuple, dict] = {}


def f4_table(model_file: Path, gate: Any, coins: list, sol: SolUsd) -> dict[str, np.ndarray]:
    """Per-coin scores built exactly like f4_learned_search.build/score_table: causal feature rows,
    gate, rows with a next bar, fold-ensemble average."""
    key = (str(model_file), gate, tuple(c.mint for c in coins))
    if key in _TABLES:
        return _TABLES[key]
    ens = F4.FoldEnsemble.load(model_file)
    table = {}
    for coin in coins:
        arr = np.full(coin.n, np.nan)
        F = F4.coin_features(coin, sol)
        g = F4.gate_mask(F, F4.vol10(coin.v), gate)
        rows = np.nonzero(g)[0]
        rows = rows[rows + 1 < coin.n]
        if len(rows):
            arr[rows] = ens.score(F[rows])
        table[coin.mint] = arr
    _TABLES[key] = table
    return table


def factory_for(fin: dict, coins: list, sol: SolUsd, live: bool = False):
    cls = fin["strategy_class"]
    if cls == "DipReboundPlus":
        return F1.make(**fin["params"])
    if cls == "F4Learned":
        p = F4.F4Params(**fin["params"]["strategy"])
        model_file = lab_path(fin["params"]["model_file"])
        if live:
            return F4.factory(p, F4.ModelScorer(F4.FoldEnsemble.load(model_file), p.gate))
        return F4.factory(p, F4.TableScorer(f4_table(model_file, p.gate, coins, sol)))
    raise ValueError(f"unknown strategy class {cls}")


# =========================================================================== metrics


def coin_sums(trades) -> tuple[np.ndarray, np.ndarray]:
    by: dict[str, list[float]] = {}
    for t in trades:
        by.setdefault(t.mint, []).append(t.ret)
    sums = np.array([sum(v) for v in by.values()], dtype=float)
    lens = np.array([len(v) for v in by.values()], dtype=float)
    return sums, lens


def boot_means(sums: np.ndarray, lens: np.ndarray, b: int, seed: int) -> np.ndarray:
    """Coin-level bootstrap of the pooled mean per-trade return (resample coins with replacement)."""
    rng = np.random.default_rng(seed)
    n = len(sums)
    out = np.empty(b)
    step = max(1, 2_000_000 // max(n, 1))
    for a in range(0, b, step):
        k = min(step, b - a)
        idx = rng.integers(0, n, size=(k, n))
        out[a:a + k] = sums[idx].sum(1) / lens[idx].sum(1)
    return out


def boot_test(trades, b: int = B_P, seed: int = 20261008, m: int = 1) -> dict:
    """One-sided H0: mean per-trade return <= 0, coin-level bootstrap (resample coins, pool their trades).

    Primary p-value = CI inversion: p = (1 + #{bootstrap mean <= 0}) / (B + 1), i.e. the smallest one-sided
    level at which the percentile CI excludes 0. (A null-SHIFTED bootstrap was tried in the VALIDATION dry run
    and rejected: with returns capped by the take-profit, the shifted resamples can never reach the observed
    mean, giving p ~ 1e-6 for a strategy whose 95 % CI includes 0.)
    Cross-check: cluster-robust t statistic (coins as clusters), Student t with n_coins - 1 df.
    CIs: 95 % and the Bonferroni level 1 - 0.05/m (two-sided)."""
    from scipy import stats as st
    sums, lens = coin_sums(trades)
    n = len(sums)
    if n < 2:
        return {"p_one_sided": None, "n_coins": int(n)}
    mu = sums.sum() / lens.sum()
    bs = boot_means(sums, lens, b, seed)
    p = (1 + int((bs <= 0).sum())) / (b + 1)
    resid = sums - mu * lens
    se = math.sqrt(n / (n - 1) * float((resid ** 2).sum())) / lens.sum()
    t = mu / se if se > 0 else math.inf
    p_t = float(st.t.sf(t, n - 1)) if math.isfinite(t) else 0.0
    q = lambda a: round(100 * float(np.quantile(bs, a)), 3)  # noqa: E731
    a = ALPHA / (2 * m)
    return {"mean_pct": round(100 * mu, 3), "p_one_sided": p, "p_cluster_t": p_t, "t_stat": round(t, 3),
            "n_coins": int(n), "ci95_pct": [q(0.025), q(0.975)], "ci_bonf_pct": [q(a), q(1 - a)],
            "ci_bonf_level": 1 - 2 * a}


KEEP = ["coins", "trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor",
        "expectancy_usd", "exp_ci95_pct", "net_pnl_usd", "total_return_pct", "final_equity_usd",
        "max_drawdown_pct", "best_coin_share_pct", "top3_share_pct", "pnl_without_best_coin_usd",
        "pnl_without_top3_usd", "exit_reasons", "costs_usd", "avg_hold_min"]


def summ(res: H.Result) -> dict:
    m = res.metrics(B_CI)
    out = {k: (round(m[k], 4) if isinstance(m.get(k), float) else m.get(k)) for k in KEEP}
    by: dict[str, list] = {}
    for t in res.trades:
        by.setdefault(t.mint, []).append(t)
    ranked = sorted(by, key=lambda mm: sum(t.pnl_usd for t in by[mm]), reverse=True)
    for lab, drop in (("avg_ret_pct_wo_best", 1), ("avg_ret_pct_wo_top3", 3)):
        rest = [t.ret for mm in ranked[drop:] for t in by[mm]]
        out[lab] = round(100 * float(np.mean(rest)), 4) if rest else None
    out["best_coin"] = by[ranked[0]][0].symbol if ranked else None
    if res.rejected:
        out["rejected"] = dict(res.rejected)
    return out


def run_both(fac, coins: list, cfg: H.SimConfig | None = None, sol: SolUsd | None = None,
             keep_trades: bool = False) -> dict:
    pc = H.run_per_coin(fac, coins, cfg or H.SimConfig(), sol)
    pf = H.run_portfolio(fac, coins, cfg, sol)
    out = {"per_coin": summ(pc), "portfolio": summ(pf)}
    if keep_trades:
        out["_pc_trades"] = pc.trades
        out["_pf_trades"] = pf.trades
    return out


def trade_rows(trades) -> list[dict]:
    rows = []
    for t in trades:
        d = t.to_dict()
        d.pop("fills", None)
        rows.append(d)
    return rows


# =========================================================================== validation reproduction


def _close(a, b, tol=0.02) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= tol


def validate() -> dict:
    sol = SolUsd.from_lab()
    coins = H.load_coins(split="validation")
    fins = load_finalists()
    rep: dict[str, Any] = {"n_validation_coins": len(coins), "finalists": {}}
    for fin in fins:
        t0 = time.time()
        fac = factory_for(fin, coins, sol)
        got = {"base": run_both(fac, coins, None, sol),
               "costs_x1.5": run_both(fac, coins, H.SimConfig(cost=CostModel().stressed(1.5)), sol),
               "latency_+1bar": run_both(fac, coins, H.SimConfig(entry_delay_bars=2), sol)}
        rob = fin["robustness"]["validation"]
        lat_key = "latency_plus1_bar" if "latency_plus1_bar" in rob else "latency_+1bar"
        reported = {"base": fin["validation_metrics"], "costs_x1.5": rob["costs_x1.5"], "latency_+1bar": rob[lat_key]}
        checks = {}
        for var in got:
            for mode in ("per_coin", "portfolio"):
                g, r = got[var][mode], reported[var][mode]
                for k in ("trades", "avg_ret_pct", "exp_ci95_pct", "total_return_pct", "net_pnl_usd"):
                    if r.get(k) is None:
                        continue  # the finalist file did not report this field
                    ok = _close(g.get(k), r.get(k))
                    checks[f"{var}.{mode}.{k}"] = {"reported": r.get(k), "judge": g.get(k), "match": ok}
        mism = [k for k, v in checks.items() if not v["match"]]
        extra = {}
        if fin["strategy_class"] == "F4Learned":
            # the search's saved VALIDATION scores vs the judge's freshly built table (same model file)
            tbl = f4_table(lab_path(fin["params"]["model_file"]), F4.F4Params(**fin["params"]["strategy"]).gate,
                           coins, sol)
            saved = np.load(H.LAB / "f4" / "scores" / f"val_{fin['params']['label']}_{fin['params']['model']}.npy")
            ds = np.load(H.LAB / "f4" / "dataset_validation.npz", allow_pickle=False)
            mints, ci, bar = ds["mints"], ds["coin"], ds["bar"]
            mine = np.array([tbl[str(mints[c])][b] for c, b in zip(ci, bar)])
            extra["score_table_max_abs_diff_vs_saved"] = float(np.nanmax(np.abs(mine - saved)))
            extra["score_table_rows"] = int(len(saved))
            n_tbl = int(sum(np.isfinite(a).sum() for a in tbl.values()))
            extra["score_table_rows_judge"] = n_tbl
        rep["finalists"][fin["name"]] = {"mismatches": mism, "checks": checks, "extra": extra,
                                         "judge": got, "secs": round(time.time() - t0, 1)}
        b = got["base"]
        print(f"{fin['name']}: pc n={b['per_coin']['trades']} avg={b['per_coin']['avg_ret_pct']} "
              f"ci={b['per_coin']['exp_ci95_pct']} | pf ret={b['portfolio']['total_return_pct']} "
              f"n={b['portfolio']['trades']}  mismatches={mism} extra={extra} ({time.time() - t0:.0f}s)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation_reproduction.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


# =========================================================================== freeze


CONFIGS_TRIED = {
    # logged selection tries (counted from the run logs by the judge) + unlogged exploration (from reports)
    "f1-dip-rebound-plus": {"train": 828, "validation": 6, "unlogged": "event study on TRAIN to design the grid"},
    "f2-momentum": {"train": 982, "validation": 19, "unlogged": "68 exploratory event-study checks on TRAIN"},
    "f3-lifecycle": {"train": 487, "validation": 8, "unlogged": "13 logged event-study cuts (149 groups) + 3 drill-downs"},
    "f4-learned": {"train": 240, "validation": 5, "unlogged": "none reported"},
}

DECISION_RULE = {
    "family_for_adjustment": "the finalists evaluated on TEST (Holm over m = number of frozen finalists)",
    "winner_requires_all": {
        "W1_trades": "per-coin TEST trades >= 30",
        "W2_net_profitable": "per-coin TEST mean net return per trade > 0 AND $100 portfolio total return > 0",
        "W3_adjusted_significance": "Holm-adjusted one-sided coin-bootstrap p < 0.05 AND the Bonferroni "
                                    "(1 - 0.05/m two-sided) coin-bootstrap CI lower bound > 0",
        "W4_costs_x1.5": "per-coin mean > 0 AND portfolio return > 0 with every cost component x1.5",
        "W5_latency": "per-coin mean > 0 AND portfolio return > 0 with fills one extra bar later",
        "W6_concentration": "per-coin P&L > 0 without the best coin AND without the top-3 coins; "
                            "portfolio return > 0 re-run without the best coin",
        "W7_fill_realism": "per-coin mean > 0 with rug-aware stop fills (a stop fills no better than the bar close)",
        "W8_lookahead": "audit_lookahead on the TEST coins returns no problems",
    },
    "informational_only": [
        "Bonferroni across every configuration tried in the lab (deflated view)",
        "costs x2, wick_fill=worst",
        "baselines on TEST: random entry, buy at graduation hold 60 min, nightcrawler default",
        "validation-stage verdicts of the researchers (all finalists were marked REJECTED / recommend_test=false)",
    ],
    "no_retuning": "Parameters, thresholds and model files are frozen by hash; nothing is changed after TEST.",
}


def freeze(validation_report: dict | None = None) -> dict:
    fins = load_finalists()
    rep = validation_report or json.loads((OUT / "validation_reproduction.json").read_text())
    code = {p: sha256(LABDIR / p) for p in ("harness.py", "costs.py", "strategies/f1-dip-rebound-plus.py",
                                            "strategies/f4-learned.py", "f4_learned_search.py", "baseline.py",
                                            "judge/judge.py")}
    frozen = []
    for fin in fins:
        entry = {"name": fin["name"], "family_file": fin["family_file"], "strategy_class": fin["strategy_class"],
                 "module": fin["module"], "params": fin["params"], "researcher_verdict": fin["verdict"],
                 "recommend_test": fin["recommend_test"],
                 "validation_reproduced": not rep["finalists"][fin["name"]]["mismatches"],
                 "validation_mismatches": rep["finalists"][fin["name"]]["mismatches"]}
        if fin["strategy_class"] == "F4Learned":
            mf = lab_path(fin["params"]["model_file"])
            entry["model_sha256"] = sha256(mf)
        frozen.append(entry)
    total_train = sum(v["train"] for v in CONFIGS_TRIED.values())
    total_val = sum(v["validation"] for v in CONFIGS_TRIED.values())
    doc = {"frozen_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "finalists": frozen,
           "m": len(frozen), "configs_tried": CONFIGS_TRIED,
           "configs_tried_total": {"train": total_train, "validation": total_val, "all": total_train + total_val},
           "code_sha256": code, "splits_sha256": sha256(H.SPLITS), "decision_rule": DECISION_RULE,
           "test_cost_model": "CostModel() defaults; wick_fill='half'; $20 per-coin; $100 portfolio"}
    FROZEN.write_text(json.dumps(doc, indent=1))
    print(f"frozen {len(frozen)} finalists -> {FROZEN}")
    return doc


# =========================================================================== the TEST pass


def holm(pvals: list[float | None]) -> list[float | None]:
    idx = [k for k, p in enumerate(pvals) if p is not None]
    m = len(idx)
    order = sorted(idx, key=lambda k: pvals[k])
    adj: list[float | None] = [None] * len(pvals)
    running = 0.0
    for r, k in enumerate(order):
        running = max(running, min(1.0, (m - r) * pvals[k]))
        adj[k] = running
    return adj


def _pos(d: dict | None, mode: str, key: str) -> bool:
    v = ((d or {}).get(mode) or {}).get(key)
    return v is not None and v > 0


def check_frozen() -> tuple[dict, list[dict]]:
    doc = json.loads(FROZEN.read_text())
    for p, h in doc["code_sha256"].items():
        if sha256(LABDIR / p) != h:
            raise SystemExit(f"{p} changed after the freeze")
    if sha256(H.SPLITS) != doc["splits_sha256"]:
        raise SystemExit("splits.json changed after the freeze")
    fins = []
    by_name = {f["name"]: f for f in load_finalists()}
    for e in doc["finalists"]:
        f = by_name[e["name"]]
        if f["params"] != e["params"]:
            raise SystemExit(f"{e['name']} params changed after the freeze")
        if "model_sha256" in e and sha256(lab_path(e["params"]["model_file"])) != e["model_sha256"]:
            raise SystemExit(f"{e['name']} model changed after the freeze")
        fins.append(f)
    return doc, fins


def full_eval(split: str, doc: dict, fins: list[dict], out_name: str, audit_cuts: int = 1) -> dict:
    """Every frozen finalist on ``split``: base, robustness, bootstrap, audit; baselines; Holm; gates."""
    sol = SolUsd.from_lab()
    coins = H.load_coins(split=split)
    m = len(fins)
    print(f"{split.upper()}: {len(coins)} coins in the default universe, {m} finalists", flush=True)
    res: dict[str, Any] = {"split": split, "n_coins": len(coins), "started_utc":
                           time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "finalists": {}, "baselines": {}}
    from f4_learned_search import rug_aware_fills  # same stress the researchers used (F2/F4)

    for fin in fins:
        t0 = time.time()
        name = fin["name"]
        fac = factory_for(fin, coins, sol)
        r: dict[str, Any] = {}
        base = run_both(fac, coins, None, sol, keep_trades=True)
        pc_trades, pf_trades = base.pop("_pc_trades"), base.pop("_pf_trades")
        r["base"] = base
        r["trades_per_coin"] = trade_rows(pc_trades)
        r["trades_portfolio"] = trade_rows(pf_trades)
        r["bootstrap"] = boot_test(pc_trades, m=m)
        r["costs_x1.5"] = run_both(fac, coins, H.SimConfig(cost=CostModel().stressed(1.5)), sol)
        r["costs_x2"] = run_both(fac, coins, H.SimConfig(cost=CostModel().stressed(2.0)), sol)
        r["latency_+1bar"] = run_both(fac, coins, H.SimConfig(entry_delay_bars=2), sol)
        r["wick_worst"] = run_both(fac, coins, H.SimConfig(wick_fill="worst"), sol)
        with rug_aware_fills():
            r["rug_aware_fills"] = run_both(fac, coins, None, sol)
        by: dict[str, float] = {}
        for t in pc_trades:
            by[t.mint] = by.get(t.mint, 0.0) + t.pnl_usd
        if by:
            best = max(by, key=by.get)
            rest = [c for c in coins if c.mint != best]
            r["without_best_coin"] = run_both(fac, rest, None, sol)  # table scorer is keyed by mint
            r["without_best_coin"]["removed"] = next(c.symbol for c in coins if c.mint == best)
        half = len(coins) // 2
        r["first_half"] = run_both(fac, coins[:half], None, sol)
        r["second_half"] = run_both(fac, coins[half:], None, sol)
        # lookahead audit with the live-style strategy (F4: ModelScorer on the view, not the table)
        t1 = time.time()
        live = factory_for(fin, coins, sol, live=True)
        r["audit_lookahead"] = H.audit_lookahead(live, coins, cuts_per_coin=audit_cuts, seed=99, sol=sol)
        if fin["strategy_class"] == "F4Learned":
            lv = H.run_per_coin(live, coins, H.SimConfig(), sol)
            a = [(t.mint, t.entry_ts, round(t.ret, 9)) for t in lv.trades]
            b = [(t.mint, t.entry_ts, round(t.ret, 9)) for t in pc_trades]
            r["live_scorer_equals_table"] = a == b
        r["audit_secs"] = round(time.time() - t1, 1)
        r["secs"] = round(time.time() - t0, 1)
        res["finalists"][name] = r
        pc = base["per_coin"]
        print(f"{name}: n={pc['trades']} avg={pc['avg_ret_pct']} ci={pc['exp_ci95_pct']} "
              f"p={r['bootstrap'].get('p_one_sided')} port={base['portfolio']['total_return_pct']} "
              f"audit={len(r['audit_lookahead'])} ({r['secs']}s, audit {r['audit_secs']}s)", flush=True)

    import baseline as BL  # nightcrawler imported read-only
    for key, cls in BL.BASELINES.items():
        t0 = time.time()
        b = run_both(cls, coins, None, sol, keep_trades=True)
        tr = b.pop("_pc_trades")
        b.pop("_pf_trades")
        b["bootstrap"] = boot_test(tr, b=20_000)
        res["baselines"][key] = b
        print(f"baseline {key}: n={b['per_coin']['trades']} avg={b['per_coin']['avg_ret_pct']} "
              f"port={b['portfolio']['total_return_pct']} ({time.time() - t0:.0f}s)", flush=True)

    names = [f["name"] for f in fins]
    pv = [res["finalists"][n]["bootstrap"].get("p_one_sided") for n in names]
    adj = holm(pv)
    n_all = doc["configs_tried_total"]["all"]
    for n, p, a in zip(names, pv, adj):
        r = res["finalists"][n]
        r["p_holm"] = a
        r["p_bonferroni_all_configs"] = None if p is None else min(1.0, p * n_all)
        pc = r["base"]["per_coin"]
        ci_b = r["bootstrap"].get("ci_bonf_pct")
        gates = {
            "W1_trades": (pc["trades"] or 0) >= 30,
            "W2_net_profitable": _pos(r["base"], "per_coin", "avg_ret_pct")
                                  and _pos(r["base"], "portfolio", "total_return_pct"),
            "W3_adjusted_significance": a is not None and a < ALPHA and bool(ci_b) and ci_b[0] > 0,
            "W4_costs_x1.5": _pos(r["costs_x1.5"], "per_coin", "avg_ret_pct")
                              and _pos(r["costs_x1.5"], "portfolio", "total_return_pct"),
            "W5_latency": _pos(r["latency_+1bar"], "per_coin", "avg_ret_pct")
                           and _pos(r["latency_+1bar"], "portfolio", "total_return_pct"),
            "W6_concentration": (pc.get("pnl_without_best_coin_usd") or -1) > 0
                                 and (pc.get("pnl_without_top3_usd") or -1) > 0
                                 and _pos(r.get("without_best_coin"), "portfolio", "total_return_pct"),
            "W7_fill_realism": _pos(r["rug_aware_fills"], "per_coin", "avg_ret_pct"),
            "W8_lookahead": not r["audit_lookahead"],
        }
        r["gates"] = gates
        r["winner"] = all(gates.values())
    res["m"] = m
    res["configs_tried_total"] = n_all
    res["winners"] = [n for n in names if res["finalists"][n]["winner"]]
    res["finished_utc"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / out_name).write_text(json.dumps(res, indent=1, default=str))
    print("WINNERS:", res["winners"], flush=True)
    return res


def dryrun() -> dict:
    """The exact TEST pipeline on VALIDATION (shake out bugs before the one TEST pass)."""
    doc, fins = check_frozen()
    return full_eval("validation", doc, fins, "validation_dryrun.json")


def test() -> dict:
    if os.environ.get(H.TEST_ENV) != "1":
        raise SystemExit("set LAB_ALLOW_TEST=1 (judge only)")
    if MARKER.exists():
        raise SystemExit(f"the TEST pass already ran ({MARKER}); one honest pass only")
    doc, fins = check_frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    return full_eval("test", doc, fins, "test_results.json")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "validate":
        validate()
    elif cmd == "freeze":
        freeze()
    elif cmd == "dryrun":
        dryrun()
    elif cmd == "test":
        test()
    else:
        raise SystemExit(__doc__)
