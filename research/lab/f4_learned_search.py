"""F4 learned-filter research driver (TRAIN search, VALIDATION shortlist, robustness).

Subcommands (run from anywhere; data goes to LAB/f4/, nothing under src/ or tests/ is touched):

  python research/lab/f4_learned_search.py build      # causal features + net-of-cost labels per split
  python research/lab/f4_learned_search.py train      # fold models on TRAIN, OOF scores, val scores
  python research/lab/f4_learned_search.py sweep      # harness runs on TRAIN (OOF scores) for every config
  python research/lab/f4_learned_search.py shortlist  # pre-registered TRAIN rule -> VALIDATION runs
  python research/lab/f4_learned_search.py robust     # robustness of the finalists (VALIDATION and TRAIN)
  python research/lab/f4_learned_search.py audit      # live scorer == search tables; audit_lookahead
  python research/lab/f4_learned_search.py finalize   # finalists/f4-learned.json (after robust + audit)
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


clean_X = F4.clean_X

# model variants: "all" = every gated row; "nofarm" = rows of non-farm coins only (F4.farm_flag), and the
# strategy then skips farm coins too (Gate.exclude_farm)
VARIANTS = ("all", "nofarm")


def tag(key: str, kind: str, variant: str = "all") -> str:
    return f"{key}_{kind}" if variant == "all" else f"{key}_{kind}_{variant}"


def row_mask(ds: dict, variant: str) -> np.ndarray:
    if variant == "all":
        return np.ones(len(ds["X"]), dtype=bool)
    if variant == "nofarm":
        return ~F4.farm_flag(ds["X"])
    raise ValueError(variant)


def train_all(variant: str = "all", kinds: tuple[str, ...] = MODELS) -> dict:
    """Fit fold models for every label x model; save OOF TRAIN scores and VALIDATION scores."""
    from sklearn.metrics import roc_auc_score
    tr, va = load_ds("train"), load_ds("validation")
    folds = time_folds(tr["coin"], tr["created"])
    Xtr, Xva = clean_X(tr["X"]), clean_X(va["X"])
    rm_tr, rm_va = row_mask(tr, variant), row_mask(va, variant)
    cols = list(range(Xtr.shape[1]))
    summary = {}
    for d in LABELS:
        key = lab_key(*d)
        ytr_raw = tr[f"y_{key}"]
        ok = ~np.isnan(ytr_raw) & rm_tr
        ytr = (ytr_raw > 0).astype(int)
        for kind in kinds:
            oof = np.full(len(Xtr), np.nan)
            models = []
            for f in range(N_FOLDS):
                fit = ok & (folds != f)
                m = make_model(kind)
                m.fit(Xtr[fit][:, cols], ytr[fit])
                models.append(m)
                sel = (folds == f) & rm_tr
                oof[sel] = m.predict_proba(Xtr[sel][:, cols])[:, 1]
            ens = F4.FoldEnsemble(models, cols, kind, {"label": key, "variant": variant,
                                                       "features": list(F4.FEATURES)})
            t = tag(key, kind, variant)
            ens.save(OUT / "models" / f"{t}.pkl")
            sva = np.full(len(Xva), np.nan)
            sva[rm_va] = ens.score(Xva[rm_va])
            (OUT / "scores").mkdir(parents=True, exist_ok=True)
            np.save(OUT / "scores" / f"oof_{t}.npy", oof)
            np.save(OUT / "scores" / f"val_{t}.npy", sva)
            auc = roc_auc_score(ytr[ok], oof[ok]) if ytr[ok].min() != ytr[ok].max() else None
            summary[t] = {"base_rate": float(ytr[ok].mean()), "rows": int(ok.sum()), "oof_auc": auc,
                          "oof_mean_ret_top": {str(q): float(np.nanmean(ytr_raw[ok & (oof >= np.quantile(oof[ok], q))]))
                                               for q in QUANTILES}}
            print(t, json.dumps(summary[t]), flush=True)
    path = OUT / ("train_summary.json" if variant == "all" else f"train_summary_{variant}.json")
    path.write_text(json.dumps(summary, indent=1))
    return summary


def score_table(split: str, key: str, kind: str, variant: str = "all") -> dict[str, np.ndarray]:
    """Per-coin score arrays (NaN where the gate is closed) for TableScorer."""
    ds = load_ds(split)
    s = np.load(OUT / "scores" / f"{'oof' if split == 'train' else 'val'}_{tag(key, kind, variant)}.npy")
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


def thresholds_for(key: str, kind: str, variant: str = "all") -> dict[float, float]:
    oof = np.load(OUT / "scores" / f"oof_{tag(key, kind, variant)}.npy")
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


def make_params(d: tuple[float, float, float], thr: float, variant: str = "all", max_entries: int = 1) -> Any:
    return F4.F4Params(threshold=thr, tp=d[0], sl=d[1], hold_min=d[2], max_entries=max_entries,
                       max_age_min=GATE.max_age_min, min_vol10_usd=GATE.min_vol10_usd,
                       min_mcap_sol=GATE.min_mcap_sol, exclude_farm=(variant == "nofarm"))


def sweep(stage: str = "A", variant: str = "all", kinds: tuple[str, ...] = MODELS) -> None:
    """Every label x model x threshold quantile on TRAIN (out-of-fold scores).
    Stage A = all rows; stage B = the "nofarm" variant."""
    coins = _coins("train")
    done = {json.loads(x)["id"] for x in RUNS.read_text().splitlines()} if RUNS.exists() else set()
    for d in LABELS:
        key = lab_key(*d)
        for kind in kinds:
            table = score_table("train", key, kind, variant)
            scorer = F4.TableScorer(table)
            for q, thr in thresholds_for(key, kind, variant).items():
                cfg = {"stage": stage, "label": key, "model": kind, "q": q, "max_entries": 1}
                if variant != "all":
                    cfg["variant"] = variant
                cid = config_id(cfg)
                if cid in done:
                    continue
                p = make_params(d, thr, variant)
                t = time.time()
                res = evaluate(p, scorer, coins)
                rec = {"id": cid, "split": "train", **cfg, "params": asdict(p), **res, "secs": round(time.time() - t, 1)}
                log_run(rec)
                pc, pf = res["per_coin"], res["portfolio"]
                print(f"{cid} {key:16s} {kind:5s} q={q:<5} n={pc['trades']:4d} avg={pc['avg_ret_pct']} "
                      f"ci={pc['exp_ci95_pct']} port={pf['total_return_pct']} dd={pf['max_drawdown_pct']}", flush=True)


# =========================================================================== diagnostics


def cluster_of(coin: H.Coin, entry_mid: float) -> str:
    """Descriptive tag (analysis only): the brand-ticker launch farm F2 found (instant graduation,
    graduation-bar close $250-500k), the >$5M ticker-clone cluster, or other."""
    gi = F4.graduation_index(coin.ts.astype(float), coin.dur.astype(float), coin.graduated_ts)
    grad_mc = float(coin.c[min(gi, coin.n - 1)]) * 1e9
    if coin.graduated_ts - coin.created_ts < 10 and 250e3 <= grad_mc <= 500e3:
        return "farm"
    if entry_mid * 1e9 >= 5e6:
        return "big"
    return "other"


def breakdown(res: H.Result, coins: list) -> dict:
    by_mint = {c.mint: c for c in coins}
    out: dict[str, dict] = {}
    for t in res.trades:
        k = cluster_of(by_mint[t.mint], t.entry_mid)
        d = out.setdefault(k, {"trades": 0, "pnl_usd": 0.0, "rets": []})
        d["trades"] += 1
        d["pnl_usd"] += t.pnl_usd
        d["rets"].append(t.ret)
    for d in out.values():
        d["avg_ret_pct"] = round(100 * float(np.mean(d.pop("rets"))), 3)
        d["pnl_usd"] = round(d["pnl_usd"], 3)
    return out


def trade_rows(res: H.Result, coins: list) -> list[dict]:
    by_mint = {c.mint: c for c in coins}
    rows = []
    for t in res.trades:
        c = by_mint[t.mint]
        rows.append({"symbol": t.symbol, "entry_min_after_grad": round((t.entry_ts - c.graduated_ts) / 60, 1),
                     "grad_delay_s": round(c.graduated_ts - c.created_ts, 1), "entry_mcap": round(t.entry_mid * 1e9),
                     "ret_pct": round(100 * t.ret, 2), "exit": t.exit_reason, "tag": t.tag,
                     "cluster": cluster_of(c, t.entry_mid)})
    return rows


def importance(key: str, kind: str, repeats: int = 3) -> dict[str, float]:
    """Mean drop in held-out AUC when one feature is permuted (fold models on their own held-out
    TRAIN fold; coin-grouped folds). For logit also the mean standardized coefficient."""
    from sklearn.inspection import permutation_importance
    tr = load_ds("train")
    folds = time_folds(tr["coin"], tr["created"])
    X = clean_X(tr["X"])
    y_raw = tr[f"y_{key}"]
    ens = F4.FoldEnsemble.load(OUT / "models" / f"{key}_{kind}.pkl")
    acc = np.zeros(X.shape[1])
    for f, m in enumerate(ens.models):
        sel = (folds == f) & ~np.isnan(y_raw)
        r = permutation_importance(m, X[sel], (y_raw[sel] > 0).astype(int), scoring="roc_auc",
                                   n_repeats=repeats, random_state=0)
        acc += r.importances_mean
    out = {f: round(float(v / len(ens.models)), 5) for f, v in zip(F4.FEATURES, acc)}
    out = dict(sorted(out.items(), key=lambda kv: -kv[1]))
    if kind == "logit":
        coefs = np.mean([m[-1].coef_[0] for m in ens.models], axis=0)
        out = {"perm_auc_drop": out,
               "std_coef": dict(sorted(((f, round(float(c), 4)) for f, c in zip(F4.FEATURES, coefs)),
                                       key=lambda kv: -abs(kv[1])))}
    else:
        out = {"perm_auc_drop": out}
    return out


# =========================================================================== shortlist / validation

MIN_TRADES, MIN_COINS, MAX_SHORTLIST, MAX_PER_LABEL = 15, 10, 6, 2


def _ok(pc: dict) -> bool:
    ci = pc.get("exp_ci95_pct")
    return (pc["trades"] or 0) > 0 and pc["avg_ret_pct"] is not None and pc["avg_ret_pct"] > 0 \
        and ci is not None and ci[0] > 0


def shortlist_rule(recs: list[dict]) -> list[dict]:
    """PRE-REGISTERED (written before any VALIDATION run). Eligible TRAIN configs:
    >= 15 trades on >= 10 coins (per-coin run); per-trade mean > 0 with coin-bootstrap CI low > 0;
    $100 portfolio return > 0; mean still > 0 without the top-3 coins; and at least one adjacent
    threshold quantile of the same label/model/variant also has mean > 0 and CI low > 0 (plateau,
    not a spike). Rank by CI low; keep at most 2 per (variant, label) and 6 overall."""
    train = [r for r in recs if r["split"] == "train" and r.get("stage") in ("A", "B")]
    groups: dict[tuple, dict[float, dict]] = {}
    for r in train:
        groups.setdefault((r.get("variant", "all"), r["label"], r["model"]), {})[r["q"]] = r
    elig = []
    for g, byq in groups.items():
        qs = sorted(byq)
        for k, q in enumerate(qs):
            r = byq[q]
            pc, pf = r["per_coin"], r["portfolio"]
            if pc["trades"] < MIN_TRADES or pc["coins_traded"] < MIN_COINS or not _ok(pc):
                continue
            if (pf.get("total_return_pct") or 0) <= 0 or (pc.get("avg_ret_pct_wo_top3") or -1) <= 0:
                continue
            nb = [byq[qs[j]] for j in (k - 1, k + 1) if 0 <= j < len(qs)]
            if not any(_ok(x["per_coin"]) for x in nb):
                continue
            elig.append(r)
    elig.sort(key=lambda r: -r["per_coin"]["exp_ci95_pct"][0])
    out, per = [], {}
    for r in elig:
        g = (r.get("variant", "all"), r["label"])
        if per.get(g, 0) >= MAX_PER_LABEL:
            continue
        per[g] = per.get(g, 0) + 1
        out.append(r)
        if len(out) >= MAX_SHORTLIST:
            break
    return out


def label_tuple(key: str) -> tuple[float, float, float]:
    for d in LABELS:
        if lab_key(*d) == key:
            return d
    raise KeyError(key)


def scorer_for(split: str, rec: dict) -> Any:
    return F4.TableScorer(score_table(split, rec["label"], rec["model"], rec.get("variant", "all")))


def validate_shortlist() -> list[dict]:
    recs = [json.loads(x) for x in RUNS.read_text().splitlines()]
    sl = shortlist_rule(recs)
    (OUT / "shortlist.json").write_text(json.dumps([r["id"] for r in sl], indent=1))
    coins = _coins("validation")
    done = {r["id"] for r in recs}
    out = []
    for r in sl:
        p = F4.F4Params(**r["params"])
        cfg = {"stage": "V", "train_id": r["id"]}
        cid = config_id(cfg)
        if cid in done:
            out.append(next(x for x in recs if x["id"] == cid))
            continue
        res = evaluate(p, scorer_for("validation", r), coins)
        rec = {"id": cid, "split": "validation", **cfg, "label": r["label"], "model": r["model"], "q": r["q"],
               "variant": r.get("variant", "all"), "params": r["params"], **res}
        res_pc = H.run_per_coin(F4.factory(p, scorer_for("validation", r)), coins)
        rec["clusters"] = breakdown(res_pc, coins)
        log_run(rec)
        out.append(rec)
        pc, pf = res["per_coin"], res["portfolio"]
        print(f"VAL {r['id']} {r['label']} {r['model']} {r.get('variant', 'all')} q={r['q']}: n={pc['trades']} "
              f"avg={pc['avg_ret_pct']} ci={pc['exp_ci95_pct']} port={pf['total_return_pct']} "
              f"dd={pf['max_drawdown_pct']} clusters={rec['clusters']}", flush=True)
    return out


class rug_aware_fills:
    """Stress (this process only, same as F2's): a stop that wicks through fills at no better than the
    bar close - on a one-transaction rug nobody sells at the halfway price "half" assumes."""

    def __enter__(self):
        self.oi, self.od = H.CoinEngine._intrabar, H.CoinEngine._down_fill
        oi, od = self.oi, self.od

        def intrabar(eng, j):
            eng._cur_close = float(eng.coin.c[j])
            return oi(eng, j)

        def down_fill(eng, level, o, low):
            f = od(eng, level, o, low)
            c = getattr(eng, "_cur_close", None)
            return min(f, max(c, low)) if c is not None else f

        H.CoinEngine._intrabar, H.CoinEngine._down_fill = intrabar, down_fill
        return self

    def __exit__(self, *a):
        H.CoinEngine._intrabar, H.CoinEngine._down_fill = self.oi, self.od


def robustness(rec: dict, split: str = "validation") -> dict:
    """Costs x1.5 / x2, +1 bar latency, $10 / $40 positions, wick worst / touch, rug-aware fills,
    without the best coin, first vs second half of the split (by creation time)."""
    coins = _coins(split)
    p = F4.F4Params(**rec["params"])
    sc = scorer_for(split, rec)
    base = H.SimConfig()
    out: dict[str, Any] = {"base": evaluate(p, sc, coins)}
    out["costs_x1.5"] = evaluate(p, sc, coins, H.SimConfig(cost=CostModel().stressed(1.5)))
    out["costs_x2"] = evaluate(p, sc, coins, H.SimConfig(cost=CostModel().stressed(2.0)))
    out["latency_+1bar"] = evaluate(p, sc, coins, H.SimConfig(entry_delay_bars=2))
    out["size_$10"] = evaluate(p, sc, coins, H.SimConfig(fixed_usd=10, position_pct=1.0, min_usd=10, max_usd=10))
    out["size_$40"] = evaluate(p, sc, coins, H.SimConfig(fixed_usd=40, position_pct=1.0, min_usd=40, max_usd=40))
    out["wick_worst"] = evaluate(p, sc, coins, H.SimConfig(wick_fill="worst"))
    out["wick_touch"] = evaluate(p, sc, coins, H.SimConfig(wick_fill="touch"))
    with rug_aware_fills():
        out["rug_aware_fills"] = evaluate(p, sc, coins)
    pc = H.run_per_coin(F4.factory(p, sc), coins, base)
    by: dict[str, float] = {}
    for t in pc.trades:
        by[t.mint] = by.get(t.mint, 0.0) + t.pnl_usd
    if by:
        best = max(by, key=by.get)
        out["without_best_coin"] = evaluate(p, sc, [c for c in coins if c.mint != best])
        out["without_best_coin"]["removed"] = next(c.symbol for c in coins if c.mint == best)
    half = len(coins) // 2
    out["first_half"] = evaluate(p, sc, coins[:half])
    out["second_half"] = evaluate(p, sc, coins[half:])
    out["clusters"] = breakdown(pc, coins)
    out["trades"] = trade_rows(pc, coins)
    return out


FINALIST_IDS = ["8e870ebcf0", "314fea3f67"]  # chosen on VALIDATION from the pre-registered shortlist
FINALIST_NAMES = ["F4_farm_climb_gbt_tp30_sl15_h15_q98", "F4_farm_climb_gbt_tp30_sl15_h15_q99"]


def run_robust(ids: list[str] = FINALIST_IDS) -> dict:
    by_id = {json.loads(x)["id"]: json.loads(x) for x in RUNS.read_text().splitlines()}
    out = {tid: {"validation": robustness(by_id[tid], "validation"), "train": robustness(by_id[tid], "train")}
           for tid in ids}
    (OUT / "robustness.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def run_audit(ids: list[str] = FINALIST_IDS) -> dict:
    """Live-style ModelScorer (features from the view, fold-ensemble model): (1) its decisions and trades
    on every VALIDATION coin equal the search's table run; (2) audit_lookahead is clean on every
    VALIDATION coin (2 cuts) and every TRAIN coin (1 cut)."""
    by_id = {json.loads(x)["id"]: json.loads(x) for x in RUNS.read_text().splitlines()}
    coins = _coins("validation")
    last = {c.mint: c.n - 1 for c in coins}
    out = {}
    for tid in ids:
        r = by_id[tid]
        p = F4.F4Params(**r["params"])
        model = F4.FoldEnsemble.load(OUT / "models" / f"{tag(r['label'], r['model'], r.get('variant', 'all'))}.pkl")
        live_fac = F4.factory(p, F4.ModelScorer(model, p.gate))
        live = H.run_per_coin(live_fac, coins, keep_decisions=True)
        fast = H.run_per_coin(F4.factory(p, scorer_for("validation", r)), coins, keep_decisions=True)
        # a Buy decided on a coin's very last bar can never fill; the table has no row there
        dl = {m: [d for d in v if d[0] < last[m]] for m, v in live.decisions.items()}
        df = {m: [d for d in v if d[0] < last[m]] for m, v in fast.decisions.items()}
        out[tid] = {
            "live_equals_table_decisions": dl == df,
            "live_equals_table_trades": [round(t.ret, 12) for t in live.trades] == [round(t.ret, 12) for t in fast.trades],
            "audit_validation_problems": H.audit_lookahead(live_fac, coins, cuts_per_coin=2),
            "audit_train_problems": H.audit_lookahead(live_fac, _coins("train"), cuts_per_coin=1),
            "audit_coins": {"validation": len(coins), "train": len(_coins("train"))},
        }
        print(tid, json.dumps(out[tid]), flush=True)
    (OUT / "audit.json").write_text(json.dumps(out, indent=1))
    return out


# =========================================================================== finalists file

KEYS = ("trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "exp_ci95_pct",
        "expectancy_usd", "profit_factor", "total_return_pct", "max_drawdown_pct", "best_coin_share_pct",
        "top3_share_pct", "pnl_without_best_coin_usd", "pnl_without_top3_usd", "avg_ret_pct_wo_best",
        "avg_ret_pct_wo_top3", "exit_reasons", "rejected")


def _trim(ev: dict) -> dict:
    return {mode: {k: ev[mode].get(k) for k in KEYS if k in ev[mode]} for mode in ("per_coin", "portfolio") if mode in ev}


def finalize(train_ids: list[str], names: list[str]) -> list[dict]:
    recs = [json.loads(x) for x in RUNS.read_text().splitlines()]
    by_id = {r["id"]: r for r in recs}
    rob = json.loads((OUT / "robustness.json").read_text())
    audit = json.loads((OUT / "audit.json").read_text()) if (OUT / "audit.json").exists() else {}
    cnt = count()
    out = []
    for tid, name in zip(train_ids, names):
        tr = by_id[tid]
        va = next(r for r in recs if r.get("stage") == "V" and r.get("train_id") == tid)
        rv, rt = rob[tid]["validation"], rob[tid]["train"]
        au = audit.get(tid, {})

        def pos(ev, mode="per_coin", key="avg_ret_pct"):
            v = ev[mode].get(key)
            return v is not None and v > 0

        gates = {
            "train_avg_positive": pos(tr), "train_ci_above_0": tr["per_coin"]["exp_ci95_pct"][0] > 0,
            "train_portfolio_positive": pos(tr, "portfolio", "total_return_pct"),
            "validation_avg_positive": pos(va), "validation_ci_above_0": (va["per_coin"]["exp_ci95_pct"] or [-1])[0] > 0,
            "validation_portfolio_positive": pos(va, "portfolio", "total_return_pct"),
            "validation_without_best_coin_positive": pos(va, "per_coin", "avg_ret_pct_wo_best"),
            "validation_without_top3_positive": pos(va, "per_coin", "avg_ret_pct_wo_top3"),
            "validation_costs_x2_positive": pos(rv["costs_x2"]),
            "validation_wick_worst_positive": pos(rv["wick_worst"]),
            "validation_wick_worst_portfolio_positive": pos(rv["wick_worst"], "portfolio", "total_return_pct"),
            "validation_rug_aware_fills_positive": pos(rv["rug_aware_fills"]),
            "audit_lookahead_clean": bool(au) and not au.get("audit_validation_problems") and not au.get("audit_train_problems"),
            "live_scorer_equals_search_table": bool(au.get("live_equals_table_decisions")) and bool(au.get("live_equals_table_trades")),
        }
        fails = [k for k, v in gates.items() if not v]
        verdict = "REJECTED - fails: " + ", ".join(fails) if fails else "PASSES lab gates"
        out.append({
            "name": name, "strategy_class": "F4Learned", "module": "research/lab/strategies/f4-learned.py",
            "verdict": verdict, "recommend_test": not fails,
            "params": {"label": tr["label"], "model": tr["model"], "variant": tr.get("variant", "all"), "q": tr["q"],
                       "model_file": f"LAB/f4/models/{tag(tr['label'], tr['model'], tr.get('variant', 'all'))}.pkl",
                       "scorer": "ModelScorer(FoldEnsemble.load(model_file), F4Params.gate)",
                       "strategy": tr["params"]},
            "configs_tried": {"train": cnt.get("train_total"), "train_stage_A_all_rows": cnt.get("train:A"),
                              "train_stage_B_nofarm": cnt.get("train:B"), "validation": cnt.get("validation:V"),
                              "note": "every config is in LAB/f4/runs.jsonl; robustness variants are not selection tries"},
            "gates": gates,
            "train_metrics": {**_trim(tr), "note": "out-of-fold scores (5 time-blocked, coin-grouped folds)"},
            "validation_metrics": {**_trim(va), "clusters": va.get("clusters")},
            "robustness": {"validation": {k: (_trim(v) | ({"removed": v["removed"]} if "removed" in v else {}))
                                          for k, v in rv.items() if k not in ("clusters", "trades")},
                           "validation_trades": rv.get("trades"),
                           "train": {k: (_trim(v) | ({"removed": v["removed"]} if "removed" in v else {}))
                                     for k, v in rt.items() if k not in ("clusters", "trades")}},
            "audit": au,
        })
    path = HERE / "finalists" / "f4-learned.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"wrote {path}")
    return out


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
        train_all(sys.argv[2] if len(sys.argv) > 2 else "all")
    elif cmd == "sweep":
        v = sys.argv[2] if len(sys.argv) > 2 else "all"
        sweep("A" if v == "all" else "B", v)
    elif cmd == "shortlist":
        validate_shortlist()
    elif cmd == "robust":
        run_robust()
    elif cmd == "audit":
        run_audit()
    elif cmd == "finalize":
        finalize(FINALIST_IDS, FINALIST_NAMES)
    elif cmd == "count":
        print(json.dumps(count(), indent=1))
    else:
        raise SystemExit(f"unknown command {cmd}")
