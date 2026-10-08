"""F4 learned-filter research driver (TRAIN search, VALIDATION shortlist, robustness).

Subcommands (run from anywhere; data goes to LAB/f4/, nothing under src/ or tests/ is touched):

  python research/lab/f4_learned_search.py build      # causal features + net-of-cost labels per split
  python research/lab/f4_learned_search.py train      # fold models on TRAIN, OOF scores, val scores
  python research/lab/f4_learned_search.py sweep      # harness runs on TRAIN (OOF scores) for every config
  python research/lab/f4_learned_search.py shortlist  # pre-registered TRAIN rule -> VALIDATION runs
  python research/lab/f4_learned_search.py robust     # robustness of the finalists on VALIDATION
  python research/lab/f4_learned_search.py count      # configurations evaluated so far

Protocol (fixed before any VALIDATION run):

* Labels: for every gated bar i, the net return (default costs, $20, wick "half") of buying at the
  open of bar i+1 with stop ``sl``, take-profit ``tp`` and time stop ``hold``; y = return > 0.
  Rows whose exit window runs past the end of the data are dropped from training (censored).
* Models are trained on TRAIN rows only. Folds = 5 contiguous blocks of TRAIN coins by creation time
  (coin-grouped: all rows of a coin are in one fold). A TRAIN coin is scored by the fold model that
  did not see it (out-of-fold); VALIDATION coins are scored by the average of the 5 fold models.
* Thresholds are quantiles of the out-of-fold TRAIN scores of gated rows, frozen as absolute values.
* TRAIN harness metrics therefore use out-of-fold scores (no in-sample fit is ever evaluated).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
from costs import CostModel, SolUsd  # noqa: E402


def _load_f4():
    name = "f4_learned"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "strategies" / "f4-learned.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F4 = _load_f4()
OUT = H.LAB / "f4"
RUNS = OUT / "runs.jsonl"
GATE = F4.Gate()  # max 360 min after graduation, >= $1k in the last 10 bars, >= 30 SOL market cap

# label / exit definitions: (tp, sl, hold_min)
LABELS: list[tuple[float, float, float]] = [
    (tp, sl, hold) for tp in (0.15, 0.30, 0.60) for sl in (0.15, 0.30) for hold in (15.0, 60.0)
]
QUANTILES = (0.90, 0.95, 0.98, 0.99, 0.995)
MODELS = ("logit", "gbt")
N_FOLDS = 5


def lab_key(tp: float, sl: float, hold: float) -> str:
    return f"tp{int(round(tp * 100))}_sl{int(round(sl * 100))}_h{int(hold)}"


# =========================================================================== labels


def simulate_returns(coin: H.Coin, rows: np.ndarray, tp: float, sl: float, hold_s: float, cost: CostModel,
                     sol: SolUsd, usd: float = 20.0, wick: str = "half") -> np.ndarray:
    """Net return of buying ``usd`` at the open of bar i+1 for every decision bar i in ``rows``,
    with the harness's exit order (gap/time at the open, stop before take-profit, wick fills).
    NaN when there is no next bar or the exit window is censored by the end of the data."""
    ts, o, h, l, c = coin.ts, coin.o, coin.h, coin.l, coin.c  # noqa: E741
    n = coin.n
    out = np.full(len(rows), np.nan)
    for k, i in enumerate(rows):
        j0 = int(i) + 1
        if j0 >= n:
            continue
        mid = float(o[j0])
        t0 = float(ts[j0])
        s0 = sol.at(t0)
        tokens, _ = cost.buy(usd, mid, coin.cost_ctx, s0, curve=t0 < coin.graduated_ts)
        if tokens <= 0:
            continue
        stop, tpp, tstop = mid * (1 - sl), mid * (1 + tp), t0 + hold_s
        # last bar we need: the first bar with ts >= tstop (time stop at its open), else end of data
        jt = int(np.searchsorted(ts, tstop, side="left"))
        jend = min(jt, n - 1)
        seg = slice(j0, jend + 1)
        oo, hh, lo, cc = o[seg], h[seg], l[seg], c[seg]
        m = len(oo)
        INF = 10 ** 9
        gap = np.nonzero(oo[1:] <= stop)[0]
        j_gap = gap[0] + 1 if len(gap) else INF
        j_time = (jt - j0) if jt <= n - 1 else INF
        low = np.nonzero(lo <= stop)[0]
        j_low = low[0] if len(low) else INF
        hit = np.nonzero(hh >= tpp)[0]
        j_tp = hit[0] if len(hit) else INF
        first = min(j_gap, j_time, j_low, j_tp)
        if first >= INF:
            if jt > n - 1:
                continue  # censored: the data ends before the time stop
            first = m - 1  # (cannot happen: jt <= n-1 gives j_time)
        jo = first
        bo, bh, bl, bc = float(oo[jo]), float(hh[jo]), float(lo[jo]), float(cc[jo])
        if jo == j_gap and jo > 0:
            px = bo
        elif jo == j_time and jo > 0:
            px = bo
        elif jo == j_low:
            lvl = min(stop, bo)
            px = lvl if wick == "touch" else bl if wick == "worst" else (lvl + bl) / 2.0
        else:
            if bo >= tpp:
                px = bo
            elif wick == "touch" or bc >= tpp:
                px = tpp
            else:
                top = max(bo, bc)
                px = top if wick == "worst" else (tpp + top) / 2.0
        tj = float(ts[j0 + jo])
        s1 = sol.at(tj)
        back, _ = cost.sell(tokens, px, coin.cost_ctx, s1, curve=tj < coin.graduated_ts)
        out[k] = (back - cost.network_usd(s1) - usd - cost.network_usd(s0)) / usd
    return out


def build(split: str) -> Path:
    t = time.time()
    coins = H.load_coins(split=split)
    sol = SolUsd.from_lab()
    cost = CostModel()
    Xs, coin_ix, bar_ix, created, Ys = [], [], [], [], {lab_key(*d): [] for d in LABELS}
    mints = []
    for ci, coin in enumerate(coins):
        mints.append(coin.mint)
        F = F4.coin_features(coin, sol)
        g = F4.gate_mask(F, F4.vol10(coin.v), GATE)
        rows = np.nonzero(g)[0]
        rows = rows[rows + 1 < coin.n]
        if not len(rows):
            continue
        Xs.append(F[rows])
        coin_ix.append(np.full(len(rows), ci))
        bar_ix.append(rows)
        created.append(np.full(len(rows), coin.created_ts))
        for d in LABELS:
            Ys[lab_key(*d)].append(simulate_returns(coin, rows, d[0], d[1], d[2] * 60, cost, sol))
    path = OUT / f"dataset_{split}.npz"
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, X=np.vstack(Xs), coin=np.concatenate(coin_ix), bar=np.concatenate(bar_ix),
                        created=np.concatenate(created), mints=np.array(mints),
                        **{f"y_{k}": np.concatenate(v) for k, v in Ys.items()})
    print(f"{split}: {sum(len(x) for x in Xs)} gated rows from {len(Xs)} of {len(coins)} coins "
          f"({time.time() - t:.0f}s) -> {path}")
    return path


def load_ds(split: str) -> dict:
    d = np.load(OUT / f"dataset_{split}.npz", allow_pickle=False)
    return {k: d[k] for k in d.files}


# =========================================================================== models


def time_folds(coin_ix: np.ndarray, created: np.ndarray, k: int = N_FOLDS) -> np.ndarray:
    """Fold id per row: coins sorted by creation time, cut into k contiguous blocks of coins."""
    uc = np.unique(coin_ix)
    order = uc[np.argsort([created[coin_ix == c][0] for c in uc], kind="stable")]
    fold_of = {c: min(int(r * k / len(order)), k - 1) for r, c in enumerate(order)}
    return np.array([fold_of[c] for c in coin_ix])


def make_model(kind: str, seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "logit":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))
    if kind == "gbt":
        return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=400,
                                              l2_regularization=5.0, max_features=0.5, random_state=seed)
    raise ValueError(kind)


def clean_X(X: np.ndarray) -> np.ndarray:
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(X, -50, 50)


def train_all() -> dict:
    """Fit fold models for every label x model; save OOF TRAIN scores and VALIDATION scores."""
    from sklearn.metrics import roc_auc_score
    tr, va = load_ds("train"), load_ds("validation")
    folds = time_folds(tr["coin"], tr["created"])
    Xtr, Xva = clean_X(tr["X"]), clean_X(va["X"])
    cols = list(range(Xtr.shape[1]))
    summary = {}
    for d in LABELS:
        key = lab_key(*d)
        ytr_raw = tr[f"y_{key}"]
        ok = ~np.isnan(ytr_raw)
        ytr = (ytr_raw > 0).astype(int)
        for kind in MODELS:
            oof = np.full(len(Xtr), np.nan)
            models = []
            for f in range(N_FOLDS):
                fit = ok & (folds != f)
                m = make_model(kind)
                m.fit(Xtr[fit][:, cols], ytr[fit])
                models.append(m)
                oof[folds == f] = m.predict_proba(Xtr[folds == f][:, cols])[:, 1]
            ens = F4.FoldEnsemble(models, cols, kind, {"label": key, "features": list(F4.FEATURES)})
            ens.save(OUT / "models" / f"{key}_{kind}.pkl")
            sva = ens.score(Xva)
            (OUT / "scores").mkdir(parents=True, exist_ok=True)
            np.save(OUT / "scores" / f"oof_{key}_{kind}.npy", oof)
            np.save(OUT / "scores" / f"val_{key}_{kind}.npy", sva)
            auc = roc_auc_score(ytr[ok], oof[ok]) if ytr[ok].min() != ytr[ok].max() else None
            summary[f"{key}_{kind}"] = {"base_rate": float(ytr[ok].mean()), "rows": int(ok.sum()),
                                        "oof_auc": auc,
                                        "oof_mean_ret_top": {str(q): float(np.nanmean(ytr_raw[ok & (oof >= np.quantile(oof[ok], q))]))
                                                             for q in QUANTILES}}
            print(key, kind, json.dumps(summary[f"{key}_{kind}"]))
    (OUT / "train_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def score_table(split: str, key: str, kind: str) -> dict[str, np.ndarray]:
    """Per-coin score arrays (NaN where the gate is closed) for TableScorer."""
    ds = load_ds(split)
    s = np.load(OUT / "scores" / f"{'oof' if split == 'train' else 'val'}_{key}_{kind}.npy")
    lens = {c.mint: c.n for c in _coins(split)}
    table = {m: np.full(lens[m], np.nan) for m in lens}
    mints = ds["mints"]
    for ci in np.unique(ds["coin"]):
        sel = ds["coin"] == ci
        table[str(mints[ci])][ds["bar"][sel]] = s[sel]
    return table


_COINS: dict[str, list] = {}


def _coins(split: str) -> list:
    if split not in _COINS:
        _COINS[split] = H.load_coins(split=split)
    return _COINS[split]


def thresholds_for(key: str, kind: str) -> dict[float, float]:
    oof = np.load(OUT / "scores" / f"oof_{key}_{kind}.npy")
    oof = oof[~np.isnan(oof)]
    return {q: float(np.quantile(oof, q)) for q in QUANTILES}


# =========================================================================== evaluation


def _m(res: H.Result) -> dict:
    m = res.metrics()
    keep = ["trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor",
            "expectancy_usd", "exp_ci95_pct", "net_pnl_usd", "total_return_pct", "max_drawdown_pct",
            "best_coin_share_pct", "top3_share_pct", "pnl_without_best_coin_usd", "pnl_without_top3_usd",
            "exit_reasons", "costs_usd", "avg_hold_min"]
    out = {k: m.get(k) for k in keep}
    for k, v in list(out.items()):
        if isinstance(v, float):
            out[k] = round(v, 4)
    # mean per-trade return without the best / top-3 coins (by P&L)
    by: dict[str, list] = {}
    for t in res.trades:
        by.setdefault(t.mint, []).append(t)
    ranked = sorted(by, key=lambda mm: sum(t.pnl_usd for t in by[mm]), reverse=True)
    for lab, drop in (("avg_ret_pct_wo_best", 1), ("avg_ret_pct_wo_top3", 3)):
        rest = [t.ret for mm in ranked[drop:] for t in by[mm]]
        out[lab] = round(100 * float(np.mean(rest)), 4) if rest else None
    if res.rejected:
        out["rejected"] = dict(res.rejected)
    return out


def evaluate(params: Any, scorer: Any, coins: list, cfg: H.SimConfig | None = None, per_coin: bool = True) -> dict:
    fac = F4.factory(params, scorer)
    out = {"portfolio": _m(H.run_portfolio(fac, coins, cfg))}
    if per_coin:
        pc_cfg = cfg or H.SimConfig()
        out["per_coin"] = _m(H.run_per_coin(fac, coins, pc_cfg))
    return out


def config_id(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]


def log_run(rec: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def sweep() -> None:
    """Stage A: every label x model x threshold quantile on TRAIN (out-of-fold scores)."""
    coins = _coins("train")
    done = {json.loads(x)["id"] for x in RUNS.read_text().splitlines()} if RUNS.exists() else set()
    for d in LABELS:
        key = lab_key(*d)
        for kind in MODELS:
            table = score_table("train", key, kind)
            scorer = F4.TableScorer(table)
            for q, thr in thresholds_for(key, kind).items():
                cfg = {"stage": "A", "label": key, "model": kind, "q": q, "max_entries": 1}
                cid = config_id(cfg)
                if cid in done:
                    continue
                p = F4.F4Params(threshold=thr, tp=d[0], sl=d[1], hold_min=d[2], max_entries=1,
                                max_age_min=GATE.max_age_min, min_vol10_usd=GATE.min_vol10_usd,
                                min_mcap_sol=GATE.min_mcap_sol)
                t = time.time()
                res = evaluate(p, scorer, coins)
                rec = {"id": cid, "split": "train", **cfg, "params": asdict(p), **res, "secs": round(time.time() - t, 1)}
                log_run(rec)
                pc, pf = res["per_coin"], res["portfolio"]
                print(f"{cid} {key:16s} {kind:5s} q={q:<5} n={pc['trades']:4d} avg={pc['avg_ret_pct']} "
                      f"ci={pc['exp_ci95_pct']} port={pf['total_return_pct']} dd={pf['max_drawdown_pct']}", flush=True)


def count() -> dict:
    if not RUNS.exists():
        return {}
    recs = [json.loads(x) for x in RUNS.read_text().splitlines()]
    out: dict[str, int] = {}
    for r in recs:
        k = f"{r['split']}:{r.get('stage', '?')}"
        out[k] = out.get(k, 0) + 1
    out["train_total"] = sum(v for k, v in out.items() if k.startswith("train"))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    if cmd == "build":
        for s in (sys.argv[2:] or ["train", "validation"]):
            build(s)
    elif cmd == "train":
        train_all()
    elif cmd == "sweep":
        sweep()
    elif cmd == "count":
        print(json.dumps(count(), indent=1))
    else:
        raise SystemExit(f"unknown command {cmd}")
